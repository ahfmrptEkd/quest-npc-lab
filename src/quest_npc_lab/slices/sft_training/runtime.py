"""Lazy CUDA execution; all training, checkpoint, and log state stays in this slice."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import gc
from importlib.metadata import version
import math
import platform
import json
from pathlib import Path
import time
from typing import Any, cast

from .sft_training import (
    REVIEW_PATH,
    TRAIN_PATH,
    TrainingLog,
    load_training_cases,
    tokenize_example,
    training_example,
    verify_request,
)
from quest_npc_lab.slices.prompt_evaluation import load_manifest
from quest_npc_lab.slices.prompt_evaluation.prompt_evaluation import MANIFEST_PATH


@dataclass(frozen=True)
class Hyperparameters:
    epochs: int = 3
    learning_rate: float = 1e-4
    batch_size: int = 4
    seed: int = 42
    lora_r: int = 8
    lora_alpha: int = 16
    target_modules: tuple[str, ...] = ("q_proj", "v_proj")
    max_training_seconds: int = 900


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_training(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    config = Hyperparameters()
    report = {
        "run_kind": "main_sft",
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "hyperparameters": asdict(config),
    }
    started = time.monotonic()
    try:
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for main SFT")
        train_and_save(directory, config, report)
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
    report["execution_seconds"] = time.monotonic() - started
    write_json(directory / "sft_training_report.json", report)
    return report


def reverify_checkpoint(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "status": "failed",
        "created_at": datetime.now(UTC).isoformat(),
    }
    started = time.monotonic()
    try:
        report = json.loads((directory / "sft_training_report.json").read_text())
        checkpoint = directory / "sft_checkpoint"
        for name, digest in report["checkpoint_files"].items():
            if Path(name).name != name or sha256(checkpoint / name) != digest:
                raise ValueError("checkpoint integrity mismatch")
        if report["status"] != "passed":
            raise ValueError("original training report must have passed")
        if provenance() != report["provenance"]:
            raise ValueError("training data or prompt provenance mismatch")
        result.update(
            reload_checkpoint(
                checkpoint,
                load_training_cases()[0],
                expected_digest=report["adapter_parameter_sha256"],
            )
        )
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    result["execution_seconds"] = time.monotonic() - started
    write_json(directory / "sft_reload_verification.json", result)
    return result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance() -> dict:
    manifest = load_manifest()
    return {
        "model_name": manifest["model_name"],
        "model_revision": manifest["model_revision"],
        "prompt_version": manifest["version"],
        "prompt_sha256": sha256(MANIFEST_PATH),
        "dataset": TRAIN_PATH.name,
        "dataset_sha256": sha256(TRAIN_PATH),
        "review_sha256": sha256(REVIEW_PATH),
        "case_count": 180,
        "initial_checkpoint": "original_base_model",
        "validation_used": False,
        "checkpoint_selection": "final epoch only; no evaluation or seed selection",
    }


def snapshot(model) -> dict:
    return {
        name: parameter.detach().float().cpu().clone()
        for name, parameter in model.named_parameters()
        if "lora_" in name
    }


def parameter_digest(parameters: dict) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(parameters.items()):
        digest.update(name.encode())
        digest.update(str(tuple(tensor.shape)).encode())
        digest.update(tensor.contiguous().numpy().tobytes())
    return digest.hexdigest()


def load_base():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    manifest = load_manifest()
    tokenizer = AutoTokenizer.from_pretrained(
        manifest["model_name"],
        revision=manifest["model_revision"],
        local_files_only=True,
    )
    model = cast(
        Any,
        AutoModelForCausalLM.from_pretrained(
            manifest["model_name"],
            revision=manifest["model_revision"],
            local_files_only=True,
            dtype=getattr(torch, manifest["dtype"]),
        ),
    ).to("cuda")
    return model, tokenizer


def reload_checkpoint(checkpoint: Path, case, *, expected_digest: str) -> dict:
    import torch
    from peft import PeftModel
    from transformers import set_seed

    manifest = load_manifest()
    torch.set_num_threads(1)
    set_seed(manifest["seed"])
    base, tokenizer = load_base()
    model = PeftModel.from_pretrained(
        base, str(checkpoint), local_files_only=True
    ).eval()
    if parameter_digest(snapshot(model)) != expected_digest:
        raise ValueError("reloaded adapter parameters differ from trained weights")

    def generate(prompt):
        messages = [
            {**message, "content": message["content"].format(formatted_prompt=prompt)}
            for message in manifest["chat_template"]["messages"]
        ]
        inputs = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=manifest["chat_template"]["add_generation_prompt"],
            return_tensors="pt",
            return_dict=True,
        ).to("cuda")
        length = inputs["input_ids"].shape[1]
        if length > manifest["input_limits"]["max_input_tokens"]:
            raise ValueError("input token limit exceeded")
        with torch.inference_mode():
            output = model.generate(**inputs, **manifest["generation"])
        return tokenizer.decode(output[0, length:], skip_special_tokens=True)

    result = verify_request(case, generate)
    result["matches_trained_weights"] = True
    result["generation"] = manifest["generation"]
    return result


def train_and_save(directory: Path, config: Hyperparameters, report: dict) -> None:
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import TrainerCallback, set_seed
    from trl.trainer.sft_config import SFTConfig
    from trl.trainer.sft_trainer import SFTTrainer

    cases = load_training_cases()
    manifest = load_manifest()
    report["provenance"] = provenance()
    report["environment"] = {
        "python": platform.python_version(),
        "device": "cuda",
        "gpu": torch.cuda.get_device_name(0),
        "cuda_version": torch.version.cuda,
        "libraries": {
            name: version(name)
            for name in (
                "torch",
                "transformers",
                "peft",
                "trl",
                "datasets",
                "accelerate",
            )
        },
        "torch_num_threads": 1,
    }
    torch.set_num_threads(1)
    set_seed(config.seed)
    torch.cuda.reset_peak_memory_stats()
    model, tokenizer = load_base()
    examples = [
        tokenize_example(
            training_example(case),
            tokenizer,
            max_input_tokens=manifest["input_limits"]["max_input_tokens"],
        )
        for case in cases
    ]
    report["tokenization"] = {
        "max_sequence_tokens": max(len(e["input_ids"]) for e in examples),
        "truncated": False,
        "completion_only_loss": True,
    }
    log = TrainingLog(
        directory / "sft_training_steps.jsonl", max_seconds=config.max_training_seconds
    )
    report["loss_trajectory"] = log.rows

    class LossCallback(TrainerCallback):
        def on_step_begin(self, args, state, control, **kwargs):
            torch.cuda.synchronize()
            self.started = time.monotonic()

        def on_log(self, args, state, control, logs=None, **kwargs):
            if logs is not None and "loss" in logs:
                torch.cuda.synchronize()
                log.record(
                    step=state.global_step,
                    loss=float(logs["loss"]),
                    seconds=time.monotonic() - self.started,
                )
                if not math.isfinite(float(logs.get("grad_norm", 0))):
                    raise ValueError("non-finite gradient norm")
                print(f"step {state.global_step}: loss={logs['loss']:.4f}", flush=True)

    bf16 = torch.cuda.is_bf16_supported()
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=Dataset.from_list(examples),
        peft_config=LoraConfig(
            r=config.lora_r,
            lora_alpha=config.lora_alpha,
            target_modules=list(config.target_modules),
            lora_dropout=0.0,
            task_type="CAUSAL_LM",
        ),
        args=SFTConfig(
            output_dir=str(directory / "sft_trainer"),
            num_train_epochs=config.epochs,
            per_device_train_batch_size=config.batch_size,
            gradient_accumulation_steps=1,
            learning_rate=config.learning_rate,
            lr_scheduler_type="constant",
            warmup_steps=0,
            optim="adamw_torch",
            weight_decay=0.0,
            max_grad_norm=1.0,
            seed=config.seed,
            data_seed=config.seed,
            bf16=bf16,
            fp16=False,
            gradient_checkpointing=False,
            logging_steps=1,
            logging_nan_inf_filter=False,
            save_strategy="no",
            eval_strategy="no",
            report_to="none",
            disable_tqdm=True,
            max_length=None,
            packing=False,
            completion_only_loss=True,
            loss_type="chunked_nll",
        ),
        callbacks=[LossCallback()],
    )
    report["training_settings"] = {
        "base_dtype": manifest["dtype"],
        "mixed_precision": "bf16" if bf16 else "none",
        "gradient_accumulation_steps": 1,
        "gradient_checkpointing": False,
        "optimizer": "adamw_torch",
        "lr_scheduler": "constant",
        "warmup_steps": 0,
        "weight_decay": 0.0,
        "max_grad_norm": 1.0,
        "lora_dropout": 0.0,
        "loss_type": "chunked_nll",
        "packing": False,
        "save_strategy": "final only",
        "stop_policy": "135 steps maximum; 900 training seconds checked after each step; no retries",
    }
    before = snapshot(trainer.model)
    started = time.monotonic()
    trainer.train()
    report["training_seconds"] = time.monotonic() - started
    trained = snapshot(trainer.model)
    delta = math.sqrt(
        sum(float((trained[name] - old).pow(2).sum()) for name, old in before.items())
    )
    report.update(
        log.finish(
            parameter_delta_norm=delta,
            expected_steps=math.ceil(len(cases) / config.batch_size) * config.epochs,
        )
    )
    report["trainable_parameter_count"] = sum(t.numel() for t in trained.values())
    report["changed_tensor_count"] = sum(
        not torch.equal(old, trained[name]) for name, old in before.items()
    )
    report["adapter_parameter_sha256"] = parameter_digest(trained)
    report["peak_cuda_memory_gb"] = torch.cuda.max_memory_allocated() / 1024**3
    checkpoint = directory / "sft_checkpoint"
    cast(Any, trainer.model).save_pretrained(checkpoint)
    report["checkpoint_files"] = {
        name: sha256(checkpoint / name)
        for name in ("adapter_config.json", "adapter_model.safetensors")
    }
    write_json(
        checkpoint / "training_metadata.json",
        {
            "provenance": report["provenance"],
            "hyperparameters": report["hyperparameters"],
            "adapter_parameter_sha256": report["adapter_parameter_sha256"],
            "checkpoint_files": report["checkpoint_files"],
        },
    )
    del trainer, model
    gc.collect()
    torch.cuda.empty_cache()
    report["reload_verification"] = reload_checkpoint(
        checkpoint, cases[0], expected_digest=report["adapter_parameter_sha256"]
    )
    report["status"] = report["reload_verification"]["status"]
