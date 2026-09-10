"""Validated cases and review workflow for the guild receptionist dataset."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
from typing import Callable, Sequence

from quest_npc_lab.slices.guild_receptionist import (
    Action as ActionType,
    DEFAULT_CHARACTER_PERSONA,
    DEFAULT_RULES,
)

SHORTCUT_TAGS = frozenset(
    {
        "always_reject",
        "state_only_grant",
        "accept_false_claim",
        "duplicate_grant",
        "abuse_other_clarify",
        "ignore_cancel",
    }
)
DATASET_SPLITS = frozenset({"train_pilot", "train", "validation", "final_eval"})
REVIEW_STATUSES = frozenset({"ai_approved", "user_approved"})
CASE_FIELDS = frozenset(
    {
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
)
DATA_DIRECTORY = Path(__file__).with_name("data")
PILOT_DATASET_PATH = DATA_DIRECTORY / "pilot_60.jsonl"
REVIEW_MANIFEST_PATH = DATA_DIRECTORY / "review_batches.json"
SHORTCUT_BASELINE_PATH = DATA_DIRECTORY / "shortcut_baselines.json"


class DatasetValidationError(ValueError):
    """Raised when a dataset case or collection violates its contract."""


@dataclass(frozen=True, slots=True)
class DatasetCaseBlueprint:
    """Protected state, intent, label, and grouping inputs for synthesis."""

    quest_name: str
    target_count: int
    current_count: int
    reward_description: str
    reward_claimed: bool
    player_intent: str
    ground_truth_action: ActionType
    shortcut_tags: tuple[str, ...]
    expression_group: str
    split: str

    def __post_init__(self) -> None:
        for field_name in (
            "quest_name",
            "reward_description",
            "player_intent",
            "expression_group",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise DatasetValidationError(f"{field_name} must be a non-empty string")
        if type(self.target_count) is not int or self.target_count <= 0:
            raise DatasetValidationError("target_count must be a positive integer")
        if type(self.current_count) is not int or self.current_count < 0:
            raise DatasetValidationError("current_count must be a non-negative integer")
        if type(self.reward_claimed) is not bool:
            raise DatasetValidationError("reward_claimed must be a boolean")
        if not isinstance(self.ground_truth_action, ActionType):
            raise DatasetValidationError("ground_truth_action must be an ActionType")
        if not isinstance(self.shortcut_tags, (tuple, list)) or any(
            not isinstance(tag, str) for tag in self.shortcut_tags
        ):
            raise DatasetValidationError("shortcut_tags must be a list of strings")
        tags = tuple(self.shortcut_tags)
        unknown_tags = set(tags) - SHORTCUT_TAGS
        if unknown_tags:
            raise DatasetValidationError(
                f"shortcut_tags contains unsupported values: {sorted(unknown_tags)}"
            )
        if len(tags) != len(set(tags)):
            raise DatasetValidationError("shortcut_tags must not contain duplicates")
        object.__setattr__(self, "shortcut_tags", tags)
        if self.split not in DATASET_SPLITS:
            raise DatasetValidationError(f"split must be one of {sorted(DATASET_SPLITS)}")
        if self.reward_claimed and self.current_count < self.target_count:
            raise DatasetValidationError(
                "reward_claimed cannot be true before target_count is reached"
            )
        if self.ground_truth_action is ActionType.GRANT_REWARD and (
            self.current_count < self.target_count or self.reward_claimed
        ):
            raise DatasetValidationError(
                "grant_reward requires completed, unclaimed server state"
            )
        if (
            self.ground_truth_action is ActionType.ALREADY_CLAIMED
            and not self.reward_claimed
        ):
            raise DatasetValidationError(
                "already_claimed requires reward_claimed server state"
            )


@dataclass(frozen=True, slots=True)
class SynthesizedExpression:
    """Player wording and receptionist answer synthesized from one blueprint."""

    player_utterance: str
    reference_dialogue: str

    def __post_init__(self) -> None:
        for field_name in ("player_utterance", "reference_dialogue"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise DatasetValidationError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class DatasetCaseDraft(DatasetCaseBlueprint):
    """One synthesized case before any AI approval claim is attached."""

    player_utterance: str
    reference_dialogue: str

    def __post_init__(self) -> None:
        DatasetCaseBlueprint.__post_init__(self)
        SynthesizedExpression(self.player_utterance, self.reference_dialogue)

    def to_blueprint(self) -> DatasetCaseBlueprint:
        return DatasetCaseBlueprint(
            quest_name=self.quest_name,
            target_count=self.target_count,
            current_count=self.current_count,
            reward_description=self.reward_description,
            reward_claimed=self.reward_claimed,
            player_intent=self.player_intent,
            ground_truth_action=self.ground_truth_action,
            shortcut_tags=self.shortcut_tags,
            expression_group=self.expression_group,
            split=self.split,
        )

    def to_dict(self) -> dict[str, object]:
        """Return draft content without claiming an approval status."""
        return {
            "quest_name": self.quest_name,
            "target_count": self.target_count,
            "current_count": self.current_count,
            "reward_description": self.reward_description,
            "reward_claimed": self.reward_claimed,
            "player_intent": self.player_intent,
            "ground_truth_action": self.ground_truth_action.value,
            "player_utterance": self.player_utterance,
            "reference_dialogue": self.reference_dialogue,
            "shortcut_tags": list(self.shortcut_tags),
            "expression_group": self.expression_group,
            "split": self.split,
        }

    def with_review_status(self, review_status: str) -> DatasetCase:
        return DatasetCase(
            quest_name=self.quest_name,
            target_count=self.target_count,
            current_count=self.current_count,
            reward_description=self.reward_description,
            reward_claimed=self.reward_claimed,
            player_intent=self.player_intent,
            ground_truth_action=self.ground_truth_action,
            shortcut_tags=self.shortcut_tags,
            expression_group=self.expression_group,
            split=self.split,
            player_utterance=self.player_utterance,
            reference_dialogue=self.reference_dialogue,
            review_status=review_status,
        )


@dataclass(frozen=True, slots=True)
class DatasetCase(DatasetCaseDraft):
    """One AI- or user-approved case; approval is absent from drafts."""

    review_status: str

    def __post_init__(self) -> None:
        DatasetCaseDraft.__post_init__(self)
        if self.review_status not in REVIEW_STATUSES:
            raise DatasetValidationError(
                f"review_status must be one of {sorted(REVIEW_STATUSES)}"
            )

    def as_draft(self) -> DatasetCaseDraft:
        return DatasetCaseDraft(
            quest_name=self.quest_name,
            target_count=self.target_count,
            current_count=self.current_count,
            reward_description=self.reward_description,
            reward_claimed=self.reward_claimed,
            player_intent=self.player_intent,
            ground_truth_action=self.ground_truth_action,
            shortcut_tags=self.shortcut_tags,
            expression_group=self.expression_group,
            split=self.split,
            player_utterance=self.player_utterance,
            reference_dialogue=self.reference_dialogue,
        )

    def to_dict(self) -> dict[str, object]:
        """Return the exact JSON-compatible case schema."""
        payload = DatasetCaseDraft.to_dict(self)
        payload["review_status"] = self.review_status
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> DatasetCase:
        """Load one case while rejecting missing or additional schema fields."""
        if not isinstance(payload, dict) or set(payload) != CASE_FIELDS:
            raise DatasetValidationError(
                f"dataset case must contain exactly these fields: {sorted(CASE_FIELDS)}"
            )
        values = dict(payload)
        try:
            values["ground_truth_action"] = ActionType(values["ground_truth_action"])
        except (TypeError, ValueError) as error:
            raise DatasetValidationError(
                "ground_truth_action must be an allowed ActionType"
            ) from error
        try:
            return cls(**values)  # type: ignore[arg-type]
        except TypeError as error:
            raise DatasetValidationError(str(error)) from error


CaseSynthesizer = Callable[[DatasetCaseBlueprint], SynthesizedExpression]
AIReviewer = Callable[[tuple[DatasetCaseDraft, ...]], Sequence[str]]


@dataclass(frozen=True, slots=True)
class UserReviewDecision:
    """One human decision in an exhaustive 20-case review."""

    case_index: int
    decision: str
    note: str = ""

    def __post_init__(self) -> None:
        if type(self.case_index) is not int or not 0 <= self.case_index < 20:
            raise DatasetValidationError("case_index must be between 0 and 19")
        if self.decision not in {"approve", "modify", "exclude"}:
            raise DatasetValidationError(
                "user decision must be approve, modify, or exclude"
            )
        if not isinstance(self.note, str):
            raise DatasetValidationError("user decision note must be a string")

    def to_dict(self) -> dict[str, object]:
        return {
            "case_index": self.case_index,
            "decision": self.decision,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ReviewBatchArtifact:
    """Readable record of AI review and subsequent user approval for one batch."""

    batch_id: str
    cases: tuple[DatasetCaseDraft | DatasetCase, ...]
    ai_approved: bool
    ai_review_issues: tuple[str, ...]
    user_approval_status: str
    review_duration_seconds: float | None = None
    user_decisions: tuple[UserReviewDecision, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "case_count": len(self.cases),
            "ai_review": {
                "status": "approved" if self.ai_approved else "needs_revision",
                "issues": list(self.ai_review_issues),
            },
            "user_review": {
                "status": self.user_approval_status,
                "duration_seconds": self.review_duration_seconds,
                "decisions": [decision.to_dict() for decision in self.user_decisions],
            },
            "cases": [case.to_dict() for case in self.cases],
        }


def _validate_review_batch(cases: tuple[DatasetCaseDraft, ...]) -> None:
    if len(cases) != 20:
        raise DatasetValidationError("review batch must contain exactly 20 cases")
    if {case.ground_truth_action for case in cases} != set(ActionType):
        raise DatasetValidationError("review batch must mix all six actions")
    utterances = [case.player_utterance.strip() for case in cases]
    if len(utterances) != len(set(utterances)):
        raise DatasetValidationError("review batch contains duplicate player_utterance")


class PilotReviewFlow:
    """Enforce sequential 20-case AI review and explicit user approval gates."""

    def __init__(self) -> None:
        self._current: ReviewBatchArtifact | None = None
        self._artifacts: list[ReviewBatchArtifact] = []

    @property
    def artifacts(self) -> tuple[ReviewBatchArtifact, ...]:
        return tuple(self._artifacts)

    def submit_batch(
        self,
        batch_id: str,
        cases: Sequence[DatasetCaseDraft | DatasetCase],
        *,
        ai_reviewer: AIReviewer,
    ) -> ReviewBatchArtifact:
        if not isinstance(batch_id, str) or not batch_id.strip():
            raise DatasetValidationError("batch_id must be a non-empty string")
        if self._current is not None and self._current.user_approval_status != "approved":
            if self._current.batch_id != batch_id:
                state = (
                    "user approval"
                    if self._current.user_approval_status == "pending"
                    else "current batch revision"
                )
                raise DatasetValidationError(f"{state} is required before the next batch")
        drafts = tuple(
            case.as_draft() if isinstance(case, DatasetCase) else case
            for case in cases
        )
        _validate_review_batch(drafts)
        try:
            issues = tuple(str(issue).strip() for issue in ai_reviewer(drafts))
        except Exception as error:
            issues = (f"AI reviewer failed: {error}",)
        issues = tuple(issue for issue in issues if issue)
        reviewed_cases: tuple[DatasetCaseDraft | DatasetCase, ...]
        if issues:
            reviewed_cases = drafts
        else:
            reviewed_cases = tuple(
                case.with_review_status("ai_approved") for case in drafts
            )
        artifact = ReviewBatchArtifact(
            batch_id=batch_id,
            cases=reviewed_cases,
            ai_approved=not issues,
            ai_review_issues=issues,
            user_approval_status="pending" if not issues else "blocked",
        )
        self._current = artifact
        self._artifacts.append(artifact)
        return artifact

    def generate_batch(
        self,
        batch_id: str,
        blueprints: Sequence[DatasetCaseBlueprint],
        *,
        synthesizer: CaseSynthesizer,
        ai_reviewer: AIReviewer,
    ) -> ReviewBatchArtifact:
        """Synthesize expressions independently, then validate and review them."""
        if len(blueprints) != 20:
            raise DatasetValidationError("generation batch must contain 20 blueprints")
        drafts: list[DatasetCaseDraft] = []
        for index, blueprint in enumerate(blueprints):
            try:
                expression = synthesizer(blueprint)
            except Exception as error:
                raise DatasetValidationError(
                    f"synthesis failed for case {index}: {error}"
                ) from error
            if not isinstance(expression, SynthesizedExpression):
                raise DatasetValidationError(
                    "synthesizer must return SynthesizedExpression"
                )
            drafts.append(
                DatasetCaseDraft(
                    quest_name=blueprint.quest_name,
                    target_count=blueprint.target_count,
                    current_count=blueprint.current_count,
                    reward_description=blueprint.reward_description,
                    reward_claimed=blueprint.reward_claimed,
                    player_intent=blueprint.player_intent,
                    ground_truth_action=blueprint.ground_truth_action,
                    shortcut_tags=blueprint.shortcut_tags,
                    expression_group=blueprint.expression_group,
                    split=blueprint.split,
                    player_utterance=expression.player_utterance,
                    reference_dialogue=expression.reference_dialogue,
                )
            )
        return self.submit_batch(batch_id, drafts, ai_reviewer=ai_reviewer)

    def review_current_batch(
        self,
        decisions: Sequence[UserReviewDecision],
        *,
        review_duration_seconds: float,
    ) -> ReviewBatchArtifact:
        """Record all 20 user decisions; revisions must re-enter AI review."""
        if self._current is None:
            raise DatasetValidationError("there is no current batch to review")
        if not self._current.ai_approved:
            raise DatasetValidationError("AI review must pass before user review")
        _validate_review_duration(review_duration_seconds)
        normalized_decisions = tuple(decisions)
        if len(normalized_decisions) != 20 or {
            decision.case_index for decision in normalized_decisions
        } != set(range(20)):
            raise DatasetValidationError(
                "user review must contain one decision for every case"
            )
        all_approved = all(
            decision.decision == "approve" for decision in normalized_decisions
        )
        cases = self._current.cases
        if all_approved:
            cases = tuple(
                case.with_review_status("user_approved")
                if isinstance(case, DatasetCaseDraft)
                and not isinstance(case, DatasetCase)
                else replace(case, review_status="user_approved")
                for case in cases
            )
        artifact = replace(
            self._current,
            cases=cases,
            user_approval_status="approved" if all_approved else "changes_requested",
            review_duration_seconds=float(review_duration_seconds),
            user_decisions=normalized_decisions,
        )
        self._current = artifact
        self._artifacts.append(artifact)
        return artifact

    def approve_current_batch(
        self, *, review_duration_seconds: float
    ) -> ReviewBatchArtifact:
        return self.review_current_batch(
            tuple(
                UserReviewDecision(index, "approve") for index in range(20)
            ),
            review_duration_seconds=review_duration_seconds,
        )


def _validate_review_duration(review_duration_seconds: float) -> None:
    if (
        isinstance(review_duration_seconds, bool)
        or not isinstance(review_duration_seconds, (int, float))
        or review_duration_seconds < 0
    ):
        raise DatasetValidationError(
            "review_duration_seconds must be a non-negative number"
        )


def _normalized_utterance(case: DatasetCase) -> str:
    return " ".join(case.player_utterance.split()).casefold()


def _expression_fingerprint(case: DatasetCase) -> str:
    utterance = _normalized_utterance(case)
    utterance = utterance.replace(case.quest_name.casefold(), "<quest>")
    utterance = re.sub(r"\d+", "<number>", utterance)
    return re.sub(r"[^\w<>]+", " ", utterance).strip()


def validate_dataset(cases: Sequence[DatasetCase]) -> None:
    """Validate collection-level duplicate and expression-split invariants."""
    if not cases:
        raise DatasetValidationError("dataset must contain at least one case")
    utterance_groups: dict[str, str] = {}
    group_splits: dict[str, set[str]] = {}
    fingerprints: dict[str, tuple[str, str]] = {}
    observed: list[DatasetCase] = []
    for case in cases:
        normalized_utterance = _normalized_utterance(case)
        previous_group = utterance_groups.get(normalized_utterance)
        if previous_group is not None:
            raise DatasetValidationError(
                "duplicate player_utterance appears in expression groups "
                f"{previous_group!r} and {case.expression_group!r}"
            )
        utterance_groups[normalized_utterance] = case.expression_group
        group_splits.setdefault(case.expression_group, set()).add(case.split)
        fingerprint = _expression_fingerprint(case)
        prior_pattern = fingerprints.get(fingerprint)
        if prior_pattern is not None and prior_pattern[0] != case.expression_group:
            raise DatasetValidationError(
                "equivalent expression pattern must share one expression_group"
            )
        fingerprints[fingerprint] = (case.expression_group, case.split)
        for prior_case in observed:
            if prior_case.split == case.split:
                continue
            similarity = SequenceMatcher(
                None,
                _expression_fingerprint(prior_case),
                fingerprint,
            ).ratio()
            if similarity >= 0.92:
                raise DatasetValidationError(
                    "near-paraphrase expression pattern crosses splits"
                )
        observed.append(case)
    crossing_groups = {
        group: sorted(splits)
        for group, splits in group_splits.items()
        if len(splits) > 1
    }
    if crossing_groups:
        raise DatasetValidationError(
            f"expression_group crosses splits: {crossing_groups}"
        )


@dataclass(frozen=True, slots=True)
class PilotDatasetSummary:
    """Counts captured after the complete pilot contract passes validation."""

    total: int
    action_counts: dict[str, int]
    shortcut_tag_counts: dict[str, int]
    expression_group_count: int
    review_status: str


def validate_pilot_dataset(cases: Sequence[DatasetCase]) -> PilotDatasetSummary:
    """Enforce the approved 60-case pilot's balance and provenance contract."""
    validate_dataset(cases)
    if len(cases) != 60:
        raise DatasetValidationError("pilot dataset must contain exactly 60 cases")
    action_counts = Counter(case.ground_truth_action.value for case in cases)
    expected_action_counts = {action.value: 10 for action in ActionType}
    if dict(action_counts) != expected_action_counts:
        raise DatasetValidationError(
            f"pilot action counts must be {expected_action_counts}, got {dict(action_counts)}"
        )
    if {case.split for case in cases} != {"train_pilot"}:
        raise DatasetValidationError("all pilot cases must use split train_pilot")
    review_statuses = {case.review_status for case in cases}
    if len(review_statuses) != 1:
        raise DatasetValidationError(
            "all pilot cases must have the same review_status"
        )
    tag_counts = Counter(tag for case in cases for tag in case.shortcut_tags)
    missing_tags = SHORTCUT_TAGS - set(tag_counts)
    if missing_tags:
        raise DatasetValidationError(
            f"pilot dataset is missing shortcut tags: {sorted(missing_tags)}"
        )
    return PilotDatasetSummary(
        total=len(cases),
        action_counts=expected_action_counts,
        shortcut_tag_counts={tag: tag_counts[tag] for tag in sorted(tag_counts)},
        expression_group_count=len({case.expression_group for case in cases}),
        review_status=next(iter(review_statuses)),
    )


