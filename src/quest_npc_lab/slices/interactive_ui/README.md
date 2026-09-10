# Local interactive comparison UI

Run from the repository root (Python 3.12+, dependencies installed by `uv`):

```bash
uv run python -m quest_npc_lab.slices.interactive_ui --offline
# Open http://127.0.0.1:8000
uv run python -m quest_npc_lab.slices.interactive_ui
# Optional CPU execution:
uv run python -m quest_npc_lab.slices.interactive_ui --device cpu --port 8001
```

Without `uv`, activate the installed project environment and use
`python -m quest_npc_lab.slices.interactive_ui`.

Offline mode needs no GPU, model weights, or network. It always returns a
clearly labeled `clarify` test response for the two base conditions. This
checks the UI flow, not Korean understanding or model quality. SFT and GRPO
remain **미준비 / Checkpoint not ready**, even if paths are supplied in offline
mode. Unit tests inject other model outputs to exercise grants, blocking and
format errors.

Live mode uses the locally cached `Qwen/Qwen2.5-0.5B-Instruct` revision
`7ae557604adf67be50417f59c2c2f167def9a775` selected by the model-smoke slice.
The loader uses `local_files_only=True`: it never downloads weights or calls
an inference API. If the cache is missing, the condition displays the load
error. Provision that model/revision in the Hugging Face cache before using
live mode. `--model-id` and `--revision` can select another cached compatible
causal language model. The default device is CUDA when available, otherwise
CPU; CPU generation can be slow. First use loads the model. Requests are
serialized to protect model use and session state.

All live conditions use greedy decoding, float32 weights and the same
`--max-new-tokens` (default 256). No automatic retry, JSON repair or output
substitution occurs. Raw output means the decoded generated text before
parsing; tokenizer special tokens are omitted. Incomplete or invalid JSON
remains visible alongside its parse error. Inference exceptions have no raw
output and leave that condition's state unchanged; other conditions still run.

## Conditions and checkpoints

The cards show model/revision, adapter path, prompt identifier, mode, device
selection and generation settings. `minimal-v1` uses the receptionist's
existing default rules. `improved-ui-v1` adds the agreed intent/cancellation
rules; this is a UI integration prompt, not a claim that the main-training
prompt has been finalized or evaluated. All improved conditions use identical
rules.

```bash
uv run python -m quest_npc_lab.slices.interactive_ui \
  --sft-checkpoint checkpoints/sft \
  --grpo-checkpoint checkpoints/grpo
```

Each trained path must be a local PEFT adapter directory with
`adapter_config.json` and `adapter_model.safetensors` or `adapter_model.bin`,
compatible with the selected base model. Readiness means these files exist;
load/compatibility errors are displayed on execution. A trained condition
loads its own adapter over a separate base instance, never the unadapted
base runner. Up to three model instances may occupy device memory. Restart
the server after adding/replacing checkpoints. Do not use the model-smoke
slice's preparation checkpoints as main-experiment results.

## State and API behavior

- **Compare** (`POST /api/compare`, `{state, utterance}`) validates the entire
  input before inference or session mutation, resets all four conditions to
  independent copies of the supplied state, then runs available conditions.
- **Continue** (`POST /api/turn`, `{condition, utterance}`) uses only that
  condition's retained server state and the current utterance. The common
  state editor is used only for a new comparison.
- `GET /api/session` creates or resumes a browser session using an HttpOnly,
  SameSite cookie. Different browser profiles/contexts have separate sessions;
  tabs in the same browser profile share one. Refresh restores card states
  and the latest artifacts, not unsent form edits. Requests are single-turn:
  prior utterances and responses never enter the next model prompt.
- Sessions live in server memory until restart (maximum 128 browser sessions).
  The server binds only to `127.0.0.1` and accepts same-origin local requests.
  This is a local tool, not a public hosting server.
- State limits come from the receptionist boundary: quest name 200 characters,
  reward 500, utterance 2000, positive integer target, nonnegative current
  count, and no claimed reward before completion. Surpassing the target is
  valid. The HTTP JSON body limit is 32 KiB. Extra request/state fields are
  rejected; clients cannot supply ground truth.
- Free-form input is always **미채점 / Unrated**. Server approval validates a
  state transition; it does not determine whether the model understood the
  player's intent correctly.

All handlers, assets, inference wiring and tests live in this slice. Domain
validation, parsing and enforcement use the public `execute_request` boundary
in the sibling receptionist slice.

```bash
uv run pytest src/quest_npc_lab/slices/interactive_ui/test_interactive_ui.py
uv run pytest
```

Tests use deterministic inference doubles and an actual loopback HTTP server.
Real checkpoint integration and model quality are separate from those tests.
