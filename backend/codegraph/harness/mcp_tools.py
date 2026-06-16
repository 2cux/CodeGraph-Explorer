"""MCP-facing helpers for running Harness modules safely."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.harness.artifacts import ArtifactManager
from codegraph.harness.manifest import list_builtin_manifests, manifest_for
from codegraph.harness.models import HarnessArtifact, HarnessRunState
from codegraph.harness.runner import HarnessRunner
from codegraph.harness.store import RunStore
from codegraph.harness.utils import sanitize_artifact_name, validate_run_id

MAX_ARTIFACT_READ_BYTES = 32 * 1024
_MCP_RUN_ALLOWED_MODULE_IDS = {
    "workflow.impact",
    "workflow.test_audit",
    "workflow.explain",
    "workflow.find",
}


def list_harness_manifests() -> list[dict[str, Any]]:
    """Return builtin harness module manifests only."""
    return [
        manifest.model_dump(mode="json")
        for manifest in list_builtin_manifests()
    ]


def run_harness_module(
    *,
    module_id: str,
    input_data: dict[str, Any] | None,
    persist: bool,
    project_root: Path,
) -> dict[str, Any]:
    """Execute one builtin harness module under the resolved project root."""
    if not persist:
        raise ValueError("codegraph_harness_run requires persist=true")
    manifest = _require_allowed_manifest(module_id)
    normalized_input = _normalize_input_payload(input_data)
    result = HarnessRunner().run(
        module_id,
        normalized_input,
        project_root=project_root,
        persist=persist,
    )
    output = result.output or {}
    return {
        "run_id": result.run_id,
        "module_id": result.module_id,
        "status": result.status.value,
        "summary": _summarize_run(result.module_id, output, result.status.value),
        "output": output,
        "artifacts": _artifact_path_map(
            run_id=result.run_id,
            artifact_names=result.artifacts,
        ),
        "persisted": persist,
        "manifest": manifest.model_dump(mode="json"),
    }


def get_harness_status(
    *,
    run_id: str,
    project_root: Path,
) -> dict[str, Any]:
    """Return persisted state for a harness run."""
    store = RunStore(project_root=project_root)
    state = _require_run_state(store, run_id)
    artifacts = ArtifactManager(store.artifacts_dir(run_id)).list_artifacts()
    return _status_payload(state=state, artifacts=artifacts)


def get_harness_artifacts(
    *,
    run_id: str,
    project_root: Path,
    artifact_name: str | None = None,
    include_content: bool = False,
    max_bytes: int = MAX_ARTIFACT_READ_BYTES,
) -> dict[str, Any]:
    """List artifacts for one run, optionally reading one small text artifact."""
    if max_bytes <= 0 or max_bytes > MAX_ARTIFACT_READ_BYTES:
        raise ValueError(
            f"max_bytes must be between 1 and {MAX_ARTIFACT_READ_BYTES}"
        )

    store = RunStore(project_root=project_root)
    state = _require_run_state(store, run_id)
    manager = ArtifactManager(store.artifacts_dir(run_id))

    if artifact_name is not None:
        safe_name = sanitize_artifact_name(artifact_name)
        artifact = manager.get_artifact(safe_name)
        if artifact is None:
            raise FileNotFoundError(
                f"Artifact not found for run {run_id}: {safe_name}"
            )
        payload: dict[str, Any] = {
            "run_id": run_id,
            "module_id": state.module_id,
            "status": state.status.value,
            "artifact": _serialize_artifact(run_id=run_id, artifact=artifact),
            "content_included": False,
            "max_bytes": max_bytes,
        }
        if include_content:
            payload["artifact"]["content"] = _read_artifact_content(
                artifacts_dir=manager.dir,
                artifact=artifact,
                max_bytes=max_bytes,
            )
            payload["content_included"] = True
        return payload

    if include_content:
        raise ValueError(
            "include_content requires artifact_name to avoid bulk file reads"
        )

    artifacts = manager.list_artifacts()
    return {
        "run_id": run_id,
        "module_id": state.module_id,
        "status": state.status.value,
        "artifacts": [
            _serialize_artifact(run_id=run_id, artifact=artifact)
            for artifact in artifacts
        ],
        "content_included": False,
        "max_bytes": max_bytes,
    }


def _require_allowed_manifest(module_id: str):
    try:
        manifest = manifest_for(module_id)
    except KeyError as exc:
        raise ValueError(f"Unknown harness module: {module_id}") from exc
    if module_id not in _MCP_RUN_ALLOWED_MODULE_IDS:
        raise ValueError(f"Harness module is not exposed over MCP: {module_id}")
    return manifest


def _normalize_input_payload(input_data: dict[str, Any] | None) -> dict[str, Any]:
    if input_data is None:
        return {}
    if not isinstance(input_data, dict):
        raise ValueError("input must be a JSON object")
    return dict(input_data)


def _require_run_state(store: RunStore, run_id: str) -> HarnessRunState:
    validate_run_id(run_id)
    state = store.load_run(run_id)
    if state is None:
        raise FileNotFoundError(f"Harness run not found: {run_id}")
    return state


def _status_payload(
    *,
    state: HarnessRunState,
    artifacts: list[HarnessArtifact],
) -> dict[str, Any]:
    run_id = state.run_id
    return {
        "run_id": run_id,
        "module_id": state.module_id,
        "status": state.status.value,
        "summary": f"{state.module_id} {state.status.value}",
        "artifacts": _artifact_path_map(
            run_id=run_id,
            artifact_names=[artifact.name for artifact in artifacts],
        ),
        "state": state.model_dump(mode="json"),
    }


def _artifact_path_map(
    *,
    run_id: str,
    artifact_names: list[str],
) -> dict[str, str]:
    return {
        _artifact_key(name): f".codegraph/runs/{run_id}/artifacts/{name}"
        for name in artifact_names
    }


def _artifact_key(name: str) -> str:
    normalized = name.strip().lower().replace(".", "_")
    normalized = normalized.replace("-", "_").replace(" ", "_")
    return normalized or "artifact"


def _serialize_artifact(
    *,
    run_id: str,
    artifact: HarnessArtifact,
) -> dict[str, Any]:
    return {
        "name": artifact.name,
        "path": f".codegraph/runs/{run_id}/artifacts/{artifact.name}",
        "relative_path": artifact.path,
        "media_type": artifact.media_type,
        "size_bytes": artifact.size_bytes,
        "created_at": artifact.created_at,
    }


def _read_artifact_content(
    *,
    artifacts_dir: Path,
    artifact: HarnessArtifact,
    max_bytes: int,
) -> str:
    if artifact.size_bytes > max_bytes:
        raise ValueError(
            f"Artifact {artifact.name} is {artifact.size_bytes} bytes; "
            f"max readable size is {max_bytes} bytes"
        )
    path = (artifacts_dir / artifact.name).resolve()
    base = artifacts_dir.resolve()
    if not path.is_relative_to(base):
        raise ValueError("Artifact path escapes the run artifacts directory")
    if not path.is_file():
        raise FileNotFoundError(f"Artifact file missing: {artifact.name}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Artifact {artifact.name} is not a UTF-8 text artifact"
        ) from exc


def _summarize_run(
    module_id: str,
    output: dict[str, Any],
    status: str,
) -> str:
    if status != "succeeded":
        return f"{module_id} {status}"

    if module_id == "workflow.impact":
        return (
            f"risk={output.get('risk_level', 'unknown')}, "
            f"affected_files={len(output.get('affected_files', []))}, "
            f"affected_tests={len(output.get('affected_tests', []))}"
        )
    if module_id == "workflow.test_audit":
        summary = output.get("summary", {}) or {}
        return (
            "production_symbols_checked="
            f"{summary.get('production_symbols_checked', 0)}, "
            "symbols_without_test_signal="
            f"{summary.get('symbols_without_test_signal', 0)}"
        )
    if module_id == "workflow.explain":
        target = output.get("target", {}) or {}
        target_name = target.get("symbol") or target.get("file") or target.get("kind", "target")
        return f"target={target_name}, confidence={output.get('confidence', 'unknown')}"
    if module_id == "workflow.find":
        return (
            f"query={output.get('query', '')!s}, "
            f"results={len(output.get('results', []))}, "
            f"confidence={output.get('confidence', 'unknown')}"
        )

    if isinstance(output.get("summary"), str) and output["summary"].strip():
        return output["summary"].strip()
    return f"{module_id} succeeded"
