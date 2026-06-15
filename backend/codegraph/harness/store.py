"""Run persistence layer — manages .codegraph/runs/<run-id>/ directories.

Matches PRD Section 26.4.3 RunStore specification.

Each run directory contains::

    .codegraph/runs/<run-id>/
      state.json
      input.json
      output.json
      events.jsonl
      checkpoints.jsonl
      logs/
        stdout.log
        stderr.log
      artifacts/
        report.md
        report.json
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codegraph.harness.models import HarnessRunState, RunStatus
from codegraph.harness.utils import (
    append_jsonl,
    atomic_write_json,
    timestamp_compact,
    timestamp_utc,
    validate_run_id,
)


def _generate_run_id(module_id: str) -> str:
    """Generate a unique, human-readable run identifier.

    Format: ``{module-hyphenated}-{timestamp}-{4-hex}``

    Example: ``workflow-impact-20260615T103012Z-a8f3``
    """
    module_slug = module_id.replace(".", "-").replace("_", "-")
    ts = timestamp_compact()
    suffix = secrets.token_hex(2)  # 4 hex chars
    return f"{module_slug}-{ts}-{suffix}"


# ── Root resolution ─────────────────────────────────────────────────────


def _resolve_project_root() -> Path:
    """Resolve the project root, matching the pattern from ``api/deps.py``."""
    env_root = os.environ.get("CODEGRAPH_PROJECT_ROOT", "")
    if env_root:
        return Path(env_root).resolve()
    return Path.cwd()


def _resolve_codegraph_dir() -> Path:
    """Resolve the ``.codegraph/`` directory, creating it if needed."""
    root = _resolve_project_root()
    cg_dir = root / ".codegraph"
    cg_dir.mkdir(parents=True, exist_ok=True)
    return cg_dir


# ── RunStore ────────────────────────────────────────────────────────────


class RunStore:
    """Manage run persistence under ``.codegraph/runs/``.

    Usage::

        store = RunStore()
        run = store.create_run("workflow.impact", input_params={"files": ["src/a.py"]})
        store.update_run_status(run.run_id, RunStatus.RUNNING)
        # ... execute module ...
        store.write_output(run.run_id, {"impact": {...}})
        store.update_run_status(run.run_id, RunStatus.SUCCEEDED)
    """

    def __init__(self) -> None:
        cg_dir = _resolve_codegraph_dir()
        self._base_dir = cg_dir / "runs"
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def base_dir(self) -> Path:
        """Path to ``.codegraph/runs/``."""
        return self._base_dir

    # ── Internal path builder (single point of path construction) ──────

    def _run_path(self, run_id: str) -> Path:
        """Return the absolute path to a run's directory.

        Validates *run_id* for path-traversal safety before constructing
        the path.  Every public method that accepts a ``run_id`` routes
        through this method so there is exactly one place to audit.
        """
        validate_run_id(run_id)
        return self._base_dir / run_id

    # ── Run lifecycle ──────────────────────────────────────────────────

    def create_run(
        self,
        module_id: str,
        input_params: dict[str, Any] | None = None,
        project_root: str | None = None,
    ) -> HarnessRunState:
        """Create a new run directory and return its initial state.

        Args:
            module_id: Dotted module identifier, e.g. ``"workflow.impact"``.
            input_params: Optional input parameters to persist as ``input.json``.
            project_root: Optional project root override.

        Returns:
            The freshly created ``HarnessRunState``.
        """
        run_id = _generate_run_id(module_id)
        root = project_root or str(_resolve_project_root())
        run_dir = self._run_path(run_id)

        state = HarnessRunState(
            run_id=run_id,
            module_id=module_id,
            status=RunStatus.CREATED,
            project_root=root,
            started_at=None,
            finished_at=None,
            input_path="input.json" if input_params else None,
            output_path=None,
            artifacts_dir="artifacts/",
            logs_dir="logs/",
            checkpoints_path="checkpoints.jsonl",
            error=None,
        )

        # Create directory structure — fail if run_id already exists
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "logs").mkdir(exist_ok=True)
        (run_dir / "artifacts").mkdir(exist_ok=True)

        # Write state.json
        atomic_write_json(run_dir / "state.json", state.model_dump())

        # Write input.json if provided
        if input_params:
            atomic_write_json(run_dir / "input.json", input_params)

        return state

    def load_run(self, run_id: str) -> HarnessRunState | None:
        """Load a run's state from disk.

        Returns ``None`` if the run directory does not exist.
        """
        state_path = self._run_path(run_id) / "state.json"
        if not state_path.exists():
            return None
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            return HarnessRunState.model_validate(data)
        except (json.JSONDecodeError, OSError):
            return None

    def update_run(self, state: HarnessRunState) -> None:
        """Persist an updated run state to disk.

        Always writes, even on failure — failed runs must still record state.
        """
        run_dir = self._run_path(state.run_id)
        atomic_write_json(run_dir / "state.json", state.model_dump())

    def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
        finished_at: str | None = None,
    ) -> HarnessRunState | None:
        """Convenience: load, update status, and persist.

        Returns the updated state, or ``None`` if the run is not found.
        """
        state = self.load_run(run_id)
        if state is None:
            return None
        state.status = status
        if status == RunStatus.RUNNING and state.started_at is None:
            state.started_at = timestamp_utc()
        if status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
            state.finished_at = finished_at or timestamp_utc()
        if error:
            state.error = error
        self.update_run(state)
        return state

    # ── Input / Output ─────────────────────────────────────────────────

    def write_input(self, run_id: str, params: dict[str, Any]) -> None:
        """Write (or overwrite) the run's ``input.json``.

        The run must already exist (created via ``create_run``).
        """
        run_dir = self._run_path(run_id)
        if not run_dir.is_dir():
            raise FileNotFoundError(
                f"Run directory does not exist: {run_dir}. "
                f"Call create_run() first."
            )
        atomic_write_json(run_dir / "input.json", params)

        # Update state to reflect input_path
        state = self.load_run(run_id)
        if state:
            state.input_path = "input.json"
            self.update_run(state)

    def write_output(self, run_id: str, output: dict[str, Any]) -> None:
        """Write the run's ``output.json``.

        The run must already exist (created via ``create_run``).
        """
        run_dir = self._run_path(run_id)
        if not run_dir.is_dir():
            raise FileNotFoundError(
                f"Run directory does not exist: {run_dir}. "
                f"Call create_run() first."
            )
        atomic_write_json(run_dir / "output.json", output)

        # Update state to reflect output_path
        state = self.load_run(run_id)
        if state:
            state.output_path = "output.json"
            self.update_run(state)

    def read_output(self, run_id: str) -> dict[str, Any] | None:
        """Read a run's ``output.json``, or ``None`` if missing."""
        output_path = self._run_path(run_id) / "output.json"
        if not output_path.exists():
            return None
        try:
            return json.loads(output_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # ── Event / Checkpoint appends ──────────────────────────────────────

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        """Append a single event record to ``events.jsonl``."""
        path = self._run_path(run_id) / "events.jsonl"
        append_jsonl(path, event)

    def append_checkpoint(self, run_id: str, checkpoint: dict[str, Any]) -> None:
        """Append a single checkpoint record to ``checkpoints.jsonl``."""
        path = self._run_path(run_id) / "checkpoints.jsonl"
        append_jsonl(path, checkpoint)

    # ── Listing ────────────────────────────────────────────────────────

    def list_runs(
        self,
        module_id: str | None = None,
        limit: int = 50,
    ) -> list[HarnessRunState]:
        """List recent runs, optionally filtered by module.

        Results are sorted by modification time (newest first).
        Directories whose ``stat()`` fails (e.g. permission errors) are
        silently skipped.
        """
        runs: list[HarnessRunState] = []

        # Collect (mtime, path) pairs, skipping entries whose stat() fails
        entries: list[tuple[float, Path]] = []
        try:
            for rd in self._base_dir.iterdir():
                if not rd.is_dir():
                    continue
                try:
                    entries.append((rd.stat().st_mtime, rd))
                except OSError:
                    # Permission error or deleted between iterdir and stat
                    continue
        except OSError:
            return runs

        # Sort by mtime descending
        entries.sort(key=lambda e: e[0], reverse=True)

        for _mtime, rd in entries:
            state_path = rd / "state.json"
            if not state_path.exists():
                continue
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                state = HarnessRunState.model_validate(data)
                if module_id and state.module_id != module_id:
                    continue
                runs.append(state)
                if len(runs) >= limit:
                    break
            except (json.JSONDecodeError, OSError):
                continue
        return runs

    # ── Deletion / Pruning ─────────────────────────────────────────────

    def delete_run(self, run_id: str) -> bool:
        """Delete a run directory and all its contents.

        Returns ``True`` if deleted, ``False`` if not found.
        """
        run_dir = self._run_path(run_id)
        # Resolve to catch symlinks / .. tricks that survived validation
        resolved = run_dir.resolve()
        if not resolved.is_relative_to(self._base_dir.resolve()):
            raise ValueError(
                f"Run directory {str(resolved)!r} is outside the runs directory"
            )
        if not resolved.exists():
            return False
        shutil.rmtree(resolved)
        return True

    def prune_runs(self, keep_days: int = 30) -> int:
        """Remove runs older than *keep_days*.

        Returns the number of directories removed.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - (keep_days * 86400)
        removed = 0
        try:
            for rd in self._base_dir.iterdir():
                if not rd.is_dir():
                    continue
                try:
                    if rd.stat().st_mtime < cutoff:
                        shutil.rmtree(rd)
                        removed += 1
                except OSError:
                    continue
        except OSError:
            pass
        return removed

    # ── Path helpers ───────────────────────────────────────────────────

    def run_dir(self, run_id: str) -> Path:
        """Return the absolute path to a run's directory."""
        return self._run_path(run_id)

    def artifacts_dir(self, run_id: str) -> Path:
        """Return the absolute path to a run's artifacts directory."""
        return self._run_path(run_id) / "artifacts"

    def logs_dir(self, run_id: str) -> Path:
        """Return the absolute path to a run's logs directory."""
        return self._run_path(run_id) / "logs"
