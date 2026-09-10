from __future__ import annotations

from dataclasses import replace
import json

import pytest

from quest_npc_lab.slices.dataset_pipeline import (
    ActionType,
    DatasetCaseBlueprint,
    DatasetCaseDraft,
    DatasetCase,
    DatasetValidationError,
    PILOT_DATASET_PATH,
    PilotReviewFlow,
    SynthesizedExpression,
    UserReviewDecision,
    build_model_prompt,
    evaluate_shortcut_baselines,
    evaluate_shortcut_patterns,
    load_pilot_dataset,
    load_review_manifest,
    load_shortcut_baseline_report,
    prepare_training_cases,
    validate_dataset,
    validate_pilot_dataset,
    validate_review_manifest,
)


def valid_case(**overrides: object) -> DatasetCase:
    values: dict[str, object] = {
        "quest_name": "늑대 소탕",
        "target_count": 5,
        "current_count": 5,
        "reward_description": "금화 100개",
        "reward_claimed": False,
        "player_intent": "완료한 퀘스트 보상 지급 요청",
        "ground_truth_action": ActionType.GRANT_REWARD,
        "player_utterance": "보상을 주세요.",
        "reference_dialogue": "확인되었습니다. 금화 100개를 지급해 드리겠습니다.",
        "shortcut_tags": ("always_reject",),
        "expression_group": "direct-grant-01",
        "split": "train_pilot",
        "review_status": "ai_approved",
    }
    values.update(overrides)
    return DatasetCase(**values)  # type: ignore[arg-type]


def case_for_action(action: ActionType, index: int) -> DatasetCase:
    overrides: dict[str, object] = {
        "ground_truth_action": action,
        "player_intent": f"{action.value} 의도 {index}",
        "player_utterance": f"서로 다른 요청 {index}: {action.value}",
        "reference_dialogue": f"정중한 안내 {index}입니다.",
        "expression_group": f"synthetic-{action.value}",
        "shortcut_tags": (),
    }
    if action is ActionType.EXPLAIN_PROGRESS:
        overrides.update(current_count=2)
    elif action is ActionType.ALREADY_CLAIMED:
        overrides.update(reward_claimed=True)
    return valid_case(**overrides)


def mixed_batch(offset: int = 0) -> tuple[DatasetCase, ...]:
    actions = tuple(ActionType)
    return tuple(
        case_for_action(actions[index % len(actions)], offset + index)
        for index in range(20)
    )


def mixed_blueprints(offset: int = 0) -> tuple[DatasetCaseBlueprint, ...]:
    return tuple(case.to_blueprint() for case in mixed_batch(offset))


def test_case_schema_rejects_contradictory_server_state() -> None:
    with pytest.raises(DatasetValidationError, match="reward_claimed"):
        DatasetCase(
            quest_name="늑대 소탕",
            target_count=5,
            current_count=4,
            reward_description="금화 100개",
            reward_claimed=True,
            player_intent="이미 받은 보상 재요청",
            ground_truth_action=ActionType.ALREADY_CLAIMED,
            player_utterance="보상을 다시 주세요.",
            reference_dialogue="이미 수령하신 보상은 다시 드릴 수 없습니다.",
            shortcut_tags=("duplicate_grant",),
            expression_group="duplicate-request-01",
            split="train_pilot",
            review_status="ai_approved",
        )


def test_prompt_contains_only_runtime_state_and_player_utterance() -> None:
    case = valid_case(
        player_intent="SECRET_INTENT",
        reference_dialogue="SECRET_DIALOGUE",
    )

    prompt = json.loads(build_model_prompt(case))

    assert set(prompt) == {
        "character_persona",
        "rules",
        "server_state",
        "player_utterance",
    }
    assert prompt["server_state"] == {
        "quest_name": "늑대 소탕",
        "target_count": 5,
        "current_count": 5,
        "reward_description": "금화 100개",
        "reward_claimed": False,
    }
    assert prompt["player_utterance"] == "보상을 주세요."
    assert "SECRET_INTENT" not in build_model_prompt(case)
    assert "ground_truth_action" not in build_model_prompt(case)
    assert "SECRET_DIALOGUE" not in build_model_prompt(case)


def test_case_schema_round_trips_as_strict_json_fields() -> None:
    case = valid_case()

    payload = case.to_dict()

    assert set(payload) == {
        "quest_name",
        "target_count",
        "current_count",
        "reward_description",
        "reward_claimed",
        "player_intent",
        "ground_truth_action",
        "player_utterance",
        "reference_dialogue",
        "shortcut_tags",
        "expression_group",
        "split",
        "review_status",
    }
    assert payload["ground_truth_action"] == "grant_reward"
    assert payload["shortcut_tags"] == ["always_reject"]
    assert DatasetCase.from_dict(payload) == case

    payload["unexpected"] = "not allowed"
    with pytest.raises(DatasetValidationError, match="exactly"):
        DatasetCase.from_dict(payload)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"target_count": 0}, "target_count"),
        ({"current_count": -1}, "current_count"),
        ({"reward_claimed": 1}, "reward_claimed"),
        ({"player_intent": " "}, "player_intent"),
        ({"ground_truth_action": "grant_reward"}, "ground_truth_action"),
        ({"shortcut_tags": ("invented",)}, "shortcut_tags"),
        ({"expression_group": ""}, "expression_group"),
        ({"split": "dev"}, "split"),
        ({"review_status": "pending"}, "review_status"),
        ({"current_count": 4}, "grant_reward"),
        (
            {"ground_truth_action": ActionType.ALREADY_CLAIMED},
            "already_claimed",
        ),
    ],
)
def test_case_schema_rejects_invalid_fields(
    overrides: dict[str, object], reason: str
) -> None:
    with pytest.raises(DatasetValidationError, match=reason):
        valid_case(**overrides)


