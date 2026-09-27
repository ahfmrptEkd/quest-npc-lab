# Offline DPO exploratory comparison

This slice continues **an existing SFT adapter**, preserving it, and writes a
new DPO adapter. It does not retrain SFT. The trainable policy adapter and a frozen reference adapter share a frozen
base model and start from identical SFT bytes. See `docs/dpo-comparison.md`
and issue #28 for the fixed experiment and its limitations.

```bash
uv run python -m quest_npc_lab.slices.dpo_training \
  --source /path/to/preserved-reproduction/artifacts \
  --output /path/outside/worktrees/new-dpo-run

uv run python -m quest_npc_lab.slices.dpo_training \
  --source /path/to/preserved-reproduction/artifacts \
  --output /path/outside/worktrees/new-dpo-run --recompute
```

The output must not exist for a new run. Keep the complete source reproduction
and output folders. Neither ignored weights nor local experiment directories
are backed up by Git; archive and verify them before cleaning any checkout.

Pairs are the first reward-1 and first reward-0 response of each mixed group,
with independently rechecked rewards. Ties are skipped. These are rule-based
action preferences, not human assessments of dialogue. Pair generation uses
approved train cases only. No automatic tuning, output repair, or response retry.

The 60 DPO responses are evaluated separately; the original 240 baseline
responses are reused after provenance checks. Wrong-grant rate uses cases whose
expected action is not `grant_reward` as its denominator (50 of 60 here), and
counts the model's raw choice before the server can block it. JSON failures are
counted separately and are never treated as correct actions.

The already-inspected evaluation set and evolving GRPO source policies make
this an exploratory extension, not an unbiased algorithm superiority result.
