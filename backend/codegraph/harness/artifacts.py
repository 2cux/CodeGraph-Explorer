"""Artifact manager — write and list run artifacts safely.

Matches PRD Section 26.4.4 ArtifactManager specification.

All artifact paths are restricted to the current run's ``artifacts/``
directory. Arbitrary path writes outside that directory are forbidden.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codegraph.harness.models import HarnessArtifact
from codegraph.harness.utils import (
    atomic_write,
    atomic_write_bytes,
    guess_media_type,
    sanitize_artifact_name,
    timestamp_utc,
)


class ArtifactManager:
    """Manage artifact files within a single run's ``artifacts/`` directory.

    Usage::

        mgr = ArtifactManager(store.artifacts_dir(run_id))
        art = mgr.write_text_artifact("report.md", "# My Report\\n...")
        arts = mgr.list_artifacts()
    """

    def __init__(self, artifacts_dir: Path) -> None:
        self._dir = artifacts_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def dir(self) -> Path:
        """Path to the artifacts directory."""
        return self._dir

    # ── Public write helpers ───────────────────────────────────────────

    def write_text_artifact(
        self,
        name: str,
        content: str,
        *,
        media_type: str | None = None,
    ) -> HarnessArtifact:
        """Write a text artifact and return its metadata.

        Args:
            name: Safe filename within the artifacts directory (e.g. ``"report.md"``).
            content: Text content to write.
            media_type: Optional MIME type override.
        """
        safe_name = sanitize_artifact_name(name)
        path = self._dir / safe_name
        atomic_write(path, content)
        return self._record(safe_name, media_type or guess_media_type(safe_name))

    def write_json_artifact(
        self,
        name: str,
        data: dict[str, Any] | list[Any],
        *,
        media_type: str = "application/json",
    ) -> HarnessArtifact:
        """Write a JSON artifact and return its metadata.

        Args:
            name: Safe filename (e.g. ``"report.json"``).
            data: JSON-serializable dict or list.
            media_type: MIME type override.
        """
        safe_name = sanitize_artifact_name(name)
        path = self._dir / safe_name
        atomic_write(
            path,
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
        )
        return self._record(safe_name, media_type)

    def write_bytes_artifact(
        self,
        name: str,
        content: bytes,
        *,
        media_type: str = "application/octet-stream",
    ) -> HarnessArtifact:
        """Write a binary artifact and return its metadata."""
        safe_name = sanitize_artifact_name(name)
        path = self._dir / safe_name
        atomic_write_bytes(path, content)
        return self._record(safe_name, media_type)

    # ── Listing ────────────────────────────────────────────────────────

    def list_artifacts(self) -> list[HarnessArtifact]:
        """List all artifacts in this run's artifacts directory.

        Returns artifacts sorted by creation time (newest first), inferred
        from file modification time.
        """
        results: list[HarnessArtifact] = []
        if not self._dir.exists():
            return results
        for f in sorted(
            self._dir.iterdir(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            if f.is_file():
                results.append(
                    HarnessArtifact(
                        name=f.name,
                        path=f.name,  # relative to artifacts dir
                        media_type=guess_media_type(f.name),
                        size_bytes=f.stat().st_size,
                        created_at=datetime.fromtimestamp(
                            f.stat().st_mtime, tz=timezone.utc
                        ).isoformat(),
                    )
                )
        return results

    def get_artifact(self, name: str) -> HarnessArtifact | None:
        """Get a single artifact by name, or ``None`` if not found."""
        safe_name = sanitize_artifact_name(name)
        path = self._dir / safe_name
        if not path.exists():
            return None
        return HarnessArtifact(
            name=safe_name,
            path=safe_name,
            media_type=guess_media_type(safe_name),
            size_bytes=path.stat().st_size,
            created_at=datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
        )

    # ── Internal helpers ───────────────────────────────────────────────

    def _record(self, name: str, media_type: str) -> HarnessArtifact:
        """Build a ``HarnessArtifact`` from a file that was just written."""
        path = self._dir / name
        size = path.stat().st_size if path.exists() else 0
        return HarnessArtifact(
            name=name,
            path=name,
            media_type=media_type,
            size_bytes=size,
            created_at=timestamp_utc(),
        )


# ── Module-level convenience ───────────────────────────────────────────

# Default artifact names used by modules that don't specify their own.
DEFAULT_TEXT_ARTIFACT = "report.md"
DEFAULT_JSON_ARTIFACT = "report.json"
