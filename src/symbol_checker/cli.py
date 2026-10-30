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
        default=None,
        help="Path to the symbol schema configuration file (default: symbols.toml).",
    )
    args = parser.parse_args(argv)

    config_path = _resolve_config_path(args.config)
    try:
        schema = load_schema(config_path)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        print(
            f"{config_path}:1:1: Failed to load symbol schema: {error}",
            file=sys.stderr,
        )
        return 2

    findings = check_project(schema, targets=tuple(args.files) or None)
    for finding in findings:
        print(finding.format_line())

    return 1 if findings else 0


def _resolve_config_path(config_path: Path | None) -> Path:
    if config_path is not None:
        return config_path
    cwd = Path.cwd().resolve()
    for directory in (cwd, *cwd.parents):
        candidate = directory / "symbols.toml"
        if candidate.is_file():
            return candidate
    return Path("symbols.toml")


if __name__ == "__main__":
    raise SystemExit(main())
