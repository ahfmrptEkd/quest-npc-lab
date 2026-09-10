"""Terminal reward and group-relative training evidence; no server intervention."""

import math
from statistics import fmean, pstdev
from typing import Any

from quest_npc_lab.slices.guild_receptionist import Action
from quest_npc_lab.slices.guild_receptionist.receptionist_slice import (
    OutputParseError,
    parse_model_output,
)


def evaluate_group(
    raw_responses: list[str], ground_truth: Action, *, epsilon=1e-4
) -> dict[str, Any]:
    """Score raw completions with exact 1/0 rewards and population-standardized advantages."""
    if len(raw_responses) < 2 or not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError(
            "a group needs at least two candidates and positive finite epsilon"
        )
    rewards = []
    for raw in raw_responses:
        try:
            rewards.append(float(parse_model_output(raw).action == ground_truth))
        except OutputParseError:
            rewards.append(0.0)
    mean, std = fmean(rewards), pstdev(rewards)
    return {
        "raw_responses": raw_responses,
        "rewards": rewards,
        "reward_mean": mean,
        "reward_std": std,
        "advantages": [(reward - mean) / (std + epsilon) for reward in rewards],
        "has_reward_variance": std > 0,
    }


def training_prompt(case) -> list[dict[str, str]]:
    """Project only state and utterance into the frozen chat template."""
    from quest_npc_lab.slices.prompt_evaluation import format_prompt, load_manifest
    from quest_npc_lab.slices.sft_training.sft_training import case_state

    if case.split != "train" or case.review_status != "user_approved":
        raise ValueError("GRPO requires user-approved train cases")
    prompt = format_prompt(case_state(case), case.player_utterance)
    return [
        {**message, "content": message["content"].format(formatted_prompt=prompt)}
        for message in load_manifest()["chat_template"]["messages"]
    ]


def summarize_run(
    groups, *, group_size, expected_groups, parameter_delta_norm
) -> dict[str, Any]:
    """Report incomplete or signal-free runs honestly; never infer success from steps."""
    differing = sum(group["has_reward_variance"] for group in groups)
    finite_delta = math.isfinite(parameter_delta_norm) and parameter_delta_norm > 0
    return {
        "group_size": group_size,
        "group_count": len(groups),
        "step_count": sum(group["optimizer_step"] for group in groups),
        "groups_with_differing_rewards": differing,
        "groups_with_identical_rewards": len(groups) - differing,
        "nonzero_reward_variance_fraction": differing / len(groups) if groups else 0.0,
        "policy_loss_curve": [group["policy_loss"] for group in groups],
        "parameter_delta_norm": parameter_delta_norm
        if math.isfinite(parameter_delta_norm)
        else None,
        "training_signals_passed": bool(
            len(groups) == expected_groups
            and differing
            and finite_delta
            and all(len(group["rewards"]) == group_size for group in groups)
            and any(group["optimizer_step"] for group in groups)
        ),
    }
