"""Exercise sequential model factories at the external Transformers boundary."""

import sys
from pathlib import Path
from types import SimpleNamespace
import weakref

import pytest


@pytest.mark.parametrize("fail_first", [False, True])
def test_sequential_conditions_do_not_retain_previous_model(monkeypatch, fail_first):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from .inference import ModelSettings, local_generator

    live = weakref.WeakSet()

    class Batch(dict):
        def to(self, device):
            return self

    class Tokenizer:
        def apply_chat_template(self, *args, **kwargs):
            return Batch(input_ids=torch.tensor([[1]]))

        def decode(self, *args, **kwargs):
            return '{"action":"other","dialogue":"안녕하세요"}'

    class Model:
        device = "cpu"

        def __init__(self):
            self.cycle = self

        def to(self, device):
            return self

        def eval(self):
            return self

        def generate(self, **kwargs):
            nonlocal fail_first
            if fail_first:
                fail_first = False
                raise RuntimeError("injected generation failure")
            return torch.tensor([[1, 2]])

    def load(*args, **kwargs):
        assert not live, "previous condition still retains a loaded model"
        model = Model()
        live.add(model)
        return model

    monkeypatch.setattr(AutoModelForCausalLM, "from_pretrained", load)
    monkeypatch.setattr(AutoTokenizer, "from_pretrained", lambda *a, **kw: Tokenizer())
    monkeypatch.setitem(
        sys.modules,
        "peft",
        SimpleNamespace(
            PeftModel=SimpleNamespace(from_pretrained=lambda model, *a, **kw: model)
        ),
    )
    generators = [
        local_generator(ModelSettings(device="cpu"), adapter)
        for adapter in [None, Path("sft"), Path("grpo")]
    ]
    for generate in generators:
        try:
            assert "안녕하세요" in generate("hello")
        except RuntimeError as error:
            assert str(error) == "injected generation failure"
    assert not live
