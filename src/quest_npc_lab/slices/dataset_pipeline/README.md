# Dataset pipeline

This vertical slice owns the structured case model, leakage-safe model prompt,
20-case review gate, collection validators, shortcut baselines, tests, and the
60-case Korean training pilot plus the 180-case train and 60-case validation splits. The utterances and dialogues are original
synthetic text; no public dataset text or translation is included.

## Decision boundaries and tone

The label is determined from both the trusted server state and the player's
final intent. A completed, unclaimed state is not enough to grant a reward:
an information-only question remains `explain_progress` or `explain_reward`.
A reward request below target is `explain_progress`, and a reward request after
claiming is `already_claimed`. Clear cancellation is honored; a trailing reward
question does not cancel an otherwise clear grant request. Conflicting or
underspecified quest requests use `clarify`, while greetings and unsupported
requests use `other`.

Reference dialogue uses a courteous guild-receptionist voice. It is concise,
states the trusted count or reward when relevant, never accepts a player's
claim over server state, and never promises a duplicate reward.

Representative boundaries are present in the pilot:

- completed + explicit grant request → `grant_reward`
- incomplete + false completion claim → `explain_progress`
- completed + reward-information-only request → `explain_reward`
- claimed + replacement or duplicate request → `already_claimed`
- contradictory receive/do-not-receive intent → `clarify`
- cooking, directions, repairs, or small talk → `other`

## Review flow

`PilotReviewFlow.generate_batch` takes 20 protected blueprints and a supplied
expression synthesizer, then passes the resulting drafts through validation and
a supplied AI reviewer. A draft receives `ai_approved` only when that review has
no unresolved issue; reviewer and synthesis failures remain blocked. User review
records one `approve`, `modify`, or `exclude` decision for every case. Modified
or replenished batches must be resubmitted under the same ID and pass AI review
again. A different batch cannot start until the current batch has explicit user
approval. `approve_current_batch` is the all-approved convenience path and
records review duration.

`build_model_prompt` deliberately projects a case down to only persona, rules,
trusted server state, and the current player utterance. `player_intent`,
`ground_truth_action`, and `reference_dialogue` never cross that boundary.

## Checked-in artifacts

- `data/pilot_60.jsonl`: the unchanged approved 60-case pilot, 10 per action.
- `data/review_batches.json` and `data/shortcut_baselines.json`: original pilot records.
- `data/train_180.jsonl`: 30 cases per action; the first 60 are the pilot with
  only `split` changed from `train_pilot` to `train`.
- `data/val_60.jsonl`: 10 cases per action, with separate expression families.
- `data/expression_groups.json`: family assignments established before synthesis,
  including related state comparisons and cancellation variants.
- `data/train_180_review_batches.json` and `data/val_60_review_batches.json`:
  nine and three mixed-action batches, respectively, bound to each file's SHA-256.
- `data/expansion_shortcut_baselines.json`: recomputable policy and six-pattern
  scores, action and state counts, and expression-group counts for both splits.

The expansion uses `user_approved` under the explicit Issue #5 implementation
request to provide that status for pipeline readiness. New batch records use
`approval_basis: explicit_task_instruction` and a null review duration. They do
not claim a separate per-case human inspection or a measured review time. The
first three training batches retain the pilot's existing approval records.
`PilotReviewFlow` continues to enforce sequential review for future generation;
this recorded task authorization does not auto-approve later batches.

## Isolation and verification

Same-family paraphrases and state comparisons stay in one split. Validation
holds out intake-note, quoted-intent, and parallel-contrast expression families;
it is an exploratory expression holdout, not a claim of unseen game rules.
Exact text, normalized quest/number patterns, and cross-split near-paraphrases
(SequenceMatcher ratio >= 0.92) are checked together. Family review complements
this lexical heuristic: it cannot prove the absence of every semantic paraphrase.
Final-evaluation cases are not inputs to this slice's expansion or verification.

`load_dataset(path)` applies the strict schema to either split.
`validate_train_validation_datasets(train, validation)` verifies counts, action
balance, user approval, pilot retention, shortcut counterexamples, and joint
isolation. `prepare_training_cases` accepts either the complete approved pilot
or the complete approved 180-case train split; it rejects validation cases.
`validate_review_manifest` checks each 20-case batch and binds the supplied
cases to the exact hashed JSONL file, so a stale manifest or modified case fails.

Validate the artifacts, recompute the stored shortcut scores, and test prompt
separation across all 240 cases with:

```bash
uv run pytest src/quest_npc_lab/slices/dataset_pipeline/test_dataset_pipeline.py
uv run pytest
```

The shortcut scores are deliberately naive policy results used to check the
data. They are not learned-model accuracy results. The prompt tests change
intent, action, reference dialogue, and review metadata while requiring the
model input to remain identical.
