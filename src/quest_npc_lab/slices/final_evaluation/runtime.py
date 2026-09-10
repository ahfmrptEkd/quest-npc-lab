"""Local cached model inference; no training, model downloads, or retries."""

import gc
import hashlib
from importlib.metadata import version
import json
from typing import Any, cast
from pathlib import Path
import platform
import secrets
import time

from .final_evaluation import RAW_NAME, REPORT_NAME, generate_responses, write_json
from .review import build_blind_review, summarize_review
from quest_npc_lab.slices.evaluation_dataset.evaluation_dataset import (
    validate_eval_freeze,
)
from quest_npc_lab.slices.prompt_evaluation import load_manifest
from quest_npc_lab.slices.prompt_evaluation.prompt_evaluation import (
    MANIFEST_PATH,
    MINIMAL_RULES,
)


def validate_checkpoints(directory: Path) -> dict[str, Any]:
    """Verify supplied frozen bytes and that GRPO continued this exact SFT adapter."""
    from quest_npc_lab.slices.sft_training.runtime import provenance, sha256

    config = load_manifest()
    expected = provenance()
    metadata = {}
    for name in ("sft", "grpo"):
        checkpoint = directory / f"{name}_checkpoint"
        item = json.loads(
            (checkpoint / "training_metadata.json").read_text(encoding="utf-8")
        )
        for filename in ("adapter_config.json", "adapter_model.safetensors"):
            if sha256(checkpoint / filename) != item["checkpoint_files"][filename]:
                raise ValueError(f"{name} checkpoint integrity mismatch")
        source = item["provenance"]
        if name == "sft" and source != expected:
            raise ValueError("SFT frozen prompt or training data provenance mismatch")
        if name == "grpo":
            for field in (
                "model_name",
                "model_revision",
                "prompt_sha256",
                "prompt_version",
                "dataset_sha256",
                "review_sha256",
            ):
                if source[field] != expected[field]:
                    raise ValueError(f"GRPO provenance mismatch: {field}")
            if (
                source["initial_checkpoint"] != "sft_checkpoint"
                or source["initial_adapter_parameter_sha256"]
                != metadata["sft"]["adapter_parameter_sha256"]
                or source["final_evaluation_used"] is not False
                or item["evaluation_generation"] != config["generation"]
            ):
                raise ValueError("GRPO lineage or evaluation settings mismatch")
        metadata[name] = item
    return metadata


