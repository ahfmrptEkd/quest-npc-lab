# Final evaluation dataset

Issue #6's frozen evaluation contains 60 original Korean cases, 10 for each of
six actions, in `data/eval_60.jsonl`. The 12 dialogue review IDs (two per action)
and selection reasons were fixed in `data/eval_manifest.json` before any model
responses were generated or inspected. They cover compound requests,
cancellation, authority/record bypass, ambiguous intent, and misleading
quest vocabulary in out-of-scope requests.

## Authorization and review record

The user's explicit task instruction authorized completing the remaining 40
cases, all 60 final cases, sample selection, freeze, commit, push, and PR. This
replaces the earlier sequential approval gate for this task. The cases use
`review_status=user_approved` with `approval_basis=explicit_task_instruction`
in the manifest. This records authorized adoption, not separate per-case human
inspection. No human review duration or individual human decisions are invented.

AI review checked every case's server state, final intent, label, reference
response, grouping, and duplicates in three mixed-action batches of 20.
`review_batches.md` records the review and revisions. The first batch's JSONL
and readable review are retained and updated to the final content. The shared
`DatasetCase` and dataset validation rules are reused because these contracts
are common across the dataset slices.

## Isolation

The final 10 expression families are recorded in `data/expression_groups.json`.
Draft form, quoted-correction, and contrast families overlapped the completed
validation split and were replaced before freeze; no training or validation
content was edited. The replacement families were assigned before synthesis.
State comparisons and related paraphrases remain together in evaluation.

`validate_eval_freeze()` loads both `train_180.jsonl` and `val_60.jsonl` by default,
verifies their contracts, rejects any expression-group intersection, and runs
joint duplicate checks over all 300 cases. Missing or invalid development files
stop evaluation. The pilot is retained inside train_180 and is not added again.
The manifest records the development file hashes used at freeze as audit
provenance; runtime isolation checks use the current development files.

Checks include exact text, quest/number-normalized equivalents, and cross-split
SequenceMatcher similarity at 0.92. AI family review also inspected the closest
cross-split expressions. These checks do not prove that no semantic paraphrase
exists; this remains a small exploratory expression holdout over shared rules.

Keep this directory out of training generation, editing, prompt improvement,
and configuration-selection contexts. Do not send its questions or answers to
training agents. A directory in a shared repository is an organizational
boundary, not access control. An isolated leakage reviewer may inspect all
splits and report offending development groups without copying held-out wording
to training workers. The evaluator receives the frozen artifacts, these review
records, and the versioned commit. Public availability does not authorize using
held-out content to tune the model or reward.

## Freeze and evaluator handoff

The manifest records version, UTC timestamp, exact-byte dataset SHA-256, count,
action distribution, and the explicit sample IDs. Version 2 is the final freeze:
independent review identified two semantic overlaps in the initial pre-inference
freeze, which was superseded before publication. The manifest preserves that
version's hashes and the revision reason. No model outcomes informed the change.
Keep both final files in version control; do not recompute the hash to accept
later dataset edits. No evaluation loader writes or repairs these files. The
regression test pins both artifact hashes so changes require explicit review.
A checksum detects alteration relative to a trusted manifest; it cannot
authenticate simultaneous replacement of all trusted artifacts and tests.

Before inference, call `validate_eval_freeze()` and use the returned immutable
`FrozenEvaluation` value. Any `EvalFreezeError` stops evaluation. The loader
hashes and parses the same bytes. `training_cases=` is an explicit override for
isolated fixtures or an externally supplied complete development corpus; normal
evaluators should omit it to require both repository splits.

Use `build_eval_prompt(item)` to emit only persona, rules, trusted server state,
and player utterance. Keep case IDs as output bookkeeping outside the prompt.
Intent, action labels, reference dialogue, groups, and review status never enter
inference input. Use the same 12 IDs for later blind review of 48 responses
across the four model conditions; do not select again based on model outcomes.

Run `uv run pytest` for the full suite. No model inference or training is needed
to validate the dataset freeze.
