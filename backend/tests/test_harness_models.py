"""Tests for harness core data models — PRD Section 26.3.

Covers:
- Enums: RunStatus, EventType, ModuleCategory
- HarnessModuleManifest (manifest creation, defaults, validation)
- HarnessRunState (run_id generation, status lifecycle)
- HarnessRunResult (success/failure wrapping)
- HarnessCheckpoint (record payload, timestamp)
- HarnessArtifact (metadata, path safety)
- HarnessEvent (serialization, alias mapping)
"""

from __future__ import annotations

import json

import pytest

from codegraph.harness.models import (
    EventType,
    HarnessArtifact,
    HarnessCheckpoint,
    HarnessEvent,
    HarnessModuleManifest,
    HarnessRunResult,
    HarnessRunState,
    ModuleCategory,
    RunStatus,
)


# ── Enums ──────────────────────────────────────────────────────────────────


class TestRunStatus:
    def test_all_status_values(self) -> None:
        assert RunStatus.CREATED.value == "created"
        assert RunStatus.RUNNING.value == "running"
        assert RunStatus.SUCCEEDED.value == "succeeded"
        assert RunStatus.FAILED.value == "failed"
        assert RunStatus.CANCELLED.value == "cancelled"

    def test_run_status_from_string(self) -> None:
        assert RunStatus("succeeded") == RunStatus.SUCCEEDED
        assert RunStatus("failed") == RunStatus.FAILED


class TestEventType:
    def test_all_event_types(self) -> None:
        assert EventType.RUN_CREATED.value == "run.created"
        assert EventType.MODULE_STARTED.value == "module.started"
        assert EventType.MODULE_FINISHED.value == "module.finished"
        assert EventType.MODULE_FAILED.value == "module.failed"
        assert EventType.ARTIFACT_WRITTEN.value == "artifact.written"
        assert EventType.CHECKPOINT_RECORDED.value == "checkpoint.recorded"


class TestModuleCategory:
    def test_all_categories(self) -> None:
        assert ModuleCategory.WORKFLOW.value == "workflow"
        assert ModuleCategory.ENRICH.value == "enrich"
        assert ModuleCategory.BENCHMARK.value == "benchmark"
        assert ModuleCategory.DOCTOR.value == "doctor"
        assert ModuleCategory.AGENT.value == "agent"
        assert ModuleCategory.MCP.value == "mcp"


# ── HarnessModuleManifest ──────────────────────────────────────────────────


class TestHarnessModuleManifest:
    def test_minimal_manifest_creation(self) -> None:
        """Manifest with only required fields should create successfully."""
        manifest = HarnessModuleManifest(
            id="test.module",
            name="Test Module",
            description="A test harness module.",
            category="workflow",
        )
        assert manifest.id == "test.module"
        assert manifest.name == "Test Module"
        assert manifest.description == "A test harness module."
        assert manifest.category == "workflow"
        assert manifest.version == "1.0.0"
        assert manifest.input_schema is None
        assert manifest.output_schema is None
        assert manifest.default_artifacts == ["report.md", "report.json"]
        assert manifest.persist_by_default is True
        assert manifest.supports_checkpoints is True
        assert manifest.is_stable is False

    def test_full_manifest_with_schemas(self) -> None:
        """Manifest with input/output schemas should serialize correctly."""
        manifest = HarnessModuleManifest(
            id="workflow.impact",
            name="Workflow Impact",
            description="Analyze impact of planned edits.",
            category="workflow",
            version="2.0.0",
            input_schema={
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "risk_level": {"type": "string"},
                },
            },
            default_artifacts=["report.md", "report.json", "graph.dot"],
            persist_by_default=True,
            supports_checkpoints=True,
            is_stable=True,
        )
        assert manifest.version == "2.0.0"
        assert manifest.input_schema is not None
        assert manifest.input_schema["type"] == "object"
        assert manifest.output_schema is not None
        assert manifest.output_schema["properties"]["risk_level"]["type"] == "string"
        assert manifest.default_artifacts == ["report.md", "report.json", "graph.dot"]
        assert manifest.is_stable is True

    def test_manifest_model_dump_includes_all_fields(self) -> None:
        manifest = HarnessModuleManifest(
            id="test.module",
            name="Test Module",
            description="A test harness module.",
            category="workflow",
        )
        data = manifest.model_dump()
        assert data["id"] == "test.module"
        assert data["name"] == "Test Module"
        assert data["version"] == "1.0.0"
        assert data["category"] == "workflow"
        assert "default_artifacts" in data

    def test_manifest_json_mode_dump(self) -> None:
        """model_dump(mode='json') should produce JSON-serializable output."""
        manifest = HarnessModuleManifest(
            id="test.module",
            name="Test Module",
            description="A test harness module.",
            category="workflow",
        )
        data = manifest.model_dump(mode="json")
        # Should be directly JSON-serializable
        json_str = json.dumps(data)
        assert "test.module" in json_str

    def test_manifest_model_validate_from_dict(self) -> None:
        """model_validate should accept a plain dict and coerce."""
        data = {
            "id": "dynamic.module",
            "name": "Dynamic",
            "description": "Built at runtime.",
            "category": "benchmark",
        }
        manifest = HarnessModuleManifest.model_validate(data)
        assert manifest.id == "dynamic.module"
        assert manifest.category == "benchmark"

    def test_manifest_with_reserved_module_flags(self) -> None:
        """Reserved modules: is_stable=False, empty default_artifacts."""
        manifest = HarnessModuleManifest(
            id="enrich.prepare",
            name="Enrich Prepare",
            description="Reserved / planned: generate enrichment input.",
            category="enrich",
            is_stable=False,
            default_artifacts=[],
        )
        assert manifest.is_stable is False
        assert manifest.default_artifacts == []


