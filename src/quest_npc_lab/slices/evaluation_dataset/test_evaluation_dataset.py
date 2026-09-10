"""Tests at the final evaluation loading and prompt boundaries."""

import hashlib
import json

import pytest

from quest_npc_lab.slices.evaluation_dataset.evaluation_dataset import (
    EvalFreezeError,
    validate_eval_freeze,
)


def test_changed_dataset_bytes_stop_evaluation(tmp_path):
    dataset = tmp_path / "eval_60.jsonl"
    dataset.write_bytes(b"original\n")
    manifest = tmp_path / "eval_manifest.json"
    manifest.write_text(json.dumps({
        "dataset": dataset.name,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
    }))
    dataset.write_bytes(b"changed\n")
    with pytest.raises(EvalFreezeError, match="SHA-256"):
        validate_eval_freeze(manifest)


@pytest.fixture
def frozen_artifact(tmp_path):
    # Existing cases are test fixtures only, never final evaluation content.
    from quest_npc_lab.slices.dataset_pipeline.dataset_pipeline import load_pilot_dataset
    rows = [dict(case.to_dict(), case_id=f"fixture-{i:03}", split="final_eval")
            for i, case in enumerate(load_pilot_dataset())]
    dataset = tmp_path / "eval_60.jsonl"
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows))
    selected = []
    counts = {}
    for row in rows:
        action = row["ground_truth_action"]
        if counts.get(action, 0) < 2:
            selected.append(row["case_id"])
            counts[action] = counts.get(action, 0) + 1
    manifest = {
        "version": "1",
        "dataset": dataset.name,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "case_count": 60,
        "action_distribution": {action: 10 for action in counts},
        "dialogue_review_ids": selected,
        "freeze_timestamp": "2026-09-10T00:00:00+00:00",
    }
    path = tmp_path / "eval_manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_validated_artifact_returns_all_cases_and_preselected_sample(frozen_artifact):
    frozen = validate_eval_freeze(frozen_artifact, training_cases=())
    assert len(frozen.cases) == 60
    assert len(frozen.dialogue_review_ids) == 12
    assert frozen.cases[0].case_id == "fixture-000"


@pytest.mark.parametrize("field,value", [
    ("case_count", 59),
    ("case_count", True),
    ("action_distribution", {"grant_reward": 60}),
    ("dialogue_review_ids", ["unknown"] * 12),
    ("dialogue_review_ids", []),
    ("freeze_timestamp", "not a date"),
    ("freeze_timestamp", "2026-09-10T00:00:00"),
    ("version", ""),
])
def test_manifest_contract_is_enforced(frozen_artifact, field, value):
    manifest = json.loads(frozen_artifact.read_text())
    manifest[field] = value
    frozen_artifact.write_text(json.dumps(manifest))
    with pytest.raises(EvalFreezeError):
        validate_eval_freeze(frozen_artifact, training_cases=())


def test_training_expression_groups_cannot_cross_into_eval(frozen_artifact):
    with pytest.raises(EvalFreezeError, match="split"):
        validate_eval_freeze(frozen_artifact)


def test_prompt_contains_only_inference_inputs(frozen_artifact):
    from dataclasses import replace
    from quest_npc_lab.slices.evaluation_dataset.evaluation_dataset import build_eval_prompt
    item = validate_eval_freeze(frozen_artifact, training_cases=()).cases[0]
    hidden = replace(item, case=replace(
        item.case, player_intent="SECRET_INTENT", reference_dialogue="SECRET_REFERENCE",
        expression_group="SECRET_GROUP",
    ), case_id="SECRET_ID")
    prompt = build_eval_prompt(hidden)
    assert "SECRET_" not in prompt
    payload = json.loads(prompt)
    assert set(payload) == {"character_persona", "rules", "server_state", "player_utterance"}
    assert payload["player_utterance"] == item.case.player_utterance
    assert payload["server_state"]["current_count"] == item.case.current_count
    assert build_eval_prompt(item) == prompt


@pytest.mark.parametrize("content", ["{", "[]", '{"dataset":"../outside.jsonl"}',
    '{"dataset":"/tmp/outside.jsonl"}', '{"dataset":"eval_60.jsonl","dataset":"other.jsonl"}'])
def test_invalid_manifests_raise_freeze_error(tmp_path, content):
    path = tmp_path / "eval_manifest.json"
    path.write_text(content)
    with pytest.raises(EvalFreezeError):
        validate_eval_freeze(path)


def test_missing_artifact_raises_freeze_error(tmp_path):
    with pytest.raises(EvalFreezeError):
        validate_eval_freeze(tmp_path / "missing.json")


@pytest.mark.parametrize("change", ["missing", "duplicate_id", "imbalance", "wrong_split", "duplicate_json_key"])
def test_rehashing_invalid_cases_does_not_bypass_contract(frozen_artifact, change):
    manifest = json.loads(frozen_artifact.read_text())
    dataset = frozen_artifact.parent / manifest["dataset"]
    rows = [json.loads(line) for line in dataset.read_text().splitlines()]
    if change == "missing":
        rows.pop()
    elif change == "duplicate_id":
        rows[1]["case_id"] = rows[0]["case_id"]
    elif change == "imbalance":
        rows[0]["ground_truth_action"] = "explain_progress"
    elif change == "wrong_split":
        rows[0]["split"] = "train"
    raw = "".join(json.dumps(row) + "\n" for row in rows)
    if change == "duplicate_json_key":
        raw = raw.replace('"split": "final_eval"', '"split": "train", "split": "final_eval"', 1)
    dataset.write_text(raw)
    manifest["dataset_sha256"] = hashlib.sha256(dataset.read_bytes()).hexdigest()
    frozen_artifact.write_text(json.dumps(manifest))
    with pytest.raises(EvalFreezeError):
        validate_eval_freeze(frozen_artifact, training_cases=())


