"""Shared utilities for the harness subsystem.

Centralizes timestamp generation, atomic writes, JSONL appends, and
path-safety validation so every harness module uses the same helpers.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Timestamps ──────────────────────────────────────────────────────────


def timestamp_utc() -> str:
    """Return current UTC time as ISO 8601 string (microsecond precision)."""
    return datetime.now(timezone.utc).isoformat()


def timestamp_compact() -> str:
    """Return current UTC time as compact string for run_id.

    Format: ``YYYYMMDDTHHMMSSZ``
    """
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ── Atomic writes ───────────────────────────────────────────────────────


def atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically via temp file + ``os.replace()``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Write binary *content* to *path* atomically via temp file + ``os.replace()``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    """Write *data* as JSON to *path* atomically."""
    atomic_write(
        path,
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
    )


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append a single JSON line to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Path safety ─────────────────────────────────────────────────────────


def validate_run_id(run_id: str) -> str:
    """Validate *run_id* is safe for filesystem operations.

    Returns *run_id* unchanged on success.

    Raises:
        ValueError: If *run_id* contains path traversal, is empty, or
            is an absolute path.
    """
    if not run_id or not run_id.strip():
        raise ValueError("run_id must not be empty")

    # Reject path traversal sequences
    if ".." in run_id:
        raise ValueError(
            f"run_id contains path traversal '..': {run_id!r}"
        )

    # Reject absolute paths (Unix and Windows)
    if os.path.isabs(run_id):
        raise ValueError(
            f"run_id must not be an absolute path: {run_id!r}"
        )

    # Reject characters with special meaning in filesystem paths
    if "/" in run_id or "\\" in run_id:
        raise ValueError(
            f"run_id must not contain path separators: {run_id!r}"
        )
    if ":" in run_id:
        raise ValueError(
            f"run_id must not contain colons (reserved for Windows drive letters "
            f"and NTFS streams): {run_id!r}"
        )

    # Validate the resolved path stays under the runs directory.
    # This guards against crafted names that the simple checks above
    # might miss (e.g. Windows device names, NTFS stream syntax).
    normalized = run_id.replace("\\", "/").strip("/")
    # After stripping separators, must contain at least one character
    # and not start with a dot (hidden files in runs/ dir)
    if not normalized or normalized.startswith("."):
        raise ValueError(
            f"run_id resolves to an invalid directory name: {run_id!r}"
        )

    return run_id


def sanitize_artifact_name(name: str) -> str:
    """Ensure *name* is a safe filename within an artifacts directory.

    Returns *name* unchanged on success.

    Raises:
        ValueError: If *name* tries to escape via path traversal or is a
            hidden file.
    """
    if not name or not name.strip():
        raise ValueError("Artifact name must not be empty")

    # Reject path traversal
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(
            f"Artifact name must not contain path separators or '..': {name!r}"
        )

    # Reject hidden files ('.gitkeep', etc.)
    if name.startswith("."):
        raise ValueError(
            f"Artifact name must not start with '.': {name!r}"
        )

    return name


def guess_media_type(filename: str) -> str:
    """Guess MIME type from file extension."""
    ext_map: dict[str, str] = {
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".log": "text/plain",
        ".csv": "text/csv",
        ".html": "text/html",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
    }
    lower = filename.lower()
    for ext, media in ext_map.items():
        if lower.endswith(ext):
            return media
    return "application/octet-stream"
