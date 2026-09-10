---
title: Quest NPC Lab
emoji: 🏰
colorFrom: green
colorTo: gray
sdk: gradio
sdk_version: 6.26.0
python_version: "3.12"
app_file: app.py
pinned: false
---

# Quest NPC Lab · live inference bundle

Deployment status: **not verified on hosted ZeroGPU**. This directory is the
deployment template; first build its standalone runtime from the repository:

```bash
uv run python -m quest_npc_lab.slices.public_showcase spaces
```

Upload the contents of `src/quest_npc_lab/slices/public_showcase/build/spaces/`
to an eligible Gradio Space. Select **ZeroGPU** hardware in Space settings;
README metadata alone does not allocate hardware. No paid upgrade is required
by this bundle or authorized by this project.

## Configuration

The pinned base is downloaded at startup. For both final adapters configure:

- `SFT_REPO_ID`, `SFT_REVISION`: adapter Hub repo and full immutable commit SHA.
- `GRPO_REPO_ID`, `GRPO_REVISION`: same for the final GRPO adapter.
- `PAGES_URL`: verified published Pages URL (default is the intended repository URL).
- `HF_TOKEN`: only if needed for private repositories, stored as a Space secret.
- `QUEST_DEVICE`: normally `cuda` on Spaces; `cpu`/`auto` for local bundle checks.

For local checks, `SFT_CHECKPOINT` and `GRPO_CHECKPOINT` may point to preserved
adapter directories. Downloaded/local adapter file hashes must match the final
evaluation metadata embedded in `deployment.json`; an unconfigured adapter is
shown unavailable, never replaced with base weights. Configured but invalid
adapters fail startup. This checkout does not supply public adapter repository
IDs or invent a license for their redistribution. Publish rights-cleared adapters
separately, then record their immutable revisions and configure the Space.

## ZeroGPU compatibility and limits

Checked against the [official ZeroGPU documentation](https://huggingface.co/docs/hub/spaces-zerogpu)
on 2026-09-10: eligible free personal accounts need a verified email and an account
older than 30 days; they may host up to two ZeroGPU Spaces. Gradio is required.
Python 3.12 and PyTorch 2.13.0 are listed as supported. The bundle pins those
versions and uses `spaces.GPU(duration=120)` with a serialized, bounded queue.
Models move to CUDA at startup; inference runs inside the decorated callback.
No `torch.compile`, paid API, runtime image generation, or fallback outputs.

Visitors face daily quotas and queues; the page links to saved Pages results
and displays inference errors and elapsed time including waiting. The 120-second
GPU request is a ceiling, not measured hosted latency. Local final evaluation used
PyTorch 2.14.0; the hosted 2.13.0 stack needs its own compatibility/output check.
See also [Spaces metadata](https://huggingface.co/docs/hub/spaces-config-reference).

Before claiming deployment success, record the public URL, account eligibility,
actual hardware and installed versions, cold/warm timings, all four adapters'
readiness, free input/state editing, session isolation, invalid input, duplicate
grant blocking, quota/error behavior, and the Pages link. If the free path is
unavailable, stop and report that blocker; do not purchase PRO/GPU/credits.

Original SVG portraits are CC0-1.0 per the bundled media manifest. The pinned
Qwen model is Apache-2.0 per its model card. No model weights, credentials, local
operations notes, evaluation answers, or hidden dialogue-review key are bundled.
