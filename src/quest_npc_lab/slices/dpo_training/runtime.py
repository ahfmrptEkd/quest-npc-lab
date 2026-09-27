"""One bounded DPO run with an explicit frozen SFT reference and durable evidence."""

import gc
from importlib.metadata import version
import json
import math
from pathlib import Path
import time

from .dpo_training import build_pairs
from quest_npc_lab.slices.grpo_training.runtime import validate_sft_checkpoint
from quest_npc_lab.slices.sft_training.runtime import (
    load_base,
    parameter_digest,
    reload_checkpoint,
    sha256,
    snapshot,
    write_json,
)
from quest_npc_lab.slices.sft_training.sft_training import (
    load_training_cases,
    TrainingLog,
)


def validate_source(source):
    metadata = validate_sft_checkpoint(source)
    sft = json.loads((source / "sft_training_report.json").read_text())
    grpo = json.loads((source / "grpo_training_report.json").read_text())
    groups = [
        json.loads(x)
        for x in (source / "grpo_training_groups.jsonl").read_text().splitlines()
    ]
    if (
        sft["status"] != "passed"
        or grpo["status"] != "passed"
        or sft["checkpoint_files"] != metadata["checkpoint_files"]
        or sft["adapter_parameter_sha256"] != metadata["adapter_parameter_sha256"]
        or grpo["provenance"]["initial_adapter_parameter_sha256"]
        != metadata["adapter_parameter_sha256"]
        or grpo["sft_checkpoint_files"] != metadata["checkpoint_files"]
        or groups != grpo["groups"]
        or len(groups) != 180
    ):
        raise ValueError("source reports, SFT identity or GRPO trajectory mismatch")
    pairs = build_pairs(groups)
    hashes = {
        n: sha256(source / n)
        for n in (
            "sft_checkpoint/adapter_config.json",
            "sft_checkpoint/adapter_model.safetensors",
            "sft_checkpoint/training_metadata.json",
            "sft_training_report.json",
            "grpo_training_report.json",
            "grpo_training_groups.jsonl",
        )
    }
    return metadata, pairs, hashes


