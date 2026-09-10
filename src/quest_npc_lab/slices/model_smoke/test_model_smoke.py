from __future__ import annotations

import pytest

from quest_npc_lab.slices.guild_receptionist import Action
from quest_npc_lab.slices.model_smoke import (
    strict_action_reward,
    summarize_reward_groups,
)


@pytest.mark.parametrize(
    ("raw_output", "expected"),
    [
        ('{"action":"grant_reward","dialogue":"지급합니다."}', 1.0),
        ('  {"action":"grant_reward","dialogue":"지급합니다."}\n', 1.0),
        ('{"action":"other","dialogue":"안녕하세요."}', 0.0),
        ('```json\n{"action":"grant_reward","dialogue":"지급합니다."}\n```', 0.0),
        ('{"action":"grant_reward","dialogue":"지급합니다.","extra":1}', 0.0),
        ('{"action":"grant_reward","dialogue":"   "}', 0.0),
        ("보상을 드릴게요.", 0.0),
    ],
)
def test_reward_is_one_only_for_valid_format_and_correct_action(
    raw_output: str, expected: float
) -> None:
    assert strict_action_reward(raw_output, Action.GRANT_REWARD) == expected


def test_reward_groups_report_relative_signal_only_when_some_group_varies() -> None:
    varied = summarize_reward_groups({"a": [1.0, 0.0, 0.0, 1.0], "b": [0.0, 0.0]})

    assert varied == {
        "group_count": 2,
        "varied_group_count": 1,
        "identical_group_count": 1,
        "identical_group_ratio": 0.5,
        "has_relative_signal": True,
        "rewards_by_group": {"a": [1.0, 0.0, 0.0, 1.0], "b": [0.0, 0.0]},
    }

    flat = summarize_reward_groups({"a": [0.0, 0.0], "b": [1.0, 1.0]})
    assert flat["has_relative_signal"] is False
    assert flat["identical_group_ratio"] == 1.0


def test_reward_groups_without_any_group_have_no_signal() -> None:
    empty = summarize_reward_groups({})

    assert empty["group_count"] == 0
    assert empty["identical_group_ratio"] is None
    assert empty["has_relative_signal"] is False


def _grant_case():
    from quest_npc_lab.slices.dataset_pipeline import load_pilot_dataset

    case = load_pilot_dataset()[0]
    assert case.ground_truth_action is Action.GRANT_REWARD
    return case


def _assert_no_answer_leak(prompt: str, case) -> None:
    from quest_npc_lab.slices.dataset_pipeline import build_model_prompt

    assert prompt == build_model_prompt(case)
    assert case.reference_dialogue not in prompt
    assert case.player_intent not in prompt
    assert "ground_truth" not in prompt


def test_inference_smoke_routes_real_output_through_request_pipeline() -> None:
    from quest_npc_lab.slices.model_smoke import run_inference_smoke

    case = _grant_case()
    prompts: list[str] = []

    def generate(prompt: str) -> str:
        prompts.append(prompt)
        return '{"action":"grant_reward","dialogue":"보상을 지급합니다."}'

    artifact = run_inference_smoke(case, generate)

    _assert_no_answer_leak(prompts[0], case)
    assert (
        artifact["raw_output"]
        == '{"action":"grant_reward","dialogue":"보상을 지급합니다."}'
    )
    assert artifact["model_action"] == "grant_reward"
    assert artifact["evaluation"]["score"] == 1
    assert artifact["server_execution"]["approved"] is True
    assert artifact["server_execution"]["final_state"]["reward_claimed"] is True


def test_inference_smoke_records_invalid_output_without_state_change() -> None:
    from quest_npc_lab.slices.model_smoke import run_inference_smoke

    case = _grant_case()
    artifact = run_inference_smoke(
        case, lambda _: '```json\n{"action":"grant_reward"}\n```'
    )

    assert artifact["evaluation"] == {
        "is_format_valid": False,
        "is_action_correct": False,
        "score": 0,
    }
    assert artifact["server_execution"]["state_changed"] is False
    assert artifact["error"]["stage"] == "model_output"


def test_sft_example_puts_reference_answer_only_in_completion() -> None:
    import json

    from quest_npc_lab.slices.guild_receptionist import parse_model_output
    from quest_npc_lab.slices.model_smoke import sft_example

    case = _grant_case()
    example = sft_example(case)

    assert [m["role"] for m in example["prompt"]] == ["user"]
    _assert_no_answer_leak(example["prompt"][0]["content"], case)
    [completion] = example["completion"]
    assert completion["role"] == "assistant"
    parsed = parse_model_output(completion["content"])
    assert parsed.action is Action.GRANT_REWARD
    assert parsed.dialogue == case.reference_dialogue
    assert json.loads(completion["content"]) == {
        "action": "grant_reward",
        "dialogue": case.reference_dialogue,
    }


