from __future__ import annotations

import ast
from pathlib import Path

from symbol_checker.schema import Finding, Symbol, SymbolKind

INTRINSIC_NAMES: frozenset[str] = frozenset({"_", "self", "cls"})

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
        symbols.append(Symbol(name=module_name, file=file, line=1, column=1, kind="module"))
    _extract_from_node(tree, file, symbols, seen_names)
    return symbols, []


def _extract_from_node(
    node: ast.AST,
    file: Path,
    symbols: list[Symbol],
    seen_names: set[str],
) -> None:
    binding = _extract_node_binding(node)
    if binding is not None:
        name, line, column, kind = binding
        if not _is_intrinsic_name(name) and name not in seen_names:
            seen_names.add(name)
            symbols.append(Symbol(name=name, file=file, line=line, column=column, kind=kind))

    child_seen = set() if isinstance(node, SCOPE_NODE_TYPES) else seen_names
    for child in ast.iter_child_nodes(node):
        _extract_from_node(child, file, symbols, child_seen)


def _extract_node_binding(node: ast.AST) -> tuple[str, int, int, SymbolKind] | None:
    if isinstance(node, ast.ClassDef):
        return node.name, node.lineno, node.col_offset + 1, "class"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name, node.lineno, node.col_offset + 1, "function"
    if isinstance(node, ast.arg):
        return node.arg, node.lineno, node.col_offset + 1, "parameter"
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        return node.id, node.lineno, node.col_offset + 1, "variable"
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        return _extract_attribute_binding(node)
    return _extract_pattern_or_alias_binding(node)


def _extract_attribute_binding(node: ast.Attribute) -> tuple[str, int, int, SymbolKind] | None:
    if isinstance(node.value, ast.Name) and node.value.id in ("self", "cls"):
        return node.attr, node.lineno, node.col_offset + 1, "attribute"
    return None


def _extract_pattern_or_alias_binding(node: ast.AST) -> tuple[str, int, int, SymbolKind] | None:
    if isinstance(node, ast.ExceptHandler) and node.name:
        return node.name, node.lineno, node.col_offset + 1, "exception"
    if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
        return node.name, node.lineno, node.col_offset + 1, "variable"
    if isinstance(node, ast.alias) and node.asname:
        return node.asname, node.lineno, node.col_offset + 1, "alias"
    if isinstance(node, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple)):
        return node.name, node.lineno, node.col_offset + 1, "typevar"
    return None


def _is_intrinsic_name(name: str) -> bool:
    if not name or name in INTRINSIC_NAMES:
        return True
    return len(name) > 4 and name.startswith("__") and name.endswith("__")
