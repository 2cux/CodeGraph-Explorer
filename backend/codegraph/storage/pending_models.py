"""Per-file pending change models for state.json.

Replaces the legacy flat ``pending_changes: {changed: [str], added: [str],
deleted: [str]}`` format with structured per-file records that include
mtime, sync status, affected symbols, and response visibility.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PendingFileChange(BaseModel):
    """Per-file pending change record stored in state.json.

    Each record tracks whether a changed file has been synced to the
    index and whether it appeared in the current MCP response.
    """

    file_path: str
    mtime: float = 0.0
    synced: bool = False
    affected_symbols: list[str] = Field(default_factory=list)
    appeared_in_response: bool = False
    change_type: str = ""  # "cosmetic" | "structural" | "architecture" | "added" | "deleted"


class PendingChangeSet(BaseModel):
    """Container for all pending changes grouped by change category."""

    changed: list[PendingFileChange] = Field(default_factory=list)
    added: list[PendingFileChange] = Field(default_factory=list)
    deleted: list[PendingFileChange] = Field(default_factory=list)

    @property
    def total(self) -> int:
        """Total number of pending changes across all categories."""
        return len(self.changed) + len(self.added) + len(self.deleted)

    def breakdown(self) -> dict[str, int]:
        """Return counts by change_type."""
        result: dict[str, int] = {}
        for pc in self.changed + self.added + self.deleted:
            ct = pc.change_type or "unknown"
            result[ct] = result.get(ct, 0) + 1
        return result

    def unsynced(self) -> list[PendingFileChange]:
        """Return all pending changes that have not been synced."""
        return [
            pc for pc in self.changed + self.added + self.deleted
            if not pc.synced
        ]
