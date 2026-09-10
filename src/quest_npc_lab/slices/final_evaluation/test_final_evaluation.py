"""Final evaluation behavior at generation, artifact, and recomputation seams."""

import json

import pytest

from quest_npc_lab.slices.final_evaluation.final_evaluation import generate_responses


def test_generates_exactly_240_isolated_responses_without_repair(tmp_path):
    prompts = []

    def generate(condition, prompt):
        prompts.append((condition, json.loads(prompt)))
        return (
            ' {"action":"grant_reward","dialogue":"지급합니다."} '
            if condition == "base_minimal"
            else "```bad JSON"
        )

    path = tmp_path / "raw.jsonl"
    generate_responses(path, generate)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == len(prompts) == 240
    assert len({(r["condition"], r["case_id"]) for r in rows}) == 240
    assert (
        rows[0]["raw_output"] == ' {"action":"grant_reward","dialogue":"지급합니다."} '
    )
    assert rows[60]["raw_output"] == "```bad JSON"
    assert rows[60]["artifact"]["error"]["stage"] == "model_output"
    assert rows[60]["artifact"]["parsed_output"] is None
    assert (
        rows[0]["state"]
        == rows[60]["state"]
        == rows[120]["state"]
        == rows[180]["state"]
    )
    assert all(
        set(p) == {"character_persona", "rules", "server_state", "player_utterance"}
        for _, p in prompts
    )
    assert prompts[60][1] == prompts[120][1] == prompts[180][1]
    assert prompts[0][1]["rules"] != prompts[60][1]["rules"]
    with pytest.raises(FileExistsError):
        generate_responses(path, generate)
    assert len(prompts) == 240


@pytest.fixture(scope="module")
def raw_rows(tmp_path_factory):
    path = tmp_path_factory.mktemp("evaluation") / "raw.jsonl"
    generate_responses(
        path, lambda condition, prompt: '{"action":"other","dialogue":"안녕하세요."}'
    )
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_recompute_uses_raw_outputs_instead_of_saved_scores(raw_rows):
    from copy import deepcopy
    from quest_npc_lab.slices.final_evaluation.final_evaluation import recompute

    rows = deepcopy(raw_rows)
    for row in rows:
        row["artifact"] = {"evaluation": {"is_action_correct": True}}
        if row["condition"] == "base_minimal":
            row["raw_output"] = "broken"
    report = recompute(rows)
    base = report["conditions"]["base_minimal"]
    improved = report["conditions"]["base_improved"]
    assert base["accuracy"] == 0
    assert base["format_error_rate"] == 1
    assert improved["accuracy"] == 10 / 60
    assert improved["other_misclassification_rate"] == 1
    assert improved["other_denominator"] == 50
    assert improved["by_action"]["other"]["accuracy"] == 1
    assert improved["by_action"]["grant_reward"]["accuracy"] == 0
    assert len(improved["by_shortcut"]) == 6
    assert all(v["count"] > 0 for v in improved["by_shortcut"].values())
    assert report["deltas"]["prompt"]["relative_accuracy_delta"] is None
    assert report["deltas"]["prompt"]["outcome"] == "improvement"
    assert report["deltas"]["grpo"]["accuracy_delta"] == 0
    assert report["deltas"]["grpo"]["outcome"] == "tie"
    assert report == recompute(list(reversed(rows)))


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "condition", "state", "selection", "raw_type"]
)
def test_recompute_rejects_incomplete_or_inconsistent_runs(raw_rows, mutation):
    from copy import deepcopy
    from quest_npc_lab.slices.final_evaluation.final_evaluation import recompute

    rows = deepcopy(raw_rows)
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1] = rows[0]
    elif mutation == "condition":
        rows[0]["condition"] = "unknown"
    elif mutation == "state":
        rows[0]["state"]["current_count"] += 1
    elif mutation == "selection":
        rows[0]["dialogue_review_selected"] = not rows[0]["dialogue_review_selected"]
    else:
        rows[0]["raw_output"] = None
    with pytest.raises(ValueError):
        recompute(rows)