# ── HarnessRunState ────────────────────────────────────────────────────────


class TestHarnessRunState:
    def test_initial_state_defaults(self) -> None:
        state = HarnessRunState(
            run_id="wf-impact-20260616T120000Z-a1b2",
            module_id="workflow.impact",
            project_root="/home/user/project",
        )
        assert state.run_id == "wf-impact-20260616T120000Z-a1b2"
        assert state.module_id == "workflow.impact"
        assert state.status == RunStatus.CREATED
        assert state.project_root == "/home/user/project"
        assert state.started_at is None
        assert state.finished_at is None
        assert state.input_path is None
        assert state.output_path is None
        assert state.artifacts_dir is None
        assert state.logs_dir is None
        assert state.checkpoints_path is None
        assert state.error is None

    def test_full_state_serialization_roundtrip(self) -> None:
        state = HarnessRunState(
            run_id="wf-impact-20260616T120000Z-a1b2",
            module_id="workflow.impact",
            status=RunStatus.SUCCEEDED,
            project_root="/home/user/project",
            started_at="2026-06-16T12:00:00.000000+00:00",
            finished_at="2026-06-16T12:00:05.000000+00:00",
            input_path="input.json",
            output_path="output.json",
            artifacts_dir="artifacts/",
            logs_dir="logs/",
            checkpoints_path="checkpoints.jsonl",
            error=None,
        )
        data = state.model_dump()
        assert data["status"] == "succeeded"
        assert data["output_path"] == "output.json"

        # Re-hydrate
        state2 = HarnessRunState.model_validate(data)
        assert state2.run_id == state.run_id
        assert state2.status == RunStatus.SUCCEEDED

    def test_failed_state_stores_error_message(self) -> None:
        state = HarnessRunState(
            run_id="wf-impact-20260616T120000Z-a1b2",
            module_id="workflow.impact",
            status=RunStatus.FAILED,
            project_root="/home/user/project",
            finished_at="2026-06-16T12:00:05.000000+00:00",
            error="ValueError: symbol not found",
        )
        assert state.error == "ValueError: symbol not found"

    def test_state_model_dump_json_mode(self) -> None:
        state = HarnessRunState(
            run_id="test-run-1",
            module_id="test.module",
            status=RunStatus.CREATED,
            project_root="/tmp/test",
        )
        data = state.model_dump(mode="json")
        assert data["status"] == "created"
        json_str = json.dumps(data)
        assert "test-run-1" in json_str


# ── HarnessRunResult ───────────────────────────────────────────────────────


class TestHarnessRunResult:
    def test_success_result(self) -> None:
        result = HarnessRunResult(
            run_id="test-run-1",
            module_id="workflow.impact",
            status=RunStatus.SUCCEEDED,
            output={"risk_level": "medium", "affected_files": ["a.py"]},
            artifacts=["report.md", "report.json"],
        )
        assert result.status == RunStatus.SUCCEEDED
        assert result.output is not None
        assert result.output["risk_level"] == "medium"
        assert result.error is None
        assert result.error_details is None
        assert result.artifacts == ["report.md", "report.json"]

    def test_failure_result(self) -> None:
        result = HarnessRunResult(
            run_id="test-run-2",
            module_id="workflow.impact",
            status=RunStatus.FAILED,
            output=None,
            error="Module execution failed",
            error_details={
                "code": "module_execution_failed",
                "message": "boom",
                "traceback": "Traceback...",
            },
            artifacts=[],
        )
        assert result.status == RunStatus.FAILED
        assert result.error == "Module execution failed"
        assert result.error_details is not None
        assert result.error_details["code"] == "module_execution_failed"
        assert result.artifacts == []

    def test_result_serialization(self) -> None:
        result = HarnessRunResult(
            run_id="test-run-1",
            module_id="test.module",
            status=RunStatus.SUCCEEDED,
            output={"ok": True},
            artifacts=["report.json"],
        )
        data = result.model_dump()
        assert data["status"] == "succeeded"
        assert data["output"]["ok"] is True


# ── HarnessCheckpoint ──────────────────────────────────────────────────────


