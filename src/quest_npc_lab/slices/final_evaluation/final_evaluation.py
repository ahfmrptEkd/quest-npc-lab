"""One-pass final generation and raw-output-only metric recomputation."""

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from quest_npc_lab.slices.evaluation_dataset.evaluation_dataset import (
    validate_eval_freeze,
)
from quest_npc_lab.slices.guild_receptionist import (
    Action,
    QuestState,
    RequestInput,
    execute_request,
)
from quest_npc_lab.slices.prompt_evaluation import format_prompt, load_manifest
from quest_npc_lab.slices.prompt_evaluation.prompt_evaluation import MINIMAL_RULES

CONDITIONS = ("base_minimal", "base_improved", "sft_improved", "grpo_improved")
RAW_NAME = "final_240_responses.jsonl"
REPORT_NAME = "final_evaluation_report.json"


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def score_raw(row: dict[str, Any]) -> dict[str, Any]:
    """Replay the original choice through the existing strict request boundary."""
    request = RequestInput(
        QuestState(**row["state"]),
        row["player_utterance"],
        Action(row["ground_truth_action"]),
        row["character_persona"],
        row["rules"],
    )
    return execute_request(request, lambda prompt: row["raw_output"]).to_dict()


def generate_responses(
    path: Path,
    generate: Callable[[str, str], str],
    *,
    provenance: dict[str, Any] | None = None,
) -> None:
    """The model boundary gets only condition and prompt, never labels or tags."""
    frozen = validate_eval_freeze()
    config = load_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        for condition in CONDITIONS:
            baseline = "minimal" if condition == "base_minimal" else "improved"
            for item in frozen.cases:
                case = item.case
                state = QuestState(
                    case.quest_name,
                    case.target_count,
                    case.current_count,
                    case.reward_description,
                    case.reward_claimed,
                )
                prompt = format_prompt(state, case.player_utterance, baseline=baseline)
                row = {
                    "condition": condition,
                    "case_id": item.case_id,
                    "state": asdict(state),
                    "player_utterance": case.player_utterance,
                    "ground_truth_action": case.ground_truth_action.value,
                    "shortcut_tags": list(case.shortcut_tags),
                    "dialogue_review_selected": item.case_id
                    in frozen.dialogue_review_ids,
                    "dataset_sha256": frozen.dataset_sha256,
                    "character_persona": config["character_persona"],
                    "rules": MINIMAL_RULES
                    if baseline == "minimal"
                    else config["system_rules"],
                    "generation": config["generation"],
                    "seed": config["seed"],
                    "provenance": provenance or {},
                    "raw_output": generate(condition, prompt),
                }
                if not isinstance(row["raw_output"], str):
                    raise ValueError("generation must return an unmodified string")
                row["artifact"] = score_raw(row)
                stream.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
                stream.flush()


def validate_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Require a complete Cartesian product with identical embedded case inputs."""
    from quest_npc_lab.slices.dataset_pipeline.dataset_pipeline import SHORTCUT_TAGS

    if len(rows) != 240:
        raise ValueError("expected exactly 240 raw responses")
    cases = {}
    seen = set()
    common = ("dataset_sha256", "generation", "seed", "provenance", "character_persona")
    case_fields = (
        "state",
        "player_utterance",
        "ground_truth_action",
        "shortcut_tags",
        "dialogue_review_selected",
    )
    rules = {}
    for row in rows:
        key = (row["condition"], row["case_id"])
        if (
            key[0] not in CONDITIONS
            or key in seen
            or not isinstance(row["raw_output"], str)
        ):
            raise ValueError(
                "invalid condition, duplicate response, or non-string raw output"
            )
        seen.add(key)
        if any(row[field] != rows[0][field] for field in common):
            raise ValueError("inconsistent run provenance or decoding settings")
        identity = {field: row[field] for field in case_fields}
        if row["case_id"] in cases and cases[row["case_id"]] != identity:
            raise ValueError("case metadata differs between conditions")
        cases[row["case_id"]] = identity
        if key[0] in rules and rules[key[0]] != row["rules"]:
            raise ValueError("prompt rules differ within condition")
        rules[key[0]] = row["rules"]
        artifact = score_raw(row)
        if artifact["error"] and artifact["error"]["stage"] != "model_output":
            raise ValueError("invalid embedded request input")
    if len(cases) != 60 or seen != {(c, i) for c in CONDITIONS for i in cases}:
        raise ValueError("expected the same 60 cases in all four conditions")
    if len({rules[c] for c in CONDITIONS[1:]}) != 1:
        raise ValueError("all improved conditions must share prompt rules")
    if Counter(c["ground_truth_action"] for c in cases.values()) != {
        a.value: 10 for a in Action
    }:
        raise ValueError("expected ten cases per action")
    selected = [c for c in cases.values() if c["dialogue_review_selected"] is True]
    if Counter(c["ground_truth_action"] for c in selected) != {
        a.value: 2 for a in Action
    }:
        raise ValueError("expected twelve preselected cases, two per action")
    if {tag for c in cases.values() for tag in c["shortcut_tags"]} != SHORTCUT_TAGS:
        raise ValueError("expected six shortcut patterns")
    return sorted(rows, key=lambda r: (CONDITIONS.index(r["condition"]), r["case_id"]))


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Every rate includes its numerator/denominator; None denotes N/A."""
    count = len(rows)
    correct = sum(
        r["artifact"]["evaluation"]["is_action_correct"] is True for r in rows
    )
    errors = sum(not r["artifact"]["evaluation"]["is_format_valid"] for r in rows)
    non_other = [r for r in rows if r["ground_truth_action"] != "other"]
    other_errors = sum(r["artifact"]["model_action"] == "other" for r in non_other)
    return {
        "count": count,
        "correct": correct,
        "accuracy": correct / count if count else None,
        "format_errors": errors,
        "format_error_rate": errors / count if count else None,
        "other_misclassifications": other_errors,
        "other_denominator": len(non_other),
        "other_misclassification_rate": other_errors / len(non_other)
        if non_other
        else None,
    }


