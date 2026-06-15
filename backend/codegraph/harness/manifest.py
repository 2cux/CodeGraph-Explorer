"""Builtin harness module manifests.

Centralizes manifest definitions for stable and reserved modules.
"""

from __future__ import annotations

from typing import Final

from codegraph.harness.models import HarnessModuleManifest, ModuleCategory


_MODULE_MANIFEST_DATA: Final[dict[str, dict[str, object]]] = {
    "workflow.impact": {
        "name": "Workflow Impact",
        "description": "Analyze callers, files, and tests affected by planned edits.",
        "category": ModuleCategory.WORKFLOW.value,
        "is_stable": True,
    },
    "workflow.test_audit": {
        "name": "Workflow Test Audit",
        "description": "Audit graph-based test coverage gaps for the selected scope.",
        "category": ModuleCategory.WORKFLOW.value,
        "is_stable": True,
    },
    "workflow.explain": {
        "name": "Workflow Explain",
        "description": "Produce an evidence-backed explanation for a symbol or file.",
        "category": ModuleCategory.WORKFLOW.value,
        "is_stable": True,
    },
    "workflow.find": {
        "name": "Workflow Find",
        "description": "Search indexed symbols and files by keyword, type, and path scope.",
        "category": ModuleCategory.WORKFLOW.value,
        "is_stable": True,
    },
    "doctor.run": {
        "name": "Doctor Run",
        "description": "Run CodeGraph doctor diagnostics and optionally perform repair.",
        "category": ModuleCategory.DOCTOR.value,
        "is_stable": True,
    },
    "enrich.prepare": {
        "name": "Enrich Prepare",
        "description": "Reserved / planned: generate bounded enrichment input from the index.",
        "category": ModuleCategory.ENRICH.value,
        "is_stable": False,
    },
    "enrich.validate": {
        "name": "Enrich Validate",
        "description": "Reserved / planned: validate agent-produced enrichment JSON.",
        "category": ModuleCategory.ENRICH.value,
        "is_stable": False,
    },
    "enrich.import": {
        "name": "Enrich Import",
        "description": "Reserved / planned: import validated enrichment data into storage.",
        "category": ModuleCategory.ENRICH.value,
        "is_stable": False,
    },
    "benchmark.gate": {
        "name": "Benchmark Gate",
        "description": "Reserved / planned: run benchmark regression gate checks.",
        "category": ModuleCategory.BENCHMARK.value,
        "is_stable": False,
    },
    "agent_ab.regression": {
        "name": "Agent AB Regression",
        "description": "Reserved / planned: run agent A/B regression evaluation workflows.",
        "category": ModuleCategory.AGENT.value,
        "is_stable": False,
    },
    "mcp.execute": {
        "name": "MCP Execute",
        "description": "Reserved / planned: wrap MCP tool execution and record harness runs.",
        "category": ModuleCategory.MCP.value,
        "is_stable": False,
    },
}


def manifest_for(module_id: str) -> HarnessModuleManifest:
    """Return the manifest for a builtin harness module."""
    try:
        data = _MODULE_MANIFEST_DATA[module_id]
    except KeyError as exc:
        raise KeyError(f"Unknown builtin harness module: {module_id}") from exc
    return HarnessModuleManifest(id=module_id, **data)


def list_builtin_manifests() -> list[HarnessModuleManifest]:
    """Return all builtin manifests sorted by module id."""
    return [manifest_for(module_id) for module_id in sorted(_MODULE_MANIFEST_DATA)]
