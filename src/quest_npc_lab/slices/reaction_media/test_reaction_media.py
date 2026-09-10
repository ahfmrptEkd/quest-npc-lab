"""Reaction behavior at the mapper, asset and comparison boundaries."""

import pytest

from . import reaction_state


@pytest.mark.parametrize("approved", [False, None, 1, "true", {}, []])
def test_model_grant_alone_cannot_trigger_smiling(approved):
    assert reaction_state({
        "parsed_output": {"action": "grant_reward"},
        "server_execution": {"approved": approved},
    }) == "firm"


@pytest.mark.parametrize(("action", "expected"), [
    ("grant_reward", "smiling"), ("clarify", "thinking"),
    ("already_claimed", "firm"), ("explain_progress", "default"),
    ("explain_reward", "default"), ("other", "default"), ("idle", "default"),
])
def test_action_mapping(action, expected):
    assert reaction_state({
        "parsed_output": {"action": action},
        "server_execution": {"approved": True},
    }) == expected


@pytest.mark.parametrize("artifact", [
    None, {}, {"raw_output": '{"action":"grant_reward"}'},
    {"parsed_output": None, "error": {"stage": "model_output"}},
])
def test_idle_and_malformed_output_use_default(artifact):
    assert reaction_state(artifact) == "default"


def test_manifest_and_all_static_fallbacks():
    import json
    from xml.etree import ElementTree
    from . import MEDIA_ROOT, reaction_media, read_asset

    manifest = json.loads((MEDIA_ROOT / "media_manifest.json").read_text())
    assert set(manifest["assets"]) == {"default", "thinking", "firm", "smiling"}
    assert manifest["generation"]["paid_requests"] == 0
    for state, entry in manifest["assets"].items():
        assert entry["license"] and entry["provenance"] and entry["method"]
        media = reaction_media(state)
        assert media["video"] is None
        body, mime = read_asset(media["image"])
        assert mime == "image/svg+xml"
        svg = ElementTree.fromstring(body)
        assert svg.find("{http://www.w3.org/2000/svg}title").text
        assert media["label"]


def test_optional_video_and_missing_asset_fallback(tmp_path):
    from . import reaction_media, read_asset

    (tmp_path / "thinking.mp4").write_bytes(b"video fixture")
    assert reaction_media("thinking", root=tmp_path)["video"] == "/media/thinking.mp4"
    assert reaction_media("firm", root=tmp_path)["video"] is None
    assert read_asset("/media/thinking.mp4", root=tmp_path) == (b"video fixture", "video/mp4")
    assert read_asset("/media/firm.mp4", root=tmp_path) is None
    assert read_asset("/media/../../interactive_ui/server.py") is None
    assert read_asset("/media/media_manifest.json") is None


def test_ui_uses_server_result_for_grant_and_repeated_grant():
    from quest_npc_lab.slices.interactive_ui import ComparisonApp

    app = ComparisonApp(
        offline=True,
        base_model=lambda _: '{"action":"grant_reward","dialogue":"지급합니다."}',
    )
    session = app.new_session()
    assert all(c["reaction"]["state"] == "default" for c in app.describe(session)["conditions"])
    first = app.turn(session, {"condition": "base_minimal", "utterance": "보상 줘"})
    assert first["conditions"][0]["reaction"]["state"] == "smiling"
    second = app.turn(session, {"condition": "base_minimal", "utterance": "다시 줘"})
    assert second["conditions"][0]["reaction"]["state"] == "firm"
    assert second["conditions"][1]["reaction"]["state"] == "default"


def test_http_serves_portraits_and_rejects_unknown_media():
    from threading import Thread
    from urllib.request import urlopen
    from urllib.error import HTTPError
    from quest_npc_lab.slices.interactive_ui import ComparisonApp
    from quest_npc_lab.slices.interactive_ui.server import make_server

    server = make_server(ComparisonApp(offline=True), port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for state in ("default", "thinking", "firm", "smiling"):
            with urlopen(base + f"/media/{state}.svg") as response:
                assert response.headers["Content-Type"] == "image/svg+xml"
                assert b"<svg" in response.read()
        with urlopen(base + "/reaction-media.js") as response:
            assert b"createReactionMedia" in response.read()
        for path in ("/media/firm.mp4", "/media/../media_manifest.json"):
            with pytest.raises(HTTPError) as caught:
                urlopen(base + path)
            assert caught.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_browser_renderer_fallback_and_motion():
    import shutil
    import subprocess
    from . import MEDIA_ROOT

    node = shutil.which("node")
    if node is None:
        pytest.skip("Renderer tests require Node.js 18+; Python media tests still run")
    subprocess.run(
        [node, "--test", str(MEDIA_ROOT / "test_renderer.cjs")],
        check=True, capture_output=True, text=True,
    )
