from __future__ import annotations

from pathlib import Path

import pytest

from symbol_checker.checker import check_project, check_source
from symbol_checker.cli import main
from symbol_checker.schema import Replacement, SymbolSchema


def _build_test_schema(source_path: Path = Path("symbols.toml")) -> SymbolSchema:
    return SymbolSchema(
        include=("src/**/*.py",),
        exclude=("src/ignored/**",),
        forbidden_subwords=("data",),
        replacements=(Replacement(canonical="load", forbidden=("fetch",)),),
        source_path=source_path,
    )


def test_check_source_reports_forbidden_subword() -> None:
    findings = check_source("user_data = 1\n", _build_test_schema(), file=Path("src/sample.py"))
    assert [finding.format_line() for finding in findings] == [
        "src/sample.py:1:1: Symbol 'user_data': "
        "Contains ambiguous forbidden subword 'data'. "
        "Suggestion: Replace 'data' with a specific domain noun."
    ]


def test_check_source_reports_forbidden_module_stem() -> None:
    findings = check_source("clean_name = 1\n", _build_test_schema(), file=Path("src/user_data.py"))
    assert [finding.format_line() for finding in findings] == [
        "src/user_data.py:1:1: Symbol 'user_data': "
        "Contains ambiguous forbidden subword 'data'. "
        "Suggestion: Replace 'data' with a specific domain noun."
    ]


def test_check_source_reports_replacement_finding() -> None:
    findings = check_source(
        "def fetch_schema() -> None:\n    pass\n",
        _build_test_schema(),
        file=Path("src/sample.py"),
    )
    assert [finding.format_line() for finding in findings] == [
        "src/sample.py:1:1: Symbol 'fetch_schema': "
        "Uses non-canonical 'fetch'. "
        "Suggestion: Use canonical 'load'."
    ]


def test_check_project_respects_include_exclude_and_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("src/gitignored/\n", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "clean.py").write_text("clean_name = 1\n", encoding="utf-8")

    gitignored_dir = src_dir / "gitignored"
    gitignored_dir.mkdir()
    (gitignored_dir / "bad.py").write_text("user_data = 1\n", encoding="utf-8")

    excluded_dir = src_dir / "ignored"
    excluded_dir.mkdir()
    (excluded_dir / "bad.py").write_text("user_data = 1\n", encoding="utf-8")

    schema = _build_test_schema(source_path=tmp_path / "symbols.toml")
    assert check_project(schema, root=tmp_path) == []


def test_check_project_reports_invalid_utf8_file(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "corrupt.py").write_bytes(b"\xff\xfe\x00\x00")

    schema = _build_test_schema(source_path=tmp_path / "symbols.toml")
    findings = check_project(schema, root=tmp_path)
    assert len(findings) == 1
    assert "Failed to read UTF-8 source file" in findings[0].message


def test_cli_main_returns_zero_when_clean(tmp_path: Path) -> None:
    config_path = tmp_path / "symbols.toml"
    config_path.write_text('[settings]\ninclude = ["src/**/*.py"]\n', encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "module.py").write_text("clean_name = 1\n", encoding="utf-8")

    assert main(["--config", str(config_path)]) == 0


def test_cli_main_returns_one_when_findings_exist(tmp_path: Path) -> None:
    config_path = tmp_path / "symbols.toml"
    config_path.write_text(
        '[settings]\ninclude = ["src/**/*.py"]\nforbidden_subwords = ["data"]\n',
        encoding="utf-8",
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "module.py").write_text("user_data = 1\n", encoding="utf-8")

    assert main(["--config", str(config_path)]) == 1


def test_cli_main_returns_two_when_config_missing(tmp_path: Path) -> None:
    assert main(["--config", str(tmp_path / "missing.toml")]) == 2


