from __future__ import annotations

from pathlib import Path

import pytest

from symbol_checker.extractor import extract_symbols


@pytest.mark.parametrize(
    ("source_code", "expected_names"),
    [
        (
            "import os as os_alias\nfrom pathlib import Path as path_alias",
            ["os_alias", "path_alias"],
        ),
        (
            "type EntryList[EntryType] = list[EntryType]",
            ["EntryList", "EntryType"],
        ),
        (
            "MAX_RETRIES = 3\nfirst_const = second_const = 4",
            ["MAX_RETRIES", "first_const", "second_const"],
        ),
        (
            "class SampleProcessor:\n"
            "    field_name: str\n"
            "    def __init__(self, count: int, *extra: str, **options: int) -> None:\n"
            "        self.instance_attr = count\n",
            ["SampleProcessor", "field_name", "count", "extra", "options", "instance_attr"],
        ),
        (
            "for entry_name, *remaining_names in pairs:\n    pass",
            ["entry_name", "remaining_names"],
        ),
        (
            "async def load_records(source_path: str) -> None:\n"
            "    transform_fn = lambda raw_text: raw_text",
            ["load_records", "source_path", "transform_fn", "raw_text"],
        ),
        (
            "if (walrus_count := 1) > 0:\n"
            "    result_list = [comp_entry for comp_entry in range(walrus_count)]",
            ["walrus_count", "result_list", "comp_entry"],
        ),
        (
            "try:\n"
            "    with open('file') as (left_handle, right_handle):\n"
            "        pass\n"
            "except OSError as captured_error:\n"
            "    pass",
            ["left_handle", "right_handle", "captured_error"],
        ),
        (
            "match subject:\n"
            "    case str(matched_text) as matched_alias:\n"
            "        pass\n"
            "    case [first_element, *rest_elements]:\n"
            "        pass",
            ["matched_alias", "matched_text", "first_element", "rest_elements"],
        ),
    ],
)
def test_extract_symbols_from_syntax(source_code: str, expected_names: list[str]) -> None:
    symbols, findings = extract_symbols(source_code, file=Path("sample.py"))
    assert not findings
    assert [symbol.name for symbol in symbols] == ["sample", *expected_names]


def test_extract_symbols_records_ast_symbol_kinds() -> None:
    source_code = (
        "import os as os_alias\n"
        "type RecordList[RecordType] = list[RecordType]\n"
        "class SampleProcessor:\n"
        "    def load_entry(self, count: int) -> None:\n"
        "        self.instance_attr = count\n"
        "        try:\n"
        "            local_name = 1\n"
        "        except OSError as captured_error:\n"
        "            pass\n"
    )
    symbols, findings = extract_symbols(source_code, file=Path("sample.py"))
    assert not findings
    assert [(symbol.name, symbol.kind) for symbol in symbols] == [
        ("sample", "module"),
        ("os_alias", "alias"),
        ("RecordList", "variable"),
        ("RecordType", "typevar"),
        ("SampleProcessor", "class"),
        ("load_entry", "function"),
        ("count", "parameter"),
        ("instance_attr", "attribute"),
        ("local_name", "variable"),
        ("captured_error", "exception"),
    ]


def test_extract_symbols_skips_module_stem_for_memory_and_dunder() -> None:
    memory_symbols, _ = extract_symbols("entry = 1\n", file=Path("<memory>"))
    dunder_symbols, _ = extract_symbols("entry = 1\n", file=Path("__init__.py"))
    pkg_symbols, _ = extract_symbols("entry = 1\n", file=Path("src/pkg_name/__init__.py"))
    assert [symbol.name for symbol in memory_symbols] == ["entry"]
    assert [symbol.name for symbol in dunder_symbols] == ["entry"]
    assert [symbol.name for symbol in pkg_symbols] == ["pkg_name", "entry"]


def test_extract_symbols_deduplicates_within_same_scope() -> None:
    symbols, findings = extract_symbols("repeated_name = 1\nrepeated_name = 2\n")
    assert not findings
    assert [symbol.name for symbol in symbols] == ["repeated_name"]


def test_extract_symbols_reports_syntax_error() -> None:
    symbols, findings = extract_symbols("def load_broken(:\n    pass\n", file=Path("broken.py"))
    assert not symbols
    assert len(findings) == 1
    assert findings[0].line == 1
    assert "Syntax error" in findings[0].message