def test_review_flow_requires_ai_clearance_and_user_approval_before_next_batch() -> None:
    flow = PilotReviewFlow()

    first = flow.submit_batch("batch_01", mixed_batch(), ai_reviewer=lambda _: ())

    assert first.ai_approved is True
    assert first.user_approval_status == "pending"
    assert len(first.cases) == 20
    with pytest.raises(DatasetValidationError, match="user approval"):
        flow.submit_batch("batch_02", mixed_batch(20), ai_reviewer=lambda _: ())

    approved = flow.approve_current_batch(review_duration_seconds=95)

    assert approved.user_approval_status == "approved"
    assert approved.review_duration_seconds == 95
    assert {case.review_status for case in approved.cases} == {"user_approved"}
    second = flow.submit_batch("batch_02", mixed_batch(20), ai_reviewer=lambda _: ())
    assert second.batch_id == "batch_02"


def test_review_flow_keeps_ai_issues_out_of_user_review_until_resubmitted() -> None:
    flow = PilotReviewFlow()

    failed = flow.submit_batch(
        "batch_01",
        mixed_batch(),
        ai_reviewer=lambda _: ("case 7 dialogue contradicts its action",),
    )

    assert failed.ai_approved is False
    assert failed.user_approval_status == "blocked"
    assert all(isinstance(case, DatasetCaseDraft) for case in failed.cases)
    assert all(not hasattr(case, "review_status") for case in failed.cases)
    with pytest.raises(DatasetValidationError, match="AI review"):
        flow.approve_current_batch(review_duration_seconds=10)
    with pytest.raises(DatasetValidationError, match="current batch"):
        flow.submit_batch("batch_02", mixed_batch(20), ai_reviewer=lambda _: ())

    repaired = flow.submit_batch(
        "batch_01", mixed_batch(), ai_reviewer=lambda _: ()
    )
    assert repaired.ai_approved is True
    assert repaired.ai_review_issues == ()


def test_generation_synthesizes_each_blueprint_before_ai_review() -> None:
    flow = PilotReviewFlow()
    seen: list[DatasetCaseBlueprint] = []

    def synthesize(blueprint: DatasetCaseBlueprint) -> SynthesizedExpression:
        seen.append(blueprint)
        return SynthesizedExpression(
            player_utterance=f"생성 발화 {len(seen)}",
            reference_dialogue=f"생성 안내 {len(seen)}입니다.",
        )

    artifact = flow.generate_batch(
        "batch_01",
        mixed_blueprints(),
        synthesizer=synthesize,
        ai_reviewer=lambda _: (),
    )

    assert tuple(seen) == mixed_blueprints()
    assert artifact.ai_approved is True
    assert {case.review_status for case in artifact.cases} == {"ai_approved"}


