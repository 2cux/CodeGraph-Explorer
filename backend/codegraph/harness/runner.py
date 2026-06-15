"""Harness runner that manages the full run lifecycle."""

from __future__ import annotations

import os
import secrets
import shutil
import traceback
from pathlib import Path
from typing import Any

from codegraph.harness.artifacts import ArtifactManager
from codegraph.harness.checkpoints import CheckpointManager
from codegraph.harness.context import HarnessRunContext
from codegraph.harness.models import (
    HarnessModuleManifest,
    HarnessRunResult,
    HarnessRunState,
    RunStatus,
)
from codegraph.harness.registry import get_module
from codegraph.harness.store import RunStore
from codegraph.harness.utils import (
    atomic_write_json,
    timestamp_compact,
    timestamp_utc,
    validate_run_id,
)


class HarnessRunner:
    """Unified execution engine for harness modules."""

    def __init__(self, store: RunStore | None = None) -> None:
        self._store = store or RunStore()

    def run(
        self,
        module_id: str,
        input_data: dict[str, Any],
        project_root: Path | None = None,
        persist: bool = True,
        run_id: str | None = None,
    ) -> HarnessRunResult:
        """Execute a registered harness module and persist run state."""
        resolved_root = self._resolve_project_root(project_root)
        module = get_module(module_id)
        if module is None:
            raise ValueError(f"Unknown harness module: {module_id}")

        manifest = self._load_manifest(module, module_id)
        effective_run_id = run_id or self._generate_run_id(module_id)
        validate_run_id(effective_run_id)

        run_dir = self._runs_base_dir(resolved_root) / effective_run_id
        if run_dir.exists():
            raise FileExistsError(f"Harness run already exists: {effective_run_id}")

        state = self._create_run_state(
            run_id=effective_run_id,
            module_id=module_id,
            project_root=resolved_root,
        )
        ctx: HarnessRunContext | None = None

        try:
            self._initialize_run_files(
                run_dir=run_dir,
                manifest=manifest,
                input_data=input_data,
                state=state,
            )
            ctx = self._create_context(run_dir, resolved_root, state)
            ctx.event("run.created", {"run_id": effective_run_id, "module_id": module_id})

            state.status = RunStatus.RUNNING
            state.started_at = timestamp_utc()
            self._write_state(run_dir, state)
            ctx.event("module.started", {"module_id": module_id})

            output = module.run(ctx, input_data)
            if output is None:
                output = {}
            if not isinstance(output, dict):
                raise TypeError(
                    f"Module {module_id} returned {type(output).__name__}, expected dict"
                )

            atomic_write_json(run_dir / "output.json", output)
            state.output_path = "output.json"
            state.status = RunStatus.SUCCEEDED
            state.finished_at = timestamp_utc()
            state.error = None
            self._write_state(run_dir, state)
            ctx.event("module.finished", {"module_id": module_id})
            return self._build_result(state=state, output=output, ctx=ctx)
        except Exception as exc:
            error_text = traceback.format_exc()
            partial_output = self._extract_partial_output(exc)
            if partial_output is not None:
                atomic_write_json(run_dir / "output.json", partial_output)
                state.output_path = "output.json"
            state.status = RunStatus.FAILED
            state.finished_at = timestamp_utc()
            state.error = error_text
            self._write_state(run_dir, state)
            if ctx is not None:
                ctx.log_error(str(exc))
                ctx.event(
                    "module.failed",
                    {
                        "module_id": module_id,
                        "error": str(exc),
                        "traceback": error_text,
                    },
                )
                return self._build_result(state=state, output=partial_output, ctx=ctx)
            return HarnessRunResult(
                run_id=state.run_id,
                module_id=state.module_id,
                status=state.status,
                output=partial_output,
                error=state.error,
                artifacts=[],
            )
        finally:
            if not persist and run_dir.exists():
                shutil.rmtree(run_dir)

    def _resolve_project_root(self, project_root: Path | None) -> Path:
        """Resolve the project root for a run."""
        if project_root is not None:
            return project_root.resolve()
        env_root = os.environ.get("CODEGRAPH_PROJECT_ROOT", "")
        if env_root:
            return Path(env_root).resolve()
        return Path.cwd().resolve()

    def _runs_base_dir(self, project_root: Path) -> Path:
        """Return ``<project_root>/.codegraph/runs`` for the active run."""
        runs_dir = project_root / ".codegraph" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        return runs_dir

    def _load_manifest(
        self,
        module: Any,
        module_id: str,
    ) -> HarnessModuleManifest:
        """Load and normalize the manifest for a registered module."""
        raw_manifest = getattr(module, "manifest", None)
        if raw_manifest is None:
            raise ValueError(f"Module {module_id} does not define a manifest")
        if isinstance(raw_manifest, HarnessModuleManifest):
            return raw_manifest
        if not isinstance(raw_manifest, dict):
            raise TypeError(
                f"Module {module_id} manifest must be a HarnessModuleManifest or dict"
            )
        data = dict(raw_manifest)
        data.setdefault("id", module_id)
        return HarnessModuleManifest.model_validate(data)

    def _generate_run_id(self, module_id: str) -> str:
        """Generate a human-readable run id."""
        module_slug = module_id.replace(".", "-").replace("_", "-")
        return f"{module_slug}-{timestamp_compact()}-{secrets.token_hex(2)}"

    def _create_run_state(
        self,
        *,
        run_id: str,
        module_id: str,
        project_root: Path,
    ) -> HarnessRunState:
        """Build the initial run state."""
        return HarnessRunState(
            run_id=run_id,
            module_id=module_id,
            status=RunStatus.CREATED,
            project_root=str(project_root),
            started_at=None,
            finished_at=None,
            input_path="input.json",
            output_path=None,
            artifacts_dir="artifacts/",
            logs_dir="logs/",
            checkpoints_path="checkpoints.jsonl",
            error=None,
        )

    def _create_context(
        self,
        run_dir: Path,
        project_root: Path,
        state: HarnessRunState,
    ) -> HarnessRunContext:
        """Create a run context with artifact and checkpoint managers."""
        return HarnessRunContext(
            run_state=state,
            run_dir=run_dir,
            project_root=project_root,
            artifacts=ArtifactManager(run_dir / "artifacts"),
            checkpoints=CheckpointManager(run_dir),
        )

    def _initialize_run_files(
        self,
        *,
        run_dir: Path,
        manifest: HarnessModuleManifest,
        input_data: dict[str, Any],
        state: HarnessRunState,
    ) -> None:
        """Create the run directory and write initial persisted files."""
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "manifest.json", manifest.model_dump(mode="json"))
        atomic_write_json(run_dir / "input.json", input_data)
        self._write_state(run_dir, state)

    def _write_state(self, run_dir: Path, state: HarnessRunState) -> None:
        """Persist ``state.json`` for the run."""
        atomic_write_json(run_dir / "state.json", state.model_dump(mode="json"))

    def _extract_partial_output(
        self,
        exc: Exception,
    ) -> dict[str, Any] | None:
        """Return a structured partial output payload if the exception carries one."""
        partial = getattr(exc, "partial_output", None)
        return partial if isinstance(partial, dict) else None

    def _build_result(
        self,
        *,
        state: HarnessRunState,
        output: dict[str, Any] | None,
        ctx: HarnessRunContext,
    ) -> HarnessRunResult:
        """Create the compact result returned to callers."""
        artifacts = [artifact.name for artifact in ctx.artifacts.list_artifacts()]
        return HarnessRunResult(
            run_id=state.run_id,
            module_id=state.module_id,
            status=state.status,
            output=output,
            error=state.error,
            artifacts=artifacts,
        )
