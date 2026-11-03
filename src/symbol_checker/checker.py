from __future__ import annotations

import contextlib
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pathspec

from symbol_checker.extractor import extract_symbols, filter_ignored_findings
from symbol_checker.schema import (
    Finding,
    Replacement,
    Symbol,
    SymbolSchema,
    matches_subwords,
    normalize_subwords,
    singularize,
)
from symbol_checker.validator import validate_schema


@dataclass(frozen=True, slots=True)
class _CompiledRules:
    forbidden_subwords: frozenset[str]
    allowed_symbols: frozenset[str]
    replacements: tuple[tuple[tuple[str, ...], str, Replacement, frozenset[str]], ...]


def check_project(
    schema: SymbolSchema,
    root: Path | None = None,
    targets: Sequence[Path] | None = None,
) -> list[Finding]:
    """Validate the schema and check all discovered project files matching include globs."""
    findings = validate_schema(schema)
    parent = schema.source_path.parent.resolve()
    default_root = parent.parent if parent.name == ".policy" else parent
    base_dir = root.resolve() if root is not None else default_root
    include_matcher = pathspec.PathSpec.from_lines("gitignore", schema.include)
    ignore_matcher = _build_ignore_matcher(base_dir, schema.exclude)
    compiled = _build_compiled_rules(schema)

    discovered = discover_files(base_dir, include_matcher, ignore_matcher)
    target_files, target_findings = _filter_targets(discovered, base_dir, targets, schema)
    findings.extend(target_findings)
    for target_file in target_files:
        display_path = _format_relative_path(target_file, base_dir)
        source_text, read_finding = _load_source_text(target_file, display_path)
        if read_finding is not None:
            findings.append(read_finding)
            continue
        findings.extend(_check_source_with_rules(source_text, compiled, file=display_path))

    return findings


def check_source(
    source_text: str,
    schema: SymbolSchema,
    file: Path = Path("<memory>"),
) -> list[Finding]:
    """Extract symbols from source_text and check each symbol against the schema."""
    compiled = _build_compiled_rules(schema)
    return _check_source_with_rules(source_text, compiled, file=file)


def _check_source_with_rules(
    source_text: str, compiled: _CompiledRules, file: Path
) -> list[Finding]:
    symbols, findings = extract_symbols(source_text, file=file)
    if findings:
        return findings
    candidates = [
        candidate
        for symbol in symbols
        if symbol.name not in compiled.allowed_symbols
        for candidate in _check_single_symbol(symbol, compiled)
    ]
    return filter_ignored_findings(candidates, source_text, file)


def _build_compiled_rules(schema: SymbolSchema) -> _CompiledRules:
    replacements = tuple(
        (
            norm,
            raw,
            entry,
            frozenset({"_".join(norm), "_".join(normalize_subwords(entry.canonical))}),
        )
        for entry in schema.replacements
        for raw in entry.forbidden
        if (norm := normalize_subwords(raw))
    )
    return _CompiledRules(
        forbidden_subwords=frozenset(singularize(word) for word in schema.forbidden_subwords),
        allowed_symbols=frozenset(schema.allowed_symbols),
        replacements=replacements,
    )


def _check_single_symbol(
    symbol: Symbol, compiled: _CompiledRules
) -> list[tuple[Finding, frozenset[str]]]:
    subwords = normalize_subwords(symbol.name)
    subword_findings = [
        _build_symbol_finding(
            symbol,
            f"Contains ambiguous forbidden subword '{word}'.",
            f"Replace '{word}' with a specific domain noun.",
            frozenset({word}),
        )
        for word in dict.fromkeys(subwords)
        if word in compiled.forbidden_subwords
    ]
    replacement_findings = [
        _build_symbol_finding(
            symbol,
            f"Uses non-canonical '{raw_forbidden}'.",
            f"Use canonical '{entry.canonical}'.",
            ignore_keys,
        )
        for forbidden_words, raw_forbidden, entry, ignore_keys in compiled.replacements
        if matches_subwords(subwords, forbidden_words)
    ]
    return [*subword_findings, *replacement_findings]