def run_generation(output: Path, checkpoint_directory: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    names = (
        RAW_NAME,
        REPORT_NAME,
        "dialogue_review_48_blind.md",
        ".dialogue_review_48_key.json",
        "dialogue_review_48_scores.json",
        "dialogue_review_summary.json",
        "final_evaluation_run.json",
    )
    for name in names:
        if (output / name).exists():
            raise FileExistsError(f"refusing to overwrite preserved evaluation: {name}")
    frozen = validate_eval_freeze()
    metadata = validate_checkpoints(checkpoint_directory)
    config = load_manifest()
    if (
        config["generation"]
        != {"do_sample": False, "temperature": 0.0, "max_new_tokens": 128}
        or config["seed"] != 42
    ):
        raise ValueError("final evaluation requires frozen greedy settings and seed 42")
    grpo_report = json.loads(
        (checkpoint_directory / "grpo_training_report.json").read_text()
    )
    if (
        grpo_report["acceptance_passed"] is not True
        or grpo_report["training_signals_passed"] is not True
        or grpo_report["checkpoint_files"] != metadata["grpo"]["checkpoint_files"]
        or grpo_report["sft_checkpoint_files"] != metadata["sft"]["checkpoint_files"]
    ):
        raise ValueError("GRPO training acceptance or checkpoint evidence mismatch")
    sft_report = json.loads(
        (checkpoint_directory / "sft_training_report.json").read_text()
    )
    warnings = []
    if sft_report["checkpoint_files"] != metadata["sft"]["checkpoint_files"]:
        warnings.append(
            "Supplied SFT matches current checkpoint metadata and GRPO parent, but differs from the historical SFT training report. Historical SFT update/reload evidence does not verify this adapter."
        )

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
    from quest_npc_lab.slices.sft_training.runtime import parameter_digest, snapshot

    torch.set_num_threads(1)
    set_seed(42)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    provenance = {
        "model_name": config["model_name"],
        "model_revision": config["model_revision"],
        "prompt_manifest_sha256": hashlib.sha256(
            MANIFEST_PATH.read_bytes()
        ).hexdigest(),
        "minimal_rules_sha256": hashlib.sha256(MINIMAL_RULES.encode()).hexdigest(),
        "checkpoints": metadata,
        "provenance_warnings": warnings,
        "dataset_sha256": frozen.dataset_sha256,
        "environment": {
            "python": platform.python_version(),
            "device": device,
            "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
            "libraries": {
                name: version(name) for name in ("torch", "transformers", "peft")
            },
            "dtype": config["dtype"],
            "batch_size": 1,
            "torch_num_threads": 1,
        },
        "retries": 0,
        "checkpoint_selection": "user-supplied fixed checkpoints; no final-evaluation selection",
    }
    tokenizer = AutoTokenizer.from_pretrained(
        config["model_name"], revision=config["model_revision"], local_files_only=True
    )
    model: Any = None
    active_condition = None
    count = 0
    started = time.monotonic()

    def generate(condition, prompt):
        nonlocal model, active_condition, count
        if condition != active_condition:
            model = None
            gc.collect()
            if device == "cuda":
                torch.cuda.empty_cache()
            model = cast(
                Any,
                AutoModelForCausalLM.from_pretrained(
                    config["model_name"],
                    revision=config["model_revision"],
                    local_files_only=True,
                    dtype=getattr(torch, config["dtype"]),
                ),
            ).to(device)
            if condition.startswith(("sft_", "grpo_")):
                adapter = condition.split("_")[0]
                model = PeftModel.from_pretrained(
                    model,
                    str(checkpoint_directory / f"{adapter}_checkpoint"),
                    local_files_only=True,
                    is_trainable=False,
                )
                if (
                    parameter_digest(snapshot(model))
                    != metadata[adapter]["adapter_parameter_sha256"]
                ):
                    raise ValueError("loaded adapter parameter identity mismatch")
            model.eval()
            active_condition = condition
            set_seed(42)
        messages = [
            {**message, "content": message["content"].format(formatted_prompt=prompt)}
            for message in config["chat_template"]["messages"]
        ]
        inputs = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        ).to(device)
        length = inputs["input_ids"].shape[1]
        if length > config["input_limits"]["max_input_tokens"]:
            raise ValueError("input exceeds token limit; truncation forbidden")
        with torch.inference_mode():
            tokens = model.generate(
                **inputs,
                **config["generation"],
                pad_token_id=tokenizer.eos_token_id,
                use_cache=True,
            )
        raw = tokenizer.decode(tokens[0, length:].tolist(), skip_special_tokens=True)
        count += 1
        print(
            f"{condition}: {count}/240 responses, {time.monotonic() - started:.1f}s",
            flush=True,
        )
        return raw

    run: dict[str, Any] = {"status": "running", "provenance": provenance}
    write_json(output / "final_evaluation_run.json", run)
    try:
        generate_responses(output / RAW_NAME, generate, provenance=provenance)
        if validate_checkpoints(checkpoint_directory) != metadata:
            raise ValueError("checkpoints changed during evaluation")
        rows = [
            json.loads(line)
            for line in (output / RAW_NAME).read_text(encoding="utf-8").splitlines()
        ]
        markdown, key, scores = build_blind_review(rows, seed=secrets.randbits(64))
        key_path = output / ".dialogue_review_48_key.json"
        with key_path.open("x", encoding="utf-8") as stream:
            key_path.chmod(0o600)
            stream.write(json.dumps(key, ensure_ascii=False, indent=2) + "\n")
        (output / "dialogue_review_48_blind.md").write_text(markdown, encoding="utf-8")
        (output / "dialogue_review_48_scores.json").write_text(
            json.dumps(scores, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_json(output / "dialogue_review_summary.json", summarize_review(scores))
        run.update(status="completed", human_review="pending")
    except Exception as error:
        run.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        run.update(response_count=count, seconds=time.monotonic() - started)
        write_json(output / "final_evaluation_run.json", run)
