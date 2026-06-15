"""Run context for harness module execution.

Provides a small v1 API for events, checkpoints, artifacts, and logs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.harness.artifacts import ArtifactManager
from codegraph.harness.checkpoints import CheckpointManager
from codegraph.harness.models import HarnessArtifact, HarnessCheckpoint, HarnessRunState
from codegraph.harness.utils import append_jsonl, timestamp_utc


class HarnessRunContext:
    """Runtime context passed to a harness module's ``run()`` method."""

    def __init__(
        self,
        *,
        run_state: HarnessRunState,
        run_dir: Path,
        project_root: Path,
        artifacts: ArtifactManager,
        checkpoints: CheckpointManager,
    ) -> None:
        self.run_state = run_state
        self.run_dir = run_dir
        self.project_root = project_root
        self.artifacts = artifacts
        self.checkpoints = checkpoints
        self._events_path = run_dir / "events.jsonl"
        self._stdout_log_path = run_dir / "logs" / "stdout.log"
        self._stderr_log_path = run_dir / "logs" / "stderr.log"

    @property
    def run_id(self) -> str:
        """Return the active run identifier."""
        return self.run_state.run_id

    @property
    def module_id(self) -> str:
        """Return the active module identifier."""
        return self.run_state.module_id

    def event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an event to ``events.jsonl``."""
        record = {
            "time": timestamp_utc(),
            "type": event_type,
            "payload": payload or {},
        }
        append_jsonl(self._events_path, record)
        return record

    def checkpoint(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
    ) -> HarnessCheckpoint:
        """Record a checkpoint and emit the matching lifecycle event."""
        checkpoint = self.checkpoints.record_checkpoint(name, payload)
        self.event(
            "checkpoint.recorded",
            {"name": name, "payload": payload or {}},
        )
        return checkpoint

    def artifact_text(self, name: str, content: str) -> HarnessArtifact:
        """Write a text artifact and emit ``artifact.written``."""
        artifact = self.artifacts.write_text_artifact(name, content)
        self.event(
            "artifact.written",
            {"name": artifact.name, "media_type": artifact.media_type},
        )
        return artifact

    def artifact_json(
        self,
        name: str,
        data: dict[str, Any] | list[Any],
    ) -> HarnessArtifact:
        """Write a JSON artifact and emit ``artifact.written``."""
        artifact = self.artifacts.write_json_artifact(name, data)
        self.event(
            "artifact.written",
            {"name": artifact.name, "media_type": artifact.media_type},
        )
        return artifact

    def log_info(self, message: str) -> None:
        """Append an INFO message to ``logs/stdout.log``."""
        self._write_log("INFO", message, self._stdout_log_path)

    def log_warning(self, message: str) -> None:
        """Append a WARNING message to ``logs/stderr.log``."""
        self._write_log("WARNING", message, self._stderr_log_path)

    def log_error(self, message: str) -> None:
        """Append an ERROR message to ``logs/stderr.log``."""
        self._write_log("ERROR", message, self._stderr_log_path)

    def _write_log(self, level: str, message: str, path: Path) -> None:
        """Append a plain-text log line to the selected log file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        line = f"[{timestamp_utc()}] {level} {message}\n"
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