def test_grpo_example_keeps_ground_truth_out_of_model_prompt() -> None:
    from quest_npc_lab.slices.model_smoke import grpo_example

    case = _grant_case()
    example = grpo_example(case, case_id="pilot-001")

    assert set(example) == {"prompt", "ground_truth_action", "case_id"}
    _assert_no_answer_leak(example["prompt"][0]["content"], case)
    assert example["ground_truth_action"] == "grant_reward"
    assert example["case_id"] == "pilot-001"


def test_parameter_diff_detects_changed_tensors() -> None:
    import torch

    from quest_npc_lab.slices.model_smoke import parameter_diff

    before = {"a": torch.zeros(2), "b": torch.ones(3)}
    after = {"a": torch.tensor([3.0, 4.0]), "b": torch.ones(3)}

    assert parameter_diff(before, after) == {
        "tensor_count": 2,
        "changed_tensor_count": 1,
        "l2_norm": 5.0,
        "max_abs": 4.0,
        "changed": True,
    }
    assert parameter_diff(before, before)["changed"] is False


def test_parameter_diff_rejects_mismatched_parameter_sets() -> None:
    import torch

    from quest_npc_lab.slices.model_smoke import parameter_diff

    with pytest.raises(ValueError):
        parameter_diff({"a": torch.zeros(1)}, {"b": torch.zeros(1)})


def _ok_phases(**overrides: dict) -> dict:
    phases: dict = {
        "inference": {"status": "ok"},
        "sft": {
            "status": "ok",
            "seconds_per_case": 0.5,
            "weight_diff": {"changed": True},
            "reload": {"status": "ok", "matches_trained_weights": True},
        },
        "grpo": {
            "status": "ok",
            "seconds_per_prompt": 4.0,
            "reward_groups": {"has_relative_signal": True},
            "parameter_diff": {"changed": True},
        },
    }
    phases.update(overrides)
    return phases


def test_smoke_report_extrapolates_budget_and_marks_artifacts_smoke_only() -> None:
    from quest_npc_lab.slices.model_smoke import build_smoke_report

    report = build_smoke_report(
        environment={"device": "cuda"}, limits={"seed": 42}, phases=_ok_phases()
    )

    assert report["run_kind"] == "smoke"
    assert report["status"] == "passed"
    assert report["blockers"] == []
    assert report["smoke_artifacts"]["reusable_for_main_experiment"] is False
    assert report["budget_estimate"]["target_train_cases"] == 180
    assert report["budget_estimate"]["sft_seconds_per_epoch"] == 90.0
    assert report["budget_estimate"]["grpo_seconds_per_epoch"] == 720.0
    assert report["zerogpu_considerations"]
    assert report["environment"] == {"device": "cuda"}
    assert report["limits"] == {"seed": 42}


def test_smoke_report_blocks_without_signal_update_or_on_phase_failure() -> None:
    from quest_npc_lab.slices.model_smoke import build_smoke_report

    no_signal = build_smoke_report(
        environment={},
        limits={},
        phases=_ok_phases(
            grpo={
                "status": "ok",
                "seconds_per_prompt": 4.0,
                "reward_groups": {"has_relative_signal": False},
                "parameter_diff": {"changed": False},
            }
        ),
    )
    assert no_signal["status"] == "blocked"
    assert any("relative reward signal" in b for b in no_signal["blockers"])
    assert any("parameters unchanged" in b for b in no_signal["blockers"])

    failed = build_smoke_report(
        environment={},
        limits={},
        phases=_ok_phases(sft={"status": "failed", "error": "OOM"}),
    )
    assert failed["status"] == "blocked"
    assert "sft: OOM" in failed["blockers"]
    assert failed["budget_estimate"]["sft_seconds_per_epoch"] is None

    bad_reload = build_smoke_report(
        environment={},
        limits={},
        phases=_ok_phases(
            sft={
                "status": "ok",
                "seconds_per_case": 0.5,
                "weight_diff": {"changed": False},
                "reload": {"status": "ok", "matches_trained_weights": False},
            }
        ),
    )
    assert any("LoRA weights unchanged" in b for b in bad_reload["blockers"])
    assert any("reloaded adapter" in b for b in bad_reload["blockers"])