def test_cli_main_filters_to_positional_target_files(tmp_path: Path) -> None:
    config_path = tmp_path / "symbols.toml"
    config_path.write_text(
        '[settings]\ninclude = ["src/**/*.py"]\nforbidden_subwords = ["data"]\n',
        encoding="utf-8",
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    clean_file = src_dir / "clean.py"
    dirty_file = src_dir / "dirty.py"
    clean_file.write_text("clean_name = 1\n", encoding="utf-8")
    dirty_file.write_text("user_data = 1\n", encoding="utf-8")

    assert main(["--config", str(config_path), str(clean_file)]) == 0
    assert main(["--config", str(config_path), str(dirty_file)]) == 1


def test_cli_main_filters_to_target_directory(tmp_path: Path) -> None:
    config_path = tmp_path / "symbols.toml"
    config_path.write_text(
        '[settings]\ninclude = ["src/**/*.py", "tests/**/*.py"]\nforbidden_subwords = ["data"]\n',
        encoding="utf-8",
    )
    src_dir = tmp_path / "src"
    tests_dir = tmp_path / "tests"
    src_dir.mkdir()
    tests_dir.mkdir()
    (src_dir / "dirty.py").write_text("user_data = 1\n", encoding="utf-8")
    (tests_dir / "clean.py").write_text("clean_name = 1\n", encoding="utf-8")

    assert main(["tests/", "--config", str(config_path)]) == 0
    assert main(["src/", "--config", str(config_path)]) == 1


def test_check_source_deduplicates_repeated_subword_and_honors_ignore() -> None:
    schema = SymbolSchema(
        forbidden_subwords=("data",),
        allowed_symbols=("allowed_data",),
        replacements=(Replacement(canonical="load", forbidden=("fetch", "read_config")),),
    )
    findings = check_source(
        "data_to_data = 1\n"
        "ignored_data = 2  # symbol: ignore\n"
        "compact_data = 3  #symbol:ignore\n"
        'literal_marker = "# symbol: ignore"; unignored_data = 4\n'
        "fetch_data = 5  # symbol: ignore[data]\n"
        "allowed_data = 6\n"
        "read_config_path = 7  # symbol: ignore[readConfigs]\n",
        schema,
    )
    assert [(finding.symbol_name, finding.message) for finding in findings] == [
        ("data_to_data", "Contains ambiguous forbidden subword 'data'."),
        ("unignored_data", "Contains ambiguous forbidden subword 'data'."),
        ("fetch_data", "Uses non-canonical 'fetch'."),
    ]


def test_check_source_reports_empty_and_unused_ignore_comments() -> None:
    schema = SymbolSchema(
        forbidden_subwords=("data",),
        replacements=(Replacement(canonical="load", forbidden=("fetch",)),),
    )
    findings = check_source(
        "user_data = 1  # symbol: ignore[]\n"
        "clean_name = 2  # symbol: ignore\n"
        "fetch_record = 3  # symbol: ignore[load, typo]\n",
        schema,
    )
    assert [(finding.line, finding.symbol_name, finding.message) for finding in findings] == [
        (1, "user_data", "Contains ambiguous forbidden subword 'data'."),
        (1, None, "Empty 'symbol: ignore[]' comment specifies no targets."),
        (2, None, "Unused 'symbol: ignore' comment matched no findings."),
        (3, None, "Unused ignore target 'typo' in 'symbol: ignore' comment."),
    ]


def test_check_project_reports_finding_when_no_files_discovered(tmp_path: Path) -> None:
    config_path = tmp_path / "symbols.toml"
    config_path.write_text('[settings]\ninclude = ["nomatch/**/*.py"]\n', encoding="utf-8")

    assert main(["--config", str(config_path)]) == 1


def test_cli_main_reports_missing_or_unmatched_targets(tmp_path: Path) -> None:
    config_path = tmp_path / "symbols.toml"
    config_path.write_text('[settings]\ninclude = ["src/**/*.py"]\n', encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "clean.py").write_text("clean_name = 1\n", encoding="utf-8")
    outside_file = tmp_path / "outside.py"
    outside_file.write_text("clean_name = 1\n", encoding="utf-8")

    assert main(["--config", str(config_path), "missing.py"]) == 1
    assert main(["--config", str(config_path), str(outside_file)]) == 1


def test_cli_main_discovers_parent_config_from_subdirectory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "symbols.toml").write_text(
        '[settings]\ninclude = ["**/*.py"]\nforbidden_subwords = ["data"]\n',
        encoding="utf-8",
    )
    root_tests = tmp_path / "tests"
    root_tests.mkdir()
    (root_tests / "dirty.py").write_text("user_data = 1\n", encoding="utf-8")

    pkg_tests = tmp_path / "pkg" / "tests"
    pkg_tests.mkdir(parents=True)
    (pkg_tests / "clean.py").write_text("clean_name = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path / "pkg")

    assert main(["tests/"]) == 0
    assert main(["--config", "symbols.toml", "tests/"]) == 2
