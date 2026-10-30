from __future__ import annotations

import ast
import contextlib
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

from symbol_checker.c_rust import (
    C_RUST_EXTS,
    extract_c_rust_ignore_matches,
    extract_c_rust_symbols,
)
from symbol_checker.schema import Finding, Symbol, normalize_subwords

INTRINSIC_NAMES: frozenset[str] = frozenset({"_", "self", "cls"})
IGNORE_COMMENT_PATTERN = re.compile(
    r"#\s*symbol\s*:\s*ignore(?:\[([^\]]*)\])?(?=\s|$|#)",
    re.IGNORECASE,
)

SCOPE_NODE_TYPES = (
    ast.ClassDef,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def extract_symbols(
    source_text: str,
    file: Path = Path("<memory>"),
) -> tuple[list[Symbol], list[Finding]]:
    """Parse source_text and extract defined symbols and syntax findings."""
    if file.suffix.lower() in C_RUST_EXTS:
        return extract_c_rust_symbols(source_text, file=file)
    try:
        tree = ast.parse(source_text, filename=str(file))
    except SyntaxError as error:
        return [], [
            Finding(
                file=file,
                line=error.lineno or 1,
                column=error.offset or 1,
                message="Syntax error detected in source file.",
                suggestion="Fix the syntax error before checking symbol names.",
            )
        ]

    symbols: list[Symbol] = []
    seen_names: set[str] = set()
    module_name = file.parent.name if file.stem == "__init__" else file.stem
    if file != Path("<memory>") and not _is_intrinsic_name(module_name):
        seen_names.add(module_name)
        symbols.append(Symbol(name=module_name, file=file, line=1, column=1))
    _extract_from_node(tree, file, symbols, seen_names, set())
    return symbols, []


def _extract_from_node(
    node: ast.AST,
    file: Path,
    symbols: list[Symbol],
    seen_names: set[str],
    class_seen: set[str],
) -> None:
    name = _extract_binding_name(node)
    if name is not None and not _is_intrinsic_name(name):
        scope_seen = class_seen if isinstance(node, ast.Attribute) else seen_names
        if name not in scope_seen:
            scope_seen.add(name)
            line, column = node.lineno, node.col_offset + 1
            symbols.append(Symbol(name=name, file=file, line=line, column=column))

    child_seen = set() if isinstance(node, SCOPE_NODE_TYPES) else seen_names
    child_class_seen = child_seen if isinstance(node, ast.ClassDef) else class_seen
    for child in ast.iter_child_nodes(node):
        _extract_from_node(child, file, symbols, child_seen, child_class_seen)


def _extract_binding_name(node: ast.AST) -> str | None:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if isinstance(node, ast.arg):
        return node.arg
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        is_instance = isinstance(node.value, ast.Name) and node.value.id in ("self", "cls")
        return node.attr if is_instance else None
    return _extract_pattern_or_alias_name(node)


def _extract_pattern_or_alias_name(node: ast.AST) -> str | None:
    if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
        return node.name
    if isinstance(node, ast.alias):
        return node.asname
    if isinstance(node, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple)):
        return node.name
    return None


def _is_intrinsic_name(name: str) -> bool:
    if not name or name in INTRINSIC_NAMES:
        return True
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


@dataclass(frozen=True, slots=True)
class IgnoreDirective:
    """A parsed '# symbol: ignore' comment on a source line."""

    line: int
    column: int
    raw_targets: tuple[str, ...] | None = None
    norm_targets: frozenset[str] = frozenset()


def filter_ignored_findings(
    candidates: list[tuple[Finding, frozenset[str]]],
    source_text: str,
    file: Path,
) -> list[Finding]:
    """Filter symbol findings using 'symbol: ignore' comments and report invalid directives."""
    directives = _extract_ignored_lines(source_text, file=file)
    used_lines: set[int] = set()
    used_targets: dict[int, set[str]] = {}
    findings = [
        finding
        for finding, ignore_keys in candidates
        if not _is_ignored(
            finding.line, ignore_keys, directives.get(finding.line), used_lines, used_targets
        )
    ]
    for directive in directives.values():
        findings.extend(_check_single_directive(directive, used_lines, used_targets, file))
    return findings


def _is_ignored(
    line: int,
    ignore_keys: frozenset[str],
    directive: IgnoreDirective | None,
    used_lines: set[int],
    used_targets: dict[int, set[str]],
) -> bool:
    if directive is None:
        return False
    if directive.raw_targets is None:
        used_lines.add(line)
        return True
    matched = ignore_keys & directive.norm_targets
    if not matched:
        return False
    used_targets.setdefault(line, set()).update(matched)
    return True


def _extract_ignored_lines(
    source_text: str, file: Path = Path("<memory>")
) -> dict[int, IgnoreDirective]:
    if file.suffix.lower() in C_RUST_EXTS:
        return {
            line: _build_ignore_directive(line, col, group)
            for line, col, group in extract_c_rust_ignore_matches(source_text)
        }
    ignored: dict[int, IgnoreDirective] = {}
    reader = io.StringIO(source_text).readline
    with contextlib.suppress(tokenize.TokenError, IndentationError):
        for comment_record in tokenize.generate_tokens(reader):
            if comment_record.type != tokenize.COMMENT:
                continue
            match = IGNORE_COMMENT_PATTERN.search(comment_record.string)
            if match is not None:
                line = comment_record.start[0]
                column = comment_record.start[1] + match.start() + 1
                ignored[line] = _build_ignore_directive(line, column, match.group(1))
    return ignored


def _build_ignore_directive(
    line: int,
    column: int,
    raw_group: str | None,
) -> IgnoreDirective:
    if raw_group is None:
        return IgnoreDirective(line=line, column=column)
    stripped = raw_group.strip()
    if not stripped:
        return IgnoreDirective(line=line, column=column, raw_targets=())
    raw_targets = tuple(part.strip() for part in stripped.split(","))
    norm_targets = frozenset(
        target for part in raw_targets if (target := "_".join(normalize_subwords(part)))
    )
    return IgnoreDirective(line, column, raw_targets, norm_targets)


def _check_single_directive(
    directive: IgnoreDirective,
    used_lines: set[int],
    used_targets: dict[int, set[str]],
    file: Path,
) -> list[Finding]:
    if directive.raw_targets is None:
        if directive.line in used_lines:
            return []
        return [
            Finding(
                file,
                directive.line,
                directive.column,
                "Unused 'symbol: ignore' comment matched no findings.",
                "Remove the unused 'symbol: ignore' comment.",
            )
        ]
    if not directive.raw_targets:
        return [
            Finding(
                file,
                directive.line,
                directive.column,
                "Empty 'symbol: ignore[]' comment specifies no targets.",
                "Specify target subwords in 'symbol: ignore[...]' or use '# symbol: ignore'.",
            )
        ]
    line_used = used_targets.get(directive.line, set())
    return [
        Finding(
            file,
            directive.line,
            directive.column,
            f"Unused ignore target '{raw_target}' in 'symbol: ignore' comment.",
            "Remove the unused target or specify a subword reported on this line.",
        )
        for raw_target in directive.raw_targets
        if not (norm := "_".join(normalize_subwords(raw_target))) or norm not in line_used
    ]
