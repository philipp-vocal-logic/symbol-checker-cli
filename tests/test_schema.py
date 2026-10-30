from __future__ import annotations

from pathlib import Path

import pytest

from symbol_checker.schema import (
    Replacement,
    SymbolSchema,
    load_schema,
    matches_subwords,
    normalize_subwords,
    split_subwords,
)
from symbol_checker.validator import validate_schema


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("SymbolSchema", ("symbol", "schema")),
        ("load_schema_v2", ("load", "schema", "v", "2")),
        ("UPPER_SNAKE_CASE", ("upper", "snake", "case")),
        ("HTTPResponseCode", ("http", "response", "code")),
        ("ABCs", ("abcs",)),
        ("parseURLs", ("parse", "urls")),
    ],
)
def test_split_subwords(identifier: str, expected: tuple[str, ...]) -> None:
    assert split_subwords(identifier) == expected


def test_normalize_subwords_singularizes_plurals_and_preserves_invariants() -> None:
    assert normalize_subwords("entries_and_boxes") == ("entry", "and", "box")
    assert normalize_subwords("ABCs_and_URLs_and_IDs") == ("abc", "and", "url", "and", "id")
    assert normalize_subwords("caches_statuses_movies_cookies_axes_analyses_buses_gases") == (
        "cache",
        "status",
        "movie",
        "cookie",
        "axis",
        "analysis",
        "bus",
        "gas",
    )
    assert normalize_subwords("series_species_news_alias_bias_canvas_lenses") == (
        "series",
        "species",
        "news",
        "alias",
        "bias",
        "canvas",
        "lens",
    )


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (("project", "schema"), True),
        (("schema", "project"), False),
        ((), False),
    ],
)
def test_matches_subwords(target: tuple[str, ...], expected: bool) -> None:
    assert matches_subwords(("load", "project", "schema"), target) is expected


def test_load_schema_parses_toml_configuration(tmp_path: Path) -> None:
    config_file = tmp_path / "symbols.toml"
    config_file.write_text(
        """
[settings]
include = ["src/**/*.py"]
exclude = ["src/generated/**"]
forbidden_subwords = ["data"]

[replacements]
load = ["fetch"]
""",
        encoding="utf-8",
    )
    assert load_schema(config_file) == SymbolSchema(
        include=("src/**/*.py",),
        exclude=("src/generated/**",),
        forbidden_subwords=("data",),
        replacements=(Replacement(canonical="load", forbidden=("fetch",)),),
        source_path=config_file,
    )


@pytest.mark.parametrize(
    ("toml_text", "error_match"),
    [
        ('[unknown_section]\nkey = "value"\n', "Unknown keys in root"),
        ('[settings]\ninclude = "src/**/*.py"\n', "Expected 'settings.include' to be a list"),
        ('replacements = ["load"]\n', "Expected 'replacements' to be a TOML table"),
        (
            '[replacements]\nload = "fetch"\n',
            "Expected 'replacements.load' to be a list of strings",
        ),
        (
            "[replacements]\nload = [42]\n",
            "Expected 'replacements.load' to be a list of strings",
        ),
    ],
)
def test_load_schema_rejects_invalid_toml(
    tmp_path: Path,
    toml_text: str,
    error_match: str,
) -> None:
    config_file = tmp_path / "symbols.toml"
    config_file.write_text(toml_text, encoding="utf-8")
    with pytest.raises(ValueError, match=error_match):
        load_schema(config_file)


@pytest.mark.parametrize(
    ("schema", "expected_message"),
    [
        (
            SymbolSchema(replacements=(Replacement(canonical="", forbidden=("fetch",)),)),
            "empty replacement key",
        ),
        (
            SymbolSchema(replacements=(Replacement(canonical="load", forbidden=("",)),)),
            "empty forbidden entry",
        ),
        (
            SymbolSchema(
                replacements=(
                    Replacement(canonical="check", forbidden=("lint",)),
                    Replacement(canonical="checks", forbidden=("scan",)),
                )
            ),
            "Duplicate canonical replacement 'checks'",
        ),
        (
            SymbolSchema(
                replacements=(
                    Replacement(canonical="load", forbidden=("fetch",)),
                    Replacement(canonical="check", forbidden=("load",)),
                )
            ),
            "Replacement 'load' collides with forbidden entry 'load'",
        ),
        (
            SymbolSchema(
                replacements=(
                    Replacement(canonical="read_config_path", forbidden=("cfg_path",)),
                    Replacement(canonical="load", forbidden=("read_config",)),
                )
            ),
            "Replacement 'read_config_path' collides with forbidden entry 'read_config'",
        ),
        (
            SymbolSchema(
                replacements=(
                    Replacement(canonical="load", forbidden=("fetch",)),
                    Replacement(canonical="check", forbidden=("fetch",)),
                )
            ),
            "Forbidden entry 'fetch' in 'check' collides with 'fetch' in 'load'",
        ),
        (
            SymbolSchema(forbidden_subwords=("multi_word",)),
            "Invalid forbidden_subword 'multi_word'",
        ),
        (
            SymbolSchema(
                forbidden_subwords=("symbol",),
                replacements=(Replacement(canonical="symbol_table", forbidden=("sym_tbl",)),),
            ),
            "Canonical replacement 'symbol_table' collides with forbidden_subword 'symbol'",
        ),
        (
            SymbolSchema(
                replacements=(
                    Replacement(canonical="load", forbidden=("fetch",)),
                    Replacement(canonical="check", forbidden=("load_all",)),
                )
            ),
            "Replacement 'load' collides with forbidden entry 'load_all'",
        ),
        (
            SymbolSchema(
                forbidden_subwords=("obj",),
                replacements=(Replacement(canonical="matcher", forbidden=("filter_obj",)),),
            ),
            "Forbidden entry 'filter_obj' in 'matcher' collides with forbidden_subword 'obj'",
        ),
    ],
)
def test_validate_schema_reports_single_finding(
    schema: SymbolSchema,
    expected_message: str,
) -> None:
    findings = validate_schema(schema)
    assert len(findings) == 1
    assert expected_message in findings[0].message
