"""Unified warning types for CodeGraph Explorer.

All warnings follow a stable structure that MCP tools and CLI can both consume.
"""

from __future__ import annotations

from typing import Any

# ── Warning type registry ────────────────────────────────────────────────────

WARNING_TYPES: dict[str, dict[str, Any]] = {
    "stale_index": {
        "type": "stale_index",
        "severity": "warning",
        "description": "Index is stale. Results may be outdated.",
    },
    "symlink_outside_root": {
        "type": "symlink_outside_root",
        "severity": "warning",
        "description": "Symlink points outside repo root — skipped.",
    },
    "path_outside_root": {
        "type": "path_outside_root",
        "severity": "warning",
        "description": "File path resolves outside repo root — skipped.",
    },
    "skipped_file": {
        "type": "skipped_file",
        "severity": "info",
        "description": "File was skipped during indexing.",
    },
    "low_confidence_edge": {
        "type": "low_confidence_edge",
        "severity": "info",
        "description": "Edge has low confidence and may be inaccurate.",
    },
    "unresolved_call": {
        "type": "unresolved_call",
        "severity": "info",
        "description": "Call target could not be resolved.",
    },
    "external_symbol": {
        "type": "external_symbol",
        "severity": "info",
        "description": "Symbol is external to the indexed project.",
    },
    "sqlite_chunking_applied": {
        "type": "sqlite_chunking_applied",
        "severity": "info",
        "description": "SQLite batch write was chunked to stay within parameter limits.",
    },
    "fuzzy_match": {
        "type": "fuzzy_match",
        "severity": "info",
        "description": "Symbol was resolved via fuzzy matching.",
    },
    "index_missing": {
        "type": "index_missing",
        "severity": "warning",
        "description": "No index found for the project.",
    },
}


def build_warning(
    wtype: str,
    message: str = "",
    evidence: dict[str, Any] | None = None,
    reason_code: str = "",
) -> dict[str, Any]:
    """Build a structured warning dict from a registered type.

    Args:
        wtype: Key from ``WARNING_TYPES``.
        message: Human-readable message (uses default if empty).
        evidence: Optional dict with evidence fields (file paths, counts, etc.).
        reason_code: Machine-readable reason code.

    Returns a dict with keys: ``type``, ``severity``, ``message``, ``reason_code``,
    and any keys from *evidence* merged in.
    """
    template = WARNING_TYPES.get(wtype, {})
    result: dict[str, Any] = {
        "type": wtype,
        "severity": template.get("severity", "info"),
        "message": message or template.get("description", ""),
        "reason_code": reason_code or wtype,
    }
    if evidence:
        result.update(evidence)
    return result


def build_stale_index_warning(
    changed_files: list[str] | None = None,
    added_files: list[str] | None = None,
    deleted_files: list[str] | None = None,
) -> dict[str, Any]:
    """Build a ``stale_index`` warning with file change evidence."""
    evidence: dict[str, Any] = {}
    if changed_files:
        evidence["changed_files"] = changed_files[:10]
    if added_files:
        evidence["added_files"] = added_files[:10]
    if deleted_files:
        evidence["deleted_files"] = deleted_files[:10]

    total = len(changed_files or []) + len(added_files or []) + len(deleted_files or [])
    message = f"Index is stale — {total} file(s) changed."

    return build_warning(
        "stale_index",
        message=message,
        evidence=evidence,
        reason_code="stale_index",
    )
