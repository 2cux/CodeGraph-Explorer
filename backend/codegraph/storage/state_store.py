"""Index state persistence for .codegraph/state.json.

Tracks index freshness, watch status, pending changes, and error state.
Used by repo_status, watch mode, and MCP tool responses.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class IndexStateStore:
    """Read/write .codegraph/state.json for tracking index status."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._path = base_dir / "state.json"

    def load(self) -> dict:
        """Load the current state, returning defaults if file is missing."""
        if not self._path.exists():
            return self._default_state()
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self._default_state()

    def save(self, state: dict) -> None:
        """Atomically write state to disk."""
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    def update_status(
        self,
        status: str,
        last_indexed_at: str | None = None,
        last_incremental_at: str | None = None,
        last_error: str | None = None,
    ) -> None:
        """Update the index status fields, preserving other state."""
        current = self.load()
        current["status"] = status
        if last_indexed_at is not None:
            current["last_indexed_at"] = last_indexed_at
        if last_incremental_at is not None:
            current["last_incremental_at"] = last_incremental_at
        current["last_error"] = last_error
        self.save(current)

    def set_pending_changes(
        self, changed: list[str], added: list[str], deleted: list[str],
    ) -> None:
        """Record pending file changes before sync."""
        current = self.load()
        current["pending_changes"] = {
            "changed": changed,
            "added": added,
            "deleted": deleted,
        }
        self.save(current)

    def clear_pending_changes(self) -> None:
        """Clear pending changes after successful sync."""
        current = self.load()
        current["pending_changes"] = {"changed": [], "added": [], "deleted": []}
        self.save(current)

    def mark_indexing(self) -> None:
        """Mark that indexing is in progress."""
        current = self.load()
        current["status"] = "indexing"
        self.save(current)

    def init_watch(self, debounce_ms: int = 500) -> None:
        """Initialize watch state."""
        current = self.load()
        current["watch"] = {
            "enabled": True,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "debounce_ms": debounce_ms,
        }
        self.save(current)

    def disable_watch(self) -> None:
        """Mark watch as disabled."""
        current = self.load()
        current["watch"]["enabled"] = False
        self.save(current)

    def record_deleted_files(self, deleted_files: list[str]) -> None:
        """Append to the deleted_files tracking list."""
        current = self.load()
        existing = set(current.get("deleted_files", []))
        existing.update(deleted_files)
        current["deleted_files"] = sorted(existing)
        self.save(current)

    def clear_deleted_files(self) -> None:
        """Clear the deleted_files tracking list."""
        current = self.load()
        current["deleted_files"] = []
        self.save(current)

    def record_stats(self, symbols: int, edges: int) -> None:
        """Record node/edge counts from SQLite into state.json."""
        current = self.load()
        current["stats"] = {
            "symbols": symbols,
            "edges": edges,
        }
        self.save(current)

    @staticmethod
    def _default_state() -> dict:
        return {
            "status": "missing",
            "last_indexed_at": None,
            "last_incremental_at": None,
            "last_error": None,
            "deleted_files": [],
            "pending_changes": {
                "changed": [],
                "added": [],
                "deleted": [],
            },
            "watch": {
                "enabled": False,
                "started_at": None,
                "debounce_ms": 500,
            },
        }
