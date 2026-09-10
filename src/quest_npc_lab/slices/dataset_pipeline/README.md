# Pilot dataset pipeline

This vertical slice owns the structured case model, leakage-safe model prompt,
20-case review gate, collection validators, shortcut baselines, tests, and the
60-case Korean training pilot. The utterances and dialogues are original
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

- `data/pilot_60.jsonl`: 60 AI-reviewed `train_pilot` cases, 10 per action.
- `data/review_batches.json`: three sequential 20-case validation, AI-review,
  and pending user-review records bound to the dataset SHA-256.
- `data/shortcut_baselines.json`: reproducible scores for always-grant,
  always-reject, always-other, always-clarify, and state-only-grant policies.

Validate the slice and all repository tests with:

```bash
uv run pytest
```

The tests load the shipped JSONL through the strict model, reject contradictory
state and label combinations, enforce group/split integrity and exact balance,
validate the review manifest hash and batch ranges, and recompute every stored
shortcut score from the cases.

The checked-in pilot is intentionally not eligible for training yet.
`prepare_training_cases` rejects it until all three batches have been inspected
by the user and their case statuses and review manifest are updated to
`user_approved`. The pending status is an approval gate, not a quality failure.