def test_blind_review_has_48_shuffled_responses_and_no_condition_names(raw_rows):
    from copy import deepcopy
    from quest_npc_lab.slices.final_evaluation.review import (
        build_blind_review,
        summarize_review,
    )

    rows = deepcopy(raw_rows)
    selected = next(r for r in rows if r["dialogue_review_selected"])
    selected["raw_output"] = "```json\nmalformed <script>alert(1)</script>"
    markdown, key, scores = build_blind_review(rows, seed=17)
    assert markdown.count("## Review ") == 48
    assert not any(
        c in markdown
        for c in ("base_minimal", "base_improved", "sft_improved", "grpo_improved")
    )
    assert set(key["models"]) == {"Model A", "Model B", "Model C", "Model D"}
    assert len(key["responses"]) == len(scores) == 48
    assert all(
        markdown.count(label) >= 48
        for label in ("Consistency", "Responsiveness", "Tone/Naturalness")
    )
    assert "<script>" not in markdown
    summary = summarize_review(scores)
    assert summary["consistency"]["unassessable"] == 1
    assert summary["consistency"]["pending"] == 47
    assert summary["consistency"]["pass"] == 0
    assert (markdown, key, scores) == build_blind_review(rows, seed=17)


def test_cli_recompute_needs_only_raw_jsonl_and_preserves_it(raw_rows, tmp_path):
    import subprocess
    import sys

    path = tmp_path / "final_240_responses.jsonl"
    original = "\n".join(json.dumps(r, ensure_ascii=False) for r in raw_rows) + "\n"
    path.write_text(original)
    command = [
        sys.executable,
        "-m",
        "quest_npc_lab.slices.final_evaluation",
        "--recompute",
        "--output-dir",
        str(tmp_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    report = tmp_path / "final_evaluation_report.json"
    first = report.read_bytes()
    assert json.loads(first)["conditions"]["grpo_improved"]["accuracy"] == 10 / 60
    assert subprocess.run(command, capture_output=True).returncode == 0
    assert report.read_bytes() == first
    assert path.read_text() == original
    assert not (tmp_path / "dialogue_review_48_blind.md").exists()


def test_checkpoint_preflight_rejects_changed_weights_before_loading(tmp_path):
    import hashlib
    from quest_npc_lab.slices.final_evaluation.runtime import validate_checkpoints
    from quest_npc_lab.slices.sft_training.runtime import provenance

    parent_digest = "a" * 64
    for name in ("sft", "grpo"):
        directory = tmp_path / f"{name}_checkpoint"
        directory.mkdir()
        (directory / "adapter_config.json").write_text("{}")
        (directory / "adapter_model.safetensors").write_bytes(name.encode())
        source = provenance()
        if name == "grpo":
            source.update(
                initial_checkpoint="sft_checkpoint",
                initial_adapter_parameter_sha256=parent_digest,
                final_evaluation_used=False,
                checkpoint_selection="final training group only; no evaluation or seed selection",
            )
        metadata = {
            "provenance": source,
            "adapter_parameter_sha256": parent_digest if name == "sft" else "b" * 64,
            "checkpoint_files": {
                f: hashlib.sha256((directory / f).read_bytes()).hexdigest()
                for f in ("adapter_config.json", "adapter_model.safetensors")
            },
        }
        if name == "grpo":
            metadata["evaluation_generation"] = {
                "do_sample": False,
                "temperature": 0.0,
                "max_new_tokens": 128,
            }
        (directory / "training_metadata.json").write_text(json.dumps(metadata))
    (tmp_path / "grpo_checkpoint" / "adapter_model.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        validate_checkpoints(tmp_path)


def test_review_aggregation_binds_ratings_to_original_blind_sample(raw_rows):
    from copy import deepcopy
    from quest_npc_lab.slices.final_evaluation.review import (
        aggregate_review,
        build_blind_review,
    )

    rows = deepcopy(raw_rows)
    next(r for r in rows if r["dialogue_review_selected"])["raw_output"] = "bad"
    _, key, scores = build_blind_review(rows, seed=19)
    assert aggregate_review(scores, rows, key)["consistency"]["unassessable"] == 1
    invalid = next(s for s in scores if not s["assessable"])
    invalid["assessable"] = True
    for criterion in ("consistency", "responsiveness", "tone_naturalness"):
        invalid[criterion]["rating"] = "pass"
    with pytest.raises(ValueError, match="original"):
        aggregate_review(scores, rows, key)


def test_blind_markdown_preserves_raw_trailing_spaces_without_diff_errors(raw_rows):
    from copy import deepcopy
    import html
    from quest_npc_lab.slices.final_evaluation.review import build_blind_review

    rows = deepcopy(raw_rows)
    raw = "broken JSON \nnext line\t\n"
    next(r for r in rows if r["dialogue_review_selected"])["raw_output"] = raw
    markdown, _, _ = build_blind_review(rows, seed=20)
    assert raw in html.unescape(markdown)
    assert all(line == line.rstrip(" \t") for line in markdown.splitlines())
