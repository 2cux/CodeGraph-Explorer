"""CodeGraph Harness — unified execution framework.

Manages run lifecycle, artifacts, checkpoints, and events for all
executable tasks (workflows, enrich, benchmark, doctor, agent A/B, MCP).

Public API exports:
"""

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
from codegraph.harness.store import RunStore
from codegraph.harness.artifacts import (
    DEFAULT_JSON_ARTIFACT,
    DEFAULT_TEXT_ARTIFACT,
    ArtifactManager,
)
from codegraph.harness.checkpoints import CheckpointManager
from codegraph.harness.context import HarnessRunContext
from codegraph.harness.events import (
    EventBus,
    emit_artifact_written,
    emit_checkpoint_recorded,
    emit_module_failed,
    emit_module_finished,
    emit_module_started,
    emit_run_created,
)
from codegraph.harness.registry import HarnessModule, get_module, list_modules, register_module
from codegraph.harness.runner import HarnessRunner
from codegraph.harness.manifest import list_builtin_manifests, manifest_for

__all__ = [
    # Models
    "RunStatus",
    "EventType",
    "ModuleCategory",
    "HarnessModuleManifest",
    "HarnessRunState",
    "HarnessRunResult",
    "HarnessCheckpoint",
    "HarnessArtifact",
    "HarnessEvent",
    # Store
    "RunStore",
    # Managers
    "ArtifactManager",
    "CheckpointManager",
    "EventBus",
    "HarnessRunContext",
    "HarnessRunner",
    "HarnessModule",
    "register_module",
    "get_module",
    "list_modules",
    "manifest_for",
    "list_builtin_manifests",
    # Event emitters
    "emit_run_created",
    "emit_module_started",
    "emit_module_finished",
    "emit_module_failed",
    "emit_artifact_written",
    "emit_checkpoint_recorded",
    # Defaults
    "DEFAULT_TEXT_ARTIFACT",
    "DEFAULT_JSON_ARTIFACT",
]
