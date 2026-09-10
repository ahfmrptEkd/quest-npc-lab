# Final evaluation — Issue #10

Generate exactly 60 frozen cases × four conditions from the supplied local
checkpoints and cached, pinned Qwen/Qwen2.5-0.5B-Instruct base:

```bash
uv run python -m quest_npc_lab.slices.final_evaluation
```

The runner validates evaluation approval/hash and preselected review IDs, frozen
prompts, adapter file hashes, GRPO parent identity and training acceptance. Each
condition loads fresh base weights; SFT and GRPO each load their own adapter.
Loaded adapter parameter hashes must match metadata. Inputs contain only persona,
rules, server state and player utterance. Evaluation labels never reach inference.
All conditions use float32, seed 42, greedy decoding (`do_sample=False`,
`temperature=0.0`, `max_new_tokens=128`), batch size one and no truncation or retries.
Raw output is preserved, including incomplete JSON. Original actions and server
execution are separate fields; server approval never substitutes for accuracy.

Existing outputs cause an error before inference. Completed responses are flushed
individually. Interrupted runs remain partial and are rejected by recomputation;
the CLI does not resume or automatically regenerate them. Use `--output-dir` for
an explicitly authorized new run and `--checkpoint-dir` for the supplied adapter
root. Generation can use CPU when CUDA is unavailable; hardware can change output.

## Artifacts and offline recomputation

- `artifacts/final_240_responses.jsonl`: original text, frozen inputs and labels,
  tags, selected-review flag, provenance, parsed action/error and server result.
- `artifacts/final_evaluation_report.json`: accuracy, per-action and all six
  shortcut tables, format errors, non-other denominator and other errors, complete
  failure IDs, and consecutive prompt/SFT/GRPO accuracy deltas.
- `artifacts/final_evaluation_run.json`: execution status, environment, hashes,
  provenance caveats, elapsed time and response count.

```bash
uv run python -m quest_npc_lab.slices.final_evaluation --recompute
```

Recomputation requires only the 240 JSONL records and the installed Python package;
it never imports the inference runtime or reads model weights, training reports,
or the source evaluation dataset. It re-parses raw strings through the strict NPC
request boundary, ignoring cached scores/parsed actions. It rejects missing or
duplicate case/condition pairs and inconsistent embedded inputs. Identical raw
files yield byte-identical reports. Rates are fractions; `null` means N/A for a
zero denominator. Relative delta is `(after - before) / before`; percentage-point
delta is also included. Pattern tags overlap, so their denominators need not sum
to 60. A malformed response counts as an incorrect action and a format error.

## Blind human review

`dialogue_review_48_blind.md` contains the same preselected twelve cases across all
four conditions. Both model letters and response order are shuffled once with a
private random seed. `.dialogue_review_48_key.json` is mode 0600 and Git-ignored;
keep it local and do not inspect it, raw condition-labelled outputs, or comparison
results until ratings are complete. Blinding hides labels, not stylistic clues.

Record the human judgments in `dialogue_review_48_scores.json`, keyed by review ID.
For each of `consistency`, `responsiveness`, and `tone_naturalness`, set `rating`
to `pass`, `problem`, or `defer`, with a short `note`. `pending` means unreviewed;
malformed outputs remain `unassessable`. These are human judgments, never model
or AI-assigned quality ratings. The Markdown fields are a worksheet; only the JSON
is read for aggregation:

```bash
uv run python -m quest_npc_lab.slices.final_evaluation \
  --review-scores artifacts/dialogue_review_48_scores.json
```

This writes `dialogue_review_summary.json`, separating all five statuses for each
criterion. It checks response IDs, model letters and assessability against the
original raw outputs and local hidden key, so keep both files for aggregation. Automatic metric recomputation leaves the human scores, sample order,
and hidden key untouched. Human review is pending at generation time.

This is one seed, sixty balanced cases and one intended human reviewer. Report
improvement, ties and regressions as exploratory observations. Accuracy is not a
measure of dialogue quality. The report lists all observed action/format failures;
dialogue contradictions remain pending human assessment, and causal hypotheses
are not manufactured. The supplied SFT metadata differs from the historical SFT
training report; the runner records that discrepancy explicitly and verifies the
current adapter against the exact parent used by GRPO. It does not claim that the
historical report proves the current SFT adapter's update/reload history.

## Validation

```bash
uv run pytest
ruff check src/quest_npc_lab/slices/final_evaluation
ruff format --check src/quest_npc_lab/slices/final_evaluation
basedpyright --level error --pythonpath .venv/bin/python src/quest_npc_lab/slices/final_evaluation
```

Fast tests use supplied model strings at the generation boundary; real model
ability is measured only by the separately recorded final run.

## Recorded run and checks

The supplied checkpoints produced exactly 240 responses in 1111.6 seconds on the
RTX 3060. Both loaded adapter parameter identities matched their metadata. The
blind worksheet contains 48 entries: 24 pending human ratings and 24 unassessable
format failures per criterion. No human quality judgments have been supplied.

`uv run pytest`: **219 passed in 35.69s** (206 existing + 13 new).
Ruff lint/format checks passed, and basedpyright reported zero errors. Independent
Standards and Spec reviews are clear after fixing score-to-sample binding.
A separate artifact audit verified the frozen dataset hash, all 240 unique pairs,
all condition/action/shortcut/other/format counts, exact 48 preselected responses,
private ignored key permissions, and identical human aggregation. Running the
recompute CLI produced a byte-identical report while preserving the raw responses,
hidden key and editable scores. No extra inference was used for these checks.
