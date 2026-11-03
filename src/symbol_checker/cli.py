from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from symbol_checker.checker import check_project
from symbol_checker.schema import load_schema


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the symbol CLI entrypoint and return an integer exit code."""
    parser = argparse.ArgumentParser(
        prog="symbol",
        description="Validate symbol schema and check configured source files for findings.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Optional target files or directories to check.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("symbols.toml"),
        help="Path to the symbol schema configuration file (default: symbols.toml).",
    )
    args = parser.parse_args(argv)

    try:
        schema = load_schema(args.config)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        print(
            f"{args.config}:1:1: Failed to load symbol schema: {error}",
            file=sys.stderr,
        )
        return 2

    findings = check_project(schema, targets=tuple(args.files) or None)
    for finding in findings:
        print(finding.format_line())

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
