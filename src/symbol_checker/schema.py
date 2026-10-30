from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

SUBWORD_PATTERN = re.compile(
    r"[A-Z]{2,}s(?=[A-Z][a-z]|\d|_|\b)|[A-Z]+(?=[A-Z][a-z]|\d|_|\b)|[A-Z]?[a-z]+|\d+"
)
INVARIANT_SINGULARS: frozenset[str] = frozenset(
    {"alias", "bias", "canvas", "news", "series", "species"}
)

ALLOWED_ROOT_KEYS: frozenset[str] = frozenset({"settings", "terms"})
ALLOWED_SETTINGS_KEYS: frozenset[str] = frozenset(
    {"include", "exclude", "forbidden_subwords", "allowed_symbols"}
)
ALLOWED_TERM_KEYS: frozenset[str] = frozenset({"term", "definition", "forbidden_terms"})


@dataclass(frozen=True, slots=True)
class Term:
    """An approved domain term with its unambiguous definition and disallowed synonyms."""

    term: str
    definition: str
    forbidden_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Symbol:
    """A named code identifier extracted from a source file syntax tree."""

    name: str
    file: Path
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class Finding:
    """A deterministic problem reported during schema validation or symbol checking."""

    file: Path
    line: int
    column: int
    message: str
    suggestion: str
    symbol_name: str | None = None

    def format_line(self) -> str:
        """Format the finding as a single noise-free diagnostic line."""
        location = f"{self.file}:{self.line}:{self.column}"
        if self.symbol_name is not None:
            return (
                f"{location}: Symbol '{self.symbol_name}': "
                f"{self.message} Suggestion: {self.suggestion}"
            )
        return f"{location}: {self.message} Suggestion: {self.suggestion}"


@dataclass(frozen=True, slots=True)
class SymbolSchema:
    """The configured collection of forbidden subwords and canonical terms."""

    include: tuple[str, ...] = ("src/**/*.py", "tests/**/*.py")
    exclude: tuple[str, ...] = ()
    forbidden_subwords: tuple[str, ...] = ()
    allowed_symbols: tuple[str, ...] = ()
    terms: tuple[Term, ...] = ()
    source_path: Path = Path("symbols.toml")


def split_subwords(text: str) -> tuple[str, ...]:
    """Decompose an identifier or phrase into normalized lowercase subwords."""
    return tuple(match.group(0).lower() for match in SUBWORD_PATTERN.finditer(text))


def singularize(word: str) -> str:
    """Normalize a lowercase English subword to its singular form."""
    if len(word) <= 3 or word in INVARIANT_SINGULARS or not word.endswith("s"):
        return word
    if len(word) > 4 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if word.endswith(("sses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def normalize_subwords(text: str) -> tuple[str, ...]:
    """Decompose an identifier or phrase into singularized lowercase subwords."""
    return tuple(singularize(word) for word in split_subwords(text))


def matches_subwords(words: tuple[str, ...], target: tuple[str, ...]) -> bool:
    """Return True when target appears as a contiguous subword slice within words."""
    if not target:
        return False
    target_len = len(target)
    return any(
        words[index : index + target_len] == target for index in range(len(words) - target_len + 1)
    )


def load_schema(path: Path = Path("symbols.toml")) -> SymbolSchema:
    """Read and deserialize a SymbolSchema from a TOML file path."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    _validate_table_keys(raw, ALLOWED_ROOT_KEYS, "root")

    settings = _extract_table(raw.get("settings", {}), "settings")
    _validate_table_keys(settings, ALLOWED_SETTINGS_KEYS, "settings")

    include = _extract_string_tuple(
        settings.get("include", ["src/**/*.py", "tests/**/*.py"]),
        "settings.include",
    )
    exclude = _extract_string_tuple(settings.get("exclude", []), "settings.exclude")
    forbidden_subwords = tuple(
        word.strip().lower()
        for word in _extract_string_tuple(
            settings.get("forbidden_subwords", []),
            "settings.forbidden_subwords",
        )
    )
    allowed_symbols = tuple(
        word.strip()
        for word in _extract_string_tuple(
            settings.get("allowed_symbols", []),
            "settings.allowed_symbols",
        )
    )

    return SymbolSchema(
        include=include,
        exclude=exclude,
        forbidden_subwords=forbidden_subwords,
        allowed_symbols=allowed_symbols,
        terms=_extract_terms(raw.get("terms", [])),
        source_path=path,
    )


def _extract_table(raw_table: object, label: str) -> dict[str, object]:
    if not isinstance(raw_table, dict):
        raise ValueError(f"Expected '{label}' to be a TOML table.")
    return raw_table


def _validate_table_keys(table: dict[str, object], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        joined = ", ".join(unknown)
        raise ValueError(f"Unknown keys in {label}: {joined}.")


def _extract_string(raw_text: object, label: str) -> str:
    if not isinstance(raw_text, str):
        raise ValueError(f"Expected '{label}' to be a string.")
    return raw_text.strip()


def _extract_string_tuple(raw_list: object, label: str) -> tuple[str, ...]:
    if not isinstance(raw_list, list) or not all(isinstance(entry, str) for entry in raw_list):
        raise ValueError(f"Expected '{label}' to be a list of strings.")
    return tuple(raw_list)


def _extract_terms(raw_entries: object) -> tuple[Term, ...]:
    if not isinstance(raw_entries, list):
        raise ValueError("Expected 'terms' to be an array of tables ([[terms]]).")
    terms: list[Term] = []
    for raw_entry in raw_entries:
        entry = _extract_table(raw_entry, "terms")
        _validate_table_keys(entry, ALLOWED_TERM_KEYS, "terms")
        forbidden = _extract_string_tuple(
            entry.get("forbidden_terms", []),
            "terms.forbidden_terms",
        )
        terms.append(
            Term(
                term=_extract_string(entry.get("term", ""), "terms.term"),
                definition=_extract_string(entry.get("definition", ""), "terms.definition"),
                forbidden_terms=tuple(synonym.strip() for synonym in forbidden),
            )
        )
    return tuple(terms)
