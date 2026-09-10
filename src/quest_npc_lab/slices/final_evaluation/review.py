"""Blind human dialogue review; ratings are never inferred from action accuracy."""

import html
import json
from typing import Any
import random

from .final_evaluation import CONDITIONS, score_raw, validate_records

CRITERIA = {
    "consistency": "Consistency (내용 정합성): server state, chosen action, and reward facts agree",
    "responsiveness": "Responsiveness (요청 대응): answers the request, including compound questions",
    "tone_naturalness": "Tone/Naturalness (캐릭터·자연스러움): friendly, rule-respecting guild receptionist; fluent and not repetitive",
}
RATINGS = ("pass", "problem", "defer", "unassessable", "pending")


def summarize_review(scores: list[dict[str, Any]]) -> dict[str, Any]:
    if len(scores) != 48 or len({s["review_id"] for s in scores}) != 48:
        raise ValueError("review requires 48 unique response IDs")
    summary = {criterion: dict.fromkeys(RATINGS, 0) for criterion in CRITERIA}
    for score in scores:
        for criterion in CRITERIA:
            rating = score[criterion]["rating"]
            if rating not in RATINGS or not isinstance(score[criterion]["note"], str):
                raise ValueError("invalid human rating or note")
            if not score["assessable"] and rating != "unassessable":
                raise ValueError("malformed response must remain unassessable")
            summary[criterion][rating] += 1
    return summary


def build_blind_review(
    rows: list[dict[str, Any]], *, seed: int
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    rows = validate_records(rows)
    rng = random.Random(seed)
    conditions = list(CONDITIONS)
    rng.shuffle(conditions)
    models = dict(zip(("Model A", "Model B", "Model C", "Model D"), conditions))
    labels = {condition: label for label, condition in models.items()}
    selected = [r for r in rows if r["dialogue_review_selected"]]
    rng.shuffle(selected)
    key: dict[str, Any] = {"models": models, "shuffle_seed": seed, "responses": {}}
    scores = []
    lines = [
        "# Blind dialogue review — 48 responses",
        "",
        "One human reviewer; exploratory judgments. Do not inspect the hidden key or raw condition-labelled results until ratings are complete.",
        "",
        "Rate each criterion: pass (통과), problem (문제 있음), defer (판단 보류), with a short note. "
        "Malformed output is unassessable (평가 불가), never a pass. Pending means not yet reviewed.",
        "",
        *[f"- {description}." for description in CRITERIA.values()],
        "",
        "Record ratings in dialogue_review_48_scores.json using the Review ID; Markdown fields are a worksheet.",
        "",
    ]
    for index, row in enumerate(selected, 1):
        review_id = f"review-{index:03d}"
        artifact = score_raw(row)
        parsed = artifact["parsed_output"]
        assessable = parsed is not None
        key["responses"][review_id] = {
            "case_id": row["case_id"],
            "condition": row["condition"],
        }
        score: dict[str, Any] = {
            "review_id": review_id,
            "model": labels[row["condition"]],
            "assessable": assessable,
        }
        score.update(
            {
                c: {"rating": "pending" if assessable else "unassessable", "note": ""}
                for c in CRITERIA
            }
        )
        scores.append(score)

        # Escape untrusted model text in HTML pre blocks, including fences and tags.
        def block(text):
            escaped = (
                html.escape(text).replace(" \n", "&#32;\n").replace("\t\n", "&#9;\n")
            )
            return "<pre>" + escaped + "</pre>"

        lines.extend(
            [
                f"## Review {index:03d} — {labels[row['condition']]}",
                "",
                f"ID: {review_id}",
                "",
                "State:",
                block(json.dumps(row["state"], ensure_ascii=False, indent=2)),
                "",
                "Player utterance:",
                block(row["player_utterance"]),
                "",
                "Model action:",
                block(parsed["action"] if parsed else "Unavailable — format error"),
                "",
                "Dialogue:",
                block(parsed["dialogue"] if parsed else "평가 불가 / unassessable"),
                "",
            ]
        )
        if not assessable:
            lines.extend(
                [
                    "Raw output (unmodified):",
                    block(row["raw_output"]),
                    "Format error:",
                    block(artifact["error"]["reason"]),
                    "",
                ]
            )
        for criterion, description in CRITERIA.items():
            lines.append(f"- {description}: {score[criterion]['rating']}; note: ____")
        lines.append("")
    return "\n".join(lines), key, scores


def aggregate_review(
    scores: list[dict[str, Any]], rows: list[dict[str, Any]], key: dict[str, Any]
) -> dict[str, Any]:
    """Bind editable judgments to the original shuffled response identities."""
    _, expected_key, expected_scores = build_blind_review(
        rows, seed=key["shuffle_seed"]
    )
    if key != expected_key:
        raise ValueError("hidden key does not match original sample")
    expected = {score["review_id"]: score for score in expected_scores}
    if len(scores) != 48 or {s["review_id"] for s in scores} != set(expected):
        raise ValueError("ratings must identify the original 48 responses")
    for score in scores:
        original = expected[score["review_id"]]
        if any(score[field] != original[field] for field in ("model", "assessable")):
            raise ValueError("ratings must preserve original model and assessability")
    return summarize_review(scores)
