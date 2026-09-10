"""Spaces startup loading and session-scoped live inference; no saved responses."""

import hashlib
from pathlib import Path
import re
from typing import Any, cast

from quest_npc_lab.slices.guild_receptionist import QuestState
from quest_npc_lab.slices.interactive_ui import ComparisonApp
from quest_npc_lab.slices.interactive_ui.interactive_ui import Session
from quest_npc_lab.slices.prompt_evaluation import load_manifest


def verify_adapter(directory: Path, metadata: dict[str, Any]) -> Path:
    for name in ("adapter_config.json", "adapter_model.safetensors"):
        if (
            hashlib.sha256((directory / name).read_bytes()).hexdigest()
            != metadata["checkpoint_files"][name]
        ):
            raise ValueError("adapter differs from final evaluation checkpoint")
    return directory


def load_models(
    config: dict[str, Any], environ: dict[str, str]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Load at startup, before @spaces.GPU requests (ZeroGPU CUDA emulation)."""
    import torch
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    manifest = load_manifest()
    device = environ.get("QUEST_DEVICE", "cuda" if environ.get("SPACE_ID") else "auto")
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(1)
    tokenizer: Any = AutoTokenizer.from_pretrained(
        manifest["model_name"], revision=manifest["model_revision"]
    )
    models, unavailable = {}, {}

    def runner(adapter=None):
        model: Any = AutoModelForCausalLM.from_pretrained(
            manifest["model_name"],
            revision=manifest["model_revision"],
            dtype=torch.float32,
        )
        if adapter is not None:
            model = PeftModel.from_pretrained(
                model, str(adapter), local_files_only=True, is_trainable=False
            )
        model = model.to(device).eval()

        def generate(prompt):
            messages = [
                {**m, "content": m["content"].format(formatted_prompt=prompt)}
                for m in manifest["chat_template"]["messages"]
            ]
            inputs = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            ).to(device)
            length = inputs["input_ids"].shape[1]
            if length > manifest["input_limits"]["max_input_tokens"]:
                raise ValueError(
                    "input exceeds frozen token limit; truncation forbidden"
                )
            with torch.inference_mode():
                tokens = model.generate(
                    **inputs,
                    **manifest["generation"],
                    pad_token_id=tokenizer.eos_token_id,
                    use_cache=True,
                )
            return tokenizer.decode(
                tokens[0, length:].tolist(), skip_special_tokens=True
            )

        return generate

    base = runner()
    models.update(base_minimal=base, base_improved=base)
    for name in ("sft", "grpo"):
        key = f"{name}_improved"
        repo, revision = (
            environ.get(f"{name.upper()}_REPO_ID"),
            environ.get(f"{name.upper()}_REVISION"),
        )
        local = environ.get(f"{name.upper()}_CHECKPOINT")
        if not local and not repo:
            unavailable[key] = (
                "Final adapter not configured; no substitute model is used."
            )
            continue
        if local:
            directory = Path(local)
        else:
            if not revision or not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise ValueError(
                    f"{name.upper()}_REVISION must be an immutable Hub commit SHA"
                )
            directory = Path(
                snapshot_download(
                    cast(str, repo),
                    revision=revision,
                    allow_patterns=["adapter_config.json", "adapter_model.safetensors"],
                )
            )
        models[key] = runner(verify_adapter(directory, config["checkpoints"][name]))
    return models, unavailable


def interact(
    models: dict[str, Any],
    previous: dict[str, Any] | None,
    state: dict[str, Any],
    utterance: str,
    condition: str,
    *,
    checkpoint_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Carry only trusted per-session state across requests and GPU worker forks."""
    app = ComparisonApp(base_model=models["base_minimal"])
    app.models = dict(models)
    session_id = app.new_session()
    if condition == "compare":
        result = app.compare(session_id, {"state": state, "utterance": utterance})
    else:
        if not previous:
            raise ValueError("Compare once before continuing a condition.")
        app.sessions[session_id] = Session(
            states={c["id"]: QuestState(**c["state"]) for c in previous["conditions"]},
            artifacts={
                c["id"]: c["artifact"] for c in previous["conditions"] if c["artifact"]
            },
        )
        result = app.turn(session_id, {"condition": condition, "utterance": utterance})
    for item in result["conditions"]:
        name = item["id"].split("_")[0]
        if checkpoint_metadata and item["id"] in models and name in checkpoint_metadata:
            item["model"]["checkpoint"] = checkpoint_metadata[name]
    return result
