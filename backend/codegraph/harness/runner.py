"""Harness runner that manages the full run lifecycle."""

from __future__ import annotations

import os
import secrets
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
        self._store = store

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
        store = self._resolve_store(resolved_root)
        module = get_module(module_id)
        if module is None:
            raise ValueError(f"Unknown harness module: {module_id}")

        manifest = self._load_manifest(module, module_id)
        effective_run_id = run_id or self._generate_run_id(module_id)
        validate_run_id(effective_run_id)

        state = store.create_run(
            module_id=module_id,
            input_params=input_data,
            project_root=str(resolved_root),
            run_id=effective_run_id,
        )
        run_dir = store.base_dir / state.run_id
        ctx: HarnessRunContext | None = None

        try:
            self._initialize_run_files(run_dir=run_dir, manifest=manifest)
            ctx = self._create_context(run_dir, resolved_root, state)
            ctx.event("run.created", {"run_id": effective_run_id, "module_id": module_id})

            state.status = RunStatus.RUNNING
            state.started_at = timestamp_utc()
            store.update_run(state)
            ctx.event("module.started", {"module_id": module_id})

            output = module.run(ctx, input_data)
            if output is None:
                output = {}
            if not isinstance(output, dict):
                raise TypeError(
                    f"Module {module_id} returned {type(output).__name__}, expected dict"
                )

            store.write_output(state.run_id, output)
            state.output_path = "output.json"
            state.status = RunStatus.SUCCEEDED
            state.finished_at = timestamp_utc()
            state.error = None
            store.update_run(state)
            ctx.event("module.finished", {"module_id": module_id})
            return self._build_result(state=state, output=output, ctx=ctx)
        except Exception as exc:
            error_text = traceback.format_exc()
            partial_output = self._extract_partial_output(exc)
            error_details = self._build_error_details(
                exc,
                traceback_text=error_text,
                module_id=module_id,
                run_id=state.run_id,
            )
            if partial_output is not None:
                store.write_output(state.run_id, partial_output)
                state.output_path = "output.json"
            state.status = RunStatus.FAILED
            state.finished_at = timestamp_utc()
            state.error = error_text
            store.update_run(state)
            if ctx is not None:
                ctx.log_error(error_details["message"])
                ctx.event("module.failed", error_details)
                return self._build_result(
                    state=state,
                    output=partial_output,
                    ctx=ctx,
                    error=error_details["public_message"],
                    error_details=error_details,
                )
            return HarnessRunResult(
                run_id=state.run_id,
                module_id=state.module_id,
                status=state.status,
                output=partial_output,
                error=error_details["public_message"],
                error_details=error_details,
                artifacts=[],
            )
        finally:
            if not persist and run_dir.exists():
                store.delete_run(state.run_id)

    def _resolve_project_root(self, project_root: Path | None) -> Path:
        """Resolve the project root for a run."""
        if project_root is not None:
            return project_root.resolve()
        env_root = os.environ.get("CODEGRAPH_PROJECT_ROOT", "")
        if env_root:
            return Path(env_root).resolve()
        return Path.cwd().resolve()

    def _resolve_store(self, project_root: Path) -> RunStore:
        """Return the store to use for this run.

        If a custom store was injected, it must point at the same project root
        as the explicit ``project_root`` argument to avoid split persistence.
        """
        if self._store is None:
            return RunStore(project_root=project_root)
        expected_base_dir = (project_root / ".codegraph" / "runs").resolve()
        if self._store.base_dir.resolve() != expected_base_dir:
            raise ValueError(
                "Injected RunStore base_dir does not match the resolved project root"
            )
        return self._store

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
    ) -> None:
        """Write files that are not handled by ``RunStore`` itself."""
        atomic_write_json(run_dir / "manifest.json", manifest.model_dump(mode="json"))

    def _extract_partial_output(
        self,
        exc: Exception,
    ) -> dict[str, Any] | None:
        """Return a structured partial output payload if the exception carries one."""
        partial = getattr(exc, "partial_output", None)
        return partial if isinstance(partial, dict) else None

    def _build_error_details(
        self,
        exc: Exception,
        *,
        traceback_text: str,
        module_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Build the public structured error payload for callers."""
        message = str(exc).strip() or exc.__class__.__name__
        return {
            "code": "module_execution_failed",
            "type": exc.__class__.__name__,
            "message": message,
            "public_message": f"{exc.__class__.__name__}: {message}",
            "module_id": module_id,
            "run_id": run_id,
            "traceback": traceback_text,
        }

    def _build_result(
        self,
        *,
        state: HarnessRunState,
        output: dict[str, Any] | None,
        ctx: HarnessRunContext,
        error: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> HarnessRunResult:
        """Create the compact result returned to callers."""
        artifacts = [artifact.name for artifact in ctx.artifacts.list_artifacts()]
        return HarnessRunResult(
            run_id=state.run_id,
            module_id=state.module_id,
            status=state.status,
            output=output,
            error=error,
            error_details=error_details,
            artifacts=artifacts,
        )
