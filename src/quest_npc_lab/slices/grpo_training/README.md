# GRPO from the preserved SFT adapter (Issue #9)

```bash
uv sync --locked
uv run python -m quest_npc_lab.slices.grpo_training --preflight
uv run python -m quest_npc_lab.slices.grpo_training
uv run pytest
```

The CLI requires the **whole preserved** `artifacts/sft_checkpoint/` directory:
`adapter_config.json`, `adapter_model.safetensors`, and `training_metadata.json`.
It checks the adapter file hashes, loaded parameter digest, approved training data,
and frozen prompt against SFT provenance before updating anything. It never
recreates SFT or downloads a replacement checkpoint. Copying metadata alone is
insufficient. The pinned base model must already be in the local Hugging Face cache.

All GRPO code and tests live in this slice. Existing SFT utilities are reused for
verified-common data approval, model loading, adapter hashing, and checkpoint
reload through `execute_request`; the GRPO runner, rewards, and loss stay here.
Only the approved, balanced `train_180.jsonl` is loaded. The model sees the frozen
improved prompt, server state, and player utterance. Ground-truth action is supplied
only to the reward evaluator; reference dialogue is never serialized into GRPO
prompts. Validation and final evaluation inputs are not loaded.

Each prompt produces G=4 sampled candidates, with seed 42, temperature 1.0,
top-p 1.0, top-k disabled, and the frozen 128-token output limit. Sampling and
likelihood recomputation use the same policy, precision, and disabled dropout.
Reward is exactly 1.0 when the strict parser accepts the original response and
its action matches ground truth; every other response receives 0.0. There are no
format partial credits, negative penalties, or dialogue-quality rewards. This is
one completed-response terminal reward, with no time discount factor.

Advantages are `(reward - group_mean) / (population_std + 1e-4)`. Training uses
the original sequence-normalized GRPO policy objective, one update per newly
sampled group, and KL coefficient zero. The on-policy probability ratio is
`exp(log_prob - stop_gradient(log_prob))`: it has value one but retains a policy
gradient. With one update there is no active clipping. Consequently the reported
scalar policy loss is approximately zero even when the gradient and weight delta
are nonzero; loss decrease is not an acceptance criterion. See the
[TRL objective and loss documentation](https://huggingface.co/docs/trl/grpo_trainer#computing-the-loss).

Candidate losses are averaged over completion tokens through the first EOS,
then over the group; prompt and post-EOS padding tokens contribute no loss.
Identical-reward groups skip the optimizer entirely, including Adam momentum.
A constant 1e-5 learning rate, AdamW with zero weight decay, gradient norm cap 1.0,
and one shuffled pass over 180 inputs bound this run. Existing SFT LoRA parameters
are the only trainable weights. Base dtype remains frozen float32, with BF16
autocast when supported on CUDA. Candidate forwards/backwards run sequentially
to limit GPU memory. Non-finite loss/gradients fail the run.

The sampling-only preflight writes to `artifacts/grpo_preflight/`, processes four
fixed shuffled training inputs, and makes no updates or checkpoint. Its projected
full sampling time is a lower bound because backward passes are excluded. Inspect
its timings before the main run. The main training limit is 1800 seconds, checked
between groups, plus model setup/save/reload. This cooperative limit cannot stop a
hung CUDA operation. There is no automatic retry, seed search, or checkpoint
selection from validation/final evaluation. Additional long runs require a new
execution decision.

Outputs:

- `artifacts/grpo_training_report.json`: configuration/provenance, raw candidate
  groups, rewards/advantages, variance fraction/counts, optimizer step count,
  policy loss curve, parameter delta, memory/time, and reload verification.
- `artifacts/grpo_training_groups.jsonl`: durable completed-group evidence,
  including original responses, rewards, token counts, gradient norms, and time.
- `artifacts/grpo_checkpoint/`: final adapter and provenance metadata. Large
  weights/config are local artifacts excluded from Git; transfer the whole folder.

Existing outputs are protected from overwrite. `--artifacts-dir` selects another
artifact root containing its own preserved `sft_checkpoint/`; it does not select
a different dataset or prompt. Archive a failed report before manually retrying
once its reported cause is resolved. Incomplete coverage, absent relative reward
signal, or zero/non-finite weight delta are failures. A saved adapter is reloaded
on a fresh base, checked for exact parameter identity, and tested with the first
training request through `execute_request`. Its raw output and server processing
are recorded without retries. Action accuracy on that request is separate from
reload success. This integration check does not establish generalization,
dialogue quality, or an improvement over SFT.

## Current execution blocker

The checkout supplied for Issue #9 contains SFT metadata but neither
`adapter_config.json` nor `adapter_model.safetensors`. The CLI invocation recorded
in `artifacts/grpo_training_report.json` therefore failed before model loading,
with zero steps. No GRPO checkpoint or CUDA update is claimed. Restoring the
original files matching the metadata hashes is required to finish the real run
and checkpoint reload acceptance criteria.