def train(source: Path, output: Path):
    import torch
    from datasets import Dataset
    from peft import PeftModel
    from transformers import TrainerCallback, set_seed
    from trl import DPOConfig, DPOTrainer

    metadata, pairs, hashes = validate_source(source)
    report = {
        "status": "running",
        "source_hashes": hashes,
        "initial_adapter_parameter_sha256": metadata["adapter_parameter_sha256"],
        "pair_count": len(pairs),
        "human_preferences": False,
        "pair_source": "mixed reward groups from evolving GRPO policies",
        "hyperparameters": {
            "seed": 42,
            "epochs": 1,
            "batch_size": 2,
            "learning_rate": 1e-5,
            "beta": 0.1,
            "loss": "sigmoid",
            "max_training_seconds": 900,
        },
        "environment": {
            n: version(n) for n in ("torch", "trl", "transformers", "peft")
        },
    }
    report["implementation_sha256"] = {
        p.name: sha256(p) for p in Path(__file__).parent.glob("*.py")
    }
    write_json(output / "training_report.json", report)
    pair_path = output / "pairs.jsonl"
    with pair_path.open("x") as stream:
        for pair in pairs:
            stream.write(json.dumps(pair, ensure_ascii=False) + "\n")
    report["pairs_sha256"] = sha256(pair_path)
    try:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required")
        torch.set_num_threads(1)
        set_seed(42)
        base, tokenizer = load_base()
        model = PeftModel.from_pretrained(
            base,
            str(source / "sft_checkpoint"),
            is_trainable=True,
            local_files_only=True,
        )
        del base
        ref_base, _ = load_base()
        reference = PeftModel.from_pretrained(
            ref_base,
            str(source / "sft_checkpoint"),
            is_trainable=False,
            local_files_only=True,
        )
        del ref_base
        reference.requires_grad_(False)
        reference.eval()
        before = snapshot(model)
        initial = parameter_digest(before)
        if (
            initial != metadata["adapter_parameter_sha256"]
            or parameter_digest(snapshot(reference)) != initial
        ):
            raise ValueError(
                "policy and frozen reference must both equal preserved SFT"
            )
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        examples = [{k: p[k] for k in ("prompt", "chosen", "rejected")} for p in pairs]
        lengths = [
            len(tokenizer.apply_chat_template(p["prompt"] + p[k], tokenize=True))
            for p in examples
            for k in ("chosen", "rejected")
        ]
        report["max_sequence_tokens"] = max(lengths)
        log = TrainingLog(output / "steps.jsonl", max_seconds=900)

        class Callback(TrainerCallback):
            def on_train_begin(self, args, state, control, **kwargs):
                self.last = time.monotonic()

            def on_log(self, args, state, control, logs=None, **kwargs):
                if logs and "loss" in logs:
                    now = time.monotonic()
                    log.record(
                        step=state.global_step,
                        loss=float(logs["loss"]),
                        seconds=now - self.last,
                    )
                    self.last = now
                    print(
                        f"DPO step {state.global_step}: loss={logs['loss']}", flush=True
                    )

        trainer = DPOTrainer(
            model=model,
            ref_model=reference,
            processing_class=tokenizer,
            train_dataset=Dataset.from_list(examples),
            callbacks=[Callback()],
            args=DPOConfig(
                output_dir=str(output / "trainer"),
                num_train_epochs=1,
                per_device_train_batch_size=2,
                learning_rate=1e-5,
                beta=0.1,
                loss_type=["sigmoid"],
                lr_scheduler_type="constant",
                warmup_steps=0,
                optim="adamw_torch",
                weight_decay=0.0,
                max_grad_norm=1.0,
                seed=42,
                data_seed=42,
                bf16=True,
                fp16=False,
                gradient_checkpointing=False,
                max_length=None,
                logging_steps=1,
                logging_nan_inf_filter=False,
                save_strategy="no",
                eval_strategy="no",
                report_to="none",
                disable_tqdm=True,
            ),
        )
        if any(p.requires_grad for p in reference.parameters()):
            raise ValueError("reference model must stay frozen")
        started = time.monotonic()
        trainer.train()
        report["training_seconds"] = time.monotonic() - started
        after = snapshot(model)
        delta = math.sqrt(
            sum(float((after[n] - v).pow(2).sum()) for n, v in before.items())
        )
        report.update(
            log.finish(
                parameter_delta_norm=delta, expected_steps=math.ceil(len(pairs) / 2)
            )
        )
        report["changed_tensor_count"] = sum(
            not torch.equal(v, after[n]) for n, v in before.items()
        )
        report["adapter_parameter_sha256"] = parameter_digest(after)
        if parameter_digest(snapshot(reference)) != initial:
            raise ValueError("reference adapter changed")
        if validate_source(source)[2] != hashes:
            raise ValueError("source changed during training")
        report["reference_unchanged"] = True
        checkpoint = output / "dpo_checkpoint"
        model.save_pretrained(str(checkpoint))
        report["checkpoint_files"] = {
            n: sha256(checkpoint / n)
            for n in ("adapter_config.json", "adapter_model.safetensors")
        }
        report["peak_cuda_memory_gb"] = torch.cuda.max_memory_allocated() / 1024**3
        write_json(
            checkpoint / "training_metadata.json",
            {
                k: report[k]
                for k in (
                    "source_hashes",
                    "initial_adapter_parameter_sha256",
                    "adapter_parameter_sha256",
                    "checkpoint_files",
                    "pairs_sha256",
                    "hyperparameters",
                )
            },
        )
        del trainer, model, reference
        gc.collect()
        torch.cuda.empty_cache()
        report["reload_verification"] = reload_checkpoint(
            checkpoint,
            load_training_cases()[0],
            expected_digest=report["adapter_parameter_sha256"],
        )
        if not report["reload_verification"]["matches_trained_weights"]:
            raise ValueError("DPO checkpoint reload identity mismatch")
        # A malformed answer is a model-quality result, not a weight reload failure.
        report["status"] = "passed"
        return report
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        write_json(output / "training_report.json", report)
