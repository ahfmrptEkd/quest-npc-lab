# Model smoke validation slice

Bounded real-model check of the full path before the main experiment:

1. Environment: device, VRAM, host memory, disk, library versions, pinned
   model revision and license.
2. Inference: greedy response for pilot case 1, sent through
   `execute_request` (raw output, parsed action, score, server execution).
3. LoRA SFT: one step on two approved pilot cases, weight diff, adapter save
   to `artifacts/smoke/sft_adapter/`, reload, weight match, and inference with
   the reloaded adapter.
4. GRPO: one step from the SFT adapter, `G` sampled candidates per prompt,
   strict 1/0 reward (valid output contract **and** correct action), reward
   group variance, and parameter diff. Ground truth is a reward-only column,
   never part of the model prompt.

```bash
uv run python -m quest_npc_lab.slices.model_smoke            # auto device
uv run python -m quest_npc_lab.slices.model_smoke --device cpu
```

Options: `--seed`, `--max-new-tokens`, `--num-generations`, `--grpo-prompts`,
`--smoke-dir`, `--report`. Each phase runs a fixed number of steps with no
retries; a failed phase is recorded as a blocker and GRPO is skipped without
an SFT adapter. The command exits `0` only when the report status is `passed`.

The report lands in `artifacts/smoke_validation_report.json`. Checkpoints and
trainer output under `artifacts/smoke/` are git-ignored smoke artifacts and
must not be reused as main-experiment results.

`uv run pytest` covers the reward, signal, leakage, diff, and report rules
with small fixtures; it never loads the model.