class TestHarnessCheckpoint:
    def test_checkpoint_creation(self) -> None:
        cp = HarnessCheckpoint(
            name="symbols resolved",
            status="recorded",
            payload={"count": 42, "source": "store"},
            created_at="2026-06-16T12:00:01.000000+00:00",
        )
        assert cp.name == "symbols resolved"
        assert cp.status == "recorded"
        assert cp.payload["count"] == 42
        assert cp.created_at == "2026-06-16T12:00:01.000000+00:00"

    def test_checkpoint_defaults(self) -> None:
        cp = HarnessCheckpoint(
            name="empty checkpoint",
            created_at="2026-06-16T12:00:00Z",
        )
        assert cp.status == "recorded"
        assert cp.payload == {}

    def test_checkpoint_roundtrip(self) -> None:
        cp = HarnessCheckpoint(
            name="inputs.normalized",
            payload={"files": ["a.py"], "symbols": []},
            created_at="2026-06-16T12:00:00Z",
        )
        data = cp.model_dump()
        cp2 = HarnessCheckpoint.model_validate(data)
        assert cp2.name == cp.name
        assert cp2.payload == cp.payload


# ── HarnessArtifact ────────────────────────────────────────────────────────


class TestHarnessArtifact:
    def test_artifact_creation(self) -> None:
        art = HarnessArtifact(
            name="report.md",
            path="report.md",
            media_type="text/markdown",
            size_bytes=1024,
            created_at="2026-06-16T12:00:05.000000+00:00",
        )
        assert art.name == "report.md"
        assert art.path == "report.md"
        assert art.media_type == "text/markdown"
        assert art.size_bytes == 1024
        assert art.created_at == "2026-06-16T12:00:05.000000+00:00"

    def test_artifact_default_media_type(self) -> None:
        art = HarnessArtifact(
            name="report.json",
            path="report.json",
            size_bytes=0,
            created_at="2026-06-16T12:00:00Z",
        )
        assert art.media_type == "application/json"

    def test_artifact_json_serialization(self) -> None:
        art = HarnessArtifact(
            name="report.md",
            path="artifacts/report.md",
            media_type="text/markdown",
            size_bytes=2048,
            created_at="2026-06-16T12:00:00Z",
        )
        data = art.model_dump()
        assert data["name"] == "report.md"
        assert data["size_bytes"] == 2048


# ── HarnessEvent ───────────────────────────────────────────────────────────


class TestHarnessEvent:
    def test_event_creation_with_alias(self) -> None:
        """HarnessEvent uses alias: timestamp→time, event_type→type."""
        event = HarnessEvent(
            timestamp="2026-06-16T12:00:00Z",
            event_type=EventType.RUN_CREATED,
            payload={"run_id": "abc123"},
        )
        assert event.time == "2026-06-16T12:00:00Z"
        assert event.type == EventType.RUN_CREATED
        assert event.payload == {"run_id": "abc123"}

    def test_event_model_dump_uses_original_field_names(self) -> None:
        """model_dump(by_alias=False) should use the Python field names."""
        event = HarnessEvent(
            timestamp="2026-06-16T12:00:00Z",
            event_type=EventType.MODULE_STARTED,
        )
        data = event.model_dump()
        # With populate_by_name=True, input aliases are accepted
        # but model_dump uses field names by default
        assert "time" in data
        assert "type" in data

    def test_event_without_payload(self) -> None:
        event = HarnessEvent(
            timestamp="2026-06-16T12:00:00Z",
            event_type=EventType.ARTIFACT_WRITTEN,
        )
        assert event.payload is None

    def test_event_all_types(self) -> None:
        for event_type in EventType:
            event = HarnessEvent(
                timestamp="2026-06-16T12:00:00Z",
                event_type=event_type,
            )
            assert event.type == event_type


# ── Edge cases ─────────────────────────────────────────────────────────────


class TestModelEdgeCases:
    def test_manifest_empty_description(self) -> None:
        """Even empty string description should be valid."""
        manifest = HarnessModuleManifest(
            id="test.empty",
            name="Empty Desc",
            description="",
            category="workflow",
        )
        assert manifest.description == ""

    def test_run_state_without_optional_fields(self) -> None:
        """A run state with only required fields should serialize cleanly."""
        state = HarnessRunState(
            run_id="minimal-run",
            module_id="test.minimal",
            project_root="/tmp",
        )
        data = state.model_dump()
        assert data["started_at"] is None
        assert data["finished_at"] is None
        assert data["input_path"] is None
        assert data["output_path"] is None

    @pytest.mark.parametrize(
        "run_id,module_id,project_root",
        [
            ("run-1", "m.1", "/a"),
            ("workflow-impact-20260616T120000Z-a8f3", "workflow.impact", "C:\\Users\\test"),
            ("a" * 64, "x.y.z", "/home/user/projects/my-app"),
        ],
    )
    def test_run_state_various_project_roots(
        self, run_id: str, module_id: str, project_root: str
    ) -> None:
        state = HarnessRunState(
            run_id=run_id,
            module_id=module_id,
            project_root=project_root,
        )
        assert state.project_root == project_root
