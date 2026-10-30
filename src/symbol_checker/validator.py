from __future__ import annotations

from pathlib import Path

from symbol_checker.schema import (
    Finding,
    Replacement,
    SymbolSchema,
    matches_subwords,
    normalize_subwords,
)


def validate_schema(schema: SymbolSchema) -> list[Finding]:
    """Validate the schema for empty entries and subword collisions."""
    source = schema.source_path
    findings, canonical_by_norm = _validate_canonical_entries(schema.replacements, source)
    forbidden_findings = _validate_forbidden_entries(schema.replacements, source, canonical_by_norm)
    findings.extend(forbidden_findings)
    findings.extend(_check_forbidden_subword_collisions(schema, canonical_by_norm, source))
    return findings


def _build_schema_finding(source: Path, message: str, suggestion: str) -> Finding:
    return Finding(file=source, line=1, column=1, message=message, suggestion=suggestion)


def _validate_canonical_entries(
    entries: tuple[Replacement, ...],
    source: Path,
) -> tuple[list[Finding], dict[tuple[str, ...], Replacement]]:
    findings: list[Finding] = []
    canonical_by_norm: dict[tuple[str, ...], Replacement] = {}
    for entry in entries:
        findings.extend(_validate_single_entry(entry, source, canonical_by_norm))
    return findings, canonical_by_norm


def _validate_single_entry(
    entry: Replacement,
    source: Path,
    canonical_by_norm: dict[tuple[str, ...], Replacement],
) -> list[Finding]:
    norm_canonical = normalize_subwords(entry.canonical)
    if not norm_canonical:
        return [
            _build_schema_finding(
                source,
                "Schema contains an empty replacement key.",
                "Provide a non-empty canonical subword name.",
            )
        ]

    if norm_canonical in canonical_by_norm:
        existing = canonical_by_norm[norm_canonical]
        return [
            _build_schema_finding(
                source,
                f"Duplicate canonical replacement '{entry.canonical}' "
                f"(collides with '{existing.canonical}').",
                f"Keep only one replacement entry for '{existing.canonical}'.",
            )
        ]

    canonical_by_norm[norm_canonical] = entry
    return []


def _validate_forbidden_entries(
    entries: tuple[Replacement, ...],
    source: Path,
    canonical_by_norm: dict[tuple[str, ...], Replacement],
) -> list[Finding]:
    findings: list[Finding] = []
    forbidden_owner: dict[tuple[str, ...], tuple[str, Replacement]] = {}
    for entry in entries:
        for forbidden in entry.forbidden:
            findings.extend(
                _validate_single_forbidden(
                    entry, forbidden, source, canonical_by_norm, forbidden_owner
                )
            )
    return findings


def _validate_single_forbidden(
    entry: Replacement,
    forbidden: str,
    source: Path,
    canonical_by_norm: dict[tuple[str, ...], Replacement],
    forbidden_owner: dict[tuple[str, ...], tuple[str, Replacement]],
) -> list[Finding]:
    findings: list[Finding] = []
    norm_forbidden = normalize_subwords(forbidden)
    if not norm_forbidden:
        return [
            _build_schema_finding(
                source,
                f"Replacement '{entry.canonical}' contains an empty forbidden entry.",
                f"Remove the empty entry from replacements of '{entry.canonical}'.",
            )
        ]

    for norm_canonical, colliding in canonical_by_norm.items():
        if matches_subwords(norm_canonical, norm_forbidden) or matches_subwords(
            norm_forbidden, norm_canonical
        ):
            suggestion = (
                f"Remove '{forbidden}' from '{entry.canonical}'."
                if colliding.canonical == entry.canonical
                else (
                    f"Remove '{forbidden}' from '{entry.canonical}' "
                    f"or merge '{colliding.canonical}' into '{entry.canonical}'."
                )
            )
            findings.append(
                _build_schema_finding(
                    source,
                    f"Replacement '{colliding.canonical}' collides with forbidden entry "
                    f"'{forbidden}' in '{entry.canonical}'.",
                    suggestion,
                )
            )

    if norm_forbidden in forbidden_owner:
        prev_raw, prev_entry = forbidden_owner[norm_forbidden]
        findings.append(
            _build_schema_finding(
                source,
                f"Forbidden entry '{forbidden}' in '{entry.canonical}' collides with "
                f"'{prev_raw}' in '{prev_entry.canonical}'.",
                f"Keep '{forbidden}' under only one canonical replacement.",
            )
        )
    else:
        forbidden_owner[norm_forbidden] = (forbidden, entry)
    return findings


def _check_forbidden_subword_collisions(
    schema: SymbolSchema,
    canonical_by_norm: dict[tuple[str, ...], Replacement],
    source: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    for subword in schema.forbidden_subwords:
        norm = normalize_subwords(subword)
        if len(norm) != 1:
            findings.append(
                _build_schema_finding(
                    source,
                    f"Invalid forbidden_subword '{subword}' (must be a single subword).",
                    "Move multi-word entries to replacements or split into subwords.",
                )
            )
            continue
        findings.extend(
            _find_subword_replacement_collisions(subword, norm[0], canonical_by_norm, source)
        )
    return findings


def _find_subword_replacement_collisions(
    subword: str,
    target_word: str,
    canonical_by_norm: dict[tuple[str, ...], Replacement],
    source: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    for norm_canonical, entry in canonical_by_norm.items():
        if target_word in norm_canonical:
            findings.append(
                _build_schema_finding(
                    source,
                    f"Canonical replacement '{entry.canonical}' collides with "
                    f"forbidden_subword '{subword}'.",
                    f"Remove '{subword}' from forbidden_subwords or rename '{entry.canonical}'.",
                )
            )
        for forbidden in entry.forbidden:
            if target_word in normalize_subwords(forbidden):
                findings.append(
                    _build_schema_finding(
                        source,
                        f"Forbidden entry '{forbidden}' in '{entry.canonical}' collides with "
                        f"forbidden_subword '{subword}'.",
                        f"Remove '{forbidden}' from '{entry.canonical}' or "
                        f"remove '{subword}' from forbidden_subwords.",
                    )
                )
    return findings
