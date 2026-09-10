from __future__ import annotations

import json

import pytest

from quest_npc_lab.slices.guild_receptionist import (
    Action,
    MAX_PERSONA_LENGTH,
    MAX_QUEST_NAME_LENGTH,
    MAX_REWARD_DESCRIPTION_LENGTH,
    MAX_RULES_LENGTH,
    MAX_UTTERANCE_LENGTH,
    QuestState,
    RequestInput,
    execute_request,
)
from quest_npc_lab.slices.guild_receptionist.__main__ import main


def test_contradictory_state_is_rejected_before_model_call() -> None:
    calls: list[str] = []
    request = RequestInput(
        state=QuestState(
            quest_name="늑대 소탕",
            target_count=5,
            current_count=4,
            reward_description="금화 100개",
            reward_claimed=True,
        ),
        player_utterance="보상을 주세요.",
        ground_truth_action=Action.ALREADY_CLAIMED,
    )

    artifact = execute_request(request, calls.append)

    assert calls == []
    assert artifact.raw_output is None
    assert artifact.evaluation.score is None
    assert artifact.server_execution.final_state == request.state
    assert artifact.error is not None
    assert artifact.error.stage == "input_validation"
    assert "reward_claimed" in artifact.error.reason
    assert json.loads(artifact.to_json())["raw_output"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quest_name", ""),
        ("quest_name", "q" * (MAX_QUEST_NAME_LENGTH + 1)),
        ("target_count", 0),
        ("target_count", -1),
        ("target_count", True),
        ("current_count", -1),
        ("current_count", False),
        ("reward_description", "  "),
        (
            "reward_description",
            "r" * (MAX_REWARD_DESCRIPTION_LENGTH + 1),
        ),
        ("reward_claimed", 1),
    ],
)
def test_invalid_quest_state_boundaries_are_rejected(
    field: str, value: object
) -> None:
    state_values: dict[str, object] = {
        "quest_name": "늑대 소탕",
        "target_count": 5,
        "current_count": 0,
        "reward_description": "금화 100개",
        "reward_claimed": False,
    }
    state_values[field] = value
    request = RequestInput(
        state=QuestState(**state_values),  # type: ignore[arg-type]
        player_utterance="진행 상황을 알려 주세요.",
    )

    artifact = execute_request(
        request, lambda _: '{"action":"other","dialogue":"안녕"}'
    )

    assert artifact.raw_output is None
    assert artifact.server_execution.state_changed is False
    assert artifact.error is not None
    assert field in artifact.error.reason


@pytest.mark.parametrize("utterance", ["", "   ", "u" * (MAX_UTTERANCE_LENGTH + 1)])
def test_invalid_player_utterance_boundaries_are_rejected(utterance: str) -> None:
    calls: list[str] = []
    request = RequestInput(
        state=QuestState("늑대 소탕", 5, 0, "금화 100개", False),
        player_utterance=utterance,
    )

    artifact = execute_request(request, calls.append)

    assert calls == []
    assert artifact.raw_output is None
    assert artifact.error is not None
    assert "player_utterance" in artifact.error.reason


def test_exact_text_size_limits_are_accepted() -> None:
    request = RequestInput(
        state=QuestState(
            "q" * MAX_QUEST_NAME_LENGTH,
            1,
            0,
            "r" * MAX_REWARD_DESCRIPTION_LENGTH,
            False,
        ),
        player_utterance="u" * MAX_UTTERANCE_LENGTH,
    )

    artifact = execute_request(
        request, lambda _: '{"action":"other","dialogue":"안녕"}'
    )

    assert artifact.evaluation.is_format_valid is True


def test_invalid_ground_truth_action_is_rejected_before_model_call() -> None:
    calls: list[str] = []
    request = RequestInput(
        state=QuestState("늑대 소탕", 5, 0, "금화 100개", False),
        player_utterance="안녕하세요.",
        ground_truth_action="other",  # type: ignore[arg-type]
    )

    artifact = execute_request(request, calls.append)

    assert calls == []
    assert artifact.raw_output is None
    assert artifact.error is not None
    assert "ground_truth_action" in artifact.error.reason


