from __future__ import annotations

import ast
import contextlib
import io
import re
import tokenize
from pathlib import Path

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
    """Parse Python source_text with stdlib ast and extract defined symbols and syntax findings."""
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


def extract_ignored_lines(source_text: str) -> dict[int, frozenset[str]]:
    """Extract per-line ignore targets from real Python comments (empty frozenset = ignore all)."""
    ignored: dict[int, frozenset[str]] = {}
    reader = io.StringIO(source_text).readline
    with contextlib.suppress(tokenize.TokenError, IndentationError):
        for comment_record in tokenize.generate_tokens(reader):
            if comment_record.type != tokenize.COMMENT:
                continue
            match = IGNORE_COMMENT_PATTERN.search(comment_record.string)
            if match is not None:
                ignored[comment_record.start[0]] = _parse_ignore_targets(match.group(1))
    return ignored


def _parse_ignore_targets(raw_targets: str | None) -> frozenset[str]:
    if raw_targets is None:
        return frozenset()
    targets: set[str] = set()
    for part in raw_targets.split(","):
        target = "_".join(normalize_subwords(part))
        if target:
            targets.add(target)
    return frozenset(targets)
