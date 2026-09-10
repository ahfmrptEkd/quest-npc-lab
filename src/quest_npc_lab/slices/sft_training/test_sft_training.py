"""Offline behavior checks; real CUDA evidence lives in the training report."""

import json
from pathlib import Path

from quest_npc_lab.slices.sft_training.sft_training import load_training_cases


def test_training_reads_only_the_approved_180_cases(monkeypatch):
    read_text = Path.read_text
    opened = []

    def guarded_read(path, *args, **kwargs):
        if path.suffix == ".jsonl":
            opened.append(path.name)
            assert path.name == "train_180.jsonl"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    cases = load_training_cases()
    assert len(cases) == 180
    assert {case.split for case in cases} == {"train"}
    assert {case.review_status for case in cases} == {"user_approved"}
    assert opened


def test_sft_uses_exact_frozen_prompt_and_keeps_answer_in_completion():
    from quest_npc_lab.slices.sft_training.sft_training import training_example
    from quest_npc_lab.slices.prompt_evaluation import format_prompt
    from quest_npc_lab.slices.guild_receptionist import QuestState

    case = load_training_cases()[0]
    example = training_example(case)
    state = QuestState(
        case.quest_name,
        case.target_count,
        case.current_count,
        case.reward_description,
        case.reward_claimed,
    )
    assert example["prompt"] == [
        {"role": "user", "content": format_prompt(state, case.player_utterance)}
    ]
    assert case.reference_dialogue not in example["prompt"][0]["content"]
    assert json.loads(example["completion"][0]["content"]) == {
        "action": "grant_reward",
        "dialogue": case.reference_dialogue,
    }


def test_reload_request_records_strict_output_and_uses_frozen_prompt():
    from quest_npc_lab.slices.sft_training.sft_training import (
        verify_request,
        training_example,
    )

    case = load_training_cases()[0]
    seen = []

    def generate(prompt):
        seen.append(prompt)
        return '{"action":"grant_reward","dialogue":"금화 100개를 지급할게요."}'

    result = verify_request(case, generate)
    assert result["status"] == "passed"
    assert result["artifact"]["server_execution"]["state_changed"] is True
    assert seen == [training_example(case)["prompt"][0]["content"]]
    invalid = verify_request(case, lambda _: "```json\n{}\n```")
    assert invalid["status"] == "failed"
    assert invalid["artifact"]["raw_output"] == "```json\n{}\n```"
    assert invalid["artifact"]["server_execution"]["state_changed"] is False


def test_training_refuses_to_overwrite_preserved_checkpoint(tmp_path):
    from quest_npc_lab.slices.sft_training.__main__ import main

    checkpoint = tmp_path / "sft_checkpoint"
    checkpoint.mkdir()
    weights = checkpoint / "adapter_model.safetensors"
    weights.write_bytes(b"preserved SFT weights")
    assert main(["--artifacts-dir", str(tmp_path)]) == 1
    assert weights.read_bytes() == b"preserved SFT weights"
    assert not (tmp_path / "sft_training_report.json").exists()


def test_training_rejects_zero_weight_updates_and_preserves_step_evidence(tmp_path):
    import pytest
    from quest_npc_lab.slices.sft_training.sft_training import TrainingLog

    log = TrainingLog(tmp_path / "steps.jsonl", max_seconds=10)
    log.record(step=1, loss=2.0, seconds=0.5)
    log.record(step=2, loss=1.5, seconds=0.4)
    assert [row["loss"] for row in log.rows] == [2.0, 1.5]
    assert len((tmp_path / "steps.jsonl").read_text().splitlines()) == 2
    with pytest.raises(ValueError, match="parameter"):
        log.finish(parameter_delta_norm=0.0, expected_steps=2)
    with pytest.raises(ValueError, match="steps"):
        log.finish(parameter_delta_norm=0.1, expected_steps=3)
    assert (
        log.finish(parameter_delta_norm=0.1, expected_steps=2)["parameter_delta_norm"]
        == 0.1
    )
    with pytest.raises(ValueError, match="finite"):
        log.record(step=3, loss=float("nan"), seconds=0.5)
    with pytest.raises(TimeoutError):
        log.record(step=3, loss=1.0, seconds=11)


