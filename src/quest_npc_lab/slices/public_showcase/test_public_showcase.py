"""Public build outputs and final-artifact integration boundaries."""

import json
from pathlib import Path
from typing import Any
import pytest

from quest_npc_lab.slices.public_showcase import build_pages

ROOT = Path(__file__).resolve().parents[4]
ARTIFACTS = ROOT / "artifacts"


def test_pages_contains_all_real_outputs_and_recomputed_results(tmp_path):
    build_pages(ARTIFACTS, tmp_path / "pages")
    output = tmp_path / "pages"
    data = json.loads((output / "results.json").read_text())
    assert data["mode"] == "saved_real_outputs"
    assert len(data["cases"]) == 60
    assert sum(len(c["responses"]) for c in data["cases"]) == 240
    report = data["report"]
    assert [report["conditions"][c]["correct"] for c in data["conditions"]] == [
        0,
        0,
        16,
        19,
    ]
    assert [report["conditions"][c]["format_errors"] for c in data["conditions"]] == [
        60,
        60,
        0,
        0,
    ]
    assert (output / "artifacts/final_240_responses.jsonl").read_bytes() == (
        ARTIFACTS / "final_240_responses.jsonl"
    ).read_bytes()
    first = data["cases"][0]["responses"]["base_minimal"]
    assert first["artifact"]["error"]["stage"] == "model_output"
    assert first["reaction"]["state"] == "default"
    assert (output / first["reaction"]["image"]).is_file()
    assert (output / "index.html").is_file()


def test_pages_links_reports_freezes_and_licensed_portraits_only(tmp_path):
    output = build_pages(ARTIFACTS, tmp_path / "pages")
    data = json.loads((output / "results.json").read_text())
    links = data["links"]
    assert "artifacts/dialogue_review_48_blind.md" in links.values()
    assert "artifacts/dialogue_review_summary.json" in links.values()
    assert "provenance/prompt_manifest.json" in links.values()
    assert "provenance/eval_manifest.json" in links.values()
    for path in links.values():
        assert (output / path).is_file()
    assert len(list((output / "media").glob("*.svg"))) == 4
    manifest = json.loads((output / "provenance/media_manifest.json").read_text())
    assert {a["license"] for a in manifest["assets"].values()} == {"CC0-1.0"}
    assert data["report"]["provenance"]["provenance_warnings"]
    assert not list(output.rglob(".dialogue_review_48_key.json"))
    assert not list(output.rglob("*.safetensors"))


def test_pages_rejects_stale_report_before_publishing(tmp_path):
    import shutil

    source = tmp_path / "artifacts"
    source.mkdir()
    shutil.copyfile(
        ARTIFACTS / "final_240_responses.jsonl", source / "final_240_responses.jsonl"
    )
    (source / "final_evaluation_report.json").write_text("{}")
    with pytest.raises(ValueError, match="report differs"):
        build_pages(source, tmp_path / "pages")
    assert not (tmp_path / "pages").exists()


def test_local_comparison_uses_frozen_final_prompts_and_portraits(tmp_path):
    from quest_npc_lab.slices.interactive_ui import ComparisonApp
    from quest_npc_lab.slices.prompt_evaluation import format_prompt, load_manifest
    from quest_npc_lab.slices.guild_receptionist import QuestState

    # Model callbacks stand in only for inference, never for server approval.
    prompts = []

    def factory(settings, adapter):
        def generate(prompt):
            prompts.append(prompt)
            return '{"action":"grant_reward","dialogue":"보상입니다."}'

        return generate

    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}")
    (adapter / "adapter_model.safetensors").write_bytes(b"test double")
    app = ComparisonApp(
        model_factory=factory, sft_checkpoint=adapter, grpo_checkpoint=adapter
    )
    state: dict[str, Any] = dict(
        quest_name="토벌",
        target_count=5,
        current_count=5,
        reward_description="금화",
        reward_claimed=False,
    )
    result = app.compare(app.new_session(), {"state": state, "utterance": "보상 줘"})
    assert prompts == [
        format_prompt(QuestState(**state), "보상 줘", baseline=b)
        for b in ("minimal", "improved", "improved", "improved")
    ]
    assert all(c["model"]["max_new_tokens"] == 128 for c in result["conditions"])
    assert result["conditions"][1]["model"]["prompt_id"] == load_manifest()["version"]
    assert all(c["reaction"]["state"] == "smiling" for c in result["conditions"])
    assert all(
        c["artifact"]["evaluation"]["score"] is None for c in result["conditions"]
    )


