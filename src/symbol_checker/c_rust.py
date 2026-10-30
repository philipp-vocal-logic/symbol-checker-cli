from __future__ import annotations

import re
from pathlib import Path

from symbol_checker.schema import Finding, Symbol

C_RUST_EXTS: frozenset[str] = frozenset({".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".rs"})
INTRINSIC_C_RUST: frozenset[str] = frozenset(
    {
        "_",
        "self",
        "Self",
        "cls",
        "main",
        "argc",
        "argv",
        "lib",
        "mod",
        "new",
        "drop",
        "fmt",
        "from",
        "into",
        "default",
        "clone",
        "eq",
        "cmp",
        "hash",
        "deref",
        "index",
        "add",
        "sub",
        "mul",
        "div",
        "TEST",
        "TEST_F",
        "TEST_P",
    }
)
KEYWORDS: frozenset[str] = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "case",
        "default",
        "break",
        "continue",
        "return",
        "goto",
        "sizeof",
        "alignof",
        "typeof",
        "offsetof",
        "void",
        "char",
        "short",
        "int",
        "long",
        "float",
        "double",
        "signed",
        "unsigned",
        "bool",
        "_Bool",
        "size_t",
        "ssize_t",
        "ptrdiff_t",
        "intptr_t",
        "uintptr_t",
        "int8_t",
        "int16_t",
        "int32_t",
        "int64_t",
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "const",
        "volatile",
        "restrict",
        "static",
        "extern",
        "auto",
        "register",
        "inline",
        "typedef",
        "struct",
        "enum",
        "union",
        "class",
        "namespace",
        "template",
        "typename",
        "public",
        "private",
        "protected",
        "virtual",
        "override",
        "final",
        "explicit",
        "friend",
        "operator",
        "new",
        "delete",
        "this",
        "true",
        "false",
        "nullptr",
        "NULL",
        "try",
        "catch",
        "throw",
        "noexcept",
        "constexpr",
        "consteval",
        "constinit",
        "decltype",
        "using",
        "static_assert",
        "fn",
        "let",
        "mut",
        "pub",
        "crate",
        "super",
        "impl",
        "trait",
        "where",
        "type",
        "match",
        "loop",
        "move",
        "ref",
        "in",
        "as",
        " unsafe",
        "async",
        "await",
        "dyn",
        "macro_rules",
    }
)

TOKEN_OR_COMMENT_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/')
COMMENT_IGNORE_RE = re.compile(
    r"(?://|/\*+|\#)\s*symbol\s*:\s*ignore(?:\[([^\]]*)\])?\s*(?:\*/)?(?=\s|$|//|\#)",
    re.IGNORECASE,
)
DECL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"\b(?:struct|enum|union|class|namespace|trait|mod|type|using|fn)\s+([A-Za-z_]\w*)"),
    re.compile(r"\b(?:let(?:\s+mut)?|const|static)\s+([A-Za-z_]\w*)\s*(?:(?<!:):(?!:)|=)"),
    re.compile(r"\btypedef\b[^;{}]*?\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*;"),
    re.compile(r"\}\s*([A-Za-z_]\w*)\s*;"),
    re.compile(r"\b([A-Za-z_]\w*)(?<!:):(?!:)\s*[A-Za-z_&\(\[]"),
    re.compile(
        r"(?<![:\w])(?:[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*(?:<[^>]*>)?[\s\*&]+)+([A-Za-z_]\w*)(?!\s*::)\s*(?=[(\[=;,)])"
    ),
)


def _blank_span(match: re.Match[str]) -> str:
    raw = match.group(0)
    return "".join("\n" if ch == "\n" else " " for ch in raw)


def extract_c_rust_ignore_matches(source_text: str) -> list[tuple[int, int, str | None]]:
    """Return (line, column, raw_bracket_group) for ignore comments outside string literals."""
    results: list[tuple[int, int, str | None]] = []
    for token_match in TOKEN_OR_COMMENT_RE.finditer(source_text):
        token = token_match.group(0)
        if not token.startswith(("//", "/*")):
            continue
        ignore_match = COMMENT_IGNORE_RE.search(token)
        if ignore_match is not None:
            abs_offset = token_match.start() + ignore_match.start()
            line = source_text.count("\n", 0, abs_offset) + 1
            line_start = source_text.rfind("\n", 0, abs_offset) + 1
            column = abs_offset - line_start + 1
            results.append((line, column, ignore_match.group(1)))
    return results


def _offset_to_line_col(source_text: str, offset: int) -> tuple[int, int]:
    line = source_text.count("\n", 0, offset) + 1
    line_start = source_text.rfind("\n", 0, offset) + 1
    return line, offset - line_start + 1


def extract_c_rust_symbols(
    source_text: str,
    file: Path = Path("<memory>"),
) -> tuple[list[Symbol], list[Finding]]:
    """Extract declared symbol identifiers from C, C++, or Rust source text."""
    sanitized = TOKEN_OR_COMMENT_RE.sub(_blank_span, source_text)
    found: list[tuple[int, int, str]] = []
    for pattern in DECL_PATTERNS:
        for match in pattern.finditer(sanitized):
            name = match.group(1)
            if name in KEYWORDS or name in INTRINSIC_C_RUST:
                continue
            line, column = _offset_to_line_col(source_text, match.start(1))
            found.append((line, column, name))

    found.sort(key=lambda entry: (entry[0], entry[1]))
    symbols: list[Symbol] = []
    seen_names: set[str] = set()
    if file != Path("<memory>") and file.stem not in INTRINSIC_C_RUST and file.stem not in KEYWORDS:
        seen_names.add(file.stem)
        symbols.append(Symbol(name=file.stem, file=file, line=1, column=1))

    for line, column, name in found:
        if name not in seen_names:
            seen_names.add(name)
            symbols.append(Symbol(name=name, file=file, line=line, column=column))
    return symbols, []