def prepare_training_cases(
    cases: Sequence[DatasetCase],
) -> tuple[DatasetCase, ...]:
    """Allow only a complete, user-approved pilot into downstream training."""
    validate_pilot_dataset(cases)
    if {case.review_status for case in cases} != {"user_approved"}:
        raise DatasetValidationError(
            "user approval is required before pilot cases enter training"
        )
    return tuple(cases)


def load_pilot_dataset(path: Path | None = None) -> tuple[DatasetCase, ...]:
    """Load the checked-in pilot JSONL through the strict case schema."""
    source = PILOT_DATASET_PATH if path is None else path
    cases: list[DatasetCase] = []
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise DatasetValidationError(f"could not read pilot dataset: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise DatasetValidationError(
                f"pilot dataset contains a blank line at {line_number}"
            )
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise DatasetValidationError(
                f"pilot dataset line {line_number} is invalid JSON: {error.msg}"
            ) from error
        try:
            cases.append(DatasetCase.from_dict(payload))
        except DatasetValidationError as error:
            raise DatasetValidationError(
                f"pilot dataset line {line_number}: {error}"
            ) from error
    return tuple(cases)


def load_review_manifest(path: Path | None = None) -> dict[str, object]:
    """Load the human-readable batch review and approval history."""
    source = REVIEW_MANIFEST_PATH if path is None else path
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetValidationError(f"could not load review manifest: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("batches"), list):
        raise DatasetValidationError("review manifest must be an object with batches")
    return payload


def validate_review_manifest(
    cases: Sequence[DatasetCase],
    manifest: dict[str, object],
    *,
    dataset_path: Path,
) -> None:
    """Bind three approval records to the exact reviewed dataset bytes."""
    expected_digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if manifest.get("dataset") != dataset_path.name:
        raise DatasetValidationError("review manifest references the wrong dataset")
    if manifest.get("dataset_sha256") != expected_digest:
        raise DatasetValidationError("review manifest dataset_sha256 does not match")
    if manifest.get("batch_size") != 20:
        raise DatasetValidationError("review manifest batch_size must be 20")
    batches = manifest.get("batches")
    if not isinstance(batches, list) or len(batches) != 3:
        raise DatasetValidationError("review manifest must contain exactly three batches")
    expected_start = 1
    for batch_number, batch in enumerate(batches, start=1):
        if not isinstance(batch, dict):
            raise DatasetValidationError("each review batch must be an object")
        start = batch.get("line_start")
        end = batch.get("line_end")
        if start != expected_start or end != expected_start + 19:
            raise DatasetValidationError(
                f"review batch {batch_number} must cover the next 20 lines"
            )
        batch_cases = cases[start - 1 : end]
        if len(batch_cases) != 20 or {
            case.ground_truth_action for case in batch_cases
        } != set(ActionType):
            raise DatasetValidationError(
                f"review batch {batch_number} must contain 20 mixed-action cases"
            )
        if batch.get("generation_validation") != {"status": "passed"}:
            raise DatasetValidationError(
                f"review batch {batch_number} did not pass generation validation"
            )
        if batch.get("ai_review") != {"status": "approved", "issues": []}:
            raise DatasetValidationError(
                f"review batch {batch_number} did not pass AI review"
            )
        user_review = batch.get("user_review")
        if not isinstance(user_review, dict) or user_review.get("status") not in {
            "pending",
            "approved",
        }:
            raise DatasetValidationError(
                f"review batch {batch_number} has an invalid user review status"
            )
        user_status = user_review["status"]
        duration = user_review.get("duration_seconds")
        if user_status == "approved" and (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or duration < 0
        ):
            raise DatasetValidationError(
                f"review batch {batch_number} lacks a valid review duration"
            )
        if user_status == "pending" and duration is not None:
            raise DatasetValidationError(
                f"review batch {batch_number} has duration before user review"
            )
        expected_case_status = (
            "user_approved" if user_status == "approved" else "ai_approved"
        )
        if {case.review_status for case in batch_cases} != {expected_case_status}:
            raise DatasetValidationError(
                f"review batch {batch_number} case status does not match its review"
            )
        expected_start = end + 1
    if expected_start - 1 != len(cases):
        raise DatasetValidationError("review manifest does not cover the full dataset")


def load_shortcut_baseline_report(path: Path | None = None) -> dict[str, object]:
    """Load the reproducible report for deliberately naive policy scores."""
    source = SHORTCUT_BASELINE_PATH if path is None else path
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetValidationError(
            f"could not load shortcut baseline report: {error}"
        ) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("policies"), dict):
        raise DatasetValidationError(
            "shortcut baseline report must be an object with policies"
        )
    return payload


