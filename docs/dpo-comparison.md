# Offline DPO comparison

Scope approved 2026-09-27: one exploratory DPO continuation from the preserved
SFT adapter, using existing rule-labelled GRPO training trajectories. This adds
a fifth experimental condition; it does not replace the original four-condition
experiment. Human preference or dialogue-quality optimization is not claimed.

## Fixed protocol

- Validate preserved SFT bytes against metadata and its training report. Require
the source GRPO report to point to this same SFT and its groups to match the report.
- Only the 180 approved train cases may contribute. Independently recompute all
candidate rewards. For each mixed-reward group choose the first reward-1 and
first reward-0 response in recorded order: one pair per input, no cherry-picking.
The supplied reproduction has 102 such groups. Do not read evaluation answers
while constructing pairs. Keep raw chosen/rejected strings unchanged.
- Policy and frozen reference both start from the same SFT adapter, not the base
model or GRPO endpoint. Standard sigmoid DPO beta 0.1; seed 42; learning rate
1e-5; one epoch; batch size 2; AdamW, no weight decay, constant scheduler;
no truncation; bf16 CUDA, existing LoRA parameters only. No hyperparameter sweep
or best-checkpoint selection. Training budget 15 minutes; fail and retain logs
if exceeded. GPU smoke checks must not consume an extra training attempt.
- Save full provenance, source hashes, pair manifest, optimizer logs, parameter
delta, checkpoint hashes and independent reload verification outside worktrees.
Never overwrite preserved outputs or inputs. Back up complete artifacts.
- Generate exactly 60 new DPO responses on the frozen eval set with the same
prompt, greedy decoding and 128-token limit. Reuse existing SFT/GRPO responses
only after checking their dataset/prompt/generation/checkpoint provenance.
Recompute action accuracy, JSON-format pass rate and wrong-grant rate from raw
responses, with explicit counts and denominators. No retries for bad answers.
- The eval set has already been inspected. Label this an exploratory extension,
not a fresh held-out confirmation or a controlled algorithm superiority test.
The pairs came from changing GRPO policies; their acquisition cost and lineage
remain part of this experiment. Dialogue review remains a separate human task.

## Verification boundaries

Pair construction and source integrity; real parameter update and checkpoint
reload; independent raw-response metric recomputation. Preserve original tests.
