"""Behavior at the UI API boundary; inference is an external test seam."""

import pytest

from quest_npc_lab.slices.interactive_ui import ComparisonApp


def test_four_conditions_only_base_runnable_offline():
    app = ComparisonApp(offline=True)
    session = app.new_session()
    result = app.describe(session)
    assert [item["status"] for item in result["conditions"]] == [
        "ready",
        "ready",
        "checkpoint_not_ready",
        "checkpoint_not_ready",
    ]
    assert result["mode"] == "offline"
    assert result["conditions"][2]["artifact"] is None


STATE = dict(
    quest_name="슬라임 토벌",
    target_count=5,
    current_count=5,
    reward_description="금화 100개",
    reward_claimed=False,
)


def test_comparison_isolated_and_continuation_persists_without_history():
    import json

    prompts = []

    def generate(prompt):
        prompts.append(json.loads(prompt))
        return '{"action":"grant_reward","dialogue":"보상을 드립니다."}'

    app = ComparisonApp(offline=True, base_model=generate)
    session = app.new_session()
    result = app.compare(session, {"state": STATE, "utterance": "보상 줘"})
    first, second, sft, grpo = result["conditions"]
    assert first["artifact"]["server_execution"]["state_changed"] is True
    assert second["artifact"]["server_execution"]["state_changed"] is True
    assert sft["artifact"] is None and grpo["artifact"] is None
    assert all(p["server_state"]["reward_claimed"] is False for p in prompts)
    assert prompts[0]["rules"] != prompts[1]["rules"]
    assert first["artifact"]["evaluation"]["score"] is None
    assert first["evaluation_label"] == "미채점 / Unrated"
    continued = app.turn(session, {"condition": "base_minimal", "utterance": "다시 줘"})
    assert (
        continued["conditions"][0]["artifact"]["server_execution"]["approved"] is False
    )
    assert prompts[-1]["server_state"]["reward_claimed"] is True
    assert prompts[-1]["player_utterance"] == "다시 줘"
    assert set(prompts[-1]) == {
        "server_state",
        "player_utterance",
        "rules",
        "character_persona",
    }
    assert (
        app.describe(app.new_session())["conditions"][0]["state"]["reward_claimed"]
        is False
    )
    assert STATE["reward_claimed"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"target_count": 0},
        {"target_count": True},
        {"current_count": -1},
        {"current_count": 1, "reward_claimed": True},
        {"reward_claimed": "false"},
        {"quest_name": ""},
        {"reward_description": " "},
        {"current_count": 1.5},
        {"quest_name": "가" * 201},
        {"reward_description": "가" * 501},
        {"extra": "not a state field"},
    ],
)
def test_invalid_state_rejected_before_inference_and_keeps_session(change):
    def unexpected(prompt):
        pytest.fail("invalid state reached inference")

    app = ComparisonApp(offline=True, base_model=unexpected)
    session = app.new_session()
    before = app.describe(session)
    with pytest.raises(ValueError):
        app.compare(session, {"state": STATE | change, "utterance": "보상 줘"})
    assert app.describe(session) == before


@pytest.mark.parametrize("utterance", ["", " ", None, 3, "가" * 2001])
def test_invalid_utterance_rejected_before_inference(utterance):
    app = ComparisonApp(
        offline=True, base_model=lambda p: pytest.fail("inference called")
    )
    with pytest.raises(ValueError):
        app.compare(app.new_session(), {"state": STATE, "utterance": utterance})


def test_model_errors_preserve_raw_output_and_do_not_stop_other_conditions():
    outputs = iter(["```json\ninvalid\n```", RuntimeError("model unavailable")])

    def generate(prompt):
        output = next(outputs)
        if isinstance(output, Exception):
            raise output
        return output

    app = ComparisonApp(offline=True, base_model=generate)
    result = app.compare(app.new_session(), {"state": STATE, "utterance": "안녕"})
    first, second, *_ = result["conditions"]
    assert first["artifact"]["raw_output"] == "```json\ninvalid\n```"
    assert first["artifact"]["error"]["stage"] == "model_output"
    assert first["state"] == STATE
    assert second["artifact"]["error"]["stage"] == "inference"
    assert second["state"] == STATE
    assert second["artifact"]["evaluation"]["score"] is None


def test_checkpoint_readiness_and_distinct_runners(tmp_path):
    import json

    from quest_npc_lab.slices.interactive_ui.inference import ModelSettings

    checkpoint = tmp_path / "sft"
    checkpoint.mkdir()
    (checkpoint / "adapter_config.json").write_text("{}")
    (checkpoint / "adapter_model.safetensors").write_bytes(b"test fixture")
    seen = []

    def factory(settings, adapter):
        def generate(prompt):
            seen.append((adapter, json.loads(prompt)))
            return '{"action":"other","dialogue":"안녕하세요"}'

        return generate

    app = ComparisonApp(
        settings=ModelSettings(),
        sft_checkpoint=checkpoint,
        grpo_checkpoint=tmp_path / "missing",
        model_factory=factory,
    )
    result = app.compare(app.new_session(), {"state": STATE, "utterance": "안녕"})
    assert [c["status"] for c in result["conditions"]] == [
        "ready",
        "ready",
        "ready",
        "checkpoint_not_ready",
    ]
    assert [adapter for adapter, _ in seen] == [None, None, checkpoint]
    assert seen[1][1]["rules"] == seen[2][1]["rules"]
    assert result["conditions"][2]["model"]["checkpoint"] == str(checkpoint)
    assert result["conditions"][0]["model"]["do_sample"] is False
    assert result["conditions"][0]["model"]["revision"]
    offline = ComparisonApp(offline=True, sft_checkpoint=checkpoint)
    assert (
        offline.describe(offline.new_session())["conditions"][2]["status"]
        == "checkpoint_not_ready"
    )