def test_generation_and_reviewer_failures_never_become_approvals() -> None:
    flow = PilotReviewFlow()

    with pytest.raises(DatasetValidationError, match="synthesis failed"):
        flow.generate_batch(
            "batch_01",
            mixed_blueprints(),
            synthesizer=lambda _: (_ for _ in ()).throw(RuntimeError("offline")),
            ai_reviewer=lambda _: (),
        )

    blocked = flow.submit_batch(
        "batch_01",
        mixed_batch(),
        ai_reviewer=lambda _: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert blocked.ai_approved is False
    assert blocked.user_approval_status == "blocked"
    assert blocked.ai_review_issues == ("AI reviewer failed: offline",)


def test_user_review_records_modify_and_exclude_before_full_batch_rereview() -> None:
    flow = PilotReviewFlow()
    flow.submit_batch("batch_01", mixed_batch(), ai_reviewer=lambda _: ())
    decisions = tuple(
        UserReviewDecision(
            case_index=index,
            decision="modify" if index == 0 else "exclude" if index == 1 else "approve",
            note="표현 수정" if index == 0 else "",
        )
        for index in range(20)
    )

    changes = flow.review_current_batch(decisions, review_duration_seconds=120)

    assert changes.user_approval_status == "changes_requested"
    assert changes.user_decisions == decisions
    with pytest.raises(DatasetValidationError, match="current batch"):
        flow.submit_batch("batch_02", mixed_batch(20), ai_reviewer=lambda _: ())
    rereviewed = flow.submit_batch(
        "batch_01", mixed_batch(100), ai_reviewer=lambda _: ()
    )
    assert rereviewed.user_approval_status == "pending"
    assert {case.review_status for case in rereviewed.cases} == {"ai_approved"}


def test_dataset_validation_rejects_duplicate_text_and_cross_split_groups() -> None:
    original = valid_case(expression_group="paired-state-request")
    changed_split = valid_case(
        player_utterance="같은 표현 패턴의 상태 변형",
        expression_group="paired-state-request",
        split="validation",
    )

    with pytest.raises(DatasetValidationError, match="crosses splits"):
        validate_dataset((original, changed_split))

    duplicate_text = valid_case(expression_group="another-group")
    with pytest.raises(DatasetValidationError, match="duplicate player_utterance"):
        validate_dataset((original, duplicate_text))

    numeric_variant = valid_case(
        quest_name="늑대 소탕",
        target_count=6,
        current_count=6,
        player_utterance="늑대 6마리를 잡았으니 보상을 주세요.",
        expression_group="numeric-variant-b",
        split="validation",
    )
    numbered_original = valid_case(
        player_utterance="늑대 5마리를 잡았으니 보상을 주세요.",
        expression_group="numeric-variant-a",
    )
    with pytest.raises(DatasetValidationError, match="expression pattern"):
        validate_dataset((numbered_original, numeric_variant))


def test_balanced_dataset_defeats_naive_shortcut_policies() -> None:
    actions = tuple(ActionType)
    cases = tuple(
        case_for_action(actions[index % len(actions)], index) for index in range(60)
    )

    scores = evaluate_shortcut_baselines(cases)

    assert set(scores) == {
        "always_grant",
        "always_reject",
        "always_other",
        "always_clarify",
        "grant_on_state_alone",
    }
    assert scores["always_grant"].correct == 10
    assert scores["always_reject"].correct == 10
    assert scores["always_other"].correct == 10
    assert scores["always_clarify"].correct == 10
    assert all(score.accuracy < 1.0 for score in scores.values())


def test_shipped_pilot_has_60_balanced_ai_reviewed_cases_and_all_shortcut_tags() -> None:
    cases = load_pilot_dataset()

    summary = validate_pilot_dataset(cases)

    assert summary.total == 60
    assert summary.action_counts == {action.value: 10 for action in ActionType}
    assert summary.shortcut_tag_counts.keys() == {
        "always_reject",
        "state_only_grant",
        "accept_false_claim",
        "duplicate_grant",
        "abuse_other_clarify",
        "ignore_cancel",
    }
    assert {case.split for case in cases} == {"train_pilot"}
    assert {case.review_status for case in cases} == {"user_approved"}
    assert all(score.accuracy < 1.0 for score in evaluate_shortcut_baselines(cases).values())
    assert len(prepare_training_cases(cases)) == 60
    unapproved = [replace(c, review_status="ai_approved") for c in cases]
    with pytest.raises(DatasetValidationError, match="user approval"):
        prepare_training_cases(unapproved)


def test_all_six_required_shortcut_patterns_have_failing_counterexamples() -> None:
    scores = evaluate_shortcut_patterns(load_pilot_dataset())

    assert set(scores) == {
        "always_reject",
        "state_only_grant",
        "accept_false_claim",
        "duplicate_grant",
        "abuse_other_clarify",
        "ignore_cancel",
    }
    assert all(score.total > 1 for score in scores.values())
    assert all(score.accuracy < 1.0 for score in scores.values())


def test_review_manifest_partitions_pilot_into_three_mixed_batches() -> None:
    cases = load_pilot_dataset()
    manifest = load_review_manifest()

    validate_review_manifest(cases, manifest, dataset_path=PILOT_DATASET_PATH)

    assert manifest["dataset"] == "pilot_60.jsonl"
    assert len(manifest["batches"]) == 3
    covered_lines: list[int] = []
    for batch in manifest["batches"]:
        start = batch["line_start"]
        end = batch["line_end"]
        covered_lines.extend(range(start, end + 1))
        assert end - start + 1 == 20
        assert batch["generation_validation"]["status"] == "passed"
        assert batch["ai_review"] == {"status": "approved", "issues": []}
        assert batch["user_review"]["status"] == "approved"
        assert batch["user_review"]["duration_seconds"] == 120
        batch_actions = {case.ground_truth_action for case in cases[start - 1 : end]}
        assert batch_actions == set(ActionType)
    assert covered_lines == list(range(1, 61))


def test_stored_shortcut_report_matches_recomputed_policy_scores() -> None:
    cases = load_pilot_dataset()
    report = load_shortcut_baseline_report()
    computed = evaluate_shortcut_baselines(cases)
    pattern_scores = evaluate_shortcut_patterns(cases)

    assert report["dataset_sha256"] == load_review_manifest()["dataset_sha256"]
    assert report["all_shortcuts_fail"] is True
    assert report["policies"] == {
        name: {
            "correct": score.correct,
            "total": score.total,
            "accuracy": score.accuracy,
        }
        for name, score in computed.items()
    }
    assert report["required_patterns"] == {
        name: {
            "correct": score.correct,
            "total": score.total,
            "accuracy": score.accuracy,
        }
        for name, score in pattern_scores.items()
    }