def test_failed_cuda_run_writes_structured_report_without_checkpoint(
    tmp_path, monkeypatch
):
    import sys
    from types import SimpleNamespace
    from quest_npc_lab.slices.sft_training.__main__ import main

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)),
    )
    assert main(["--artifacts-dir", str(tmp_path)]) == 1
    report = json.loads((tmp_path / "sft_training_report.json").read_text())
    assert report["status"] == "failed"
    assert "CUDA" in report["error"]
    assert report["hyperparameters"]["seed"] == 42
    assert not (tmp_path / "sft_checkpoint").exists()


def test_tokenization_masks_prompt_and_rejects_truncation():
    import pytest
    from quest_npc_lab.slices.sft_training.sft_training import tokenize_example

    class OfflineTokenizer:
        def apply_chat_template(self, messages, **kwargs):
            return [10, 11] if kwargs.get("add_generation_prompt") else [10, 11, 12, 13]

    example = {
        "prompt": [{"role": "user", "content": "input"}],
        "completion": [{"role": "assistant", "content": "answer"}],
    }
    tokens = tokenize_example(example, OfflineTokenizer(), max_input_tokens=2)
    assert tokens == {"input_ids": [10, 11, 12, 13], "completion_mask": [0, 0, 1, 1]}
    with pytest.raises(ValueError, match="input token limit"):
        tokenize_example(example, OfflineTokenizer(), max_input_tokens=1)


def test_reverification_detects_tampering_without_changing_original_report(tmp_path):
    import hashlib
    from quest_npc_lab.slices.sft_training.__main__ import main

    checkpoint = tmp_path / "sft_checkpoint"
    checkpoint.mkdir()
    (checkpoint / "adapter_model.safetensors").write_bytes(b"changed")
    original = {
        "status": "passed",
        "checkpoint_files": {
            "adapter_model.safetensors": hashlib.sha256(b"original").hexdigest()
        },
    }
    report_path = tmp_path / "sft_training_report.json"
    report_path.write_text(json.dumps(original))
    assert main(["--verify-only", "--artifacts-dir", str(tmp_path)]) == 1
    assert json.loads(report_path.read_text()) == original
    verification = json.loads((tmp_path / "sft_reload_verification.json").read_text())
    assert "integrity" in verification["error"]


def test_chat_tokenizer_explicitly_requests_token_lists():
    from quest_npc_lab.slices.sft_training.sft_training import tokenize_example

    class Tokenizer:
        def apply_chat_template(self, messages, *, return_dict=True, **kwargs):
            assert return_dict is False
            return [1] if kwargs["add_generation_prompt"] else [1, 2]

    assert tokenize_example(
        {"prompt": [], "completion": []}, Tokenizer(), max_input_tokens=4
    )["completion_mask"] == [0, 1]


def test_training_refuses_unapproved_or_other_split_examples():
    from dataclasses import replace
    import pytest
    from quest_npc_lab.slices.sft_training.sft_training import training_example

    case = load_training_cases()[0]
    for invalid in (
        replace(case, split="validation"),
        replace(case, review_status="ai_approved"),
    ):
        with pytest.raises(ValueError, match="user-approved train"):
            training_example(invalid)


def test_training_rejects_modified_reviewed_bytes(monkeypatch):
    import pytest
    from quest_npc_lab.slices.sft_training.sft_training import TRAIN_PATH

    read_bytes = Path.read_bytes

    def corrupt(path):
        raw = read_bytes(path)
        return raw + b" " if path == TRAIN_PATH else raw

    monkeypatch.setattr(Path, "read_bytes", corrupt)
    with pytest.raises(ValueError, match="sha256"):
        load_training_cases()
