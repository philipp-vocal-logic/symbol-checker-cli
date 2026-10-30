from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import archcheck
from glossary_checker_cli.checker import check
from glossary_checker_cli.core import load_glossary

from symbol_checker.checker import check_project
from symbol_checker.schema import load_schema

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_project_adheres_to_own_glossary() -> None:
    glossary = load_glossary(REPO_ROOT / "glossary.toml")
    assert check(glossary) == []


def test_project_adheres_to_own_symbol_schema() -> None:
    schema = load_schema(REPO_ROOT / "symbols.toml")
    assert check_project(schema, root=REPO_ROOT) == []


def test_project_adheres_to_own_architecture() -> None:
    assert archcheck.main(["--config", str(REPO_ROOT / "arch.toml")]) == 0


def test_project_passes_ruff_check() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_project_passes_ruff_format() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
