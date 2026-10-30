from __future__ import annotations

from pathlib import Path

from symbol_checker.schema import (
    Finding,
    SymbolSchema,
    Term,
    matches_subwords,
    normalize_subwords,
)


def validate_schema(schema: SymbolSchema) -> list[Finding]:
    """Validate the schema for empty entries, collisions, and duplicate definitions."""
    source = schema.source_path
    findings, canonical_by_norm = _validate_canonical_entries(schema.terms, source)
    forbidden_findings, forbidden_owner = _validate_forbidden_entries(
        schema.terms, source, canonical_by_norm
    )
    findings.extend(forbidden_findings)
    findings.extend(_check_forbidden_subword_collisions(schema, canonical_by_norm, source))
    findings.extend(_check_duplicate_definitions(schema.terms, source))
    findings.extend(_check_definitions_for_forbidden_terms(schema.terms, forbidden_owner, source))
    return findings


def _build_schema_finding(source: Path, message: str, suggestion: str) -> Finding:
    return Finding(file=source, line=1, column=1, message=message, suggestion=suggestion)


def _validate_canonical_entries(
    entries: tuple[Term, ...],
    source: Path,
) -> tuple[list[Finding], dict[tuple[str, ...], Term]]:
    findings: list[Finding] = []
    canonical_by_norm: dict[tuple[str, ...], Term] = {}
    for entry in entries:
        findings.extend(_validate_single_entry(entry, source, canonical_by_norm))
    return findings, canonical_by_norm


def _validate_single_entry(
    entry: Term,
    source: Path,
    canonical_by_norm: dict[tuple[str, ...], Term],
) -> list[Finding]:
    findings: list[Finding] = []
    norm_term = normalize_subwords(entry.term)
    if not norm_term:
        return [
            _build_schema_finding(
                source,
                "Schema contains an empty term.",
                "Provide a non-empty canonical term name.",
            )
        ]

    if not normalize_subwords(entry.definition):
        findings.append(
            _build_schema_finding(
                source,
                f"Term '{entry.term}' has an empty definition.",
                f"Provide a clear definition for '{entry.term}'.",
            )
        )

    if norm_term in canonical_by_norm:
        existing = canonical_by_norm[norm_term]
        findings.append(
            _build_schema_finding(
                source,
                f"Duplicate canonical term '{entry.term}' (collides with '{existing.term}').",
                f"Keep only one canonical term entry for '{existing.term}'.",
            )
        )
    else:
        canonical_by_norm[norm_term] = entry
    return findings


def _validate_forbidden_entries(
    entries: tuple[Term, ...],
    source: Path,
    canonical_by_norm: dict[tuple[str, ...], Term],
) -> tuple[list[Finding], dict[tuple[str, ...], tuple[str, Term]]]:
    findings: list[Finding] = []
    forbidden_owner: dict[tuple[str, ...], tuple[str, Term]] = {}
    for entry in entries:
        for forbidden in entry.forbidden_terms:
            findings.extend(
                _validate_single_forbidden(
                    entry, forbidden, source, canonical_by_norm, forbidden_owner
                )
            )
    return findings, forbidden_owner


def _validate_single_forbidden(
    entry: Term,
    forbidden: str,
    source: Path,
    canonical_by_norm: dict[tuple[str, ...], Term],
    forbidden_owner: dict[tuple[str, ...], tuple[str, Term]],
) -> list[Finding]:
    findings: list[Finding] = []
    norm_forbidden = normalize_subwords(forbidden)
    if not norm_forbidden:
        return [
            _build_schema_finding(
                source,
                f"Term '{entry.term}' contains an empty forbidden_term.",
                f"Remove the empty entry from forbidden_terms of '{entry.term}'.",
            )
        ]

    for norm_canonical, colliding in canonical_by_norm.items():
        if matches_subwords(norm_canonical, norm_forbidden):
            findings.append(
                _build_schema_finding(
                    source,
                    f"Term '{colliding.term}' collides with forbidden_term "
                    f"'{forbidden}' in '{entry.term}'.",
                    f"Remove '{forbidden}' from forbidden_terms of '{entry.term}' "
                    f"or merge '{colliding.term}' into '{entry.term}'.",
                )
            )

    if norm_forbidden in forbidden_owner:
        prev_raw, prev_entry = forbidden_owner[norm_forbidden]
        findings.append(
            _build_schema_finding(
                source,
                f"Forbidden term '{forbidden}' in '{entry.term}' collides with "
                f"'{prev_raw}' in '{prev_entry.term}'.",
                f"Keep '{forbidden}' under only one canonical term so each "
                "forbidden_term maps to a single canonical meaning.",
            )
        )
    else:
        forbidden_owner[norm_forbidden] = (forbidden, entry)
    return findings


def _check_forbidden_subword_collisions(
    schema: SymbolSchema,
    canonical_by_norm: dict[tuple[str, ...], Term],
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
                    "Move multi-word entries to forbidden_terms or split into subwords.",
                )
            )
            continue
        target_word = norm[0]
        for norm_term, entry in canonical_by_norm.items():
            if target_word in norm_term:
                findings.append(
                    _build_schema_finding(
                        source,
                        f"Canonical term '{entry.term}' collides with "
                        f"forbidden_subword '{subword}'.",
                        f"Remove '{subword}' from forbidden_subwords or rename '{entry.term}'.",
                    )
                )
    return findings


def _check_duplicate_definitions(
    entries: tuple[Term, ...],
    source: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    seen_definitions: dict[tuple[str, ...], Term] = {}
    for entry in entries:
        norm_def = normalize_subwords(entry.definition)
        if not norm_def:
            continue
        if norm_def in seen_definitions:
            first_entry = seen_definitions[norm_def]
            findings.append(
                _build_schema_finding(
                    source,
                    f"Terms '{first_entry.term}' and '{entry.term}' have identical definitions.",
                    f"Merge '{entry.term}' into forbidden_terms of '{first_entry.term}' "
                    "or provide distinct definitions.",
                )
            )
        else:
            seen_definitions[norm_def] = entry
    return findings


def _check_definitions_for_forbidden_terms(
    entries: tuple[Term, ...],
    forbidden_owner: dict[tuple[str, ...], tuple[str, Term]],
    source: Path,
) -> list[Finding]:
    return [
        _build_schema_finding(
            source,
            f"Definition of '{entry.term}' uses forbidden_term '{raw_forbidden}'.",
            f"Use canonical term '{canonical_entry.term}' ({canonical_entry.definition}).",
        )
        for entry in entries
        if (words := normalize_subwords(entry.definition))
        for forbidden_words, (raw_forbidden, canonical_entry) in forbidden_owner.items()
        if matches_subwords(words, forbidden_words)
    ]
