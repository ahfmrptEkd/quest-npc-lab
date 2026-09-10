# Public showcase — Issue #13

All builders, Pages source assets, Spaces templates and tests live in this slice.
The existing UI's frozen prompt/default configuration is integrated in its own
slice. Build outputs are ignored under this slice's `build/` directory.

```bash
uv run python -m quest_npc_lab.slices.public_showcase pages
uv run python -m quest_npc_lab.slices.public_showcase spaces
uv run pytest src/quest_npc_lab/slices/public_showcase/test_public_showcase.py
```

Use `--artifacts` to select the preserved artifact directory, and `--output` for a
new destination. Existing destinations are rejected so stale files or secrets
cannot survive an incremental deployment build. No model is loaded by builders.

## Pages

Serve `build/pages/` with any static HTTP server. It contains plain HTML/CSS/JS,
`results.json`, exact raw JSONL, linked reports, frozen manifests and four SVGs.
The builder recomputes the report from original strings and rejects disagreements.
It replays server execution for portrait selection, ignoring cached parsed scores.
Relative paths work under a GitHub Pages repository subpath. Text is rendered
with `textContent`, so model outputs cannot inject executable HTML.

For GitHub Pages, upload the contents of `build/pages/` as the Pages artifact
using the repository's approved Pages workflow, or put those contents in the root
of a dedicated `gh-pages` branch and select that branch/root in Settings → Pages.
The intended address is `https://ahfmrptEkd.github.io/quest-npc-lab/`; it is not
advertised as verified live. This builder does not change repository settings or
publish branches. The root README links to this runnable source until hosting is
verified. Once deployed, set the Space's `PAGES_URL` to the actual address.

## Spaces

Upload **the generated `build/spaces/` contents**, not the template directory, to
the root of a Gradio Space. Follow its [configuration instructions](spaces/README.md).
The bundle contains just the four reused runtime slices and their required
assets/config; it excludes tests, data answers, review keys, weights and local docs.
Final checkpoint metadata is embedded for file-hash validation. Public adapter
repository IDs and immutable revisions must be supplied separately.

To check locally after building, use an isolated environment:

```bash
cd src/quest_npc_lab/slices/public_showcase/build/spaces
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
QUEST_DEVICE=cpu .venv/bin/python app.py
```

Configure `SFT_CHECKPOINT`/`GRPO_CHECKPOINT` with preserved local directories or
the Hub settings in the bundled README to enable all four conditions. A base-only
startup is diagnostic and does not complete deployment acceptance. Comparison
resets all conditions to the edited state; continuation uses only the selected
condition's last server state. Gradio state belongs to each visitor, and GPU worker
calls return serializable state instead of relying on global process mutations.

## Deployment status

- Pages: buildable, hosted URL not verified by this change.
- Spaces: packaged, no hosted app or eligible account verified by this change.
- ZeroGPU: official compatibility/eligibility read on 2026-09-10; actual
  hosting, queue/quota behavior and cold/warm latency still require measurement.
- Adapters: exact final hashes recorded; public Hub IDs and redistribution
  licenses are not supplied. This blocks a complete public four-condition Space.
- No paid services, account upgrades, external messaging, or model uploads were
  performed. A free-path blocker must be reported before any paid alternative.

These are outstanding deployment acceptance items from #13, even though its
code packaging and local reproduction work can be reviewed independently.

## Verification recorded for this change

- `uv run pytest`: **249 passed** (241 existing + 8 showcase tests), 46.37s.
  After quoting the Spaces Python version, the bundle/YAML tests also passed.
- Ruff lint/format and basedpyright on changed Python files passed.
- `uv pip compile` resolved all 83 Spaces runtime dependencies for Python 3.12.
  This validates resolution, not hosted CUDA compatibility.
- Recompute CLI left the committed final report byte-identical.
- Chromium exercised all 60 cases / 240 cards, action filtering, previous/next,
  raw output expansion, pattern selection, all 13 artifact links, SVG loading,
  and layouts at 1440px and 375px. A long-link overflow found at 375px was fixed.
- Preserved local adapters matched final metadata hashes. A new free-form local
  comparison completed all four conditions in 69.8s including model loading.
  Both base responses had format errors; SFT/GRPO granted an eligible reward,
  with smiles only after server approval. This is a smoke check, not another eval.
- The generated Gradio bundle started with those adapters and completed one
  queued free-form comparison in 41.0s locally, preserving raw failures and
  unscored free input. This check used local PyTorch 2.14.0; the pinned hosted
  2.13.0 stack and ZeroGPU allocation/quotas have not been executed.
- Independent Standards review found no documented violations. Its checkpoint
  display finding was fixed and covered by a regression; direct session access
  remains a small coupling tradeoff. Spec review identified the hosting and
  public-adapter acceptance gaps documented above.
