"""Rebuild original vector portraits offline: python -m ...generate_portraits."""

import json
from pathlib import Path

EXPRESSIONS = {
    "default": ("M104 139 Q113 135 122 138 M150 138 Q159 135 168 139", "M126 190 Q136 194 146 190"),
    "thinking": ("M104 137 Q113 130 122 135 M150 139 Q159 139 168 141", "M129 191 Q137 188 144 190"),
    "firm": ("M104 136 L122 141 M150 141 L168 136", "M126 192 L146 192"),
    "smiling": ("M104 137 Q113 133 122 137 M150 137 Q159 133 168 137", "M123 188 Q136 202 149 188"),
}


def generate(root: Path = Path(__file__).parent) -> None:
    for state, (brows, mouth) in EXPRESSIONS.items():
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 272 320" role="img" aria-labelledby="title desc">
<title id="title">Guild receptionist — {state}</title>
<desc id="desc">Original fictional receptionist with chestnut hair, teal uniform and brass guild pin. Static {state} expression.</desc>
<rect width="272" height="320" rx="12" fill="#eee9dc"/>
<path d="M32 276V123a104 104 0 0 1 208 0v153" fill="#dbe2d6"/>
<path d="M44 275V124a92 92 0 0 1 184 0v151" fill="none" stroke="#abbba9"/>
<circle cx="216" cy="49" r="9" fill="none" stroke="#9a7943"/>
<path d="M216 35v28m-14-14h28" stroke="#9a7943"/>
<path d="M75 233V121q0-70 61-70t61 70v112" fill="#44342f"/>
<path d="M49 320v-40q0-47 61-53h52q61 6 61 53v40" fill="#25565a"/>
<path d="M116 208v25l20 25 20-25v-25" fill="#d6a582"/>
<path d="M108 226l28 32-24 17-19-44m71-5-28 32 24 17 19-44" fill="#f6eedb"/>
<path d="M136 259v61" stroke="#a3b5a7" stroke-width="2"/>
<path d="M87 121q-5 100 49 103t49-103q-49-63-98 0" fill="#eac3a2"/>
<path d="M85 131q-5-64 46-68 48-4 57 62-26-12-38-41-19 36-65 47" fill="#44342f"/>
<path d="M104 151q9-5 18 0m28 0q9-5 18 0" fill="none" stroke="#44342f" stroke-width="3" stroke-linecap="round"/>
<ellipse cx="114" cy="152" rx="3" ry="4" fill="#34352f"/>
<ellipse cx="158" cy="152" rx="3" ry="4" fill="#34352f"/>
<path d="{brows}" fill="none" stroke="#604338" stroke-width="3" stroke-linecap="round"/>
<path d="M135 156l-4 17h7" fill="none" stroke="#bd8d6f" stroke-width="2"/>
<path d="{mouth}" fill="none" stroke="#805048" stroke-width="2.5" stroke-linecap="round"/>
<circle cx="87" cy="169" r="4" fill="#bd9653"/>
<circle cx="185" cy="169" r="4" fill="#bd9653"/>
<path d="M181 263l10 6v12l-10 6-10-6v-12z" fill="#d4b575"/>
<path d="M181 268v14m-5-10 5-4 5 4" fill="none" stroke="#25565a" stroke-width="2"/>
<path d="M65 307h142" stroke="#79918a"/>
</svg>
'''
        (root / f"{state}.svg").write_text(svg, encoding="utf-8")
    manifest = {
        "version": 1,
        "generation": {
            "method": "AI-assisted original SVG source; deterministic offline Python generator",
            "reference": "No external reference image or real person; original fictional character",
            "fallback_reason": "No paid API key supplied; authorized static expression fallback",
            "paid_requests": 0, "confirmed_cost_usd": 0, "external_transfers": 0,
            "request_log": [],
            "h3_limits": {"max_usd": 5, "max_requests_including_retries": 10},
            "video_status": "Not generated; pricing, account and publication checks deferred until paid generation is authorized",
        },
        "assets": {
            state: {
                "image": f"{state}.svg", "video": None,
                "license": "CC0-1.0",
                "provenance": "Original vector artwork created for Quest NPC Lab; no third-party assets",
                "method": "generate_portraits.py; shared geometry, expression-specific brows and closed mouth",
            } for state in EXPRESSIONS
        },
    }
    (root / "media_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    generate()