def test_spaces_bundle_is_standalone_pinned_and_contains_no_weights(tmp_path):
    import subprocess
    import sys
    from quest_npc_lab.slices.public_showcase import build_spaces

    output = build_spaces(ARTIFACTS, tmp_path / "spaces")
    readme = (output / "README.md").read_text()
    import yaml

    metadata = yaml.safe_load(readme.split("---")[1])
    assert metadata["sdk"] == "gradio"
    assert metadata["app_file"] == "app.py"
    assert metadata["python_version"] == "3.12"
    assert (
        f"gradio=={metadata['sdk_version']}"
        in (output / "requirements.txt").read_text()
    )
    assert "ZeroGPU" in readme and "not verified" in readme
    assert not list(output.rglob("*.safetensors"))
    assert not list(output.rglob("test_*.py"))
    assert not list(output.rglob(".env*"))
    config = json.loads((output / "deployment.json").read_text())
    assert config["pages_url"] == "https://ahfmrptEkd.github.io/quest-npc-lab/"
    assert (
        config["checkpoints"]["grpo"]["checkpoint_files"]["adapter_model.safetensors"]
        == "984d4c4daa397d01beeccc9ab4070f7b553e9433a08279b6147a20d69db6295f"
    )
    # Import the copied runtime outside this checkout, without inference libraries.
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "from quest_npc_lab.slices.interactive_ui import ComparisonApp; a=ComparisonApp(offline=True); assert len(a.describe(a.new_session())['conditions']) == 4",
        ],
        cwd=output,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_spaces_live_requests_preserve_isolated_state_and_errors():
    from quest_npc_lab.slices.public_showcase.spaces.runtime import interact
    from quest_npc_lab.slices.interactive_ui.interactive_ui import CONDITIONS

    prompts = []

    def generate(prompt):
        prompts.append(json.loads(prompt))
        return '{"action":"grant_reward","dialogue":"지급합니다."}'

    models = {key: generate for key, _ in CONDITIONS}
    state: dict[str, Any] = dict(
        quest_name="토벌",
        target_count=5,
        current_count=5,
        reward_description="금화",
        reward_claimed=False,
    )
    result = interact(models, None, state, "보상 줘", "compare")
    assert all(c["reaction"]["state"] == "smiling" for c in result["conditions"])
    assert all(p["server_state"]["reward_claimed"] is False for p in prompts)
    continued = interact(models, result, state, "다시 줘", "grpo_improved")
    assert (
        continued["conditions"][3]["artifact"]["server_execution"]["approved"] is False
    )
    assert continued["conditions"][3]["reaction"]["state"] != "smiling"
    assert continued["conditions"][0] == result["conditions"][0]
    assert continued["conditions"][3]["artifact"]["evaluation"]["score"] is None
    assert (
        interact(models, None, state, "보상 줘", "compare")["conditions"][0][
            "reaction"
        ]["state"]
        == "smiling"
    )
    before = len(prompts)
    with pytest.raises(ValueError):
        interact(models, None, state | {"target_count": 0}, "보상 줘", "compare")
    assert len(prompts) == before
    with pytest.raises(ValueError, match="Compare once"):
        interact(models, None, state, "보상 줘", "grpo_improved")


def test_spaces_rejects_wrong_adapter_bytes(tmp_path):
    from quest_npc_lab.slices.public_showcase.spaces.runtime import verify_adapter

    metadata = json.loads(
        (ARTIFACTS / "sft_checkpoint/training_metadata.json").read_text()
    )
    (tmp_path / "adapter_config.json").write_text("{}")
    with pytest.raises(ValueError, match="differs from final"):
        verify_adapter(tmp_path, metadata)


def test_spaces_displays_final_checkpoint_identity_for_loaded_conditions():
    from quest_npc_lab.slices.public_showcase.spaces.runtime import interact

    metadata = {
        name: json.loads(
            (ARTIFACTS / f"{name}_checkpoint/training_metadata.json").read_text()
        )
        for name in ("sft", "grpo")
    }

    def generate(prompt):
        return '{"action":"other","dialogue":"안녕하세요."}'

    state = dict(
        quest_name="토벌",
        target_count=5,
        current_count=0,
        reward_description="금화",
        reward_claimed=False,
    )
    result = interact(
        {"base_minimal": generate, "base_improved": generate, "sft_improved": generate},
        None,
        state,
        "안녕",
        "compare",
        checkpoint_metadata=metadata,
    )
    assert result["conditions"][2]["model"]["checkpoint"] == metadata["sft"]
    assert result["conditions"][3]["model"]["checkpoint"] is None
