"""Run the fixed, bounded CUDA GRPO experiment."""

import argparse
import json
from pathlib import Path


def main(argv=None) -> int:
    from .runtime import run_training

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="sample four groups without updates in a separate output directory",
    )
    args = parser.parse_args(argv)
    try:
        report = run_training(args.artifacts_dir, preflight=args.preflight)
    except (ValueError, FileExistsError) as error:
        print(str(error))
        return 1
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("status", "step_count", "error")
                if key in report
            }
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
