"""Lazy, local Transformers/PEFT inference; no paid services or fallback outputs."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from collections.abc import Callable


@dataclass(frozen=True)
class ModelSettings:
    model_id: str = "Qwen/Qwen2.5-0.5B-Instruct"
    revision: str = "7ae557604adf67be50417f59c2c2f167def9a775"
    device: str = "auto"
    max_new_tokens: int = 128
    do_sample: bool = False

    def __post_init__(self):
        if self.max_new_tokens < 1 or self.do_sample:
            raise ValueError("use a positive token limit and greedy decoding")


def checkpoint_ready(path: Path | None) -> bool:
    return (
        path is not None
        and (path / "adapter_config.json").is_file()
        and any(
            (path / name).is_file()
            for name in ("adapter_model.safetensors", "adapter_model.bin")
        )
    )


def local_generator(
    settings: ModelSettings, adapter: Path | None
) -> Callable[[str], str]:
    """Load on first request. A failed load never substitutes the base model."""
    # Auto factories select runtime-specific classes with different typed overloads.
    model: Any = None
    tokenizer: Any = None

    def generate(prompt: str) -> str:
        nonlocal model, tokenizer
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if model is None:
            device = settings.device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            tokenizer = cast(
                Any,
                AutoTokenizer.from_pretrained(
                    settings.model_id,
                    revision=settings.revision,
                    local_files_only=True,
                ),
            )
            loaded = cast(
                Any,
                AutoModelForCausalLM.from_pretrained(
                    settings.model_id,
                    revision=settings.revision,
                    local_files_only=True,
                    dtype=torch.float32,
                ),
            ).to(device)
            if adapter is not None:
                from peft import PeftModel

                loaded = PeftModel.from_pretrained(
                    loaded, str(adapter), local_files_only=True
                )
            loaded.eval()
            model = loaded
        inputs = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        ).to(model.device)
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=settings.max_new_tokens,
                do_sample=False,
            )
        return tokenizer.decode(
            output[0, inputs["input_ids"].shape[1] :], skip_special_tokens=True
        )

    return generate
