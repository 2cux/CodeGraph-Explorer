"""Harness core data models — Run, Manifest, Checkpoint, Artifact, Event.

Matches PRD Section 26.3 (Core Models) specification.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Enums ────────────────────────────────────────────────────────────────


class RunStatus(str, Enum):
    """Lifecycle status of a harness run."""

    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    """Standard harness lifecycle event types."""

    RUN_CREATED = "run.created"
    MODULE_STARTED = "module.started"
    MODULE_FINISHED = "module.finished"
    MODULE_FAILED = "module.failed"
    ARTIFACT_WRITTEN = "artifact.written"
    CHECKPOINT_RECORDED = "checkpoint.recorded"


class ModuleCategory(str, Enum):
    """Top-level category for a harness module."""

    WORKFLOW = "workflow"
    ENRICH = "enrich"
    BENCHMARK = "benchmark"
    DOCTOR = "doctor"
    AGENT = "agent"
    MCP = "mcp"


# ── Module Manifest ──────────────────────────────────────────────────────


class HarnessModuleManifest(BaseModel):
    """Static metadata for a registered harness module.

    Maps to PRD Section 26.4.8 ModuleManifest.
    """

    id: str = Field(
        description="Dotted module identifier, e.g. 'workflow.impact', 'enrich.prepare'"
    )
    name: str = Field(description="Short human-readable name")
    description: str = Field(description="One-paragraph summary of what the module does")
    category: str = Field(description="ModuleCategory value: workflow, enrich, benchmark, doctor, agent, mcp")
    version: str = Field(default="1.0.0", description="SemVer version string")
    input_schema: dict[str, Any] | None = Field(
        default=None, description="JSON Schema for input parameters"
    )
    output_schema: dict[str, Any] | None = Field(
        default=None, description="JSON Schema for output result"
    )
    default_artifacts: list[str] = Field(
        default_factory=lambda: ["report.md", "report.json"],
        description="Default artifact file names produced by this module",
    )
    persist_by_default: bool = Field(
        default=True, description="Whether runs for this module persist by default"
    )
    supports_checkpoints: bool = Field(
        default=True, description="Whether this module emits checkpoints"
    )
    is_stable: bool = Field(
        default=False, description="True for active modules, False for placeholder stubs"
    )


# ── Run State ────────────────────────────────────────────────────────────


class HarnessRunState(BaseModel):
    """Runtime state for a single harness run.

    Persisted to ``.codegraph/runs/<run-id>/state.json``.
    Maps to PRD Section 26.3.1 Run.
    """

    run_id: str = Field(
        description="Unique run identifier, e.g. 'workflow-impact-20260615T103012Z-a8f3'"
    )
    module_id: str = Field(
        description="Module identifier that produced this run, e.g. 'workflow.impact'"
    )
    status: RunStatus = Field(
        default=RunStatus.CREATED, description="Current lifecycle status"
    )
    project_root: str = Field(description="Absolute path to the project root")
    started_at: str | None = Field(
        default=None, description="ISO 8601 timestamp when the run started"
    )
    finished_at: str | None = Field(
        default=None, description="ISO 8601 timestamp when the run finished"
    )
    input_path: str | None = Field(
        default=None, description="Relative path to input.json inside the run directory"
    )
    output_path: str | None = Field(
        default=None, description="Relative path to output.json inside the run directory"
    )
    artifacts_dir: str | None = Field(
        default=None, description="Relative path to the artifacts directory"
    )
    logs_dir: str | None = Field(
        default=None, description="Relative path to the logs directory"
    )
    checkpoints_path: str | None = Field(
        default=None, description="Relative path to checkpoints.jsonl"
    )
    error: str | None = Field(
        default=None, description="Error message if status is FAILED"
    )


# ── Run Result ───────────────────────────────────────────────────────────


class HarnessRunResult(BaseModel):
    """Normalized output returned after a run completes.

    Wraps the run state plus the module's output payload.
    """

    run_id: str = Field(description="Run identifier")
    module_id: str = Field(description="Module identifier")
    status: RunStatus = Field(description="Final run status")
    output: dict[str, Any] | None = Field(
        default=None, description="Module output payload (contents of output.json)"
    )
    error: str | None = Field(
        default=None, description="Error message if run failed"
    )
    artifacts: list[str] = Field(
        default_factory=list, description="List of artifact file names produced"
    )


# ── Checkpoint ───────────────────────────────────────────────────────────


class HarnessCheckpoint(BaseModel):
    """A recorded checkpoint snapshot.

    v1: record-only — does not pause execution or support resume.
    Maps to PRD Section 26.3.3 Checkpoint.
    """

    name: str = Field(description="Human-readable label, e.g. 'symbols resolved'")
    status: str = Field(
        default="recorded", description="Checkpoint status (v1: always 'recorded')"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Module-defined snapshot data"
    )
    created_at: str = Field(description="ISO 8601 timestamp when recorded")


# ── Artifact ─────────────────────────────────────────────────────────────


class HarnessArtifact(BaseModel):
    """Metadata for a run artifact file.

    Maps to PRD Section 26.3.4 Artifact.
    """

    name: str = Field(description="Human-readable artifact name")
    path: str = Field(description="Path relative to the run's artifacts directory")
    media_type: str = Field(
        default="application/json",
        description="MIME type: 'application/json', 'text/markdown', 'text/plain'",
    )
    size_bytes: int = Field(default=0, description="File size in bytes")
    created_at: str = Field(description="ISO 8601 timestamp when written")


# ── Event ────────────────────────────────────────────────────────────────


class HarnessEvent(BaseModel):
    """A lifecycle event emitted during a run.

    Maps to PRD Section 26.3.5 RunEvent.
    """

    time: str = Field(description="ISO 8601 timestamp", alias="timestamp")
    type: EventType = Field(description="Event type discriminator", alias="event_type")
    payload: dict[str, Any] | None = Field(
        default=None, description="Optional event data"
    )

    model_config = ConfigDict(populate_by_name=True)
