"""Static publication with recomputed scores and an explicit artifact allowlist."""

import hashlib
import json
from pathlib import Path
import shutil

from quest_npc_lab.slices.final_evaluation.final_evaluation import (
    CONDITIONS,
    RAW_NAME,
    REPORT_NAME,
    recompute,
    score_raw,
    write_json,
)
from quest_npc_lab.slices.reaction_media import (
    LABELS,
    MEDIA_ROOT,
    reaction_media,
    reaction_state,
)

SLICE = Path(__file__).parent
SOURCE = SLICE.parent
PUBLIC_ARTIFACTS = (
    RAW_NAME,
    REPORT_NAME,
    "final_evaluation_run.json",
    "dialogue_review_48_blind.md",
    "dialogue_review_summary.json",
    "sft_checkpoint/training_metadata.json",
    "grpo_checkpoint/training_metadata.json",
)
PUBLIC_PROVENANCE = (
    "prompt_evaluation/prompt_manifest.json",
    "prompt_evaluation/prompt_manifest.sha256",
    "evaluation_dataset/data/eval_manifest.json",
    "dataset_pipeline/data/train_180_review_batches.json",
    "dataset_pipeline/data/val_60_review_batches.json",
    "reaction_media/media_manifest.json",
)


def build_pages(artifacts: Path, output: Path) -> Path:
    """Build into a new directory; never sweep arbitrary files into publication."""
    raw = (artifacts / RAW_NAME).read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    report = recompute(rows)
    report["raw_responses_sha256"] = hashlib.sha256(raw).hexdigest()
    if report != json.loads((artifacts / REPORT_NAME).read_text(encoding="utf-8")):
        raise ValueError("saved report differs from raw-output recomputation")
    cases = {}
    for row in rows:
        case = cases.setdefault(
            row["case_id"],
            {
                "id": row["case_id"],
                "state": row["state"],
                "utterance": row["player_utterance"],
                "expected": row["ground_truth_action"],
                "tags": row["shortcut_tags"],
                "responses": {},
            },
        )
        artifact = score_raw(row)
        reaction = reaction_media(reaction_state(artifact))
        reaction.update(image=reaction["image"].lstrip("/"), video=None)
        case["responses"][row["condition"]] = {
            "artifact": artifact,
            "reaction": reaction,
        }
    output.mkdir(parents=True, exist_ok=False)
    for name in ("index.html", "app.js", "style.css"):
        shutil.copyfile(SLICE / "pages" / name, output / name)
    (output / ".nojekyll").touch()
    for state in LABELS:
        destination = output / "media" / f"{state}.svg"
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(MEDIA_ROOT / destination.name, destination)
    for name in PUBLIC_ARTIFACTS:
        destination = output / "artifacts" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(artifacts / name, destination)
    links = {name: f"artifacts/{name}" for name in PUBLIC_ARTIFACTS}
    for name in PUBLIC_PROVENANCE:
        destination = output / "provenance" / Path(name).name
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(SOURCE / name, destination)
        links[destination.name] = f"provenance/{destination.name}"
    write_json(
        output / "results.json",
        {
            "mode": "saved_real_outputs",
            "conditions": list(CONDITIONS),
            "cases": sorted(cases.values(), key=lambda c: c["id"]),
            "report": report,
            "links": links,
        },
    )
    return output


def build_spaces(artifacts: Path, output: Path) -> Path:
    """Copy only runtime source, frozen configuration and portrait files."""
    config = {
        "pages_url": "https://ahfmrptEkd.github.io/quest-npc-lab/",
        "checkpoints": {
            name: json.loads(
                (artifacts / f"{name}_checkpoint/training_metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            for name in ("sft", "grpo")
        },
    }
    output.mkdir(parents=True, exist_ok=False)
    for name in ("app.py", "runtime.py", "requirements.txt", "README.md"):
        shutil.copyfile(SLICE / "spaces" / name, output / name)
    files = {
        "guild_receptionist": ("__init__.py", "receptionist_slice.py"),
        "interactive_ui": ("__init__.py", "interactive_ui.py", "inference.py"),
        "prompt_evaluation": (
            "__init__.py",
            "prompt_evaluation.py",
            "prompt_manifest.json",
            "prompt_manifest.sha256",
        ),
        "reaction_media": (
            "__init__.py",
            "media_manifest.json",
            *(f"{s}.svg" for s in LABELS),
        ),
    }
    for feature, names in files.items():
        directory = output / "quest_npc_lab/slices" / feature
        directory.mkdir(parents=True)
        for name in names:
            shutil.copyfile(SOURCE / feature / name, directory / name)
    for name in ("quest_npc_lab/__init__.py", "quest_npc_lab/slices/__init__.py"):
        (output / name).write_text(
            '"""Packaged Quest NPC Lab runtime."""\n', encoding="utf-8"
        )
    write_json(output / "deployment.json", config)
    return output
