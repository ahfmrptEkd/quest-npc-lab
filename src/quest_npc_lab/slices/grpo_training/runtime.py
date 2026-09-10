"""CUDA GRPO execution with immutable SFT input and durable local evidence."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import time

from .grpo_training import summarize_run
from quest_npc_lab.slices.sft_training.runtime import write_json


@dataclass(frozen=True)
class Hyperparameters:
    group_size: int = 4
    seed: int = 42
    epochs: int = 1
    learning_rate: float = 1e-5
    epsilon: float = 1e-4
    temperature: float = 1.0
    max_training_seconds: int = 1800


def run_training(directory: Path, *, preflight=False) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "grpo_preflight" if preflight else directory
    output.mkdir(parents=True, exist_ok=True)
    for name in (
        "grpo_checkpoint",
        "grpo_training_report.json",
        "grpo_training_groups.jsonl",
    ):
        path = output / name
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"refusing to overwrite preserved output: {path}")
    config = Hyperparameters()
    report = {
        "run_kind": "grpo_preflight" if preflight else "main_grpo",
        "status": "running",
        "acceptance_passed": False,
        "created_at": datetime.now(UTC).isoformat(),
        "hyperparameters": asdict(config),
        "groups": [],
        "reload_verification": {"status": "not_run"},
        **summarize_run(
            [],
            group_size=config.group_size,
            expected_groups=180,
            parameter_delta_norm=0.0,
        ),
    }
    started = time.monotonic()
    try:
        validate_sft_checkpoint(directory)
        train_and_save(directory, output, config, report, preflight=preflight)
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
    report["acceptance_passed"] = report["status"] == "passed" and not preflight
    report["execution_seconds"] = time.monotonic() - started
    write_json(output / "grpo_training_report.json", report)
    return report


def validate_sft_checkpoint(directory: Path) -> dict[str, Any]:
    from quest_npc_lab.slices.sft_training.runtime import provenance, sha256

    checkpoint = directory / "sft_checkpoint"
    required = (
        "adapter_config.json",
        "adapter_model.safetensors",
        "training_metadata.json",
    )
    if any(not (checkpoint / name).is_file() for name in required):
        raise ValueError(
            "preserved SFT checkpoint requires adapter_config.json, adapter_model.safetensors, and training_metadata.json"
        )
    metadata = json.loads((checkpoint / "training_metadata.json").read_text())
    if metadata["provenance"] != provenance():
        raise ValueError(
            "SFT checkpoint training data or frozen prompt provenance mismatch"
        )
    for name in required[:2]:
        if sha256(checkpoint / name) != metadata["checkpoint_files"][name]:
            raise ValueError("SFT checkpoint integrity mismatch")
    return metadata


def train_group(
    model,
    tokenizer,
    input_ids,
    ground_truth,
    optimizer,
    config,
    *,
    max_new_tokens,
    do_update=True,
) -> dict[str, Any]:
    """Sample one prompt, score unmodified responses, then take one on-policy update."""
    import math
    import torch
    from .grpo_training import evaluate_group
    from .loss import policy_loss

    model.eval()  # Disable dropout for both rollout and gradient recomputation.
    optimizer.zero_grad(set_to_none=True)
    with torch.no_grad():
        sequences = model.generate(
            input_ids=input_ids,
            attention_mask=torch.ones_like(input_ids),
            num_return_sequences=config.group_size,
            do_sample=True,
            temperature=config.temperature,
            top_k=0,
            top_p=1.0,
            repetition_penalty=1.0,
            max_new_tokens=max_new_tokens,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
            use_cache=True,
        )
    if len(sequences) != config.group_size:
        raise ValueError("sampling must return exactly G candidates")
    prompt_length = input_ids.shape[1]
    completions = []
    for sequence in sequences:
        completion = sequence[prompt_length:]
        eos = (completion == tokenizer.eos_token_id).nonzero()
        if len(eos):
            completion = completion[: int(eos[0].item()) + 1]
        if not len(completion):
            raise ValueError("empty token completion")
        completions.append(completion)
    group = evaluate_group(
        [
            tokenizer.decode(tokens.tolist(), skip_special_tokens=True)
            for tokens in completions
        ],
        ground_truth,
        epsilon=config.epsilon,
    )
    group.update(
        completion_token_counts=[len(tokens) for tokens in completions],
        optimizer_step=False,
        policy_loss=0.0,
        gradient_norm=0.0,
    )
    # Skip optimizer.step too: Adam momentum must not move weights on zero-signal groups.
    if not do_update or not group["has_reward_variance"]:
        return group
    for completion, advantage in zip(completions, group["advantages"], strict=True):
        sequence = torch.cat((input_ids[0], completion)).unsqueeze(0)
        logits = model(
            input_ids=sequence,
            attention_mask=torch.ones_like(sequence),
            use_cache=False,
            logits_to_keep=len(completion) + 1,
        ).logits[:, -(len(completion) + 1) : -1, :]
        log_probs = (
            logits.float()
            .log_softmax(-1)
            .gather(-1, completion.reshape(1, -1, 1))
            .squeeze(-1)
        )
        loss = (
            policy_loss(log_probs, torch.ones_like(log_probs), [advantage])
            / config.group_size
        )
        if not torch.isfinite(loss):
            raise ValueError("non-finite policy loss")
        loss.backward()
        group["policy_loss"] += float(loss.detach())
    norm = torch.nn.utils.clip_grad_norm_(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        1.0,
        error_if_nonfinite=True,
    )
    group["gradient_norm"] = float(norm)
    if not math.isfinite(group["gradient_norm"]):
        raise ValueError("non-finite gradient norm")
    optimizer.step()
    group["optimizer_step"] = True
    return group


def tokenize_prompt(messages, tokenizer, *, max_input_tokens):
    tokens = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=False,
    )
    if tokens.shape[1] > max_input_tokens:
        raise ValueError("input token limit exceeded; truncation is forbidden")
    return tokens


def train_and_save(directory, output, config, report, *, preflight):
    import gc
    from importlib.metadata import version
    import math
    import platform
    import random
    import torch
    from peft import PeftModel
    from transformers import set_seed
    from .grpo_training import training_prompt
    from quest_npc_lab.slices.prompt_evaluation import load_manifest
    from quest_npc_lab.slices.sft_training.sft_training import load_training_cases
    from quest_npc_lab.slices.sft_training.runtime import (
        load_base,
        snapshot,
        parameter_digest,
        reload_checkpoint,
        sha256,
    )

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for GRPO training")
    torch.set_num_threads(1)
    set_seed(config.seed)
    torch.cuda.reset_peak_memory_stats()
    manifest = load_manifest()
    metadata = validate_sft_checkpoint(directory)
    cases = load_training_cases()
    order = list(range(len(cases)))
    random.Random(config.seed).shuffle(order)
    if preflight:
        order = order[:4]
    report.update(
        sft_checkpoint_files=metadata["checkpoint_files"],
        provenance={
            **metadata["provenance"],
            "initial_checkpoint": "sft_checkpoint",
            "initial_adapter_parameter_sha256": metadata["adapter_parameter_sha256"],
            "checkpoint_selection": "final training group only; no evaluation or seed selection",
            "final_evaluation_used": False,
        },
        evaluation_generation=manifest["generation"],
        training_settings={
            "optimizer": "AdamW",
            "weight_decay": 0.0,
            "max_grad_norm": 1.0,
            "loss": "sequence-normalized on-policy GRPO; one update per fresh group",
            "kl_coefficient": 0.0,
            "population_standard_deviation": True,
            "dropout": "disabled",
            "top_k": 0,
            "top_p": 1.0,
            "max_new_tokens": manifest["generation"]["max_new_tokens"],
            "identical_reward_groups": "skip optimizer step including momentum",
            "stop_policy": "one pass, 1800 training seconds checked between groups; no retries",
        },
        reward_specification="1.0 iff strict format passes and original parsed action matches ground truth; otherwise 0.0. Single completed-response terminal reward.",
        environment={
            "python": platform.python_version(),
            "device": "cuda",
            "gpu": torch.cuda.get_device_name(0),
            "cuda_version": torch.version.cuda,
            "libraries": {
                name: version(name) for name in ("torch", "transformers", "peft")
            },
            "torch_num_threads": 1,
        },
    )
    base, tokenizer = load_base()
    model = PeftModel.from_pretrained(
        base,
        str(directory / "sft_checkpoint"),
        is_trainable=True,
        local_files_only=True,
    )
    before = snapshot(model)
    if parameter_digest(before) != metadata["adapter_parameter_sha256"]:
        raise ValueError("loaded SFT parameters differ from preserved adapter")
    trainable = [
        parameter for parameter in model.parameters() if parameter.requires_grad
    ]
    if not trainable or any(
        "lora_" not in name for name, p in model.named_parameters() if p.requires_grad
    ):
        raise ValueError("only existing SFT LoRA parameters may be trained")
    optimizer = torch.optim.AdamW(trainable, lr=config.learning_rate, weight_decay=0.0)
    prompts = {
        index: tokenize_prompt(
            training_prompt(cases[index]),
            tokenizer,
            max_input_tokens=manifest["input_limits"]["max_input_tokens"],
        ).to("cuda")
        for index in order
    }
    report["tokenization"] = {
        "max_input_tokens": max(p.shape[1] for p in prompts.values()),
        "truncated": False,
    }
    bf16 = torch.cuda.is_bf16_supported()
    report["training_settings"]["mixed_precision"] = "bf16" if bf16 else "none"
    report["training_settings"]["base_dtype"] = manifest["dtype"]
    started = time.monotonic()
    try:
        for group_index, case_index in enumerate(order, 1):
            if time.monotonic() - started > config.max_training_seconds:
                raise TimeoutError("GRPO exceeded the fixed training budget")
            torch.cuda.synchronize()
            group_started = time.monotonic()
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=bf16):
                group = train_group(
                    model,
                    tokenizer,
                    prompts[case_index],
                    cases[case_index].ground_truth_action,
                    optimizer,
                    config,
                    max_new_tokens=manifest["generation"]["max_new_tokens"],
                    do_update=not preflight,
                )
            torch.cuda.synchronize()
            group.update(
                group_index=group_index,
                case_id=f"train-{case_index + 1:03d}",
                ground_truth_action=cases[case_index].ground_truth_action.value,
                seconds=time.monotonic() - group_started,
            )
            report["groups"].append(group)
            with (output / "grpo_training_groups.jsonl").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(
                    json.dumps(group, ensure_ascii=False, allow_nan=False) + "\n"
                )
            print(
                f"group {group_index}/{len(order)}: rewards={group['rewards']} loss={group['policy_loss']:.6f}",
                flush=True,
            )
            if time.monotonic() - started > config.max_training_seconds:
                raise TimeoutError("GRPO exceeded the fixed training budget")
    finally:
        trained = snapshot(model)
        delta = math.sqrt(
            sum(
                float((trained[name] - old).square().sum())
                for name, old in before.items()
            )
        )
        report.update(
            summarize_run(
                report["groups"],
                group_size=config.group_size,
                expected_groups=len(order),
                parameter_delta_norm=delta,
            )
        )
        report["training_seconds"] = time.monotonic() - started
        report["peak_cuda_memory_gb"] = torch.cuda.max_memory_allocated() / 1024**3
        report["trainable_parameter_count"] = sum(t.numel() for t in trained.values())
        report["changed_tensor_count"] = sum(
            not torch.equal(old, trained[name]) for name, old in before.items()
        )
    # Recheck source bytes after training, before declaring the checkpoint preserved.
    validate_sft_checkpoint(directory)
    report["sft_checkpoint_preserved"] = True
    if preflight:
        report["estimated_full_training_seconds"] = (
            report["training_seconds"] / len(order) * len(cases)
        )
        report["status"] = (
            "passed" if delta == 0 and len(report["groups"]) == 4 else "failed"
        )
        return
    if not report["training_signals_passed"]:
        raise ValueError(
            "incomplete GRPO: all groups, nonzero reward variance, and parameter changes are required"
        )
    checkpoint = output / "grpo_checkpoint"
    model.save_pretrained(checkpoint)
    report["adapter_parameter_sha256"] = parameter_digest(trained)
    report["checkpoint_files"] = {
        name: sha256(checkpoint / name)
        for name in ("adapter_config.json", "adapter_model.safetensors")
    }
    write_json(
        checkpoint / "training_metadata.json",
        {
            "provenance": report["provenance"],
            "hyperparameters": asdict(config),
            "adapter_parameter_sha256": report["adapter_parameter_sha256"],
            "checkpoint_files": report["checkpoint_files"],
            "evaluation_generation": report["evaluation_generation"],
        },
    )
    del optimizer, trainable, model, base
    gc.collect()
    torch.cuda.empty_cache()
    report["reload_verification"] = reload_checkpoint(
        checkpoint,
        cases[0],
        expected_digest=report["adapter_parameter_sha256"],
    )
    report["status"] = report["reload_verification"]["status"]
