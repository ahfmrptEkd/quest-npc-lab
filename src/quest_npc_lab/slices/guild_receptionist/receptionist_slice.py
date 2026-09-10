"""Validation and execution boundary for one guild receptionist request."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
import json
from typing import Callable

MAX_QUEST_NAME_LENGTH = 200
MAX_REWARD_DESCRIPTION_LENGTH = 500
MAX_UTTERANCE_LENGTH = 2_000
MAX_PERSONA_LENGTH = 4_000
MAX_RULES_LENGTH = 4_000

DEFAULT_CHARACTER_PERSONA = "친절하지만 서버 규칙을 엄격히 지키는 길드 접수원"
DEFAULT_RULES = (
    "현재 서버 상태만 신뢰한다. action은 grant_reward, explain_progress, "
    "explain_reward, already_claimed, clarify, other 중 하나여야 한다. "
    "action과 비어 있지 않은 dialogue만 포함하는 JSON 객체 하나를 출력한다. "
    "grant_reward는 목표를 달성하고 보상을 아직 받지 않았을 때만 선택한다."
)


class Action(str, Enum):
    GRANT_REWARD = "grant_reward"
    EXPLAIN_PROGRESS = "explain_progress"
    EXPLAIN_REWARD = "explain_reward"
    ALREADY_CLAIMED = "already_claimed"
    CLARIFY = "clarify"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class QuestState:
    quest_name: str
    target_count: int
    current_count: int
    reward_description: str
    reward_claimed: bool


@dataclass(frozen=True, slots=True)
class RequestInput:
    state: QuestState
    player_utterance: str
    ground_truth_action: Action | None = None
    character_persona: str = DEFAULT_CHARACTER_PERSONA
    rules: str = DEFAULT_RULES


@dataclass(frozen=True, slots=True)
class ParsedOutput:
    action: Action
    dialogue: str


@dataclass(frozen=True, slots=True)
class Evaluation:
    is_format_valid: bool
    is_action_correct: bool | None
    score: int | None


@dataclass(frozen=True, slots=True)
class ServerExecution:
    approved: bool
    state_changed: bool
    final_state: QuestState


@dataclass(frozen=True, slots=True)
class RunError:
    stage: str
    reason: str


@dataclass(frozen=True, slots=True)
class RunArtifact:
    request_input: RequestInput
    raw_output: str | None
    parsed_output: ParsedOutput | None
    model_action: Action | None
    evaluation: Evaluation
    server_execution: ServerExecution
    error: RunError | None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible artifact with explicit pipeline stages."""
        ground_truth = self.request_input.ground_truth_action
        parsed_output = None
        if self.parsed_output is not None:
            parsed_output = {
                "action": self.parsed_output.action.value,
                "dialogue": self.parsed_output.dialogue,
            }
        error = None if self.error is None else asdict(self.error)
        return {
            "request_input": {
                "state": asdict(self.request_input.state),
                "player_utterance": self.request_input.player_utterance,
                "ground_truth_action": (
                    ground_truth.value
                    if isinstance(ground_truth, Action)
                    else ground_truth
                ),
                "character_persona": self.request_input.character_persona,
                "rules": self.request_input.rules,
            },
            "raw_output": self.raw_output,
            "parsed_output": parsed_output,
            "model_action": (
                None if self.model_action is None else self.model_action.value
            ),
            "evaluation": asdict(self.evaluation),
            "server_execution": {
                "approved": self.server_execution.approved,
                "state_changed": self.server_execution.state_changed,
                "final_state": asdict(self.server_execution.final_state),
            },
            "error": error,
        }

    def to_json(self) -> str:
        """Serialize the complete run artifact deterministically."""
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=False
        )


class StateValidationError(ValueError):
    """Raised when trusted server state violates the quest invariants."""


class RequestValidationError(ValueError):
    """Raised when a request cannot safely cross the model boundary."""


