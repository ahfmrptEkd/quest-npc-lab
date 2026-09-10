"""Run the fixed main SFT experiment or verify its preserved adapter."""

import argparse
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    checkpoint = args.artifacts_dir / "sft_checkpoint"
    report_path = args.artifacts_dir / "sft_training_report.json"
    if not args.verify_only and (checkpoint.exists() or report_path.exists()):
        print(
            "Refusing to overwrite an SFT run; use --verify-only or a new artifacts directory."
        )
        return 1
    from .runtime import run_training, reverify_checkpoint

    report = (
        reverify_checkpoint(args.artifacts_dir)
        if args.verify_only
        else run_training(args.artifacts_dir)
    )
    print(f"{report['status']}: {args.artifacts_dir}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