@pytest.mark.parametrize(
    ("field", "maximum_length"),
    [
        ("character_persona", MAX_PERSONA_LENGTH),
        ("rules", MAX_RULES_LENGTH),
    ],
)
def test_prompt_instruction_size_boundaries_are_enforced_before_model_call(
    field: str, maximum_length: int
) -> None:
    state = QuestState("늑대 소탕", 5, 0, "금화 100개", False)
    accepted_values = {
        "character_persona": "p" * MAX_PERSONA_LENGTH,
        "rules": "r" * MAX_RULES_LENGTH,
    }
    accepted = execute_request(
        RequestInput(state, "안녕하세요.", **accepted_values),  # type: ignore[arg-type]
        lambda _: '{"action":"other","dialogue":"안녕"}',
    )
    calls: list[str] = []
    rejected_values = dict(accepted_values)
    rejected_values[field] = "x" * (maximum_length + 1)

    rejected = execute_request(
        RequestInput(state, "안녕하세요.", **rejected_values),  # type: ignore[arg-type]
        calls.append,
    )

    assert accepted.error is None
    assert calls == []
    assert rejected.error is not None
    assert field in rejected.error.reason


def test_model_receives_only_the_allowed_prompt_inputs() -> None:
    prompts: list[str] = []
    state = QuestState("늑대 소탕", 5, 5, "금화 100개", False)
    request = RequestInput(
        state=state,
        player_utterance="보상이 무엇인가요?",
        ground_truth_action=Action.EXPLAIN_REWARD,
        character_persona="친절한 길드 접수원",
        rules="현재 서버 상태만 신뢰하고 JSON 객체 하나로 답한다.",
    )

    def model(prompt: str) -> str:
        prompts.append(prompt)
        return '{"action":"explain_reward","dialogue":"보상은 금화 100개입니다."}'

    artifact = execute_request(request, model)

    assert len(prompts) == 1
    prompt = json.loads(prompts[0])
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
    assert "ground_truth_action" not in prompt
    assert artifact.request_input == request
    assert artifact.raw_output == (
        '{"action":"explain_reward","dialogue":"보상은 금화 100개입니다."}'
    )
    assert artifact.parsed_output is not None
    assert artifact.model_action is Action.EXPLAIN_REWARD
    assert artifact.evaluation.is_format_valid is True
    assert artifact.evaluation.is_action_correct is True
    assert artifact.evaluation.score == 1
    assert artifact.server_execution.approved is True
    assert artifact.server_execution.state_changed is False
    assert artifact.server_execution.final_state == state
    assert artifact.error is None


@pytest.mark.parametrize(
    ("raw_output", "reason"),
    [
        (
            '{"action":"other","action":"clarify","dialogue":"안녕"}',
            "duplicate key",
        ),
        (
            '{"action":"other","dialogue":"안녕","confidence":1}',
            "exactly",
        ),
        ('{"action":"other"}', "exactly"),
        ('{"action":1,"dialogue":"안녕"}', "action must be a string"),
        ('{"action":"other","dialogue":1}', "dialogue must be a string"),
        ('{"action":"other","dialogue":"   "}', "non-whitespace"),
        ('{"action":"invented","dialogue":"안녕"}', "allowed action"),
        ('```json\n{"action":"other","dialogue":"안녕"}\n```', "code fences"),
        ('설명: {"action":"other","dialogue":"안녕"}', "valid JSON"),
        ('{"action":"other","dialogue":"안녕"} trailing', "valid JSON"),
        ('["other", "안녕"]', "single JSON object"),
        ('{"action":"other","dialogue":NaN}', "non-standard JSON constant"),
    ],
)
def test_malformed_model_output_is_recorded_without_state_change(
    raw_output: str, reason: str
) -> None:
    state = QuestState("늑대 소탕", 5, 5, "금화 100개", False)
    request = RequestInput(
        state=state,
        player_utterance="안녕하세요.",
        ground_truth_action=Action.OTHER,
    )

    artifact = execute_request(request, lambda _: raw_output)

    assert artifact.raw_output == raw_output
    assert artifact.parsed_output is None
    assert artifact.model_action is None
    assert artifact.evaluation.is_format_valid is False
    assert artifact.evaluation.is_action_correct is False
    assert artifact.evaluation.score == 0
    assert artifact.server_execution.approved is False
    assert artifact.server_execution.state_changed is False
    assert artifact.server_execution.final_state == state
    assert artifact.error is not None
    assert artifact.error.stage == "model_output"
    assert reason in artifact.error.reason


