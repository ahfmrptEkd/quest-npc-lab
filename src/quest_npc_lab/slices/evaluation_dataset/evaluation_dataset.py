"""Read-only validation of final evaluation artifacts before inference."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Sequence

from quest_npc_lab.slices.dataset_pipeline.dataset_pipeline import (
    DatasetCase,
    DatasetValidationError,
    SHORTCUT_TAGS,
    DATA_DIRECTORY as DEVELOPMENT_DATA_DIRECTORY,
    build_model_prompt,
    load_dataset,
    validate_dataset,
    validate_train_validation_datasets,
)
from quest_npc_lab.slices.guild_receptionist import Action

DATA_DIRECTORY = Path(__file__).with_name("data")
EVAL_MANIFEST_PATH = DATA_DIRECTORY / "eval_manifest.json"
TRAIN_DATASET_PATH = DEVELOPMENT_DATA_DIRECTORY / "train_180.jsonl"
VALIDATION_DATASET_PATH = DEVELOPMENT_DATA_DIRECTORY / "val_60.jsonl"


class EvalFreezeError(ValueError):
    """The evaluation artifact does not match its frozen contract."""


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """Stable evaluation identifier with the verified common case contract."""

    case_id: str
    case: DatasetCase


@dataclass(frozen=True, slots=True)
class FrozenEvaluation:
    cases: tuple[EvaluationCase, ...]
    dialogue_review_ids: tuple[str, ...]
    dataset_sha256: str


def validate_eval_freeze(
    manifest_path: Path = EVAL_MANIFEST_PATH,
    *,
    training_cases: Sequence[DatasetCase] | None = None,
) -> FrozenEvaluation:
    """Reject changed bytes before reading cases or building model inputs."""
    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
        if not isinstance(manifest, dict):
            raise EvalFreezeError("manifest must be an object")
        if manifest.get("dataset") != "eval_60.jsonl":
            raise EvalFreezeError("dataset must be the sibling eval_60.jsonl")
        raw = (manifest_path.parent / "eval_60.jsonl").read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest.get("dataset_sha256"):
            raise EvalFreezeError("dataset SHA-256 mismatch; stop evaluation")
        cases = []
        for line_number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
            payload = json.loads(line, object_pairs_hook=_unique_object)
            if not isinstance(payload, dict):
                raise EvalFreezeError(f"case on line {line_number} must be an object")
            case_id = payload.pop("case_id")
            cases.append(EvaluationCase(case_id, DatasetCase.from_dict(payload)))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        raise EvalFreezeError(f"invalid evaluation artifact: {error}") from error
    expected = {action.value: 10 for action in Action}
    if (
        len(cases) != 60
        or type(manifest.get("case_count")) is not int
        or manifest["case_count"] != 60
    ):
        raise EvalFreezeError("final evaluation must contain exactly 60 cases")
    distribution = Counter(item.case.ground_truth_action.value for item in cases)
    if distribution != expected or manifest.get("action_distribution") != expected:
        raise EvalFreezeError("action distribution must contain 10 per action")
    if not isinstance(manifest.get("version"), str) or not manifest["version"].strip():
        raise EvalFreezeError("version must be a non-empty string")
    try:
        timestamp = datetime.fromisoformat(manifest["freeze_timestamp"])
        if timestamp.utcoffset() is None:
            raise ValueError("timezone missing")
    except (KeyError, TypeError, ValueError) as error:
        raise EvalFreezeError(
            "freeze_timestamp must be an ISO timestamp with timezone"
        ) from error
    ids = [item.case_id for item in cases]
    if (
        any(not isinstance(value, str) or not value.strip() for value in ids)
        or len(set(ids)) != 60
    ):
        raise EvalFreezeError("case IDs must be non-empty and unique")
    selected = manifest.get("dialogue_review_ids")
    if (
        not isinstance(selected, list)
        or len(selected) != 12
        or any(not isinstance(value, str) for value in selected)
        or len(set(selected)) != 12
        or not set(selected) <= set(ids)
    ):
        raise EvalFreezeError("dialogue review requires 12 distinct known IDs")
    sample = [item.case for item in cases if item.case_id in selected]
    sample_distribution = Counter(case.ground_truth_action.value for case in sample)
    if sample_distribution != {action.value: 2 for action in Action}:
        raise EvalFreezeError("dialogue review requires two cases per action")
    eval_cases = tuple(item.case for item in cases)
    if {case.review_status for case in eval_cases} != {"user_approved"}:
        raise EvalFreezeError("user approval is required before evaluation freeze")
    if {case.split for case in eval_cases} != {"final_eval"}:
        raise EvalFreezeError("evaluation cases must use final_eval split")
    if not SHORTCUT_TAGS <= {tag for case in eval_cases for tag in case.shortcut_tags}:
        raise EvalFreezeError("evaluation must cover all six shortcut patterns")
    try:
        if training_cases is None:
            train = load_dataset(TRAIN_DATASET_PATH)
            validation = load_dataset(VALIDATION_DATASET_PATH)
            validate_train_validation_datasets(train, validation)
            training = (*train, *validation)
        else:
            training = tuple(training_cases)
    except (DatasetValidationError, UnicodeError) as error:
        raise EvalFreezeError(str(error)) from error
    training_groups = {case.expression_group for case in training}
    if training_groups & {case.expression_group for case in eval_cases}:
        raise EvalFreezeError("expression groups cross training/validation/evaluation splits")
    try:
        validate_dataset((*training, *eval_cases))
    except DatasetValidationError as error:
        raise EvalFreezeError(str(error)) from error
    return FrozenEvaluation(
        tuple(cases), tuple(manifest["dialogue_review_ids"]),
        manifest["dataset_sha256"],
    )


def build_eval_prompt(item: EvaluationCase) -> str:
    """Project to the shared inference contract; never serialize evaluation metadata."""
    return build_model_prompt(item.case)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvalFreezeError(f"duplicate JSON key: {key}")
        result[key] = value
    return result