class OutputParseError(ValueError):
    """Raised when model output violates the strict output contract."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise OutputParseError(f"duplicate key is not allowed: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise OutputParseError(f"non-standard JSON constant is not allowed: {value}")


def parse_model_output(raw_output: str) -> ParsedOutput:
    """Parse one model response without correction or regeneration."""
    if not isinstance(raw_output, str):
        raise OutputParseError("model output must be a string")
    cleaned = raw_output.strip()
    if "```" in cleaned:
        raise OutputParseError("markdown code fences are not allowed")
    try:
        payload = json.loads(
            cleaned,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except OutputParseError:
        raise
    except json.JSONDecodeError as error:
        raise OutputParseError(f"model output must be valid JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise OutputParseError("model output must be a single JSON object")
    if set(payload) != {"action", "dialogue"}:
        raise OutputParseError(
            'model output must contain exactly the fields "action" and "dialogue"'
        )
    action_value = payload["action"]
    dialogue = payload["dialogue"]
    if not isinstance(action_value, str):
        raise OutputParseError("action must be a string")
    try:
        action = Action(action_value)
    except ValueError as error:
        raise OutputParseError(f"action must be an allowed action: {action_value}") from error
    if not isinstance(dialogue, str):
        raise OutputParseError("dialogue must be a string")
    if not dialogue.strip():
        raise OutputParseError("dialogue must be non-empty and non-whitespace")
    return ParsedOutput(action=action, dialogue=dialogue)


def _validate_nonempty_string(
    value: object, *, field: str, maximum_length: int, error_type: type[ValueError]
) -> None:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{field} must be a non-empty string")
    if len(value) > maximum_length:
        raise error_type(
            f"{field} must contain at most {maximum_length} characters"
        )


def _validate_state(state: QuestState) -> None:
    _validate_nonempty_string(
        state.quest_name,
        field="quest_name",
        maximum_length=MAX_QUEST_NAME_LENGTH,
        error_type=StateValidationError,
    )
    if type(state.target_count) is not int or state.target_count <= 0:
        raise StateValidationError("target_count must be a positive integer")
    if type(state.current_count) is not int or state.current_count < 0:
        raise StateValidationError("current_count must be a non-negative integer")
    _validate_nonempty_string(
        state.reward_description,
        field="reward_description",
        maximum_length=MAX_REWARD_DESCRIPTION_LENGTH,
        error_type=StateValidationError,
    )
    if not isinstance(state.reward_claimed, bool):
        raise StateValidationError("reward_claimed must be a boolean")
    if state.reward_claimed and state.current_count < state.target_count:
        raise StateValidationError(
            "reward_claimed cannot be true before target_count is reached"
        )


def _execute_action(action: Action, state: QuestState) -> ServerExecution:
    if action is not Action.GRANT_REWARD:
        return ServerExecution(
            approved=True,
            state_changed=False,
            final_state=state,
        )
    can_grant = state.current_count >= state.target_count and not state.reward_claimed
    if not can_grant:
        return ServerExecution(
            approved=False,
            state_changed=False,
            final_state=state,
        )
    return ServerExecution(
        approved=True,
        state_changed=True,
        final_state=replace(state, reward_claimed=True),
    )


def _validate_request_input(request_input: RequestInput) -> None:
    _validate_state(request_input.state)
    _validate_nonempty_string(
        request_input.player_utterance,
        field="player_utterance",
        maximum_length=MAX_UTTERANCE_LENGTH,
        error_type=RequestValidationError,
    )
    _validate_nonempty_string(
        request_input.character_persona,
        field="character_persona",
        maximum_length=MAX_PERSONA_LENGTH,
        error_type=RequestValidationError,
    )
    _validate_nonempty_string(
        request_input.rules,
        field="rules",
        maximum_length=MAX_RULES_LENGTH,
        error_type=RequestValidationError,
    )
    if (
        request_input.ground_truth_action is not None
        and not isinstance(request_input.ground_truth_action, Action)
    ):
        raise RequestValidationError(
            "ground_truth_action must be an allowed Action or None"
        )


def _failure_artifact(
    request_input: RequestInput,
    *,
    stage: str,
    reason: str,
    raw_output: str | None,
    format_was_evaluated: bool,
) -> RunArtifact:
    has_ground_truth = request_input.ground_truth_action is not None
    return RunArtifact(
        request_input=request_input,
        raw_output=raw_output,
        parsed_output=None,
        model_action=None,
        evaluation=Evaluation(
            is_format_valid=False,
            is_action_correct=(
                False if format_was_evaluated and has_ground_truth else None
            ),
            score=0 if format_was_evaluated and has_ground_truth else None,
        ),
        server_execution=ServerExecution(
            approved=False,
            state_changed=False,
            final_state=request_input.state,
        ),
        error=RunError(stage=stage, reason=reason),
    )


def execute_request(
    request_input: RequestInput, model: Callable[[str], str]
) -> RunArtifact:
    """Execute one isolated NPC request."""
    try:
        _validate_request_input(request_input)
    except (RequestValidationError, StateValidationError) as error:
        return _failure_artifact(
            request_input,
            stage="input_validation",
            reason=str(error),
            raw_output=None,
            format_was_evaluated=False,
        )
    prompt = json.dumps(
        {
            "character_persona": request_input.character_persona,
            "rules": request_input.rules,
            "server_state": asdict(request_input.state),
            "player_utterance": request_input.player_utterance,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    raw_output = model(prompt)
    try:
        parsed_output = parse_model_output(raw_output)
    except OutputParseError as error:
        return _failure_artifact(
            request_input,
            stage="model_output",
            reason=str(error),
            raw_output=raw_output,
            format_was_evaluated=True,
        )
    is_action_correct = (
        None
        if request_input.ground_truth_action is None
        else parsed_output.action is request_input.ground_truth_action
    )
    score = None if is_action_correct is None else int(is_action_correct)
    return RunArtifact(
        request_input=request_input,
        raw_output=raw_output,
        parsed_output=parsed_output,
        model_action=parsed_output.action,
        evaluation=Evaluation(True, is_action_correct, score),
        server_execution=_execute_action(parsed_output.action, request_input.state),
        error=None,
    )
