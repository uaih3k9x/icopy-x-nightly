#!/usr/bin/env python3
"""Compare two iCopy-X dump files."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SRC = PROJECT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lib import dump_diff  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two card dump files")
    parser.add_argument("file_a")
    parser.add_argument("file_b")
    parser.add_argument(
        "--type",
        choices=("auto", "mfc", "mfu", "binary"),
        default="auto",
        help="dump grouping mode",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--ranges",
        type=int,
        default=12,
        help="number of changed ranges to show in text output",
    )
    args = parser.parse_args()

    file_a = os.path.abspath(args.file_a)
    file_b = os.path.abspath(args.file_b)
    dtype = None if args.type == "auto" else args.type
    result = dump_diff.compare_files(file_a, file_b, dump_type=dtype)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(dump_diff.format_summary(result, detail_ranges=args.ranges))
        print("SHA A: %s" % result["sha256_a"])
        print("SHA B: %s" % result["sha256_b"])

    return 0 if result.get("equal") else 1


if __name__ == "__main__":
    raise SystemExit(main())

