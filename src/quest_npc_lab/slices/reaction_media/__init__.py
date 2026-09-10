"""Stored NPC portraits and server-verified reaction selection."""

from pathlib import Path


def reaction_state(artifact: dict | None) -> str:
    """Consume a server artifact, never raw model text, to select an expression."""
    if not artifact:
        return "default"
    action = (artifact.get("parsed_output") or {}).get("action")
    if action == "grant_reward":
        execution = artifact.get("server_execution") or {}
        return "smiling" if execution.get("approved") is True else "firm"
    return {"clarify": "thinking", "already_claimed": "firm"}.get(action, "default")


MEDIA_ROOT = Path(__file__).parent
LABELS = {
    "default": "길드 접수원 · 안내",
    "thinking": "길드 접수원 · 생각 중",
    "firm": "길드 접수원 · 단호한 안내",
    "smiling": "길드 접수원 · 보상 지급 승인",
}


def reaction_media(state: str, *, root: Path = MEDIA_ROOT) -> dict:
    """Describe bundled media; absent videos always leave a static portrait."""
    if state not in LABELS:
        state = "default"
    video = root / f"{state}.mp4"
    return {
        "state": state,
        "label": LABELS[state],
        "image": f"/media/{state}.svg",
        "video": f"/media/{state}.mp4" if video.is_file() else None,
    }


def read_asset(url: str, *, root: Path = MEDIA_ROOT) -> tuple[bytes, str] | None:
    """Serve only the eight explicit portrait filenames, never arbitrary paths."""
    for state in LABELS:
        for suffix, mime in (("svg", "image/svg+xml"), ("mp4", "video/mp4")):
            if url == f"/media/{state}.{suffix}":
                try:
                    return (root / f"{state}.{suffix}").read_bytes(), mime
                except OSError:
                    return None
    return None
