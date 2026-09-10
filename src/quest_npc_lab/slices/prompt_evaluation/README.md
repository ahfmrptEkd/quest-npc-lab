# Development baselines and frozen prompt

Run `uv run python -m quest_npc_lab.slices.prompt_evaluation` from the repository
root. It uses the locally cached, pinned Qwen base model without adapters, runs
both prompts once on each of the approved 180 training and 60 validation cases,
and writes `artifacts/baseline_comparison_report.json` inside this slice.
No model download, paid service, retries, correction or training occurs.

The loader has a fixed development-file allowlist and verifies the approval
manifests, sizes, action balance and expression-group isolation. Labels, intents,
reference dialogue and review metadata are never passed to the model. Both
conditions start from each case's original server state. Artifacts retain raw
outputs, strict parsing, original-action accuracy and separate server execution.
Malformed JSON counts as incorrect; server approval does not imply correctness.

## Frozen contract for Issues #8 and #9

```python
from quest_npc_lab.slices.prompt_evaluation import format_prompt, load_manifest

config = load_manifest()
prompt = format_prompt(state, player_utterance)  # improved prompt by default
messages = [{"role": "user", "content": prompt}]
```

Both training slices must import these functions. For SFT, put the reference
answer only in the assistant completion. For GRPO, keep the scoring label in a
separate reward-only column. Do not use the earlier model-smoke prompt helpers
or smoke checkpoints for the main experiment. Apply the pinned tokenizer chat
template with `add_generation_prompt=True` and no truncation. Generation settings
in the manifest govern greedy comparisons; GRPO candidate sampling and actual
SFT/GRPO optimization schedules remain work for #8/#9, not completed training.

`prompt_manifest.json` freezes the improved wording, template, model revision,
seed 42, 128 output tokens, greedy settings, dtype and input limits. Its sibling
SHA-256 file detects accidental edits. Loading returns a fresh copy. A deliberate
future contract change requires a new version and checksum, before training;
never select changes using held-out results. Seed alone does not guarantee
identical results across hardware or library versions.

## Prompt development log

One comparison: minimal-v1 establishes persona, six action rules and strict JSON;
improved-v1 adds explicit cancellation, retained compound intent, eligibility
precedence, ambiguity and deceptive-claim handling. Wording follows the approved
rules and development cases only. No iterative search or held-out inspection is
part of this run. The report preserves both exact rule strings and environment
versions. Improved-v1 is the prespecified training prompt even if its measured
accuracy is equal to or worse than minimal-v1; no improvement is assumed.

Offline verification: `uv run pytest src/quest_npc_lab/slices/prompt_evaluation/`.

Execution note: the initial default-thread attempt was interrupted after the
first 20 responses took 148.5 seconds. No comparative scores were produced or
used to change prompts. A second single-thread attempt took 136.6 seconds for 20 responses and was
also interrupted. The completed run uses batches of eight and one CPU thread;
all model, prompt, decoding and input settings remain identical. This is an
execution restart, not an error-driven response retry.

## Measured development result

The completed run generated 480 responses in 490.03 seconds on the recorded
RTX 3060 environment. Both minimal-v1 and improved-v1 had 0/180 valid or
action-correct training responses and 0/60 valid or action-correct validation
responses. All 480 failed the strict output contract. Sampled failures include
input JSON copied inside code fences and prose instead of the required object.
No format repair or response retry was applied. This run demonstrates no
measured prompt improvement; it does not establish action-selection ability
independently of formatting. These failures are retained for the subsequent
SFT/GRPO comparison, without selecting a new prompt from held-out results.
