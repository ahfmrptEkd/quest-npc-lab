"""CLI for reproducing a single guild receptionist request."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .receptionist_slice import (
    Action,
    DEFAULT_CHARACTER_PERSONA,
    DEFAULT_RULES,
    QuestState,
    RequestInput,
    execute_request,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute one NPC request using a supplied raw model response."
    )
    parser.add_argument("--quest-name", required=True)
    parser.add_argument("--target-count", required=True, type=int)
    parser.add_argument("--current-count", required=True, type=int)
    parser.add_argument("--reward-description", required=True)
    parser.add_argument("--reward-claimed", action="store_true")
    parser.add_argument("--utterance", required=True)
    parser.add_argument("--raw-output", required=True)
    parser.add_argument(
        "--ground-truth-action", choices=[action.value for action in Action]
    )
    parser.add_argument("--character-persona", default=DEFAULT_CHARACTER_PERSONA)
    parser.add_argument("--rules", default=DEFAULT_RULES)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and print one complete artifact as JSON."""
    parser = _parser()
    arguments = parser.parse_args(argv)
    ground_truth = (
        None
        if arguments.ground_truth_action is None
        else Action(arguments.ground_truth_action)
    )
    request = RequestInput(
        state=QuestState(
            quest_name=arguments.quest_name,
            target_count=arguments.target_count,
            current_count=arguments.current_count,
            reward_description=arguments.reward_description,
            reward_claimed=arguments.reward_claimed,
        ),
        player_utterance=arguments.utterance,
        ground_truth_action=ground_truth,
        character_persona=arguments.character_persona,
        rules=arguments.rules,
    )
    artifact = execute_request(request, lambda _: arguments.raw_output)
    print(artifact.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
