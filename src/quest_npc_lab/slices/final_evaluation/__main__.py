"""Generate once, or rebuild metrics without loading models or checkpoints."""

import argparse
import json
from pathlib import Path

from .final_evaluation import RAW_NAME, REPORT_NAME, recompute_file, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recompute",
        action="store_true",
        help="Only read raw outputs; no inference or review reshuffling",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--checkpoint-dir", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--review-scores",
        type=Path,
        help="Aggregate completed human ratings separately",
    )
    args = parser.parse_args(argv)
    if args.review_scores:
        from .review import aggregate_review

        summary = aggregate_review(
            json.loads(args.review_scores.read_text(encoding="utf-8")),
            [
                json.loads(line)
                for line in (args.output_dir / RAW_NAME)
                .read_text(encoding="utf-8")
                .splitlines()
            ],
            json.loads(
                (args.output_dir / ".dialogue_review_48_key.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        write_json(args.output_dir / "dialogue_review_summary.json", summary)
        return 0
    if not args.recompute:
        from .runtime import run_generation

        run_generation(args.output_dir, args.checkpoint_dir)
    report = recompute_file(args.output_dir / RAW_NAME, args.output_dir / REPORT_NAME)
    print(
        json.dumps(
            {c: r["accuracy"] for c, r in report["conditions"].items()}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
