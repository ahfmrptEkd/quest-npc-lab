"""Approved train-only data and the frozen SFT request contract."""

from collections import Counter
import json
from pathlib import Path

from quest_npc_lab.slices.dataset_pipeline.dataset_pipeline import (
    DatasetCase,
    load_dataset,
    validate_dataset,
    validate_review_manifest,
)
from quest_npc_lab.slices.guild_receptionist import Action

TRAIN_PATH = Path(__file__).parent.parent / "dataset_pipeline/data/train_180.jsonl"
REVIEW_PATH = TRAIN_PATH.with_name("train_180_review_batches.json")


def load_training_cases() -> tuple[DatasetCase, ...]:
    """Read only the fixed training file and its approval manifest; fail closed."""
    if TRAIN_PATH.is_symlink() or REVIEW_PATH.is_symlink():
        raise ValueError("training sources must not be symlinks")
    cases = load_dataset(TRAIN_PATH)
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    validate_review_manifest(cases, review, dataset_path=TRAIN_PATH)
    if (
        len(cases) != 180
        or {c.split for c in cases} != {"train"}
        or {c.review_status for c in cases} != {"user_approved"}
        or Counter(c.ground_truth_action for c in cases) != {a: 30 for a in Action}
    ):
        raise ValueError("training requires 180 balanced, user-approved train cases")
    validate_dataset(cases)
    return cases


def training_example(case: DatasetCase) -> dict:
    """Keep supervised answers exclusively in the assistant completion."""
    from quest_npc_lab.slices.prompt_evaluation import format_prompt, load_manifest

    if case.split != "train" or case.review_status != "user_approved":
        raise ValueError("only user-approved train cases may become SFT examples")
    prompt = format_prompt(case_state(case), case.player_utterance)
    manifest = load_manifest()
    return {
        "prompt": [
            {**message, "content": message["content"].format(formatted_prompt=prompt)}
            for message in manifest["chat_template"]["messages"]
        ],
        "completion": [
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "action": case.ground_truth_action.value,
                        "dialogue": case.reference_dialogue,
                    },
                    ensure_ascii=False,
                ),
            }
        ],
    }


def case_state(case: DatasetCase):
    from quest_npc_lab.slices.guild_receptionist import QuestState

    return QuestState(
        case.quest_name,
        case.target_count,
        case.current_count,
        case.reward_description,
        case.reward_claimed,
    )


def verify_request(case: DatasetCase, generate) -> dict:
    """Verify a fixed training request through strict parsing and server execution."""
    from quest_npc_lab.slices.guild_receptionist import RequestInput, execute_request
    from quest_npc_lab.slices.prompt_evaluation import format_prompt, load_manifest

    manifest = load_manifest()
    state = case_state(case)
    expected = format_prompt(state, case.player_utterance)

    def guarded_generate(prompt):
        if prompt != expected:
            raise ValueError("request pathway diverged from frozen prompt")
        return generate(prompt)

    artifact = execute_request(
        RequestInput(
            state,
            case.player_utterance,
            case.ground_truth_action,
            manifest["character_persona"],
            manifest["system_rules"],
        ),
        guarded_generate,
    ).to_dict()
    return {
        "status": "passed" if artifact["error"] is None else "failed",
        "case_id": "train-001",
        "artifact": artifact,
    }


class TrainingLog:
    """Durable loss/timing evidence, including failures before checkpoint saving."""

    def __init__(self, path: Path, *, max_seconds: float):
        self.path = path
        self.max_seconds = max_seconds
        self.rows = []

    def record(self, *, step: int, loss: float, seconds: float) -> None:
        import math

        if not math.isfinite(loss) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError(
                "loss and duration must be finite; duration must be nonnegative"
            )
        row = {"step": step, "loss": loss, "seconds": seconds}
        self.rows.append(row)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, allow_nan=False) + "\n")
        if sum(row["seconds"] for row in self.rows) > self.max_seconds:
            raise TimeoutError("training exceeded the fixed time budget")

    def finish(self, *, parameter_delta_norm: float, expected_steps: int) -> dict:
        import math

        if not math.isfinite(parameter_delta_norm) or parameter_delta_norm <= 0:
            raise ValueError("LoRA parameter delta must be finite and non-zero")
        if len(self.rows) != expected_steps:
            raise ValueError("training did not complete the expected optimizer steps")
        return {
            "parameter_delta_norm": parameter_delta_norm,
            "loss_trajectory": self.rows,
        }


def tokenize_example(example: dict, tokenizer, *, max_input_tokens: int) -> dict:
    """Preserve the entire frozen prompt; supervise only the complete assistant turn."""
    prompt = tokenizer.apply_chat_template(
        example["prompt"], tokenize=True, add_generation_prompt=True, return_dict=False
    )
    complete = tokenizer.apply_chat_template(
        example["prompt"] + example["completion"],
        tokenize=True,
        add_generation_prompt=False,
        return_dict=False,
    )
    if len(prompt) > max_input_tokens:
        raise ValueError("input token limit exceeded; truncation is forbidden")
    if complete[: len(prompt)] != prompt or len(complete) <= len(prompt):
        raise ValueError(
            "chat template must preserve the generation prefix and completion"
        )
    return {
        "input_ids": complete,
        "completion_mask": [0] * len(prompt) + [1] * (len(complete) - len(prompt)),
    }
