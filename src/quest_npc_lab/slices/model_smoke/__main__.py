"""On-demand real-model smoke run: inference → LoRA SFT → reload → GRPO.

Run with ``uv run python -m quest_npc_lab.slices.model_smoke``. Heavy libraries
are imported inside the phases so unit tests never load them.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import gc
import json
import os
from pathlib import Path
import platform
import shutil
import time
import traceback

from quest_npc_lab.slices.dataset_pipeline import (
    DatasetCase,
    build_model_prompt,
    load_pilot_dataset,
    prepare_training_cases,
)
from quest_npc_lab.slices.guild_receptionist import Action

from .model_smoke import (
    build_smoke_report,
    grpo_example,
    parameter_diff,
    run_inference_smoke,
    sft_example,
    strict_action_reward,
    summarize_reward_groups,
)

MODEL_NAME = "Qwen/Qwen2.5-0.5B-Instruct"
MODEL_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
MODEL_LICENSE = "apache-2.0"
LORA_TARGET_MODULES = ("q_proj", "v_proj")
CANDIDATE_NOTE = (
    "티켓의 초기 후보 Qwen3-0.6B 대신 작업 지시의 Qwen2.5-0.5B-Instruct를 검증했다. "
    "Qwen3-0.6B는 이번 스모크에서 실행하지 않았다."
)
STOP_POLICY = (
    "각 단계는 고정 스텝만 실행하고 재시도하지 않는다. 단계 실패는 차단 사유로 "
    "기록하며 SFT 어댑터가 없으면 GRPO를 건너뛴다."
)


@dataclass(frozen=True, slots=True)
class SmokeLimits:
    seed: int = 42
    max_new_tokens: int = 128
    sft_cases: int = 2
    sft_steps: int = 1
    sft_learning_rate: float = 1e-4
    grpo_prompts: int = 2
    num_generations: int = 4
    grpo_steps: int = 1
    grpo_learning_rate: float = 1e-5
    grpo_temperature: float = 1.0
    lora_r: int = 8
    lora_alpha: int = 16


@dataclass(frozen=True, slots=True)
class Runtime:
    device: str
    limits: SmokeLimits
    smoke_dir: Path

    @property
    def use_bf16(self) -> bool:
        import torch

        return self.device == "cuda" and torch.cuda.is_bf16_supported()


def _case_id(index: int) -> str:
    """파일럿 JSONL 줄 번호(1부터)를 사례 식별자로 쓴다."""
    return f"pilot-{index + 1:03d}"


def _guard(phase: Callable[[], dict[str, object]]) -> dict[str, object]:
    # 호환성 실패도 결과이므로 보고서를 잃지 않고 차단 사유로 남긴다.
    try:
        return phase()
    except Exception as error:  # noqa: BLE001
        traceback.print_exc()
        return {"status": "failed", "error": f"{type(error).__name__}: {error}"}


def _reset_peak_memory(device: str) -> None:
    import torch

    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()


def _peak_memory_gb(device: str) -> float | None:
    import torch

    if device != "cuda":
        return None
    return round(torch.cuda.max_memory_allocated() / 1024**3, 3)


def _load_base(runtime: Runtime, *, padding_side: str = "right"):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_NAME, revision=MODEL_REVISION, padding_side=padding_side
    )
    dtype = torch.bfloat16 if runtime.use_bf16 else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME, revision=MODEL_REVISION, dtype=dtype
    ).to(runtime.device)
    return model, tokenizer


def _snapshot(model, *, lora_only: bool = False) -> dict[str, object]:
    return {
        name: parameter.detach().float().cpu().clone()
        for name, parameter in model.named_parameters()
        if ("lora_" in name if lora_only else parameter.requires_grad)
    }


def _greedy_generator(model, tokenizer, max_new_tokens: int, stats: dict):
    import torch

    def generate(prompt: str) -> str:
        inputs = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        ).to(model.device)
        start = time.perf_counter()
        with torch.no_grad():
            output = model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False
            )
        seconds = time.perf_counter() - start
        new_tokens = output[0, inputs["input_ids"].shape[1] :]
        stats.update(
            prompt_tokens=int(inputs["input_ids"].shape[1]),
            new_tokens=int(new_tokens.numel()),
            generation_seconds=round(seconds, 3),
            tokens_per_second=round(new_tokens.numel() / seconds, 2),
            hit_max_new_tokens=int(new_tokens.numel()) >= max_new_tokens,
        )
        return tokenizer.decode(new_tokens, skip_special_tokens=True)

    return generate


def _inference_record(model, tokenizer, case: DatasetCase, runtime: Runtime) -> dict:
    stats: dict[str, object] = {}
    generate = _greedy_generator(model, tokenizer, runtime.limits.max_new_tokens, stats)
    artifact = run_inference_smoke(case, generate)
    return {
        "status": "ok",
        "prompt": build_model_prompt(case),
        **stats,
        "artifact": artifact,
    }


def inference_phase(case: DatasetCase, runtime: Runtime) -> dict[str, object]:
    _reset_peak_memory(runtime.device)
    model, tokenizer = _load_base(runtime)
    record = _inference_record(model, tokenizer, case, runtime)
    record["model_parameter_count"] = sum(p.numel() for p in model.parameters())
    record["peak_memory_gb"] = _peak_memory_gb(runtime.device)
    return record


def _reload_check(
    adapter_dir: Path, trained: dict, case: DatasetCase, runtime: Runtime
) -> dict[str, object]:
    from peft import PeftModel

    base, tokenizer = _load_base(runtime)
    model = PeftModel.from_pretrained(base, str(adapter_dir))
    loaded = _snapshot(model, lora_only=True)
    matches = (
        set(loaded) == set(trained) and not parameter_diff(trained, loaded)["changed"]
    )
    inference = _inference_record(model, tokenizer, case, runtime)
    return {"status": "ok", "matches_trained_weights": matches, "inference": inference}


def sft_phase(cases: Sequence[DatasetCase], runtime: Runtime) -> dict[str, object]:
    from datasets import Dataset
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    limits = runtime.limits
    _reset_peak_memory(runtime.device)
    model, tokenizer = _load_base(runtime)
    trainer = SFTTrainer(
        model=model,
        args=SFTConfig(
            output_dir=str(runtime.smoke_dir / "sft_trainer"),
            max_steps=limits.sft_steps,
            per_device_train_batch_size=len(cases),
            learning_rate=limits.sft_learning_rate,
            logging_steps=1,
            save_strategy="no",
            report_to="none",
            seed=limits.seed,
            bf16=runtime.use_bf16,
            use_cpu=runtime.device == "cpu",
            gradient_checkpointing=False,
        ),
        train_dataset=Dataset.from_list([sft_example(case) for case in cases]),
        processing_class=tokenizer,
        peft_config=LoraConfig(
            r=limits.lora_r,
            lora_alpha=limits.lora_alpha,
            lora_dropout=0.0,
            target_modules=list(LORA_TARGET_MODULES),
            task_type="CAUSAL_LM",
        ),
    )
    before = _snapshot(trainer.model)
    start = time.perf_counter()
    trainer.train()
    seconds = time.perf_counter() - start
    trained = _snapshot(trainer.model)
    adapter_dir = runtime.smoke_dir / "sft_adapter"
    trainer.model.save_pretrained(str(adapter_dir))
    record: dict[str, object] = {
        "status": "ok",
        "adapter_dir": str(adapter_dir),
        "trainable_parameter_count": sum(t.numel() for t in trained.values()),
        "train_seconds": round(seconds, 3),
        "seconds_per_case": round(seconds / (len(cases) * limits.sft_steps), 3),
        "peak_memory_gb": _peak_memory_gb(runtime.device),
        "weight_diff": parameter_diff(before, trained),
        "log_history": trainer.state.log_history,
    }
    del trainer, model
    _reset_peak_memory(runtime.device)
    record["reload"] = _guard(
        lambda: _reload_check(adapter_dir, trained, cases[0], runtime)
    )
    return record


def _grpo_reward(rewards_by_group: dict[str, list[float]], samples: list[dict]):
    def action_reward(completions, ground_truth_action, case_id, **_) -> list[float]:
        rewards = []
        for completion, truth, group in zip(completions, ground_truth_action, case_id):
            text = (
                completion[-1]["content"]
                if isinstance(completion, list)
                else completion
            )
            reward = strict_action_reward(text, Action(truth))
            rewards_by_group.setdefault(group, []).append(reward)
            samples.append({"case_id": group, "raw_output": text, "reward": reward})
            rewards.append(reward)
        return rewards

    return action_reward


def grpo_phase(
    adapter_dir: Path, cases: dict[str, DatasetCase], runtime: Runtime
) -> dict[str, object]:
    from datasets import Dataset
    from peft import PeftModel
    from trl import GRPOConfig, GRPOTrainer

    limits = runtime.limits
    _reset_peak_memory(runtime.device)
    base, tokenizer = _load_base(runtime, padding_side="left")
    model = PeftModel.from_pretrained(base, str(adapter_dir), is_trainable=True)
    rewards_by_group: dict[str, list[float]] = {}
    samples: list[dict] = []
    trainer = GRPOTrainer(
        model=model,
        reward_funcs=_grpo_reward(rewards_by_group, samples),
        args=GRPOConfig(
            output_dir=str(runtime.smoke_dir / "grpo_trainer"),
            max_steps=limits.grpo_steps,
            per_device_train_batch_size=len(cases) * limits.num_generations,
            num_generations=limits.num_generations,
            max_completion_length=limits.max_new_tokens,
            temperature=limits.grpo_temperature,
            learning_rate=limits.grpo_learning_rate,
            beta=0.0,
            logging_steps=1,
            save_strategy="no",
            report_to="none",
            seed=limits.seed,
            bf16=runtime.use_bf16,
            use_cpu=runtime.device == "cpu",
            gradient_checkpointing=False,
        ),
        train_dataset=Dataset.from_list(
            [grpo_example(case, case_id=case_id) for case_id, case in cases.items()]
        ),
        processing_class=tokenizer,
    )
    before = _snapshot(trainer.model)
    start = time.perf_counter()
    trainer.train()
    seconds = time.perf_counter() - start
    return {
        "status": "ok",
        "case_ids": list(cases),
        "train_seconds": round(seconds, 3),
        "seconds_per_prompt": round(seconds / (len(cases) * limits.grpo_steps), 3),
        "peak_memory_gb": _peak_memory_gb(runtime.device),
        "reward_groups": summarize_reward_groups(rewards_by_group),
        "parameter_diff": parameter_diff(before, _snapshot(trainer.model)),
        "trl_config": {
            key: getattr(trainer.args, key)
            for key in ("loss_type", "scale_rewards", "beta", "generation_batch_size")
        },
        "samples": samples,
        "log_history": trainer.state.log_history,
    }


def inspect_environment(device: str) -> dict[str, object]:
    import accelerate
    import datasets
    import peft
    import torch
    import transformers
    import trl

    environment: dict[str, object] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "libraries": {
            module.__name__: module.__version__
            for module in (torch, transformers, peft, trl, accelerate, datasets)
        },
        "device": device,
        "cuda_available": torch.cuda.is_available(),
        "torch_cuda_version": torch.version.cuda,
        "host_memory_total_gb": round(
            os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 2
        ),
        "disk_free_gb": round(shutil.disk_usage(".").free / 1024**3, 1),
        "model": {
            "name": MODEL_NAME,
            "revision": MODEL_REVISION,
            "license": MODEL_LICENSE,
            "note": CANDIDATE_NOTE,
        },
    }
    if device == "cuda":
        properties = torch.cuda.get_device_properties(0)
        environment["gpu"] = {
            "name": properties.name,
            "total_vram_gb": round(properties.total_memory / 1024**3, 2),
            "bf16_supported": torch.cuda.is_bf16_supported(),
        }
    return environment


def run_smoke(runtime: Runtime) -> dict[str, object]:
    from transformers import set_seed

    limits = runtime.limits
    set_seed(limits.seed)
    cases = prepare_training_cases(load_pilot_dataset())
    if limits.sft_cases + limits.grpo_prompts > len(cases):
        raise ValueError(
            f"smoke needs {limits.sft_cases + limits.grpo_prompts} pilot cases, "
            f"only {len(cases)} are approved"
        )
    # SFT와 GRPO는 서로 다른 파일럿 사례를 쓴다.
    sft_cases = cases[: limits.sft_cases]
    grpo_cases = {
        _case_id(index): cases[index]
        for index in range(limits.sft_cases, limits.sft_cases + limits.grpo_prompts)
    }
    phases: dict[str, object] = {
        "inference": _guard(lambda: inference_phase(cases[0], runtime))
    }
    sft = _guard(lambda: sft_phase(sft_cases, runtime))
    phases["sft"] = sft
    if sft["status"] == "ok":
        adapter_dir = Path(str(sft["adapter_dir"]))
        phases["grpo"] = _guard(lambda: grpo_phase(adapter_dir, grpo_cases, runtime))
    else:
        phases["grpo"] = {"status": "skipped", "error": "SFT adapter is unavailable"}
    report = build_smoke_report(
        environment=inspect_environment(runtime.device),
        limits={
            **asdict(limits),
            "lora_target_modules": list(LORA_TARGET_MODULES),
            "inference_decoding": "greedy (do_sample=False)",
            "sft_case_ids": [_case_id(i) for i in range(limits.sft_cases)],
            "inference_case_id": _case_id(0),
            "chat_template": "tokenizer default (Qwen2.5 system prompt), single user turn",
            "stop_policy": STOP_POLICY,
        },
        phases=phases,
    )
    return {"created_at": datetime.now(UTC).isoformat(timespec="seconds"), **report}


def _int_at_least(minimum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        number = int(value)
        if number < minimum:
            raise argparse.ArgumentTypeError(f"must be >= {minimum}")
        return number

    return parse


def _parser() -> argparse.ArgumentParser:
    defaults = SmokeLimits()
    parser = argparse.ArgumentParser(
        description="Run the bounded real-model smoke validation."
    )
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument(
        "--max-new-tokens", type=_int_at_least(1), default=defaults.max_new_tokens
    )
    # GRPO는 그룹 안 후보가 2개 이상이어야 상대적 보상 차이를 볼 수 있다.
    parser.add_argument(
        "--num-generations", type=_int_at_least(2), default=defaults.num_generations
    )
    parser.add_argument(
        "--grpo-prompts", type=_int_at_least(1), default=defaults.grpo_prompts
    )
    parser.add_argument("--smoke-dir", type=Path, default=Path("artifacts/smoke"))
    parser.add_argument(
        "--report", type=Path, default=Path("artifacts/smoke_validation_report.json")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    import torch

    arguments = _parser().parse_args(argv)
    device = arguments.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    runtime = Runtime(
        device=device,
        limits=SmokeLimits(
            seed=arguments.seed,
            max_new_tokens=arguments.max_new_tokens,
            num_generations=arguments.num_generations,
            grpo_prompts=arguments.grpo_prompts,
        ),
        smoke_dir=arguments.smoke_dir,
    )
    report = run_smoke(runtime)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{report['status']}: {arguments.report}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