def recompute(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rebuild all automatic tables from embedded inputs and raw strings only."""
    from quest_npc_lab.slices.dataset_pipeline.dataset_pipeline import SHORTCUT_TAGS

    rows = [{**r, "artifact": score_raw(r)} for r in validate_records(rows)]
    conditions = {}
    for condition in CONDITIONS:
        group = [r for r in rows if r["condition"] == condition]
        conditions[condition] = {
            **metrics(group),
            "by_action": {
                a.value: metrics(
                    [r for r in group if r["ground_truth_action"] == a.value]
                )
                for a in Action
            },
            "by_shortcut": {
                tag: metrics([r for r in group if tag in r["shortcut_tags"]])
                for tag in sorted(SHORTCUT_TAGS)
            },
            "failures": [
                {
                    "case_id": r["case_id"],
                    "expected": r["ground_truth_action"],
                    "model_action": r["artifact"]["model_action"],
                    "error": r["artifact"]["error"],
                    "shortcut_tags": r["shortcut_tags"],
                    "wrong_grant": r["artifact"]["model_action"] == "grant_reward"
                    and r["ground_truth_action"] != "grant_reward",
                    "missed_grant": r["ground_truth_action"] == "grant_reward"
                    and r["artifact"]["model_action"] != "grant_reward",
                }
                for r in group
                if not r["artifact"]["evaluation"]["is_action_correct"]
            ],
        }
    deltas = {}
    for name, before, after in zip(
        ("prompt", "sft", "grpo"), CONDITIONS, CONDITIONS[1:]
    ):
        old, new = conditions[before]["accuracy"], conditions[after]["accuracy"]
        delta = new - old
        deltas[name] = {
            "from": before,
            "to": after,
            "accuracy_delta": delta,
            "percentage_point_delta": delta * 100,
            "relative_accuracy_delta": delta / old if old else None,
            "outcome": "improvement"
            if delta > 0
            else "regression"
            if delta < 0
            else "tie",
        }
    return {
        "response_count": 240,
        "case_count": 60,
        "conditions": conditions,
        "deltas": deltas,
        "dataset_sha256": rows[0]["dataset_sha256"],
        "provenance": rows[0]["provenance"],
        "generation": rows[0]["generation"],
        "seed": rows[0]["seed"],
        "na_representation": "null means N/A (zero denominator)",
        "limitations": [
            "Single seed; 60 balanced cases; exploratory comparison.",
            "Dialogue quality requires one human reviewer; accuracy does not establish dialogue quality.",
            "Environment differences may affect greedy outputs.",
        ],
        "analysis": {
            "observations": "All action and format failures are listed per condition, including shortcut tags.",
            "causal_hypotheses": [],
            "dialogue_contradictions": "Pending human review; not automatically judged.",
        },
    }


def recompute_file(raw_path: Path, report_path: Path) -> dict[str, Any]:
    rows = [
        json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()
    ]
    report = recompute(rows)
    report["raw_responses_sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    write_json(report_path, report)
    return report
