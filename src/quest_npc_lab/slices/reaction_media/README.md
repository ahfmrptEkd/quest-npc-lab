# NPC reaction media

The delivered media are four original, AI-assisted static SVG portraits of one
fictional guild receptionist. No paid key was supplied: the authorized image
fallback is used. No H3 requests, charges or external image transfers occurred.
These are illustrations, not generated videos or evidence of model training.

Rebuild with:
`uv run python -m quest_npc_lab.slices.reaction_media.generate_portraits`

The artwork is dedicated under CC0-1.0. Provenance, method, asset names and the
zero-cost generation record are in `media_manifest.json`.

The server maps validated artifacts: clarify → thinking, already_claimed →
firm, approved grant_reward → smiling, blocked grant_reward → firm; everything
else (including idle and malformed output) → default. The blocked-grant firm
expression follows the Issue #12 implementation request's explicit mapping.
Model dialogue and raw JSON cannot select a success portrait.

Optional local videos use `default.mp4`, `thinking.mp4`, `firm.mp4` and
`smiling.mp4` beside the SVGs. Before adding videos, record their source,
license and generation details in the manifest and review character/clothing/
framing consistency, closed-mouth motion and loop seams. H3 preparation still
requires paid-call authorization and current price/account/publication checks;
stop at USD 5 or 10 requests including retries, whichever comes first.
The loader serves only those exact media filenames.

The browser retains the SVG beneath each video and returns to it on loading or
playback errors. Reduced-motion preference and the keyboard-operable stop
checkbox use static portraits without loading video. Captions remain available
even if images fail. All four comparison conditions use the same mapper,
assets and 180 ms video fade.

Run `uv run pytest` for the Python suite and renderer checks. Renderer checks
execute the shipped JavaScript with browser API stand-ins and require Node.js
18+; pytest explicitly skips that check when Node is absent.
