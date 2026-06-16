"""Builtin harness module manifests.

Centralizes manifest definitions, including schema metadata used by docs
generation and CLI surfaces.
"""

from __future__ import annotations

from typing import Any, Final

from codegraph.harness.models import HarnessModuleManifest, ModuleCategory


def _string_list_schema(description: str) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string"},
        "default": [],
        "description": description,
    }


def _reserved_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean", "const": False},
            "status": {"type": "string", "const": "reserved"},
            "message": {"type": "string"},
        },
        "required": ["ok", "status", "message"],
        "additionalProperties": False,
    }


_MODULE_MANIFEST_DATA: Final[dict[str, dict[str, object]]] = {
    "workflow.impact": {
        "name": "Workflow Impact",
        "description": "Analyze callers, files, and tests affected by planned edits.",
        "category": ModuleCategory.WORKFLOW.value,
        "is_stable": True,
        "default_artifacts": ["report.md", "report.json"],
        "input_schema": {
            "type": "object",
            "properties": {
                "files": _string_list_schema("Repository-relative file paths to inspect."),
                "symbols": _string_list_schema("Qualified symbol ids or names to inspect."),
                "change_type": {
                    "type": "string",
                    "default": "unknown",
                    "description": "Change classification such as refactor, bugfix, or feature.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional free-form change description.",
                },
                "include_tests": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include related test recommendations.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 50,
                    "description": "Maximum number of related items to keep in result lists.",
                },
            },
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "workflow": {"type": "string", "const": "impact"},
                "input": {"type": "object"},
                "change_type": {"type": "string"},
                "description": {"type": "string"},
                "index_status": {"type": "object"},
                "risk_level": {"type": "string"},
                "planned_files": _string_list_schema("Normalized planned files."),
                "planned_symbols": _string_list_schema("Normalized planned symbols."),
                "impact_summary": {"type": "object"},
                "affected_callers": {"type": "array"},
                "affected_files": {"type": "array"},
                "affected_tests": {"type": "array"},
                "recommended_checks": {"type": "array"},
                "impact_errors": {"type": "array"},
                "warnings": {"type": "array"},
                "artifacts": {"type": "object"},
            },
            "required": [
                "ok",
                "workflow",
                "input",
                "risk_level",
                "impact_summary",
                "affected_files",
                "warnings",
                "artifacts",
            ],
        },
    },
    "workflow.test_audit": {
        "name": "Workflow Test Audit",
        "description": "Audit graph-based test coverage gaps for the selected scope.",
        "category": ModuleCategory.WORKFLOW.value,
        "is_stable": True,
        "default_artifacts": ["report.md", "report.json"],
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": _string_list_schema("Optional path globs or files to scope the audit."),
                "types": _string_list_schema("Optional production symbol types to keep."),
                "include_low_confidence": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include low-confidence tested_by links.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 50,
                    "description": "Maximum number of uncovered items to retain.",
                },
            },
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "workflow": {"type": "string", "const": "test-audit"},
                "input": {"type": "object"},
                "coverage_gaps_summary": {"type": "object"},
                "summary": {"type": "object"},
                "top_uncovered_production_symbols": {"type": "array"},
                "symbols_without_tests": {"type": "array"},
                "files_without_test_signals": {"type": "array"},
                "files_without_tests": {"type": "array"},
                "low_confidence_links": {"type": "array"},
                "path_resolution": {"type": "object"},
                "warnings": {"type": "array"},
                "heuristic_coverage_disclaimer": {"type": "string"},
                "artifacts": {"type": "object"},
            },
            "required": [
                "ok",
                "workflow",
                "input",
                "summary",
                "warnings",
                "heuristic_coverage_disclaimer",
                "artifacts",
            ],
        },
    },
    "workflow.explain": {
        "name": "Workflow Explain",
        "description": "Produce an evidence-backed explanation for a symbol or file.",
        "category": ModuleCategory.WORKFLOW.value,
        "is_stable": True,
        "default_artifacts": ["report.md", "report.json"],
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol name or id. Required when file is not provided.",
                },
                "file": {
                    "type": "string",
                    "description": "Repository-relative file path. Required when symbol is not provided.",
                },
                "include_neighbors": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include caller/callee relationship summaries.",
                },
                "include_snippets": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include source snippets when available.",
                },
                "include_tests": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include structural test signal data.",
                },
                "format": {
                    "type": "string",
                    "default": "markdown",
                    "description": "Requested presentation format.",
                },
                "max_snippet_lines": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 40,
                    "description": "Maximum source lines to include in the snippet block.",
                },
            },
            "oneOf": [
                {
                    "required": ["symbol"],
                    "not": {"required": ["file"]},
                },
                {
                    "required": ["file"],
                    "not": {"required": ["symbol"]},
                },
            ],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "workflow": {"type": "string", "const": "explain"},
                "input": {"type": "object"},
                "target": {"type": "object"},
                "summary": {"type": "string"},
                "confidence": {"type": "string"},
                "evidence": {"type": "array"},
                "relationships": {"type": "object"},
                "test_signal": {"type": "object"},
                "warnings": {"type": "array"},
                "source_snippet": {"type": "object"},
                "artifacts": {"type": "object"},
            },
            "required": [
                "ok",
                "workflow",
                "input",
                "target",
                "summary",
                "confidence",
                "evidence",
                "relationships",
                "test_signal",
                "warnings",
                "artifacts",
            ],
        },
    },
    "workflow.find": {
        "name": "Workflow Find",
        "description": "Search indexed symbols and files by keyword, type, and path scope.",
        "category": ModuleCategory.WORKFLOW.value,
        "is_stable": True,
        "default_artifacts": ["report.md", "report.json"],
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Search query used against indexed symbols.",
                },
                "types": _string_list_schema("Optional symbol types to include."),
                "paths": _string_list_schema("Optional path filters."),
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10,
                    "description": "Maximum number of primary results to return.",
                },
                "include_details": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to enrich matches with symbol metadata.",
                },
                "include_snippets": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to include source snippets.",
                },
                "include_tests": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether test symbols may appear in results.",
                },
                "format": {
                    "type": "string",
                    "default": "markdown",
                    "description": "Requested presentation format.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "workflow": {"type": "string", "const": "find"},
                "input": {"type": "object"},
                "results": {"type": "array"},
                "candidates": {"type": "array"},
                "reason": {"type": "string"},
                "confidence": {"type": "string"},
                "total": {"type": "integer"},
                "next_required_steps": {"type": "array"},
                "warnings": {"type": "array"},
                "artifacts": {"type": "object"},
            },
            "required": [
                "ok",
                "workflow",
                "input",
                "results",
                "candidates",
                "reason",
                "confidence",
                "total",
                "next_required_steps",
                "warnings",
                "artifacts",
            ],
        },
    },
    "doctor.run": {
        "name": "Doctor Run",
        "description": "Run CodeGraph doctor diagnostics and optionally perform repair.",
        "category": ModuleCategory.DOCTOR.value,
        "is_stable": True,
        "default_artifacts": ["report.md", "report.json"],
        "input_schema": {
            "type": "object",
            "properties": {
                "repair": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to pass --repair to codegraph doctor.",
                },
            },
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "status": {"type": "string"},
                "exit_code": {"type": "integer"},
                "repair": {"type": "boolean"},
                "command": _string_list_schema("Executed CLI command."),
                "output": {"type": "string"},
            },
            "required": ["ok", "status", "exit_code", "repair", "command", "output"],
        },
    },
    "enrich.prepare": {
        "name": "Enrich Prepare",
        "description": "Reserved / planned: generate bounded enrichment input from the index.",
        "category": ModuleCategory.ENRICH.value,
        "is_stable": False,
        "default_artifacts": [],
        "input_schema": {
            "type": "object",
            "description": "Reserved module. Input contract is not finalized yet.",
            "additionalProperties": True,
        },
        "output_schema": _reserved_output_schema(),
    },
    "enrich.validate": {
        "name": "Enrich Validate",
        "description": "Reserved / planned: validate agent-produced enrichment JSON.",
        "category": ModuleCategory.ENRICH.value,
        "is_stable": False,
        "default_artifacts": [],
        "input_schema": {
            "type": "object",
            "description": "Reserved module. Input contract is not finalized yet.",
            "additionalProperties": True,
        },
        "output_schema": _reserved_output_schema(),
    },
    "enrich.import": {
        "name": "Enrich Import",
        "description": "Reserved / planned: import validated enrichment data into storage.",
        "category": ModuleCategory.ENRICH.value,
        "is_stable": False,
        "default_artifacts": [],
        "input_schema": {
            "type": "object",
            "description": "Reserved module. Input contract is not finalized yet.",
            "additionalProperties": True,
        },
        "output_schema": _reserved_output_schema(),
    },
    "benchmark.gate": {
        "name": "Benchmark Gate",
        "description": "Reserved / planned: run benchmark regression gate checks.",
        "category": ModuleCategory.BENCHMARK.value,
        "is_stable": False,
        "default_artifacts": [],
        "input_schema": {
            "type": "object",
            "description": "Reserved module. Input contract is not finalized yet.",
            "additionalProperties": True,
        },
        "output_schema": _reserved_output_schema(),
    },
    "agent_ab.regression": {
        "name": "Agent AB Regression",
        "description": "Reserved / planned: run agent A/B regression evaluation workflows.",
        "category": ModuleCategory.AGENT.value,
        "is_stable": False,
        "default_artifacts": [],
        "input_schema": {
            "type": "object",
            "description": "Reserved module. Input contract is not finalized yet.",
            "additionalProperties": True,
        },
        "output_schema": _reserved_output_schema(),
    },
    "mcp.execute": {
        "name": "MCP Execute",
        "description": "Reserved / planned: wrap MCP tool execution and record harness runs.",
        "category": ModuleCategory.MCP.value,
        "is_stable": False,
        "default_artifacts": [],
        "input_schema": {
            "type": "object",
            "description": "Reserved module. Input contract is not finalized yet.",
            "additionalProperties": True,
        },
        "output_schema": _reserved_output_schema(),
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
