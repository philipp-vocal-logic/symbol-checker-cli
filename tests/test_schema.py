from __future__ import annotations

from pathlib import Path

import pytest

from symbol_checker.schema import (
    SymbolSchema,
    Term,
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
    assert normalize_subwords("ABCs_and_URLs") == ("abc", "and", "url")
    assert normalize_subwords("series_species_news_alias_bias_canvas") == (
        "series",
        "species",
        "news",
        "alias",
        "bias",
        "canvas",
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

[[terms]]
term = "load"
definition = "Read configuration from disk."
forbidden_terms = ["fetch"]
""",
        encoding="utf-8",
    )
    assert load_schema(config_file) == SymbolSchema(
        include=("src/**/*.py",),
        exclude=("src/generated/**",),
        forbidden_subwords=("data",),
        terms=(
            Term(
                term="load",
                definition="Read configuration from disk.",
                forbidden_terms=("fetch",),
            ),
        ),
        source_path=config_file,
    )


@pytest.mark.parametrize(
    ("toml_text", "error_match"),
    [
        ('[unknown_section]\nkey = "value"\n', "Unknown keys in root"),
        ('[settings]\ninclude = "src/**/*.py"\n', "Expected 'settings.include' to be a list"),
        ('[terms]\nterm = "load"\n', "Expected 'terms' to be an array"),
        (
            '[[terms]]\nterm = ["load"]\ndefinition = "Read."\n',
            "Expected 'terms.term' to be a string",
        ),
        (
            '[[terms]]\nterm = "load"\ndefinition = 42\n',
            "Expected 'terms.definition' to be a string",
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
            SymbolSchema(terms=(Term(term="", definition="Missing term name."),)),
            "empty term",
        ),
        (
            SymbolSchema(terms=(Term(term="load", definition=""),)),
            "empty definition",
        ),
        (
            SymbolSchema(
                terms=(Term(term="load", definition="Read file.", forbidden_terms=("",)),)
            ),
            "empty forbidden_term",
        ),
        (
            SymbolSchema(
                terms=(
                    Term(term="check", definition="First definition."),
                    Term(term="check", definition="Second definition."),
                )
            ),
            "Duplicate canonical term 'check'",
        ),
        (
            SymbolSchema(
                terms=(
                    Term(term="load", definition="Read file."),
                    Term(term="check", definition="Verify rules.", forbidden_terms=("load",)),
                )
            ),
            "Term 'load' collides with forbidden_term 'load'",
        ),
        (
            SymbolSchema(
                terms=(
                    Term(term="read_config_path", definition="Configuration path."),
                    Term(
                        term="load",
                        definition="Read file.",
                        forbidden_terms=("read_config",),
                    ),
                )
            ),
            "Term 'read_config_path' collides with forbidden_term 'read_config'",
        ),
        (
            SymbolSchema(
                terms=(
                    Term(term="load", definition="Read file.", forbidden_terms=("fetch",)),
                    Term(term="check", definition="Verify rules.", forbidden_terms=("fetch",)),
                )
            ),
            "Forbidden term 'fetch' in 'check' collides with 'fetch' in 'load'",
        ),
        (
            SymbolSchema(forbidden_subwords=("multi_word",)),
            "Invalid forbidden_subword 'multi_word'",
        ),
        (
            SymbolSchema(
                forbidden_subwords=("symbol",),
                terms=(Term(term="symbol_table", definition="Lookup table."),),
            ),
            "Canonical term 'symbol_table' collides with forbidden_subword 'symbol'",
        ),
        (
            SymbolSchema(
                terms=(
                    Term(term="check", definition="Verify rules.", forbidden_terms=("inspect",)),
                    Term(term="symbol", definition="Inspect a syntax tree node."),
                )
            ),
            "Definition of 'symbol' uses forbidden_term 'inspect'",
        ),
        (
            SymbolSchema(
                terms=(
                    Term(term="load", definition="Read configuration from disk."),
                    Term(term="parse", definition="Read configuration from disk."),
                )
            ),
            "Terms 'load' and 'parse' have identical definitions",
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
