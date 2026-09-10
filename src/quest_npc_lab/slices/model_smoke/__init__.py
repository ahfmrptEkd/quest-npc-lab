"""Small real-model smoke validation for inference, LoRA SFT, and GRPO."""

from .model_smoke import (
    build_smoke_report,
    grpo_example,
    parameter_diff,
    run_inference_smoke,
    sft_example,
    strict_action_reward,
    summarize_reward_groups,
)

__all__ = [
    "build_smoke_report",
    "grpo_example",
    "parameter_diff",
    "run_inference_smoke",
    "sft_example",
    "strict_action_reward",
    "summarize_reward_groups",
]
