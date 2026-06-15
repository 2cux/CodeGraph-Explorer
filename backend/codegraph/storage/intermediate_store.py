"""Store for .codegraph/intermediate/ — batch enrichment and validation artifacts.

Manages:
- Batch enrichment output files (``enrich-batch-{timestamp}-{batch_id}.json``)
- Validation reports (``validation-report.json``)
- Audit trail for tracing which batch produced which enrichment
- Batch pruning to prevent unbounded disk growth
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class IntermediateStore:
    """Manage batch enrichment files and validation artifacts.

    Usage::

        store = IntermediateStore(cg_dir)
        batch_path = store.write_batch("prepare", prepare_data)
        store.write_validation_report(validation_result)
        trail = store.audit_trail()
    """

    def __init__(self, cg_dir: Path) -> None:
        self._dir = cg_dir / "intermediate"
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def dir(self) -> Path:
        """Path to the intermediate directory."""
        return self._dir

    # ── Batch files ─────────────────────────────────────────────────────

    def write_batch(self, batch_id: str, data: dict[str, Any]) -> Path:
        """Write a batch enrichment output file.

        Args:
            batch_id: Short identifier for this batch (e.g. "prepare",
                      "symbols-001", "files-002").
            data: The enrichment data to serialize as JSON.

        Returns:
            Path to the written batch file.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"enrich-batch-{timestamp}-{batch_id}.json"
        path = self._dir / filename
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return path

    def read_batch(self, path: Path) -> dict[str, Any] | None:
        """Read a batch file, returning None if missing or corrupt.

        Args:
            path: Path to the batch JSON file (can be relative to
                  intermediate dir or absolute).

        Returns:
            Parsed dict, or None.
        """
        target = path if path.is_absolute() else self._dir / path
        if not target.exists():
            return None
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def list_batches(self) -> list[Path]:
        """List all batch files, sorted by timestamp (newest first)."""
        return sorted(
            self._dir.glob("enrich-batch-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def latest_batch(self) -> Path | None:
        """Return the most recent batch file, or None if no batches exist."""
        batches = self.list_batches()
        return batches[0] if batches else None

    # ── Validation report ───────────────────────────────────────────────

    def write_validation_report(self, result: Any) -> Path:
        """Write ``validation-report.json`` to the intermediate directory.

        Args:
            result: A Pydantic model (with ``model_dump()``) or a plain
                    dict with validation results.

        Returns:
            Path to the written report.
        """
        path = self._dir / "validation-report.json"
        if hasattr(result, "model_dump"):
            data = result.model_dump()
        elif isinstance(result, dict):
            data = result
        else:
            data = {"result": str(result)}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return path

    def read_validation_report(self) -> dict[str, Any] | None:
        """Read the last validation report, or None if missing/corrupt."""
        path = self._dir / "validation-report.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # ── Audit trail ─────────────────────────────────────────────────────

    def audit_trail(self) -> list[dict[str, str]]:
        """Return an audit trail of all batch files.

        Each entry includes:
        - ``batch_file``: filename
        - ``file_count``: number of enriched files in the batch
        - ``symbol_count``: number of enriched symbols in the batch
        - ``enriched_at``: ISO timestamp from the batch data (if present)

        Returns:
            List of audit entries, newest first.
        """
        trail: list[dict[str, str]] = []
        for batch in self.list_batches():
            try:
                data = json.loads(batch.read_text(encoding="utf-8"))
                trail.append({
                    "batch_file": batch.name,
                    "file_count": str(len(data.get("files", []))),
                    "symbol_count": str(len(data.get("symbols", []))),
                    "enriched_at": data.get("enriched_at", ""),
                })
            except Exception:
                trail.append({
                    "batch_file": batch.name,
                    "file_count": "?",
                    "symbol_count": "?",
                    "enriched_at": "",
                })
        return trail

    # ── Maintenance ─────────────────────────────────────────────────────

    def prune_batches(self, keep: int = 10) -> int:
        """Remove old batch files, keeping the most recent ``keep``.

        Args:
            keep: Number of most recent batch files to retain.

        Returns:
            Number of batch files removed.
        """
        batches = self.list_batches()
        removed = 0
        for batch in batches[keep:]:
            batch.unlink()
            removed += 1
        return removed

    def clear_all(self) -> int:
        """Remove all intermediate files. Returns count of files removed."""
        count = 0
        for f in self._dir.glob("*"):
            if f.is_file():
                f.unlink()
                count += 1
        return count