@dataclass(frozen=True, slots=True)
class PolicyScore:
    """Accuracy of one deliberately naive shortcut policy."""

    correct: int
    total: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total


ShortcutPolicy = Callable[[DatasetCase], ActionType]


def _grant_on_state_alone(case: DatasetCase) -> ActionType:
    if case.current_count >= case.target_count and not case.reward_claimed:
        return ActionType.GRANT_REWARD
    return ActionType.EXPLAIN_PROGRESS


def evaluate_shortcut_baselines(
    cases: Sequence[DatasetCase],
) -> dict[str, PolicyScore]:
    """Score shortcuts that the balanced dataset is designed to expose."""
    validate_dataset(cases)
    policies: dict[str, ShortcutPolicy] = {
        "always_grant": lambda _: ActionType.GRANT_REWARD,
        "always_reject": lambda _: ActionType.EXPLAIN_PROGRESS,
        "always_other": lambda _: ActionType.OTHER,
        "always_clarify": lambda _: ActionType.CLARIFY,
        "grant_on_state_alone": _grant_on_state_alone,
    }
    return {
        name: PolicyScore(
            correct=sum(
                policy(case) is case.ground_truth_action for case in cases
            ),
            total=len(cases),
        )
        for name, policy in policies.items()
    }


def evaluate_shortcut_patterns(
    cases: Sequence[DatasetCase],
) -> dict[str, PolicyScore]:
    """Score each required exploit only on cases tagged for that pattern."""
    validate_dataset(cases)
    policies: dict[str, ShortcutPolicy] = {
        "always_reject": lambda _: ActionType.EXPLAIN_PROGRESS,
        "state_only_grant": _grant_on_state_alone,
        "accept_false_claim": lambda _: ActionType.GRANT_REWARD,
        "duplicate_grant": lambda _: ActionType.GRANT_REWARD,
        "abuse_other_clarify": lambda _: ActionType.OTHER,
        "ignore_cancel": lambda _: ActionType.GRANT_REWARD,
    }
    scores: dict[str, PolicyScore] = {}
    for tag, policy in policies.items():
        tagged_cases = tuple(case for case in cases if tag in case.shortcut_tags)
        if not tagged_cases:
            raise DatasetValidationError(f"dataset has no cases for shortcut tag {tag}")
        scores[tag] = PolicyScore(
            correct=sum(
                policy(case) is case.ground_truth_action for case in tagged_cases
            ),
            total=len(tagged_cases),
        )
    return scores

def build_model_prompt(
    case: DatasetCase,
    *,
    character_persona: str = DEFAULT_CHARACTER_PERSONA,
    rules: str = DEFAULT_RULES,
) -> str:
    """Build model input without any label, intent, or reference-answer fields."""
    return json.dumps(
        {
            "character_persona": character_persona,
            "rules": rules,
            "server_state": {
                "quest_name": case.quest_name,
                "target_count": case.target_count,
                "current_count": case.current_count,
                "reward_description": case.reward_description,
                "reward_claimed": case.reward_claimed,
            },
            "player_utterance": case.player_utterance,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