def test_whitespace_around_the_json_object_is_allowed_without_correction() -> None:
    state = QuestState("늑대 소탕", 5, 0, "금화 100개", False)
    raw_output = ' \n {"action":"other","dialogue":"어서 오세요."}\t '

    artifact = execute_request(
        RequestInput(state=state, player_utterance="안녕하세요."),
        lambda _: raw_output,
    )

    assert artifact.raw_output == raw_output
    assert artifact.parsed_output is not None
    assert artifact.parsed_output.dialogue == "어서 오세요."
    assert artifact.evaluation.score is None


def test_unrated_malformed_output_remains_unrated() -> None:
    state = QuestState("늑대 소탕", 5, 0, "금화 100개", False)

    artifact = execute_request(
        RequestInput(state, "자유 입력"), lambda _: "not json"
    )

    assert artifact.evaluation.is_format_valid is False
    assert artifact.evaluation.is_action_correct is None
    assert artifact.evaluation.score is None


@pytest.mark.parametrize("action", list(Action))
def test_all_six_actions_are_parsed_scored_and_executed(action: Action) -> None:
    state = QuestState("늑대 소탕", 5, 5, "금화 100개", False)
    raw_output = json.dumps(
        {"action": action.value, "dialogue": f"{action.value} 응답"},
        ensure_ascii=False,
    )

    artifact = execute_request(
        RequestInput(
            state=state,
            player_utterance="테스트 요청",
            ground_truth_action=action,
        ),
        lambda _: raw_output,
    )

    assert artifact.model_action is action
    assert artifact.evaluation.score == 1
    assert artifact.server_execution.approved is True
    if action is Action.GRANT_REWARD:
        assert artifact.server_execution.state_changed is True
        assert artifact.server_execution.final_state.reward_claimed is True
    else:
        assert artifact.server_execution.state_changed is False
        assert artifact.server_execution.final_state == state


@pytest.mark.parametrize(
    ("state", "ground_truth"),
    [
        (QuestState("늑대 소탕", 5, 4, "금화 100개", False), Action.EXPLAIN_PROGRESS),
        (QuestState("늑대 소탕", 5, 5, "금화 100개", True), Action.ALREADY_CLAIMED),
    ],
)
def test_server_blocks_reward_grants_that_break_server_rules(
    state: QuestState, ground_truth: Action
) -> None:
    artifact = execute_request(
        RequestInput(
            state=state,
            player_utterance="보상을 다시 주세요.",
            ground_truth_action=ground_truth,
        ),
        lambda _: '{"action":"grant_reward","dialogue":"보상을 드립니다."}',
    )

    assert artifact.model_action is Action.GRANT_REWARD
    assert artifact.evaluation.is_action_correct is False
    assert artifact.evaluation.score == 0
    assert artifact.server_execution.approved is False
    assert artifact.server_execution.state_changed is False
    assert artifact.server_execution.final_state == state