def test_ai_review_alone_cannot_freeze_cases(frozen_artifact):
    manifest = json.loads(frozen_artifact.read_text())
    dataset = frozen_artifact.parent / manifest["dataset"]
    dataset.write_text(dataset.read_text().replace('"user_approved"', '"ai_approved"'))
    manifest["dataset_sha256"] = hashlib.sha256(dataset.read_bytes()).hexdigest()
    frozen_artifact.write_text(json.dumps(manifest))
    with pytest.raises(EvalFreezeError, match="user approval"):
        validate_eval_freeze(frozen_artifact, training_cases=())


def test_checked_in_freeze_is_balanced_isolated_and_preselected():
    from collections import Counter
    from quest_npc_lab.slices.evaluation_dataset.evaluation_dataset import DATA_DIRECTORY
    from quest_npc_lab.slices.dataset_pipeline.dataset_pipeline import (
        evaluate_shortcut_patterns,
    )

    frozen = validate_eval_freeze()
    assert len(frozen.cases) == 60
    assert Counter(item.case.ground_truth_action.value for item in frozen.cases) == {
        "grant_reward": 10, "explain_progress": 10, "explain_reward": 10,
        "already_claimed": 10, "clarify": 10, "other": 10,
    }
    assignments = json.loads((DATA_DIRECTORY / "expression_groups.json").read_text())
    assert {item.case.expression_group for item in frozen.cases} == set(assignments["groups"])
    assert frozen.dialogue_review_ids == (
        "eval-013", "eval-025", "eval-008", "eval-032", "eval-015", "eval-051",
        "eval-022", "eval-046", "eval-011", "eval-047", "eval-018", "eval-048",
    )
    sample = [item.case for item in frozen.cases if item.case_id in frozen.dialogue_review_ids]
    assert {"ignore_cancel", "accept_false_claim", "duplicate_grant"} <= {
        tag for case in sample for tag in case.shortcut_tags
    }
    scores = evaluate_shortcut_patterns([item.case for item in frozen.cases])
    assert all(score.correct < score.total for score in scores.values())


@pytest.mark.parametrize("split_path", ["TRAIN_DATASET_PATH", "VALIDATION_DATASET_PATH"])
def test_default_loading_rejects_eval_group_in_either_development_split(tmp_path, split_path):
    from quest_npc_lab.slices.evaluation_dataset import evaluation_dataset as module
    from quest_npc_lab.slices.dataset_pipeline.dataset_pipeline import load_dataset

    manifest = json.loads(module.EVAL_MANIFEST_PATH.read_text())
    rows = [json.loads(line) for line in
            (module.DATA_DIRECTORY / "eval_60.jsonl").read_text().splitlines()]
    rows[0]["expression_group"] = load_dataset(getattr(module, split_path))[0].expression_group
    raw = "".join(json.dumps(row) + "\n" for row in rows).encode()
    (tmp_path / "eval_60.jsonl").write_bytes(raw)
    manifest["dataset_sha256"] = hashlib.sha256(raw).hexdigest()
    path = tmp_path / "eval_manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(EvalFreezeError, match="expression groups cross"):
        validate_eval_freeze(path)


@pytest.mark.parametrize("split_path", ["TRAIN_DATASET_PATH", "VALIDATION_DATASET_PATH"])
def test_missing_development_split_stops_evaluation(monkeypatch, tmp_path, split_path):
    from quest_npc_lab.slices.evaluation_dataset import evaluation_dataset as module

    monkeypatch.setattr(module, split_path, tmp_path / "missing.jsonl")
    with pytest.raises(EvalFreezeError, match="could not read dataset"):
        validate_eval_freeze()


@pytest.mark.parametrize("split_path", ["TRAIN_DATASET_PATH", "VALIDATION_DATASET_PATH"])
def test_invalid_development_encoding_raises_freeze_error(monkeypatch, tmp_path, split_path):
    from quest_npc_lab.slices.evaluation_dataset import evaluation_dataset as module

    path = tmp_path / "invalid.jsonl"
    path.write_bytes(b"\xff\n")
    monkeypatch.setattr(module, split_path, path)
    with pytest.raises(EvalFreezeError, match="decode"):
        validate_eval_freeze()


def test_review_sample_must_have_two_per_action(frozen_artifact):
    manifest = json.loads(frozen_artifact.read_text())
    manifest["dialogue_review_ids"][-1] = "fixture-012"
    frozen_artifact.write_text(json.dumps(manifest))
    with pytest.raises(EvalFreezeError, match="two cases per action"):
        validate_eval_freeze(frozen_artifact, training_cases=())


def test_frozen_artifact_bytes_are_not_silently_replaced():
    from quest_npc_lab.slices.evaluation_dataset.evaluation_dataset import DATA_DIRECTORY

    # Review a new evaluation version explicitly; never refresh these to bless drift.
    expected = {
        "eval_60.jsonl": "956bfe8616042a86edc41b2976d0900478c4c6e78faa50f9144007485d496bd9",
        "eval_manifest.json": "b520bafdaaeb25dfab2ac810f39d68784ce2e0619416f8412e385ebe63a40c28"
    }
    for filename, digest in expected.items():
        assert hashlib.sha256((DATA_DIRECTORY / filename).read_bytes()).hexdigest() == digest
