"""Validate agent-produced enrichment output.

Checks schema conformance, path/symbol existence, evidence validity,
and constraint compliance. Fully deterministic — no randomness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codegraph.enrich.models import (
    AgentOutput,
    ValidationError_,
    ValidationResult,
)
from codegraph.graph.store import GraphStore


def validate_agent_output(
    output_path: Path,
    store: GraphStore,
    max_summary_chars: int = 500,
    max_tags: int = 10,
) -> ValidationResult:
    """Validate agent output JSON against schema and index consistency.

    Args:
        output_path: Path to the agent output JSON file.
        store: The loaded graph store for index verification.
        max_summary_chars: Maximum allowed summary length.
        max_tags: Maximum allowed tag count.

    Returns:
        A ``ValidationResult`` with errors, warnings, and stats.
    """
    errors: list[ValidationError_] = []
    warnings: list[ValidationError_] = []

    # 1. Read and parse JSON
    try:
        raw = output_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return ValidationResult(
            valid=False,
            errors=[ValidationError_(path="<file>", message=f"Cannot read file: {e}")],
            stats={"files_checked": 0, "symbols_checked": 0},
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return ValidationResult(
            valid=False,
            errors=[ValidationError_(path="<file>", message=f"Invalid JSON: {e}")],
            stats={"files_checked": 0, "symbols_checked": 0},
        )

    # 2. Validate against AgentOutput Pydantic schema
    try:
        output = AgentOutput.model_validate(data)
    except Exception as e:
        return ValidationResult(
            valid=False,
            errors=[ValidationError_(path="<root>", message=f"Schema validation failed: {e}")],
            stats={"files_checked": 0, "symbols_checked": 0},
        )

    # 3. Check schema marker
    if output.schema_version != "codegraph_enrichment_v1":
        errors.append(
            ValidationError_(
                path="schema_version",
                message=f"Expected schema 'codegraph_enrichment_v1', got {output.schema_version!r}",
            )
        )

    # 4. Collect known file paths and symbol names from index
    known_files: set[str] = set()
    known_symbols: dict[str, set[str]] = {}  # file_path -> set of symbol names
    for node in store.all_nodes():
        fp = _norm_path(getattr(node, "file_path", ""))
        if fp:
            known_files.add(fp)
            if fp not in known_symbols:
                known_symbols[fp] = set()
            name = getattr(node, "name", "")
            if name:
                known_symbols[fp].add(name)
            # Also index by qualified_name
            qname = getattr(node, "qualified_name", "")
            if qname:
                known_symbols[fp].add(qname)

    # 5. Validate file entries
    for i, fe in enumerate(output.files):
        prefix = f"files[{i}]"

        # 5a. Path must be relative
        if not _is_relative_path(fe.path):
            errors.append(
                ValidationError_(
                    path=f"{prefix}.path",
                    message=f"Path must be relative, got {fe.path!r}",
                )
            )

        # 5b. File must exist in index
        if fe.path and fe.path not in known_files:
            warnings.append(
                ValidationError_(
                    path=f"{prefix}.path",
                    message=f"File {fe.path!r} not found in index",
                    severity="warning",
                )
            )

        # 5c. Summary length
        if len(fe.summary) > max_summary_chars:
            errors.append(
                ValidationError_(
                    path=f"{prefix}.summary",
                    message=f"Summary too long: {len(fe.summary)} chars (max {max_summary_chars})",
                )
            )

        # 5d. Tags count
        if len(fe.tags) > max_tags:
            errors.append(
                ValidationError_(
                    path=f"{prefix}.tags",
                    message=f"Too many tags: {len(fe.tags)} (max {max_tags})",
                )
            )

        # 5e. Evidence line ranges
        for j, ev in enumerate(fe.evidence):
            _check_evidence(errors, f"{prefix}.evidence[{j}]", ev)

    # 6. Validate symbol entries
    for i, se in enumerate(output.symbols):
        prefix = f"symbols[{i}]"

        # 6a. file must be relative
        if not _is_relative_path(se.file):
            errors.append(
                ValidationError_(
                    path=f"{prefix}.file",
                    message=f"Path must be relative, got {se.file!r}",
                )
            )

        # 6b. Symbol must exist in index (name match within file context)
        if se.file and se.symbol:
            file_symbols = known_symbols.get(se.file, set())
            if se.symbol not in file_symbols:
                # Try fuzzy: check if any symbol in that file contains the name
                found = any(se.symbol in s for s in file_symbols)
                if not found:
                    warnings.append(
                        ValidationError_(
                            path=f"{prefix}.symbol",
                            message=f"Symbol {se.symbol!r} not found in file {se.file!r}",
                            severity="warning",
                        )
                    )

        # 6c. Summary length
        if len(se.summary) > max_summary_chars:
            errors.append(
                ValidationError_(
                    path=f"{prefix}.summary",
                    message=f"Summary too long: {len(se.summary)} chars (max {max_summary_chars})",
                )
            )

        # 6d. Evidence line ranges
        for j, ev in enumerate(se.evidence):
            _check_evidence(errors, f"{prefix}.evidence[{j}]", ev)

    # 7. Check enriched_at
    if not output.enriched_at:
        warnings.append(
            ValidationError_(
                path="enriched_at",
                message="Missing enriched_at timestamp",
                severity="warning",
            )
        )

    # 8. Warn if both files and symbols are empty
    if not output.files and not output.symbols:
        warnings.append(
            ValidationError_(
                path="<root>",
                message="Agent output contains no files and no symbols",
                severity="warning",
            )
        )

    valid = len(errors) == 0
    return ValidationResult(
        valid=valid,
        errors=errors,
        warnings=warnings,
        stats={
            "files_checked": len(output.files),
            "symbols_checked": len(output.symbols),
            "total_errors": len(errors),
            "total_warnings": len(warnings),
        },
    )


# ── helpers ──────────────────────────────────────────────────────────


def _norm_path(p: str) -> str:
    return p.replace("\\", "/")


def _is_relative_path(p: str) -> bool:
    """Check if a path is relative (no absolute prefixes, no .. traversal)."""
    if not p:
        return True
    # Normalize separators before checking
    normalized = p.replace("\\", "/")
    # Absolute paths
    if normalized.startswith("/") or (len(p) >= 2 and p[1] == ":"):
        return False
    # Parent directory traversal (check after normalization)
    if normalized.startswith("..") or "/../" in normalized:
        return False
    return True


def _check_evidence(
    errors: list[ValidationError_],
    prefix: str,
    ev: Any,
) -> None:
    """Validate a single evidence entry."""
    if hasattr(ev, "line_start") and ev.line_start is not None:
        if ev.line_start < 0:
            errors.append(
                ValidationError_(
                    path=f"{prefix}.line_start",
                    message=f"Negative line_start: {ev.line_start}",
                )
            )
    if hasattr(ev, "line_end") and ev.line_end is not None:
        if ev.line_end < 0:
            errors.append(
                ValidationError_(
                    path=f"{prefix}.line_end",
                    message=f"Negative line_end: {ev.line_end}",
                )
            )
        if (
            hasattr(ev, "line_start")
            and ev.line_start is not None
            and ev.line_end < ev.line_start
        ):
            errors.append(
                ValidationError_(
                    path=f"{prefix}",
                    message=f"line_end ({ev.line_end}) < line_start ({ev.line_start})",
                )
            )
    # Evidence file must be relative
    if hasattr(ev, "file") and ev.file:
        if not _is_relative_path(ev.file):
            errors.append(
                ValidationError_(
                    path=f"{prefix}.file",
                    message=f"Evidence file must be relative, got {ev.file!r}",
                )
            )
