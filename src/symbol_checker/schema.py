from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_UPPER = r"[A-ZÀ-ÖØ-Þ]"
_LOWER = r"[a-zß-öø-ÿ]"
SUBWORD_PATTERN = re.compile(
    rf"{_UPPER}{{2,}}s(?={_UPPER}{_LOWER}|\d|_|\b)"
    rf"|{_UPPER}+(?={_UPPER}{_LOWER}|\d|_|\b)"
    rf"|{_UPPER}?{_LOWER}+|\d+"
)
INVARIANT_SINGULARS: frozenset[str] = frozenset(
    {"alias", "atlas", "bias", "canvas", "chaos", "corpus", "lens", "news", "series", "species"}
)

SymbolKind = Literal[
    "module",
    "class",
    "function",
    "parameter",
    "variable",
    "attribute",
    "exception",
    "alias",
    "typevar",
]

ALLOWED_ROOT_KEYS: frozenset[str] = frozenset({"settings", "replacements"})
ALLOWED_SETTINGS_KEYS: frozenset[str] = frozenset(
    {"include", "exclude", "forbidden_subwords", "allowed_symbols"}
)


@dataclass(frozen=True, slots=True)
class Replacement:
    """A mapping from a canonical symbol subword to disallowed synonyms or abbreviations."""

    canonical: str
    forbidden: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Symbol:
    """A named code identifier extracted from a source file syntax tree."""

    name: str
    file: Path
    line: int
    column: int
    kind: SymbolKind = "variable"


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
    """The configured collection of forbidden subwords and canonical subword replacements."""

    include: tuple[str, ...] = ("src/**/*.py", "tests/**/*.py")
    exclude: tuple[str, ...] = ()
    forbidden_subwords: tuple[str, ...] = ()
    allowed_symbols: tuple[str, ...] = ()
    replacements: tuple[Replacement, ...] = ()
    source_path: Path = Path("symbols.toml")


def split_subwords(text: str) -> tuple[str, ...]:
    """Decompose an identifier or phrase into normalized lowercase subwords."""
    return tuple(match.group(0).lower() for match in SUBWORD_PATTERN.finditer(text))


def singularize(word: str) -> str:
    """Normalize a lowercase English subword to its singular form."""
    if len(word) <= 3 or word in INVARIANT_SINGULARS:
        return word
    if word.endswith("es") and word[:-2] in INVARIANT_SINGULARS:
        return word[:-2]
    if len(word) > 4 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if word.endswith(("sses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
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
        replacements=_extract_replacements(raw.get("replacements", {})),
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


def _extract_string_tuple(raw_list: object, label: str) -> tuple[str, ...]:
    if not isinstance(raw_list, list) or not all(isinstance(entry, str) for entry in raw_list):
        raise ValueError(f"Expected '{label}' to be a list of strings.")
    return tuple(raw_list)


def _extract_replacements(raw_replacements: object) -> tuple[Replacement, ...]:
    table = _extract_table(raw_replacements, "replacements")
    replacements: list[Replacement] = []
    for canonical, raw_forbidden in table.items():
        forbidden = _extract_string_tuple(raw_forbidden, f"replacements.{canonical}")
        replacements.append(
            Replacement(
                canonical=canonical.strip(),
                forbidden=tuple(synonym.strip() for synonym in forbidden),
            )
        )
    return tuple(replacements)
