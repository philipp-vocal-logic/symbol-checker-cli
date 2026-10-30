from __future__ import annotations

from symbol_checker.checker import check_project, check_source, discover_files
from symbol_checker.extractor import extract_symbols
from symbol_checker.schema import (
    Finding,
    Replacement,
    Symbol,
    SymbolKind,
    SymbolSchema,
    load_schema,
    matches_subwords,
    normalize_subwords,
    singularize,
    split_subwords,
)
from symbol_checker.validator import validate_schema

__all__ = [
    "Finding",
    "Replacement",
    "Symbol",
    "SymbolKind",
    "SymbolSchema",
    "check_project",
    "check_source",
    "discover_files",
    "extract_symbols",
    "load_schema",
    "matches_subwords",
    "normalize_subwords",
    "singularize",
    "split_subwords",
    "validate_schema",
]