@pytest.fixture
def http_app():
    from threading import Thread
    from quest_npc_lab.slices.interactive_ui.server import make_server

    server = make_server(ComparisonApp(offline=True), port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


def test_http_session_compare_and_error_responses(http_app):
    import json
    from http.cookiejar import CookieJar
    from urllib.error import HTTPError
    from urllib.request import build_opener, HTTPCookieProcessor, Request

    client = build_opener(HTTPCookieProcessor(CookieJar()))
    assert client.open(http_app + "/").headers["Content-Type"].startswith("text/html")
    initial = json.load(client.open(http_app + "/api/session"))
    assert len(initial["conditions"]) == 4
    response = client.open(
        Request(
            http_app + "/api/compare",
            data=json.dumps({"state": STATE, "utterance": "안녕하세요"}).encode(),
            headers={"Content-Type": "application/json"},
        )
    )
    assert (
        json.load(response)["conditions"][0]["artifact"]["parsed_output"]["action"]
        == "clarify"
    )
    assert json.load(client.open(http_app + "/api/session"))["conditions"][0][
        "artifact"
    ]
    other_client = build_opener(HTTPCookieProcessor(CookieJar()))
    assert (
        json.load(other_client.open(http_app + "/api/session"))["conditions"][0][
            "artifact"
        ]
        is None
    )
    for body in (b"{", b"[]", b"{}"):
        with pytest.raises(HTTPError) as caught:
            client.open(
                Request(
                    http_app + "/api/compare",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
            )
        assert caught.value.code == 400
        assert "error" in json.load(caught.value)
    with pytest.raises(HTTPError) as caught:
        client.open(
            Request(
                http_app + "/api/compare",
                data=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://example.com",
                },
            )
        )
    assert caught.value.code == 403
    with pytest.raises(HTTPError) as caught:
        client.open(http_app + "/../inference.py")
    assert caught.value.code == 404


@pytest.mark.parametrize("condition", ["missing", "sft_improved", "grpo_improved", []])
def test_unavailable_condition_cannot_run(condition):
    app = ComparisonApp(offline=True)
    session = app.new_session()
    before = app.describe(session)
    with pytest.raises(ValueError):
        app.turn(session, {"condition": condition, "utterance": "보상 줘"})
    assert app.describe(session) == before


def test_progress_beyond_target_and_single_condition_state_isolation():
    app = ComparisonApp(
        offline=True,
        base_model=lambda prompt: '{"action":"grant_reward","dialogue":"지급합니다."}',
    )
    session = app.new_session()
    app.compare(
        session, {"state": STATE | {"current_count": 8}, "utterance": "보상 줘"}
    )
    result = app.describe(session)
    assert result["conditions"][0]["state"]["reward_claimed"] is True
    assert result["conditions"][1]["state"]["reward_claimed"] is True
    fresh = app.new_session()
    result = app.turn(fresh, {"condition": "base_improved", "utterance": "보상 줘"})
    assert result["conditions"][0]["state"]["reward_claimed"] is False
    assert result["conditions"][1]["state"]["reward_claimed"] is True
    assert result["conditions"][0]["artifact"] is None


def test_http_turn_and_request_limits(http_app):
    import json
    from http.cookiejar import CookieJar
    from urllib.error import HTTPError
    from urllib.request import build_opener, HTTPCookieProcessor, Request

    client = build_opener(HTTPCookieProcessor(CookieJar()))
    url = http_app + "/api/turn"
    body = json.dumps({"condition": "base_minimal", "utterance": "안녕"}).encode()
    with pytest.raises(HTTPError) as caught:
        client.open(
            Request(url, data=body, headers={"Content-Type": "application/json"})
        )
    assert caught.value.code == 409
    client.open(http_app + "/api/session").close()
    result = json.load(
        client.open(
            Request(url, data=body, headers={"Content-Type": "application/json"})
        )
    )
    assert (
        result["conditions"][0]["artifact"]["request_input"]["player_utterance"]
        == "안녕"
    )
    assert result["conditions"][1]["artifact"] is None
    with pytest.raises(HTTPError) as caught:
        client.open(
            Request(
                url, data=b"x" * 32769, headers={"Content-Type": "application/json"}
            )
        )
    assert caught.value.code == 413
    with pytest.raises(HTTPError) as caught:
        client.open(Request(url, data=body))
    assert caught.value.code == 415
