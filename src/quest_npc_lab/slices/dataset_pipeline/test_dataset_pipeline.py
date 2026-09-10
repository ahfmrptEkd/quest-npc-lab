from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

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
    load_dataset,
    load_pilot_dataset,
    load_review_manifest,
    load_shortcut_baseline_report,
    prepare_training_cases,
    validate_dataset,
    validate_pilot_dataset,
    validate_review_manifest,
    validate_train_validation_datasets,
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


def test_review_manifest_covers_nine_batches_for_expanded_training(tmp_path: Path) -> None:
    cases = tuple(
        replace(case, split="train", review_status="user_approved")
        for batch in range(9)
        for case in mixed_batch(batch * 20)
    )
    dataset_path = tmp_path / "train_180.jsonl"
    dataset_path.write_text(
        "\n".join(json.dumps(case.to_dict()) for case in cases) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "dataset": dataset_path.name,
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "batch_size": 20,
        "batches": [
            {
                "batch_id": f"train_{index + 1:02}",
                "line_start": index * 20 + 1,
                "line_end": (index + 1) * 20,
                "generation_validation": {"status": "passed"},
                "ai_review": {"status": "approved", "issues": []},
                "user_review": {"status": "approved", "duration_seconds": 0},
            }
            for index in range(9)
        ],
    }
    validate_review_manifest(cases, manifest, dataset_path=dataset_path)
    manifest["batches"].pop()
    with pytest.raises(DatasetValidationError, match="batches"):
        validate_review_manifest(cases, manifest, dataset_path=dataset_path)


def expanded_training_fixture() -> tuple[DatasetCase, ...]:
    pilot = tuple(replace(case, split="train") for case in load_pilot_dataset())
    additions = tuple(
        replace(case_for_action(tuple(ActionType)[index % 6], index),
                split="train", review_status="user_approved")
        for index in range(120)
    )
    return pilot + additions


def test_training_preparation_accepts_complete_approved_expansion() -> None:
    cases = expanded_training_fixture()
    assert prepare_training_cases(cases) == cases
    with pytest.raises(DatasetValidationError, match="180"):
        prepare_training_cases(cases[:-1])
    with pytest.raises(DatasetValidationError, match="user approval"):
        prepare_training_cases((replace(cases[0], review_status="ai_approved"), *cases[1:]))


def test_expansion_preserves_every_approved_pilot_case() -> None:
    cases = expanded_training_fixture()
    changed_pilot = (replace(cases[0], reference_dialogue="승인 후 바뀐 대사"), *cases[1:])
    with pytest.raises(DatasetValidationError, match="pilot"):
        prepare_training_cases(changed_pilot)


def test_joint_validation_checks_balance_approval_and_split_isolation() -> None:
    train = expanded_training_fixture()
    validation = tuple(
        replace(case, split="validation", expression_group=f"heldout-{index}",
                player_utterance=f"Held out query {chr(0xAC00 + index)}")
        for index, case in enumerate(load_pilot_dataset())
    )
    summaries = validate_train_validation_datasets(train, validation)
    assert summaries["train"].total == 180
    assert summaries["validation"].action_counts == {action.value: 10 for action in ActionType}
    for changed, reason in [
        (validation[:-1], "60"),
        ((replace(validation[0], review_status="ai_approved"), *validation[1:]), "user approval"),
        ((replace(validation[0], expression_group=train[0].expression_group), *validation[1:]), "crosses splits"),
        ((replace(validation[0], player_utterance=train[0].player_utterance), *validation[1:]), "duplicate"),
        ((replace(validation[0], ground_truth_action=ActionType.EXPLAIN_REWARD), *validation[1:]), "balanced"),
    ]:
        with pytest.raises(DatasetValidationError, match=reason):
            validate_train_validation_datasets(train, changed)


def test_jsonl_loader_supports_expanded_splits_and_rejects_blank_rows(tmp_path: Path) -> None:
    case = replace(valid_case(), split="validation")
    path = tmp_path / "val_60.jsonl"
    path.write_text(json.dumps(case.to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")
    assert load_dataset(path) == (case,)
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="blank line at 2"):
        load_dataset(path)


def test_task_authorization_records_no_invented_manual_review_time() -> None:
    cases = load_pilot_dataset()
    manifest = load_review_manifest()
    for batch in manifest["batches"]:
        batch["user_review"] = {
            "status": "approved",
            "approval_basis": "explicit_task_instruction",
            "duration_seconds": None,
        }
    validate_review_manifest(cases, manifest, dataset_path=PILOT_DATASET_PATH)
    del manifest["batches"][0]["user_review"]["approval_basis"]
    with pytest.raises(DatasetValidationError, match="duration"):
        validate_review_manifest(cases, manifest, dataset_path=PILOT_DATASET_PATH)


def test_manifest_rejects_cases_that_differ_from_hashed_file() -> None:
    cases = load_pilot_dataset()
    changed = (replace(cases[0], player_utterance="검사할 파일과 다른 발화"), *cases[1:])
    with pytest.raises(DatasetValidationError, match="match.*dataset"):
        validate_review_manifest(changed, load_review_manifest(), dataset_path=PILOT_DATASET_PATH)


def test_shipped_expansion_is_balanced_isolated_and_bound_to_review_manifests() -> None:
    directory = PILOT_DATASET_PATH.parent
    train = load_dataset(directory / "train_180.jsonl")
    validation = load_dataset(directory / "val_60.jsonl")
    summaries = validate_train_validation_datasets(train, validation)
    assert summaries["train"].action_counts == {action.value: 30 for action in ActionType}
    assert summaries["validation"].action_counts == {action.value: 10 for action in ActionType}
    assert train[:60] == tuple(replace(case, split="train") for case in load_pilot_dataset())
    assert prepare_training_cases(train) == train
    groups = json.loads((directory / "expression_groups.json").read_text(encoding="utf-8"))
    report = json.loads((directory / "expansion_shortcut_baselines.json").read_text(encoding="utf-8"))
    for name, cases, filename, batch_count in [
        ("train", train, "train_180", 9),
        ("validation", validation, "val_60", 3),
    ]:
        manifest = load_review_manifest(directory / f"{filename}_review_batches.json")
        validate_review_manifest(cases, manifest, dataset_path=directory / f"{filename}.jsonl")
        assert len(manifest["batches"]) == batch_count
        assert {case.review_status for case in cases} == {"user_approved"}
        assert report[name]["dataset_sha256"] == manifest["dataset_sha256"]
        for key, scores in [
            ("policies", evaluate_shortcut_baselines(cases)),
            ("required_patterns", evaluate_shortcut_patterns(cases)),
        ]:
            assert report[name][key] == {
                policy: {"correct": score.correct, "total": score.total, "accuracy": score.accuracy}
                for policy, score in scores.items()
            }
            assert all(score.accuracy < 1.0 for score in scores.values())
        for case in cases:
            assert groups["groups"][case.expression_group]["split"] == name
            prompt = build_model_prompt(case)
            changed_answers = replace(
                case, player_intent="PRIVATE_INTENT", reference_dialogue="PRIVATE_DIALOGUE",
                ground_truth_action=ActionType.OTHER, expression_group="PRIVATE_GROUP",
                shortcut_tags=(), review_status="ai_approved",
            )
            assert build_model_prompt(changed_answers) == prompt
            assert set(json.loads(prompt)) == {
                "character_persona", "rules", "server_state", "player_utterance",
            }
