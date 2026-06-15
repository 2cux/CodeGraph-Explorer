"""Checkpoint manager — record module progress snapshots.

Matches PRD Section 26.4.5 CheckpointManager specification.

v1 rules:
- Append-only to ``checkpoints.jsonl``.
- Does NOT pause execution.
- Does NOT wait for user input.
- Does NOT implement resume.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codegraph.harness.models import HarnessCheckpoint
from codegraph.harness.utils import timestamp_utc


class CheckpointManager:
    """Manage checkpoint recording for a single run.

    v1: record-only — appends to a JSONL file on disk.
    No pause, no user prompt, no resume.

    Usage::

        cpm = CheckpointManager(store.run_dir(run_id))
        cp = cpm.record_checkpoint("symbols resolved", {"count": 42})
    """

    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "checkpoints.jsonl"

    @property
    def path(self) -> Path:
        """Path to the ``checkpoints.jsonl`` file."""
        return self._path

    # ── Recording ──────────────────────────────────────────────────────

    def record_checkpoint(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
    ) -> HarnessCheckpoint:
        """Record a checkpoint by appending to ``checkpoints.jsonl``.

        Args:
            name: Human-readable label (e.g. ``"symbols resolved"``).
            payload: Arbitrary snapshot data defined by the module.

        Returns:
            The recorded ``HarnessCheckpoint``.
        """
        now = timestamp_utc()
        cp = HarnessCheckpoint(
            name=name,
            status="recorded",
            payload=payload or {},
            created_at=now,
        )

        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(cp.model_dump(), ensure_ascii=False, default=str)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        return cp

    # ── Reading ────────────────────────────────────────────────────────

    def list_checkpoints(self) -> list[HarnessCheckpoint]:
        """Read all checkpoints from the JSONL file.

        Returns checkpoints in the order they were recorded (oldest first).
        """
        results: list[HarnessCheckpoint] = []
        if not self._path.exists():
            return results
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    results.append(HarnessCheckpoint.model_validate(data))
                except (json.JSONDecodeError, ValueError):
                    continue
        except OSError:
            return results
        return results

    def get_checkpoint(self, name: str) -> HarnessCheckpoint | None:
        """Find a checkpoint by name (returns the first match).

        Returns ``None`` if no checkpoint with that name exists.
        """
        for cp in self.list_checkpoints():
            if cp.name == name:
                return cp
        return None
