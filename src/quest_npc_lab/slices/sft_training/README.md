# Main LoRA SFT (Issue #8)

Run from the repository root, with the pinned model already in the local Hugging
Face cache and an available CUDA GPU:

```bash
uv sync --locked
uv run python -m quest_npc_lab.slices.sft_training
uv run python -m quest_npc_lab.slices.sft_training --verify-only
uv run pytest
```

The fixed run starts from `Qwen/Qwen2.5-0.5B-Instruct` revision
`7ae557604adf67be50417f59c2c2f167def9a775`, seed 42, for three epochs (135
optimizer steps), batch size 4, constant learning rate 0.0001, AdamW, and LoRA
rank 8 / alpha 16 on `q_proj` and `v_proj`. It uses float32 base weights and BF16
autocast when supported. No smoke adapter is loaded. The previous smoke estimate
was 168.3 seconds per epoch; the fixed training limit is 900 seconds, checked
after each optimizer step. There is no automatic retry or checkpoint selection.

Only the allowlisted `train_180.jsonl` and its approval manifest are read. All
180 cases must be user-approved, balanced (30 per action), and match the reviewed
hash. Neither validation nor evaluation data is loaded. The improved prompt is
imported from the frozen prompt evaluation slice; its manifest hash is checked.
Chat tokenization explicitly preserves the generation prefix, rejects over-limit
inputs, and masks prompt tokens from the loss. Complete examples are never
truncated or packed. The completion contains only the approved action/dialogue.
See [TRL's SFT documentation](https://huggingface.co/docs/trl/sft_trainer) for
completion masking and the chunked cross-entropy loss used here.

Outputs under `artifacts/`:

- `sft_training_report.json`: settings, versions/hashes, loss trajectory, step
  times, parameter delta, GPU memory, execution time, and raw reload request record.
- `sft_training_steps.jsonl`: durable per-step loss/time records, also kept when
  training fails.
- `sft_checkpoint/`: PEFT adapter weights/config plus tracked
  `training_metadata.json`. Large model files and transient trainer output are
  ignored by Git. Copy the **whole directory** when transferring the checkpoint.
- `sft_reload_verification.json`: independent `--verify-only` result; the original
  training report and adapter are left intact.
- `sft_attempts/01_tokenizer_preflight/sft_training_report.json`: failed initial
  preflight, before any weight updates. Transformers 5 returned `BatchEncoding`
  by default; explicitly requesting token lists fixed the compatibility issue.

Existing checkpoint/report paths are protected from overwrite. To reproduce a
separate authorized run, use `--artifacts-dir artifacts/reproduction` and retain
its report separately. OOM, non-finite loss, time limit, missing updates, incomplete
steps, or reload failures produce a failed report and nonzero exit status. The
step limit is cooperative: a hung CUDA operation is not a process watchdog.

Reload starts a fresh base model with the frozen float32 inference settings,
checks exact adapter parameter identity, and runs the first training case through
`execute_request`. The raw result is strictly parsed without repair/retry; format
errors fail verification. Action correctness is recorded separately. This one
training input is an integration check, not a generalization evaluation.

For Issue #9, load this preserved adapter with `PeftModel.from_pretrained(base,
"artifacts/sft_checkpoint", is_trainable=True)` and save GRPO output to a distinct
directory. Use the pinned base revision above and the same frozen improved prompt.
Adapter weights are local artifacts; cloning the Git repository alone does not
retrieve them. A single-seed run does not establish stable performance gains or
complete reproducibility across hardware/library versions.

## Recorded run

The RTX 3060 run completed 135 steps in 50.10 seconds of training (69.70 seconds
including setup, save, and reload). Mean batch losses by epoch were 1.5381,
1.1391, and 0.8927. All 96 LoRA tensors changed; the L2 parameter delta was 3.3951
across 540,672 trainable parameters. Peak allocated CUDA memory was 5.90 GiB.
Both initial and independent reload checks passed with identical adapter weights.
The fixed check response was valid JSON but selected `explain_reward` instead of
`grant_reward`; this error is retained and is not evidence of improved accuracy.
