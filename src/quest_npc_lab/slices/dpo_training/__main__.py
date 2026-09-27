"""Run DPO once or independently recompute its comparison metrics."""

import argparse
import json
from pathlib import Path
from .evaluation import evaluate, recompute_comparison
from .runtime import train
from quest_npc_lab.slices.sft_training.runtime import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recompute", action="store_true")
    args = parser.parse_args()
    if args.recompute:
        report = recompute_comparison(args.source, args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    args.output.mkdir(parents=True, exist_ok=False)
    state = {"status": "running", "stage": "training"}
    try:
        train(args.source, args.output)
        state["stage"] = "evaluation"
        write_json(args.output / "run_status.json", state)
        report = evaluate(args.source, args.output)
        state.update(status="passed", stage="complete")
        print(json.dumps(report["conditions"], indent=2))
    except Exception as error:
        state.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        write_json(args.output / "run_status.json", state)


if __name__ == "__main__":
    main()
