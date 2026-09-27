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
    """Load only for this request; never retain another condition's model."""

    def generate(prompt: str) -> str:
        import gc
        import torch

        # A prior failed request may have kept cycles alive through its traceback.
        gc.collect()
        try:
            return _generate_once(settings, adapter, prompt)
        finally:
            # Model objects can contain cycles. Collect before loading another
            # condition so a full comparison cannot accumulate three models.
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    return generate


def _generate_once(settings: ModelSettings, adapter: Path | None, prompt: str) -> str:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(1)
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
    model = cast(
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

        model = PeftModel.from_pretrained(model, str(adapter), local_files_only=True)
    model.eval()
    inputs = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
    ).to(model.device)
    with torch.inference_mode():
        output = model.generate(
            **inputs, max_new_tokens=settings.max_new_tokens, do_sample=False
        )
    return tokenizer.decode(
        output[0, inputs["input_ids"].shape[1] :], skip_special_tokens=True
    )
