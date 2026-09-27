"""Train-only pair construction and raw-output evaluation boundaries."""

from quest_npc_lab.slices.sft_training.sft_training import load_training_cases
from quest_npc_lab.slices.grpo_training.grpo_training import (
    evaluate_group,
    training_prompt,
)


def build_pairs(groups):
    cases = {f"train-{i:03d}": c for i, c in enumerate(load_training_cases(), 1)}
    pairs = []
    seen = set()
    for group in groups:
        key = group["case_id"]
        if key not in cases or key in seen:
            raise ValueError("unknown or duplicate training case")
        seen.add(key)
        case = cases[key]
        if group["ground_truth_action"] != case.ground_truth_action.value:
            raise ValueError("ground truth differs from approved training case")
        raw = group["raw_responses"]
        if len(raw) != 4 or any(not isinstance(x, str) for x in raw):
            raise ValueError("expected four raw string responses")
        rewards = evaluate_group(raw, case.ground_truth_action)["rewards"]
        if rewards != group["rewards"]:
            raise ValueError("recorded rewards differ from recomputed rewards")
        if set(rewards) != {0.0, 1.0}:
            continue
        chosen, rejected = rewards.index(1.0), rewards.index(0.0)
        pairs.append(
            {
                "case_id": key,
                "prompt": training_prompt(case),
                "chosen": [{"role": "assistant", "content": raw[chosen]}],
                "rejected": [{"role": "assistant", "content": raw[rejected]}],
                "chosen_index": chosen,
                "rejected_index": rejected,
            }
        )
    if not pairs:
        raise ValueError("no mixed-reward training pairs")
    return pairs


def summarize(rows):
    from quest_npc_lab.slices.final_evaluation.final_evaluation import (
        metrics,
        score_raw,
    )

    scored = [{**r, "artifact": score_raw(r)} for r in rows]
    result = metrics(scored)
    eligible = [r for r in scored if r["ground_truth_action"] != "grant_reward"]
    wrong = sum(r["artifact"]["model_action"] == "grant_reward" for r in eligible)
    result.update(
        wrong_grants=wrong,
        wrong_grant_denominator=len(eligible),
        wrong_grant_rate=wrong / len(eligible) if eligible else None,
    )
    return result
