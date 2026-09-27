"""Separate exploratory fifth condition, preserving the original four-condition run."""

import json
from pathlib import Path
import time

from .dpo_training import summarize
from .runtime import validate_source
from quest_npc_lab.slices.final_evaluation.final_evaluation import validate_records
from quest_npc_lab.slices.final_evaluation.runtime import validate_checkpoints
from quest_npc_lab.slices.evaluation_dataset.evaluation_dataset import (
    validate_eval_freeze,
)
from quest_npc_lab.slices.prompt_evaluation import format_prompt, load_manifest
from quest_npc_lab.slices.guild_receptionist import QuestState
from quest_npc_lab.slices.sft_training.runtime import (
    load_base,
    parameter_digest,
    sha256,
    snapshot,
    write_json,
)


def evaluate(source: Path, output: Path):
    import torch
    from peft import PeftModel
    from transformers import set_seed

    config = load_manifest()
    frozen = validate_eval_freeze()
    metadata, _, source_hashes = validate_source(source)
    training = json.loads((output / "training_report.json").read_text())
    if training["status"] != "passed" or training["source_hashes"] != source_hashes:
        raise ValueError("DPO training source identity mismatch")
    raw_path = source / "final_240_responses.jsonl"
    baseline_hash = sha256(raw_path)
    baseline = [json.loads(x) for x in raw_path.read_text().splitlines()]
    validate_records(baseline)
    checkpoints = validate_checkpoints(source)
    provenance = baseline[0]["provenance"]
    if (
        provenance["checkpoints"] != checkpoints
        or provenance["prompt_manifest_sha256"]
        != metadata["provenance"]["prompt_sha256"]
        or baseline[0]["dataset_sha256"] != frozen.dataset_sha256
        or baseline[0]["generation"] != config["generation"]
    ):
        raise ValueError("baseline provenance differs from frozen DPO comparison")
    templates = [r for r in baseline if r["condition"] == "sft_improved"]
    checkpoint = output / "dpo_checkpoint"
    for name, digest in training["checkpoint_files"].items():
        if sha256(checkpoint / name) != digest:
            raise ValueError("DPO checkpoint bytes changed")
    torch.set_num_threads(1)
    set_seed(42)
    base, tokenizer = load_base()
    model = PeftModel.from_pretrained(
        base, str(checkpoint), local_files_only=True
    ).eval()
    if parameter_digest(snapshot(model)) != training["adapter_parameter_sha256"]:
        raise ValueError("loaded DPO parameters differ")
    new = []
    started = time.monotonic()
    with (output / "dpo_60_responses.jsonl").open("x") as stream:
        for template in templates:
            prompt = format_prompt(
                QuestState(**template["state"]), template["player_utterance"]
            )
            messages = [
                {**m, "content": m["content"].format(formatted_prompt=prompt)}
                for m in config["chat_template"]["messages"]
            ]
            inputs = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            ).to("cuda")
            length = inputs["input_ids"].shape[1]
            if length > config["input_limits"]["max_input_tokens"]:
                raise ValueError("input too long; truncation forbidden")
            with torch.inference_mode():
                tokens = model.generate(
                    **inputs,
                    **config["generation"],
                    pad_token_id=tokenizer.eos_token_id,
                    use_cache=True,
                )
            row = {
                k: v
                for k, v in template.items()
                if k not in ("artifact", "raw_output", "provenance")
            }
            row.update(
                condition="dpo_improved",
                raw_output=tokenizer.decode(
                    tokens[0, length:].tolist(), skip_special_tokens=True
                ),
                provenance={
                    "dpo_adapter_parameter_sha256": training[
                        "adapter_parameter_sha256"
                    ],
                    "baseline_raw_sha256": baseline_hash,
                    "source_hashes": source_hashes,
                },
            )
            new.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            print(f"DPO evaluation {len(new)}/60", flush=True)
    if sha256(raw_path) != baseline_hash or validate_source(source)[2] != source_hashes:
        raise ValueError("comparison sources changed")
    report = recompute_comparison(source, output)
    report["seconds"] = time.monotonic() - started
    write_json(output / "comparison_report.json", report)
    return report


def recompute_comparison(source: Path, output: Path):
    baseline = [
        json.loads(x)
        for x in (source / "final_240_responses.jsonl").read_text().splitlines()
    ]
    validate_records(baseline)
    new = [
        json.loads(x)
        for x in (output / "dpo_60_responses.jsonl").read_text().splitlines()
    ]
    templates = {r["case_id"]: r for r in baseline if r["condition"] == "sft_improved"}
    if len(new) != 60 or {r["case_id"] for r in new} != set(templates):
        raise ValueError("expected exactly 60 matching DPO cases")
    training = json.loads((output / "training_report.json").read_text())
    if training["status"] != "passed":
        raise ValueError("DPO provenance requires successful training")
    expected_provenance = {
        "dpo_adapter_parameter_sha256": training["adapter_parameter_sha256"],
        "baseline_raw_sha256": sha256(source / "final_240_responses.jsonl"),
        "source_hashes": training["source_hashes"],
    }
    for row in new:
        if (
            row["condition"] != "dpo_improved"
            or row.get("provenance") != expected_provenance
        ):
            raise ValueError("DPO provenance differs from trained adapter or baseline")
        ref = templates[row["case_id"]]
        for field in (
            "state",
            "player_utterance",
            "ground_truth_action",
            "dataset_sha256",
            "generation",
            "seed",
            "rules",
            "character_persona",
        ):
            if row[field] != ref[field]:
                raise ValueError(f"comparison mismatch: {field}")
    conditions = {
        c: summarize([r for r in baseline if r["condition"] == c])
        for c in ("base_minimal", "base_improved", "sft_improved", "grpo_improved")
    }
    conditions["dpo_improved"] = summarize(new)
    return {
        "conditions": conditions,
        "dpo_raw_sha256": sha256(output / "dpo_60_responses.jsonl"),
        "baseline_raw_sha256": sha256(source / "final_240_responses.jsonl"),
        "limitations": [
            "Exploratory extension: evaluation set previously inspected.",
            "Offline pairs selected from evolving GRPO policies; not a controlled algorithm-only comparison.",
            "Rule-labelled action preferences, not human preferences or dialogue quality.",
            "One fixed seed; no hyperparameter or checkpoint selection.",
        ],
    }
