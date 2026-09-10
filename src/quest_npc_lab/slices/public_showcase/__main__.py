"""Build a new Pages or Spaces directory without publishing or loading weights."""

import argparse
from pathlib import Path

from . import build_pages, build_spaces


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("pages", "spaces"))
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or Path(__file__).parent / "build" / args.target
    builder = build_pages if args.target == "pages" else build_spaces
    print(builder(args.artifacts, output))


if __name__ == "__main__":
    main()