def _build_symbol_finding(
    symbol: Symbol,
    message: str,
    suggestion: str,
    ignore_keys: frozenset[str],
) -> tuple[Finding, frozenset[str]]:
    finding = Finding(symbol.file, symbol.line, symbol.column, message, suggestion, symbol.name)
    return finding, ignore_keys


def _build_ignore_matcher(base_dir: Path, exclude: tuple[str, ...]) -> pathspec.PathSpec:
    patterns: list[str] = [".git/"]
    gitignore_path = base_dir / ".gitignore"
    if gitignore_path.is_file():
        with contextlib.suppress(OSError, UnicodeDecodeError):
            patterns.extend(gitignore_path.read_text(encoding="utf-8").splitlines())
    patterns.extend(exclude)
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def discover_files(
    base_dir: Path,
    include_matcher: pathspec.PathSpec,
    ignore_matcher: pathspec.PathSpec,
) -> list[Path]:
    """Walk base_dir and return sorted files matching include_matcher and not ignore_matcher."""
    discovered: list[Path] = []
    for root_str, dirnames, filenames in os.walk(base_dir):
        root_path = Path(root_str)
        dirnames[:] = sorted(
            dirname
            for dirname in dirnames
            if not _is_ignored_dir(root_path / dirname, base_dir, ignore_matcher)
        )
        for filename in sorted(filenames):
            file_path = root_path / filename
            rel_posix = _format_relative_path(file_path, base_dir).as_posix()
            if not ignore_matcher.match_file(rel_posix) and include_matcher.match_file(rel_posix):
                discovered.append(file_path)
    return discovered


def _is_ignored_dir(dir_path: Path, base_dir: Path, ignore_matcher: pathspec.PathSpec) -> bool:
    rel_posix = _format_relative_path(dir_path, base_dir).as_posix()
    return ignore_matcher.match_file(rel_posix) or ignore_matcher.match_file(f"{rel_posix}/")


def _format_relative_path(path: Path, base_dir: Path) -> Path:
    for candidate in (path, path.resolve()):
        with contextlib.suppress(ValueError):
            return candidate.relative_to(base_dir)
    return path


def _resolve_target(base_dir: Path, target: Path) -> Path:
    cwd_candidate = target.resolve()
    if target.is_absolute() or (cwd_candidate.exists() and cwd_candidate.is_relative_to(base_dir)):
        return cwd_candidate
    base_candidate = (base_dir / target).resolve()
    return base_candidate if base_candidate.exists() else cwd_candidate


def _filter_targets(
    discovered: list[Path],
    base_dir: Path,
    targets: Sequence[Path] | None,
    schema: SymbolSchema,
) -> tuple[list[Path], list[Finding]]:
    if not targets:
        if discovered:
            return discovered, []
        return [], [
            _build_file_finding(
                schema.source_path,
                "No Python files matched the configured include and exclude globs.",
                "Adjust settings.include or settings.exclude in symbols.toml.",
            )
        ]
    resolved_targets = [(_resolve_target(base_dir, target), target) for target in targets]
    matched_files = [
        path
        for path in discovered
        if any(path.resolve().is_relative_to(resolved) for resolved, _ in resolved_targets)
    ]
    target_findings = [
        _build_unmatched_target_finding(target, resolved, base_dir)
        for resolved, target in resolved_targets
        if not any(path.resolve().is_relative_to(resolved) for path in discovered)
    ]
    return matched_files, target_findings


def _build_file_finding(file: Path, message: str, suggestion: str) -> Finding:
    return Finding(file, 1, 1, message, suggestion)


def _build_unmatched_target_finding(target: Path, resolved: Path, base_dir: Path) -> Finding:
    if not resolved.exists():
        return _build_file_finding(
            target,
            f"Target path '{target}' does not exist.",
            "Provide an existing file or directory path.",
        )
    return _build_file_finding(
        _format_relative_path(resolved, base_dir),
        f"Target path '{target}' matched no included Python files.",
        "Adjust settings.include or settings.exclude in symbols.toml.",
    )


def _load_source_text(file_path: Path, display_path: Path) -> tuple[str, Finding | None]:
    try:
        return file_path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as error:
        return "", _build_file_finding(
            display_path,
            f"Failed to read UTF-8 source file: {error}.",
            "Ensure the file is readable and UTF-8 encoded, or exclude it in symbols.toml.",
        )
