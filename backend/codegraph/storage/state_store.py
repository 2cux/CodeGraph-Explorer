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
        """Record pending file changes before sync (legacy flat format).

        Deprecated: prefer ``set_pending_changes_v2()`` which stores
        per-file ``PendingFileChange`` records with mtime, synced status,
        affected symbols, and response visibility.
        """
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

    # ── Per-file pending changes (v2) ───────────────────────────────────

    def set_pending_changes_v2(
        self,
        changed: "list[PendingFileChange]",
        added: "list[PendingFileChange]",
        deleted: "list[PendingFileChange]",
    ) -> None:
        """Record per-file pending changes before sync.

        Each entry is a ``PendingFileChange`` with file_path, mtime,
        synced status, affected_symbols, and appeared_in_response.
        """
        from codegraph.storage.pending_models import PendingFileChange

        current = self.load()
        current["pending_changes"] = {
            "changed": [pc.model_dump() for pc in changed],
            "added": [pc.model_dump() for pc in added],
            "deleted": [pc.model_dump() for pc in deleted],
        }
        self.save(current)

    def get_pending_changes(self) -> "PendingChangeSet":
        """Load pending changes as a structured ``PendingChangeSet``.

        Handles backward-compatible migration: if the stored data is in
        the old flat-string format, it is auto-upgraded to per-file records
        with minimal fields populated.
        """
        from codegraph.storage.pending_models import PendingChangeSet, PendingFileChange

        current = self.load()
        raw = current.get("pending_changes", {"changed": [], "added": [], "deleted": []})

        def _parse_list(items: list, default_change_type: str) -> list[PendingFileChange]:
            result: list[PendingFileChange] = []
            for item in items:
                if isinstance(item, str):
                    # Legacy flat format — auto-upgrade
                    result.append(PendingFileChange(
                        file_path=item,
                        mtime=0.0,
                        change_type=default_change_type,
                    ))
                elif isinstance(item, dict):
                    try:
                        result.append(PendingFileChange.model_validate(item))
                    except Exception:
                        # Skip malformed entries
                        continue
            return result

        return PendingChangeSet(
            changed=_parse_list(raw.get("changed", []), "structural"),
            added=_parse_list(raw.get("added", []), "added"),
            deleted=_parse_list(raw.get("deleted", []), "deleted"),
        )

    def mark_appeared_in_response(self, file_paths: set[str]) -> None:
        """Mark that these pending files appeared in the current MCP response.

        Call this after building an MCP response that references symbols
        from pending files, so the agent can see which pending changes
        are reflected in the current response.
        """
        current = self.load()
        raw = current.get("pending_changes", {})
        for category in ("changed", "added", "deleted"):
            entries = raw.get(category, [])
            for entry in entries:
                if isinstance(entry, dict) and entry.get("file_path") in file_paths:
                    entry["appeared_in_response"] = True
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

    def record_change_summary(self, summary: dict[str, int]) -> None:
        """Record the last change classification summary."""
        current = self.load()
        current["last_change_summary"] = summary
        self.save(current)

    def record_incremental_stats(self, stats: dict) -> None:
        """Record performance stats from the last incremental index run."""
        current = self.load()
        current["last_incremental_stats"] = stats
        self.save(current)

    def get_hook_config(self) -> dict:
        """Return the hook configuration section from state."""
        current = self.load()
        return current.get("hook", self._default_state()["hook"])

    def update_hook_config(self, **kwargs: object) -> None:
        """Partially update hook config fields.

        Accepts keyword arguments matching the hook config keys, e.g.::

            store.update_hook_config(installed=True, hook_path="/path/to/hook")
        """
        current = self.load()
        hook = dict(current.get("hook", self._default_state()["hook"]))
        hook.update({k: v for k, v in kwargs.items() if k in hook})
        current["hook"] = hook
        self.save(current)

    def record_hook_run(self, exit_code: int, duration_ms: float) -> None:
        """Record a hook execution result.

        Increments run counters and updates last-run timestamps.

        Args:
            exit_code: Process exit code (0 = success).
            duration_ms: Wall-clock duration in milliseconds.
        """
        from datetime import datetime, timezone

        current = self.load()
        hook = dict(current.get("hook", self._default_state()["hook"]))
        now = datetime.now(timezone.utc).isoformat()
        hook["last_run_at"] = now
        hook["last_run_exit_code"] = exit_code
        hook["last_run_duration_ms"] = duration_ms
        hook["total_runs"] = hook.get("total_runs", 0) + 1
        if exit_code != 0:
            hook["total_failures"] = hook.get("total_failures", 0) + 1
        current["hook"] = hook
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
            "last_change_summary": {
                "none": 0,
                "cosmetic": 0,
                "structural": 0,
                "architecture": 0,
                "added": 0,
                "deleted": 0,
                "full_reindex_required": 0,
            },
            "last_incremental_stats": {
                "changed_files": 0,
                "reparsed_files": 0,
                "dependent_files": 0,
                "deleted_nodes": 0,
                "inserted_nodes": 0,
                "deleted_edges": 0,
                "inserted_edges": 0,
                "duration_ms": 0,
                "full_replace": False,
            },
            "hook": {
                "auto_update_on_commit": True,
                "installed": False,
                "installed_at": None,
                "hook_path": None,
                "last_run_at": None,
                "last_run_exit_code": None,
                "last_run_duration_ms": None,
                "total_runs": 0,
                "total_failures": 0,
            },
        }
