import json
import pytest
from quest_npc_lab.slices.dpo_training.dpo_training import build_pairs
from quest_npc_lab.slices.sft_training.sft_training import load_training_cases


def sample():
    case = load_training_cases()[0]
    good = json.dumps(
        {"action": case.ground_truth_action.value, "dialogue": "확인했습니다."},
        ensure_ascii=False,
    )
    row = {
        "case_id": "train-001",
        "ground_truth_action": case.ground_truth_action.value,
        "raw_responses": ["invalid", good, good, "invalid"],
        "rewards": [0.0, 1.0, 1.0, 0.0],
    }
    return row, good


def test_selects_first_good_bad_without_rewriting_responses():
    row, good = sample()
    pairs = build_pairs([row])
    assert len(pairs) == 1
    assert pairs[0]["chosen"] == [{"role": "assistant", "content": good}]
    assert pairs[0]["rejected"] == [{"role": "assistant", "content": "invalid"}]
    assert pairs[0]["chosen_index"] == 1
    assert pairs[0]["rejected_index"] == 0


@pytest.mark.parametrize("change", ["reward", "label", "eval", "duplicate"])
def test_rejects_corrupt_or_nontraining_sources(change):
    row, _ = sample()
    groups = [row]
    if change == "reward":
        row["rewards"] = [1.0, 1.0, 1.0, 0.0]
    if change == "label":
        row["ground_truth_action"] = "not_an_action"
    if change == "eval":
        row["case_id"] = "eval-001"
    if change == "duplicate":
        groups.append(dict(row))
    with pytest.raises(ValueError):
        build_pairs(groups)


def test_skips_ties_and_never_invents_a_preference():
    row, good = sample()
    row.update(raw_responses=[good] * 4, rewards=[1.0] * 4)
    with pytest.raises(ValueError, match="no mixed"):
        build_pairs([row])


def test_metrics_replay_raw_output_instead_of_trusting_embedded_scores():
    from quest_npc_lab.slices.dpo_training.dpo_training import summarize

    row = {
        "state": {
            "quest_name": "쥐",
            "target_count": 3,
            "current_count": 0,
            "reward_description": "금화",
            "reward_claimed": False,
        },
        "player_utterance": "보상 줘",
        "ground_truth_action": "explain_progress",
        "character_persona": "접수원",
        "rules": "서버 상태를 따른다",
        "raw_output": '{"action":"grant_reward","dialogue":"드릴게요"}',
        "artifact": {"evaluation": {"is_action_correct": True}},
    }
    result = summarize([row])
    assert result["correct"] == 0
    assert result["wrong_grants"] == 1
    assert result["wrong_grant_denominator"] == 1


def test_recomputation_rejects_sft_rows_substituted_for_dpo(tmp_path):
    from pathlib import Path
    from quest_npc_lab.slices.dpo_training.evaluation import recompute_comparison

    source = Path(__file__).resolve().parents[4] / "artifacts"
    rows = [
        json.loads(x)
        for x in (source / "final_240_responses.jsonl").read_text().splitlines()
    ]
    sft = [r for r in rows if r["condition"] == "sft_improved"]
    (tmp_path / "dpo_60_responses.jsonl").write_text(
        "\n".join(json.dumps(r) for r in sft)
    )
    (tmp_path / "training_report.json").write_text(
        json.dumps(
            {"status": "passed", "adapter_parameter_sha256": "dpo", "source_hashes": {}}
        )
    )
    with pytest.raises(ValueError, match="DPO provenance"):
        recompute_comparison(source, tmp_path)