def test_duplicate_reward_claim_is_prevented_across_explicit_session_state() -> None:
    initial_state = QuestState("늑대 소탕", 5, 5, "금화 100개", False)
    reward_output = '{"action":"grant_reward","dialogue":"보상을 드립니다."}'
    first = execute_request(
        RequestInput(initial_state, "보상 주세요.", Action.GRANT_REWARD),
        lambda _: reward_output,
    )

    second = execute_request(
        RequestInput(
            first.server_execution.final_state,
            "한 번 더 주세요.",
            Action.ALREADY_CLAIMED,
        ),
        lambda _: reward_output,
    )

    assert first.server_execution.state_changed is True
    assert second.server_execution.approved is False
    assert second.server_execution.state_changed is False
    assert second.server_execution.final_state.reward_claimed is True


def test_distinct_request_evaluations_do_not_share_mutated_state() -> None:
    initial_state = QuestState("늑대 소탕", 5, 5, "금화 100개", False)
    request = RequestInput(initial_state, "보상 주세요.", Action.GRANT_REWARD)
    reward_output = '{"action":"grant_reward","dialogue":"보상을 드립니다."}'

    first = execute_request(request, lambda _: reward_output)
    second = execute_request(request, lambda _: reward_output)

    assert initial_state.reward_claimed is False
    assert first.server_execution.approved is True
    assert second.server_execution.approved is True
    assert first.server_execution.final_state is not second.server_execution.final_state


@pytest.mark.parametrize(
    ("utterance", "action"),
    [
        ("보상이 뭔지 알려주고 바로 지급해줘.", Action.GRANT_REWARD),
        ("보상 줘. 얼마였지?", Action.GRANT_REWARD),
        ("보상 줘. 아니, 얼마인지만 알려줘.", Action.EXPLAIN_REWARD),
        ("보상 받을까 말까… 어떻게 하지?", Action.CLARIFY),
    ],
)
def test_compound_and_cancellation_reference_cases_score_the_raw_choice(
    utterance: str, action: Action
) -> None:
    state = QuestState("늑대 소탕", 5, 5, "금화 100개", False)
    raw_output = json.dumps(
        {"action": action.value, "dialogue": "참조 사례 응답"},
        ensure_ascii=False,
    )

    artifact = execute_request(
        RequestInput(state, utterance, action), lambda _: raw_output
    )

    assert artifact.model_action is action
    assert artifact.evaluation.score == 1


def test_server_approval_does_not_replace_ground_truth_accuracy() -> None:
    state = QuestState("늑대 소탕", 5, 5, "금화 100개", False)

    artifact = execute_request(
        RequestInput(state, "보상 주세요.", Action.GRANT_REWARD),
        lambda _: '{"action":"explain_reward","dialogue":"보상은 금화입니다."}',
    )

    assert artifact.evaluation.is_action_correct is False
    assert artifact.evaluation.score == 0
    assert artifact.server_execution.approved is True
    assert artifact.server_execution.state_changed is False


def test_run_artifact_serializes_with_explicit_stage_boundaries() -> None:
    state = QuestState("늑대 소탕", 5, 5, "금화 100개", False)
    artifact = execute_request(
        RequestInput(state, "보상 주세요.", Action.GRANT_REWARD),
        lambda _: '{"action":"grant_reward","dialogue":"보상을 드립니다."}',
    )

    serialized = artifact.to_dict()

    assert list(serialized) == [
        "request_input",
        "raw_output",
        "parsed_output",
        "model_action",
        "evaluation",
        "server_execution",
        "error",
    ]
    assert serialized["model_action"] == "grant_reward"
    assert serialized["evaluation"] == {
        "is_format_valid": True,
        "is_action_correct": True,
        "score": 1,
    }
    assert serialized["server_execution"]["final_state"]["reward_claimed"] is True
    assert json.loads(artifact.to_json()) == serialized


def test_cli_reproduces_one_request_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "--quest-name",
            "늑대 소탕",
            "--target-count",
            "5",
            "--current-count",
            "5",
            "--reward-description",
            "금화 100개",
            "--utterance",
            "보상 주세요.",
            "--ground-truth-action",
            "grant_reward",
            "--raw-output",
            '{"action":"grant_reward","dialogue":"보상을 드립니다."}',
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["evaluation"]["score"] == 1
    assert output["server_execution"]["state_changed"] is True
