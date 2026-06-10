"""MCP Server for CodeGraph Explorer.

Provides Model Context Protocol tools for AI coding agents
(Claude Code, Cursor, etc.) to query the code graph directly.

Setup (recommended — one command):
    codegraph configure all        # writes stable serve --mcp config
    codegraph configure all --root /path/to/project  # pinned to one project

The configure command writes::

    {
      "mcpServers": {
        "codegraph": {
          "command": "codegraph",
          "args": ["serve", "--mcp"],
          "env": {"CODEGRAPH_PROJECT_ROOT": "/path/to/project"}
        }
      }
    }

Usage (stable — for MCP client launch):
    codegraph serve --mcp

Usage (debug — direct launch):
    python -m codegraph.mcp_server
    python -m codegraph.mcp_server --project-root /path/to/project

Diagnostics:
    codegraph serve --mcp --check   # validate env, no stdio loop
    codegraph doctor                # full health check
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from collections import deque
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import TypeAdapter

# ── Zero-Telemetry ───────────────────────────────────────────────────────
# CodeGraph Explorer is a local-only tool. It never uploads code, file paths,
# index data, error details, or any usage information to any remote service.
# All processing happens on the local machine.
ZERO_TELEMETRY_STATEMENT = (
    "CodeGraph Explorer is local-only. No code, file paths, index data, "
    "error details, or usage information are ever uploaded to any remote service."
)

from codegraph.graph import impact as graph_impact
from codegraph.graph import query as graph_query
from codegraph.graph.confidence import get_confidence_level, is_low_confidence
from codegraph.graph.impact import classify_edge_resolution
from codegraph.graph.models import CodeGraph, EdgeType, GraphEdge, GraphNode, NodeType, Resolution
from codegraph.graph.store import GraphStore
from codegraph.graph.warnings import build_warning, build_stale_index_warning
from codegraph.indexer.scanner import _is_safe_path
from codegraph.indexer.status import detect_status, get_index_status
from codegraph.storage.file_store import FileStore
from codegraph.storage.sqlite_store import SqliteStore
from codegraph.storage.state_store import IndexStateStore

# ── MCP Server ────────────────────────────────────────────────────────────

mcp = FastMCP("codegraph-explorer")

_store: GraphStore | None = None
_cg_dir: Path | None = None
_project_root: str | None = None
_watch_manager: Any | None = None  # WatchSyncManager when watch mode is active

SCHEMA_VERSION = "1.0.0"


def _log(message: str) -> None:
    """Write diagnostic/log output to stderr, keeping stdout clean for MCP protocol."""
    print(message, file=sys.stderr)


# ── Error codes ───────────────────────────────────────────────────────────

ERROR_CODES = {
    "INDEX_MISSING": "INDEX_MISSING",
    "INDEX_STALE": "INDEX_STALE",
    "SYMBOL_NOT_FOUND": "SYMBOL_NOT_FOUND",
    "AMBIGUOUS_SYMBOL": "AMBIGUOUS_SYMBOL",
    "INVALID_ARGUMENT": "INVALID_ARGUMENT",
    "GRAPH_LOAD_FAILED": "GRAPH_LOAD_FAILED",
    "INTERNAL_ERROR": "INTERNAL_ERROR",
}

# ── Response modes ────────────────────────────────────────────────────────

ResponseMode = str  # "compact" | "standard" | "full"
VALID_RESPONSE_MODES = {"compact", "standard", "full"}

# ── Compact field whitelist ────────────────────────────────────────────────
# In compact mode, only fields in this set are allowed in tool response data.
# Fields NOT in this list (e.g. full source code, full evidence, long explanations,
# absolute paths, markdown body) are stripped when response_mode == "compact".

COMPACT_FIELD_WHITELIST: set[str] = {
    # Core symbol identity
    "symbol_id", "name", "type", "file_path", "line_start", "line_end",
    # Relationship signals
    "relation", "distance", "direction",
    # Confidence / resolution
    "confidence", "confidence_level", "resolution", "resolution_category",
    "reason_codes", "reason_code", "provenance",
    # Language / framework (Phase 1 multi-language)
    "language_id", "language", "framework_id", "support_level",
    "evidence_summary",
    "route_path", "http_method", "handler", "parent_component", "child_component",
    # Layer / grouping
    "layer", "group", "role", "groups", "counts",
    # Warnings & status
    "warnings", "truncated", "index_status", "index_health",
    # Search / scoring
    "score", "match_sources", "tags", "priority", "entry_type",
    # Pagination
    "results", "total", "offset", "limit", "has_more",
    # Graph structure
    "center", "target", "nodes", "edges", "filtered_counts", "limits",
    # Impact structure
    "risk", "confirmed", "possible", "external", "external_calls",
    "tests", "related_tests", "suggested_tests",
    "confirmed_files", "possible_files",
    "confirmed_impact", "possible_impact",
    # Hook / auto-update status
    "hook_installed", "hook_auto_update", "hook_state", "hook_status", "hook",
    # Count signals
    "related_tests_count", "selected_context_count",
    "unresolved_count", "changed_file_count",
    # Evidence Pack compact fields
    "pack_id", "task", "entry_points", "related_symbols", "call_graph",
    "impact", "token_budget",
    # Repo summary compact fields
    "stats", "top_modules", "entry_point_candidates", "test_coverage_signal",
    "language_breakdown", "framework_breakdown", "support_level_breakdown",
    "edge_quality_by_language", "suggested_warnings",
    "capabilities", "repo",
    # Index status
    "status", "indexed_at", "index_files", "fingerprint_health",
    "last_change_summary", "last_incremental_stats",
    # Envelope
    "ok", "tool", "data", "error", "code", "message", "details", "meta",
    "schema_version", "response_mode", "item_count", "estimated_tokens",
    "max_items", "max_bytes",
    # Evidence Pack export
    "exported_at", "markdown_path", "format",
    # Misc allowed
    "exact_match", "match_reason", "module", "qualified_name",
    "signature", "visibility", "label", "callers", "callees",
}

# ── Reason codes ──────────────────────────────────────────────────────────

# Maps Resolution enum values to short reason_code strings for compact output
RESOLUTION_TO_REASON_CODE: dict[Resolution, str] = {
    Resolution.exact_ast_match: "exact_ast_match",
    Resolution.same_file_exact: "same_file_exact",
    Resolution.self_method_resolved: "self_method_resolved",
    Resolution.imported_function_exact: "imported_function_exact",
    Resolution.imported_function_alias: "imported_function_alias",
    Resolution.imported_module_attribute: "imported_module_attribute",
    Resolution.relative_import_resolved: "relative_import_resolved",
    Resolution.import_resolved: "import_resolved",
    Resolution.class_method_resolved: "class_method_resolved",
    Resolution.parameter_type_hint_resolved: "parameter_type_hint_resolved",
    Resolution.local_instance_resolved: "local_instance_resolved",
    Resolution.module_instance_resolved: "module_instance_resolved",
    Resolution.constructor_call_resolved: "constructor_call_resolved",
    Resolution.self_attribute_instance_resolved: "self_attribute_instance_resolved",
    Resolution.same_module_fallback: "same_module_fallback",
    Resolution.type_hint_resolved: "type_hint_resolved",
    Resolution.fastapi_route_decorator: "fastapi_route_decorator",
    Resolution.flask_route_decorator: "flask_route_decorator",
    Resolution.django_view_heuristic: "django_view_heuristic",
    Resolution.framework_route_resolved: "framework_route_resolved",
    Resolution.express_route_handler: "express_route_handler",
    Resolution.nextjs_file_route: "nextjs_file_route",
    Resolution.nestjs_controller_route: "nestjs_controller_route",
    Resolution.nestjs_injection_resolved: "nestjs_injection_resolved",
    Resolution.jsx_component_resolved: "jsx_component_resolved",
    Resolution.inline_handler: "inline_handler",
    Resolution.direct_test_call: "direct_test_call",
    Resolution.test_import_match: "test_import_match",
    Resolution.test_name_heuristic: "test_name_heuristic",
    Resolution.test_file_heuristic: "test_file_heuristic",
    Resolution.suggested_test: "suggested_test",
    Resolution.pydantic_model_detected: "pydantic_model_detected",
    Resolution.dataclass_model_detected: "dataclass_model_detected",
    Resolution.sqlalchemy_model_detected: "sqlalchemy_model_detected",
    Resolution.config_class_detected: "config_class_detected",
    Resolution.config_constant_detected: "config_constant_detected",
    Resolution.repository_name_match: "repository_name_match",
    Resolution.store_name_match: "store_name_match",
    Resolution.model_field_match: "model_field_match",
    Resolution.config_field_match: "config_field_match",
    Resolution.persistence_name_match: "persistence_name_match",
    Resolution.symbol_name_match: "symbol_name_match",
    Resolution.file_path_match: "file_path_match",
    Resolution.route_path_match: "route_path_match",
    Resolution.tag_match: "tag_match",
    Resolution.field_name_match: "field_name_match",
    Resolution.call_graph_neighbor: "call_graph_neighbor",
    Resolution.impact_neighbor: "impact_neighbor",
    Resolution.attribute_guess: "attribute_guess",
    Resolution.external_symbol: "external_symbol",
    Resolution.unresolved: "unresolved",
}

# Impact-specific reason codes (not from Resolution enum)
IMPACT_REASON_CODES: dict[str, str] = {
    "direct_definition": "direct_definition",
    "target_file": "target_file",
    "upstream_caller": "upstream_caller",
    "downstream_call": "downstream_call",
    "shared_model": "shared_model",
    "config_dependency": "config_dependency",
    "persistence_dependency": "persistence_dependency",
    "auth_path": "auth_path",
    "token_persistence": "token_persistence",
    "missing_tests": "missing_tests",
    "low_confidence_edge": "low_confidence_edge",
    "stale_index": "stale_index",
    "external_call": "external_call",
    "route_handler": "route_handler",
    "state_mutation": "state_mutation",
    "public_api": "public_api",
    "sensitive_path": "sensitive_path",
    "many_callers": "many_callers",
    "many_callees": "many_callees",
    "external_or_unresolved": "external_or_unresolved",
    "exact_id_match": "exact_id_match",
    "exact_name_match": "exact_name_match",
    "partial_id_match": "partial_id_match",
    "fuzzy_name_match": "fuzzy_name_match",
    "same_module_sibling": "same_module_sibling",
    "isolated_symbol": "isolated_symbol",
    "direct_test_cover": "direct_test_cover",
    "test_calls_target": "test_calls_target",
    "test_is_caller": "test_is_caller",
}

# ── Capability metadata ──────────────────────────────────────────────────

CAPABILITIES: dict[str, Any] = {
    "languages": ["python"],
    "beta_languages": ["typescript", "javascript", "java", "go", "csharp"],
    "supported_edges": ["calls", "imports", "contains", "tested_by", "references"],
    "supports_incremental_index": True,
    "supports_source_snippets": True,
    "supports_impact_modes": True,
    "supports_response_modes": ["compact", "standard"],
    "supports_fuzzy_resolution": True,
    "supports_role_grouping": True,
    "supports_path_glob_filtering": True,
    "supports_reason_codes": True,
    "supports_multi_language": True,
}

LIMITATIONS: list[str] = [
    "dynamic dispatch may be missed",
    "runtime monkey patching is not resolved",
    "low-confidence edges are heuristic",
    "cross-file indirect calls may be incomplete",
    "external library symbols are not indexed deeply",
]


def _get_capabilities() -> dict[str, Any]:
    """Return capability metadata for the current index."""
    caps: dict[str, Any] = dict(CAPABILITIES)
    caps["limitations"] = list(LIMITATIONS)
    # Phase 1: use LanguageRegistry for language list
    try:
        from codegraph.language_support.registry import get_registry
        registry = get_registry()
        caps["languages"] = registry.language_ids()
        caps["language_support_levels"] = {
            reg.language_id: reg.support_level.value
            for reg in registry.list_enabled()
        }
    except Exception:
        pass  # fall back to hardcoded list in CAPABILITIES
    if _store is not None:
        caps["index_stats"] = {
            "symbols": len(_store.all_nodes()),
            "edges": _store.edge_count(),
        }
    return caps


# ── Response helpers ──────────────────────────────────────────────────────


def _resolution_to_reason_code(resolution: Resolution | None) -> str:
    """Convert a Resolution enum to a compact reason code string."""
    if resolution is None:
        return "unresolved"
    return RESOLUTION_TO_REASON_CODE.get(resolution, resolution.value)


def _impact_reason_to_code(reason_text: str) -> str:
    """Map an impact reason string to a compact reason code."""
    reason_lower = reason_text.lower()
    for code_key, code_val in IMPACT_REASON_CODES.items():
        if code_key.replace("_", " ") in reason_lower or code_key in reason_lower:
            return code_val
    # Fallback: try keyword matching
    if "security" in reason_lower or "auth" in reason_lower or "credential" in reason_lower:
        return "sensitive_path"
    if "route" in reason_lower or "api" in reason_lower:
        return "public_api"
    if "state" in reason_lower or "write" in reason_lower or "persist" in reason_lower:
        return "state_mutation"
    if "caller" in reason_lower:
        return "upstream_caller"
    if "callee" in reason_lower:
        return "downstream_call"
    if "test" in reason_lower:
        return "missing_tests"
    if "isolated" in reason_lower:
        return "isolated_symbol"
    return "unknown"


def _matches_path_glob(file_path: str, pattern: str) -> bool:
    """Check if a file path matches a glob pattern (supports **)."""
    normalized = file_path.replace("\\", "/")
    return fnmatch.fnmatch(normalized, pattern)


def _matches_any_path_glob(file_path: str, patterns: list[str]) -> bool:
    """Check if a file path matches any of the given glob patterns."""
    if not patterns:
        return False
    return any(_matches_path_glob(file_path, p) for p in patterns)


# ── Serialization helpers (response_mode-aware) ───────────────────────────


def _serialize_node(node: GraphNode, response_mode: ResponseMode = "compact") -> dict[str, Any]:
    """Serialize a GraphNode based on response_mode."""
    node_type = node.type.value if isinstance(node.type, NodeType) else str(node.type)
    if response_mode == "compact":
        result: dict[str, Any] = {
            "symbol_id": node.id,
            "name": node.name,
            "type": node_type,
            "file_path": node.file_path,
        }
        if node.location:
            result["line_start"] = node.location.line_start
        if node.tags:
            result["tags"] = node.tags
        if node.language_id:
            result["language_id"] = node.language_id
        if node.framework_id:
            result["framework_id"] = node.framework_id
        if node.support_level and node.support_level != "production":
            result["support_level"] = node.support_level
        for key in ("route_path", "http_method", "handler"):
            if key in node.metadata:
                result[key] = node.metadata[key]
        return result
    elif response_mode == "standard":
        result = {
            "symbol_id": node.id,
            "name": node.name,
            "type": node_type,
            "file_path": node.file_path,
            "module": node.module,
            "qualified_name": node.qualified_name,
            "signature": node.signature,
            "visibility": node.visibility,
            "tags": node.tags,
            "framework_id": node.framework_id,
            "line_start": node.location.line_start if node.location else None,
            "line_end": node.location.line_end if node.location else None,
        }
        for key in ("route_path", "http_method", "handler"):
            if key in node.metadata:
                result[key] = node.metadata[key]
        # Docstring excerpt in standard (first 200 chars only)
        if node.docstring:
            result["docstring"] = node.docstring[:200]
        return result
    elif response_mode == "full":
        # Debug mode — returns all available fields
        loc = node.location
        return {
            "symbol_id": node.id,
            "name": node.name,
            "type": node_type,
            "file_path": node.file_path,
            "module": node.module,
            "qualified_name": node.qualified_name,
            "display_name": node.display_name,
            "signature": node.signature,
            "docstring": node.docstring,
            "code_preview": node.code_preview,
            "visibility": node.visibility,
            "tags": node.tags,
            "metadata": node.metadata,
            "line_start": loc.line_start if loc else None,
            "line_end": loc.line_end if loc else None,
            "column_start": loc.column_start if loc else None,
            "column_end": loc.column_end if loc else None,
        }
    else:  # standard (fallback)
        return {
            "symbol_id": node.id,
            "name": node.name,
            "type": node_type,
            "file_path": node.file_path,
            "module": node.module,
            "qualified_name": node.qualified_name,
            "signature": node.signature,
            "visibility": node.visibility,
            "tags": node.tags,
            "line_start": node.location.line_start if node.location else None,
            "line_end": node.location.line_end if node.location else None,
        }


def _build_evidence_summary(edge: GraphEdge) -> str | None:
    """Generate a compact evidence summary for an edge.

    Format: ``"<resolution_category> via <provenance>``.
    Returns ``None`` if no metadata is available.
    """
    if not edge.metadata or not edge.metadata.resolution:
        return None
    res_val = edge.metadata.resolution
    res_str = res_val.value if hasattr(res_val, "value") else str(res_val)
    provenance = edge.metadata.provenance or "unknown"
    return f"{res_str} via {provenance}"


def _serialize_edge(
    edge: GraphEdge,
    response_mode: ResponseMode = "compact",
    include_explanations: bool = False,
) -> dict[str, Any]:
    """Serialize a GraphEdge based on response_mode."""
    edge_type = edge.type.value if hasattr(edge.type, "value") else str(edge.type)
    resolution_str: str | None = None
    reason_code: str | None = None
    reason: str | None = None
    evidence: dict[str, Any] | None = None

    if edge.metadata:
        resolution_str = (
            edge.metadata.resolution.value
            if hasattr(edge.metadata.resolution, "value")
            else str(edge.metadata.resolution)
        )
        reason_code = _resolution_to_reason_code(edge.metadata.resolution)
        reason = edge.metadata.reason or ""
        evidence = edge.metadata.evidence or {}

    base: dict[str, Any] = {
        "type": edge_type,
        "confidence": round(edge.confidence, 4),
        "confidence_level": get_confidence_level(edge.confidence),
        "resolution": resolution_str or "unresolved",
    }

    if response_mode == "compact":
        if reason_code:
            base["reason_code"] = reason_code
        if edge.metadata and edge.metadata.provenance:
            base["provenance"] = edge.metadata.provenance
        # Generate compact evidence summary
        evidence_summary = _build_evidence_summary(edge)
        if evidence_summary:
            base["evidence_summary"] = evidence_summary
        if evidence:
            for key in (
                "framework_id",
                "route_path",
                "http_method",
                "handler",
                "parent_component",
                "child_component",
            ):
                if key in evidence:
                    base[key] = evidence[key]
        return base

    elif response_mode == "standard":
        if reason_code:
            base["reason_code"] = reason_code
        if edge.metadata and edge.metadata.provenance:
            base["provenance"] = edge.metadata.provenance
        if evidence:
            for key in (
                "framework_id",
                "route_path",
                "http_method",
                "handler",
                "parent_component",
                "child_component",
            ):
                if key in evidence:
                    base[key] = evidence[key]
        if include_explanations:
            base["reason"] = reason or ""
            if evidence:
                base["evidence"] = evidence
        return base

    elif response_mode == "full":
        # Debug mode — returns all available edge metadata
        if reason_code:
            base["reason_code"] = reason_code
        base["reason"] = reason or ""
        if evidence:
            base["evidence"] = evidence
        if edge.metadata:
            base["call_expr"] = edge.metadata.call_expr
            base["is_dynamic"] = edge.metadata.is_dynamic
        return base

    else:  # standard fallback
        if reason_code:
            base["reason_code"] = reason_code
        if include_explanations:
            base["reason"] = reason or ""
            if evidence:
                base["evidence"] = evidence
        return base


def _serialize_edge_full(
    edge: GraphEdge,
    response_mode: ResponseMode = "compact",
    include_explanations: bool = False,
) -> dict[str, Any]:
    """Serialize an edge with source/target for graph responses."""
    result = _serialize_edge(edge, response_mode, include_explanations)
    result["source"] = edge.source
    result["target"] = edge.target
    return result


# ── Unified Response Format ───────────────────────────────────────────────


def _build_index_status(project_root: str | None = None) -> dict[str, Any]:
    """Build the index_status block shared by all tool responses.

    Uses the lite ``get_index_status()`` path — reads persistent
    metadata only (state.json, metadata.json, fingerprints.json,
    validation_report.json).  No file scanning, no hashing.
    """
    root_hint = project_root or globals().get("_project_root")
    cg_dir = _find_codegraph_dir(root_hint)
    if cg_dir is None:
        return {
            "status": "missing",
            "indexed_at": None,
            "changed_files": [],
            "added_files": [],
            "deleted_files": [],
            "index_files": {
                "graph_json": False,
                "symbols_json": False,
                "sqlite": False,
                "metadata_json": False,
            },
            "stats": {"files": 0, "symbols": 0, "edges": 0},
        }

    # Lite path: metadata-only, no file scanning
    root_path = cg_dir.parent
    lite = get_index_status(root_path)

    # Enrich with live store stats when available
    stats = lite.get("stats", {"files": 0, "symbols": 0, "edges": 0})
    store_obj = globals().get("_store")
    if store_obj is not None:
        nodes = store_obj.all_nodes()
        files = {n.file_path for n in nodes if n.file_path}
        stats = {
            "files": len(files),
            "symbols": len(nodes),
            "edges": store_obj.edge_count(),
        }

    # Build backward-compatible status block
    status_block: dict[str, Any] = {
        "status": lite["status"],
        "indexed_at": lite.get("indexed_at"),
        "index_files": lite.get("index_files", {}),
        "stats": stats,
        # Lite doesn't scan files, so change lists are derived
        # from state.json's last_change_summary
        "changed_files": [],
        "added_files": [],
        "deleted_files": [],
    }

    change_summary = lite.get("last_change_summary")
    if change_summary:
        total = sum(change_summary.values())
        if total > 0:
            status_block[
                "_change_summary_note"] = f"{change_summary.get('structural', 0)} structural, {change_summary.get('added', 0)} added, {change_summary.get('deleted', 0)} deleted"

    if lite["status"] == "error":
        status_block["last_error"] = lite.get("last_error")

    if lite.get("fingerprint_health"):
        status_block["fingerprint_health"] = lite["fingerprint_health"]

    if lite.get("last_change_summary"):
        status_block["last_change_summary"] = lite["last_change_summary"]

    if lite.get("last_incremental_stats"):
        status_block["last_incremental_stats"] = lite["last_incremental_stats"]

    if lite.get("hook"):
        status_block["hook"] = lite["hook"]

    if lite.get("index_health"):
        status_block["index_health"] = lite["index_health"]

    if lite.get("suggested_fix"):
        status_block["suggested_fix"] = lite["suggested_fix"]

    return status_block


def _collect_warnings(
    fuzzy_warning: str | None = None,
) -> list[dict[str, Any]]:
    """Collect warnings including stale index check and watch state."""
    warnings: list[dict[str, Any]] = []
    index_status = _build_index_status()
    status = index_status["status"]

    if status == "indexing":
        warnings.append({
            "type": "indexing_in_progress",
            "severity": "info",
            "message": "Index update is in progress. Results may reflect the previous index.",
        })
    elif status == "error":
        last_error = index_status.get("last_error", "Unknown error")
        suggested_fix = index_status.get("suggested_fix", "codegraph doctor")
        warnings.append({
            "type": "index_update_failed",
            "severity": "warning",
            "message": f"Last incremental index failed. Results may be outdated. Run: {suggested_fix}",
            "evidence": {"error": str(last_error)},
        })
    elif status == "stale":
        change_summary = index_status.get("last_change_summary", {})
        total = sum(change_summary.values()) if change_summary else 0
        suggested_fix = index_status.get("suggested_fix", "codegraph init --incremental")
        stale_entry = build_stale_index_warning(
            changed_files=index_status.get("changed_files", []),
            added_files=index_status.get("added_files", []),
            deleted_files=index_status.get("deleted_files", []),
            suggested_fix=suggested_fix,
        )
        # Override message with the one that includes the fix command
        if total > 0:
            stale_entry["message"] = (
                f"Index is stale. Results may not reflect recent file changes. "
                f"({total} file(s) changed). Run: {suggested_fix}"
            )
        else:
            stale_entry["message"] = (
                f"Index is stale. Results may not reflect recent file changes. "
                f"Run: {suggested_fix}"
            )
        warnings.append(stale_entry)

    if fuzzy_warning:
        warnings.append(build_warning(
            "fuzzy_match",
            message=fuzzy_warning,
            reason_code="fuzzy_name_match",
        ))

    # Add index_health warning if validation found issues
    index_health = index_status.get("index_health")
    if index_health and index_health.get("status") != "ok":
        health_status = index_health["status"]
        severity = "warning" if health_status == "warning" else "error"
        issue_counts = index_health.get("issue_counts", {})
        warnings.append(build_warning(
            "index_health",
            message=(
                f"Index health warning detected. "
                f"Graph validation status is '{health_status}' "
                f"({issue_counts.get('warnings', 0)} warnings, "
                f"{issue_counts.get('fatal', 0)} fatal). "
                f"Run: codegraph doctor"
            ),
            evidence=issue_counts,
            reason_code=f"index_health_{health_status}",
        ))

    return warnings


def _respond_ok(
    data: Any,
    tool: str = "",
    warnings: list[dict[str, Any]] | None = None,
    response_mode: ResponseMode = "compact",
    item_count: int | None = None,
    truncated: bool = False,
    max_items: int | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Wrap a successful tool result in the standard envelope with payload meta."""
    estimated_tokens = _estimate_payload_tokens(data)
    idx = _build_index_status()
    idx_health = idx.get("index_health")
    return {
        "ok": True,
        "tool": tool,
        "data": data,
        "warnings": warnings or [],
        "index_status": idx["status"],
        "index_health": idx_health["status"] if idx_health else "ok",
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "response_mode": response_mode,
            "item_count": item_count,
            "estimated_tokens": estimated_tokens,
            "truncated": truncated,
            "max_items": max_items,
            "max_bytes": max_bytes,
        },
    }


def _respond_error(
    code: str,
    message: str,
    tool: str = "",
    details: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Wrap a failed tool result in the standard envelope."""
    idx = _build_index_status()
    idx_health = idx.get("index_health")
    return {
        "ok": False,
        "tool": tool,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "warnings": warnings or [],
        "index_status": idx["status"],
        "index_health": idx_health["status"] if idx_health else "ok",
        "meta": {"schema_version": SCHEMA_VERSION},
    }


# ── Result shaping ────────────────────────────────────────────────────────

# Default excluded paths (always excluded unless explicitly included)
DEFAULT_EXCLUDE_PATHS = [
    ".venv/**", "venv/**", "node_modules/**", "__pycache__/**",
    ".git/**", "*.pyc", ".codegraph/**",
]


def _apply_result_shaping(
    items: list[dict[str, Any]],
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "relevance",
    include_types: list[str] | None = None,
    exclude_types: list[str] | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    default_exclude: bool = True,
) -> dict[str, Any]:
    """Filter, sort, and paginate a list of result items.

    Each item should be a dict that may contain keys:
      ``type``, ``file_path``, ``confidence``, ``distance``, ``name``,
      ``score``, ``symbol_id``.

    Returns ``{"results": [...], "total": int, "offset": int, "limit": int, "has_more": bool}``.
    """
    filtered = list(items)

    # Apply path exclusions
    all_exclude_paths = list(exclude_paths or [])
    if default_exclude:
        all_exclude_paths.extend(DEFAULT_EXCLUDE_PATHS)

    if all_exclude_paths:
        filtered = [
            item for item in filtered
            if not _matches_any_path_glob(item.get("file_path", ""), all_exclude_paths)
        ]

    # Apply path inclusions (if specified, only keep items matching include_paths)
    if include_paths:
        filtered = [
            item for item in filtered
            if _matches_any_path_glob(item.get("file_path", ""), include_paths)
        ]

    # Apply type filters
    if include_types:
        filtered = [item for item in filtered if item.get("type") in include_types]
    if exclude_types:
        filtered = [item for item in filtered if item.get("type") not in exclude_types]

    # Sort
    if sort_by == "preserve":
        pass
    elif sort_by == "confidence":
        filtered.sort(key=lambda x: (x.get("confidence", 0) or 0), reverse=True)
    elif sort_by == "distance":
        filtered.sort(key=lambda x: (x.get("distance", 999) or 999))
    elif sort_by == "file_path":
        filtered.sort(key=lambda x: x.get("file_path", ""))
    elif sort_by == "name":
        filtered.sort(key=lambda x: x.get("name", ""))
    else:  # relevance / default
        filtered.sort(
            key=lambda x: (
                -(x.get("score", x.get("confidence", 0)) or 0),
                x.get("distance", 999) or 999,
                x.get("name", ""),
            )
        )

    total = len(filtered)
    paginated = filtered[offset:offset + limit]

    return {
        "results": paginated,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total,
    }


# ── Store helpers ─────────────────────────────────────────────────────────


def _get_project_info() -> dict[str, Any]:
    """Return current project root and index path (may be partial)."""
    info: dict[str, Any] = {}
    if _project_root:
        info["project_root"] = _project_root
    if _cg_dir:
        info["index_path"] = str(_cg_dir / "graph.json")
    return info


def _find_codegraph_dir(root: str | None = None) -> Path | None:
    """Walk up from *root* (or cwd) looking for .codegraph/graph.json."""
    start = Path(root).resolve() if root else Path.cwd()
    for parent in [start] + list(start.parents):
        candidate = parent / ".codegraph"
        if (candidate / "graph.json").exists():
            return candidate
    return None


def _resolve_project_root(cli_root: str | None) -> str | None:
    """Resolve the project root from CLI arg, env var, or CWD."""
    if cli_root:
        return cli_root
    env_root = os.environ.get("CODEGRAPH_PROJECT_ROOT")
    if env_root:
        return env_root
    return None


def _load_store(project_root: str | None = None) -> tuple[GraphStore, Path]:
    """Load graph into memory (cached after first call), preferring SQLite."""
    global _store, _cg_dir, _project_root

    if _store is not None and _cg_dir is not None:
        return _store, _cg_dir

    cg_dir = _find_codegraph_dir(project_root)
    if cg_dir is None:
        searched = project_root or str(Path.cwd())
        env_root = os.environ.get("CODEGRAPH_PROJECT_ROOT")
        lines = [
            "No .codegraph directory found.",
            f"Searched from: {searched}",
        ]
        if env_root:
            lines.append(f"CODEGRAPH_PROJECT_ROOT is set to: {env_root}")
        lines.extend([
            "",
            "Fix:",
            "  cd <your-project>",
            "  codegraph init",
            "  codegraph configure cursor --force",
            "  Restart Cursor",
        ])
        raise RuntimeError("\n".join(lines))

    store = GraphStore()
    sqlite_path = cg_dir / "index.sqlite"
    if sqlite_path.exists():
        try:
            sql_store = SqliteStore(sqlite_path)
            sql_store.initialize()
            node_adapter = TypeAdapter(list[GraphNode])
            edge_adapter = TypeAdapter(list[GraphEdge])
            store.load_from_lists(
                node_adapter.validate_python(sql_store.load_all_nodes()),
                edge_adapter.validate_python(sql_store.load_all_edges()),
            )
            sql_store.close()
        except Exception:
            graph_path = cg_dir / "graph.json"
            graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
            store.load_from_graph(graph)
    else:
        graph_path = cg_dir / "graph.json"
        graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
        store.load_from_graph(graph)

    _store = store
    _cg_dir = cg_dir
    _project_root = str(cg_dir.parent.resolve())
    return store, cg_dir


# ── Resolve helpers ───────────────────────────────────────────────────────


def _resolve_node(store: GraphStore, symbol_id: str) -> GraphNode | None:
    """Resolve a symbol ID with fuzzy fallback (exact, name, partial id)."""
    node = store.get_node(symbol_id)
    if node:
        return node
    symbol_lower = symbol_id.lower()
    for n in store.all_nodes():
        if n.name.lower() == symbol_lower or symbol_lower in n.id.lower():
            return n
    return None


def _resolve_node_detailed(
    store: GraphStore,
    symbol_id: str,
    max_candidates: int = 5,
    expected_type: str | None = None,
    path_hint: str | None = None,
) -> dict[str, Any] | None:
    """Resolve a symbol and return match metadata.

    Returns ``None`` if no match found, otherwise a dict with keys:
      ``node``, ``exact_match``, ``match_reason``, ``candidates``.
    """
    node = store.get_node(symbol_id)
    if node:
        return {
            "node": node,
            "exact_match": True,
            "match_reason": "exact_id",
            "candidates": [],
        }

    symbol_lower = symbol_id.lower()
    candidates: list[dict[str, Any]] = []

    # First pass: exact name match (highest priority)
    for n in store.all_nodes():
        if n.name.lower() == symbol_lower:
            # Check type/path hints
            if expected_type:
                ntype = n.type.value if isinstance(n.type, NodeType) else str(n.type)
                if ntype != expected_type:
                    continue
            if path_hint:
                if path_hint.lower() not in n.file_path.lower():
                    continue
            return {
                "node": n,
                "exact_match": False,
                "match_reason": "exact_name",
                "candidates": [],
            }

    # Second pass: partial ID or name match
    for n in store.all_nodes():
        ntype = n.type.value if isinstance(n.type, NodeType) else str(n.type)
        # Apply hints for candidate filtering
        if expected_type and ntype != expected_type:
            continue
        if path_hint and path_hint.lower() not in n.file_path.lower():
            continue

        if symbol_lower in n.id.lower():
            candidates.append(_node_to_summary(n))
        elif n.name and symbol_lower in n.name.lower():
            candidates.append(_node_to_summary(n))

    if not candidates:
        # Try without hints as fallback
        for n in store.all_nodes():
            if symbol_lower in n.id.lower():
                candidates.append(_node_to_summary(n))
            elif n.name and symbol_lower in n.name.lower():
                candidates.append(_node_to_summary(n))

    if not candidates:
        return None

    # Deduplicate candidates
    seen_ids: set[str] = set()
    unique_candidates: list[dict[str, Any]] = []
    for c in candidates:
        if c["symbol_id"] not in seen_ids:
            seen_ids.add(c["symbol_id"])
            unique_candidates.append(c)

    # Multiple candidates — return AMBIGUOUS
    if len(unique_candidates) > 1:
        return {
            "node": None,
            "exact_match": False,
            "match_reason": "ambiguous",
            "candidates": unique_candidates[:max_candidates],
        }

    best = unique_candidates[0]
    best_node = store.get_node(best["symbol_id"])
    if best_node is None:
        return None

    return {
        "node": best_node,
        "exact_match": False,
        "match_reason": "partial_id_or_name",
        "candidates": unique_candidates[:max_candidates],
    }


def _resolve_input_symbol(
    store: GraphStore,
    symbol_id: str | None,
    symbol: str | None,
    resolve: bool,
    expected_type: str | None = None,
    path_hint: str | None = None,
) -> dict[str, Any] | None:
    """Resolve symbol from either direct symbol_id or fuzzy symbol+resolve.

    Mode A: symbol_id provided directly (e.g. "app/api/auth.py::login")
    Mode B: symbol + resolve=true with optional expected_type/path_hint

    Returns same structure as _resolve_node_detailed, or None if neither
    input mode is usable.
    """
    if symbol_id:
        return _resolve_node_detailed(
            store, symbol_id,
            expected_type=expected_type,
            path_hint=path_hint,
        )
    elif symbol and resolve:
        return _resolve_node_detailed(
            store, symbol,
            expected_type=expected_type,
            path_hint=path_hint,
        )
    return None


def _node_to_summary(node: GraphNode) -> dict[str, Any]:
    """Serialize a GraphNode to a brief summary dict."""
    return {
        "symbol_id": node.id,
        "name": node.name,
        "type": node.type.value if isinstance(node.type, NodeType) else str(node.type),
        "file_path": node.file_path,
        "line_start": node.location.line_start if node.location else None,
        "line_end": node.location.line_end if node.location else None,
    }


def _node_to_detail(node: GraphNode) -> dict[str, Any]:
    """Serialize a GraphNode to a full detail dict."""
    return {
        "symbol_id": node.id,
        "name": node.name,
        "type": node.type.value if isinstance(node.type, NodeType) else str(node.type),
        "file_path": node.file_path,
        "module": node.module,
        "qualified_name": node.qualified_name,
        "display_name": node.display_name,
        "signature": node.signature,
        "docstring": node.docstring,
        "visibility": node.visibility,
        "tags": node.tags,
        "metadata": node.metadata,
        "confidence": 1.0,
        "line_start": node.location.line_start if node.location else None,
        "line_end": node.location.line_end if node.location else None,
    }


def _edge_to_dict(edge: GraphEdge) -> dict[str, Any]:
    """Serialize an edge to a dict with evidence fields (legacy compat)."""
    result: dict[str, Any] = {
        "type": edge.type.value if hasattr(edge.type, "value") else str(edge.type),
        "confidence": edge.confidence,
        "confidence_level": get_confidence_level(edge.confidence),
    }
    if edge.metadata:
        result["resolution"] = (
            edge.metadata.resolution.value
            if hasattr(edge.metadata.resolution, "value")
            else str(edge.metadata.resolution)
        )
        result["reason"] = edge.metadata.reason or ""
        result["evidence"] = edge.metadata.evidence or {}
    else:
        result["resolution"] = "unresolved"
        result["reason"] = ""
        result["evidence"] = {}
    return result


def _edge_to_full(edge: GraphEdge) -> dict[str, Any]:
    """Serialize an edge with source/target info for graph responses (legacy compat)."""
    result = {
        "source": edge.source,
        "target": edge.target,
        "type": edge.type.value if hasattr(edge.type, "value") else str(edge.type),
        "confidence": edge.confidence,
        "confidence_level": get_confidence_level(edge.confidence),
    }
    if edge.metadata:
        result["resolution"] = (
            edge.metadata.resolution.value
            if hasattr(edge.metadata.resolution, "value")
            else str(edge.metadata.resolution)
        )
        result["reason"] = edge.metadata.reason or ""
        result["evidence"] = edge.metadata.evidence or {}
    else:
        result["resolution"] = "unresolved"
        result["reason"] = ""
        result["evidence"] = {}
    return result


def _read_source_snippet(
    file_path: str,
    line_start: int,
    line_end: int,
    source_mode: str = "body",
    max_source_lines: int = 80,
) -> dict[str, Any]:
    """Read source code for a symbol's line range.

    Args:
        file_path: Path relative to project root
        line_start: Start line (1-indexed)
        line_end: End line (1-indexed)
        source_mode: "signature", "body", or "surrounding"
        max_source_lines: Maximum lines to return

    Returns ``{"included": bool, "content": str|None, "truncated": bool, "lines": int}``.
    Performs realpath validation to prevent symlink escape reads.
    """
    if _project_root is None:
        return {"included": False, "content": None, "truncated": False, "lines": 0, "source_mode": source_mode}
    full_path = Path(_project_root) / file_path
    if not full_path.exists():
        return {"included": False, "content": None, "truncated": False, "lines": 0, "source_mode": source_mode}

    # Symlink safety: reject reads that escape the project root
    root_path = Path(_project_root)
    is_safe, _ = _is_safe_path(full_path, root_path)
    if not is_safe:
        return {"included": False, "content": None, "truncated": False, "lines": 0, "source_mode": source_mode}

    try:
        lines = full_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {"included": False, "content": None, "truncated": False, "lines": 0, "source_mode": source_mode}

    if line_start < 1:
        line_start = 1
    if line_end > len(lines):
        line_end = len(lines)
    if line_start > len(lines):
        return {"included": False, "content": None, "truncated": False, "lines": 0, "source_mode": source_mode}

    total_lines = len(lines)
    selected_lines: list[str] = []

    if source_mode == "signature":
        # Return only the first line (declaration/signature)
        selected_lines = [lines[line_start - 1]]
    elif source_mode == "surrounding":
        # Return N lines of context above and below, centered on the symbol
        context_lines = max_source_lines // 3
        ctx_start = max(1, line_start - context_lines)
        ctx_end = min(total_lines, line_end + context_lines)
        selected_lines = lines[ctx_start - 1:ctx_end]
    else:  # body
        selected_lines = lines[line_start - 1:line_end]

    truncated = len(selected_lines) > max_source_lines
    if truncated:
        selected_lines = selected_lines[:max_source_lines]

    content = "\n".join(selected_lines)
    return {
        "included": True,
        "content": content,
        "truncated": truncated,
        "lines": len(selected_lines),
        "source_mode": source_mode,
        "source_line_start": line_start,
        "source_line_end": line_end,
    }


def _count_relations(store: GraphStore, node_id: str) -> dict[str, int]:
    """Count relations for relations_summary."""
    callers = 0
    callees = 0
    tests = 0
    impact_files: set[str] = set()

    for edge in store.get_incoming_edges(node_id):
        if edge.type == EdgeType.calls:
            caller_node = store.get_node(edge.source)
            if caller_node and caller_node.type == NodeType.test:
                tests += 1
            else:
                callers += 1
        elif edge.type == EdgeType.tested_by:
            tests += 1
            if edge.source:
                src_node = store.get_node(edge.source)
                if src_node and src_node.file_path:
                    impact_files.add(src_node.file_path)

    for edge in store.get_outgoing_edges(node_id):
        if edge.type == EdgeType.calls:
            callee_node = store.get_node(edge.target)
            if callee_node and callee_node.type == NodeType.test:
                tests += 1
            else:
                callees += 1
        elif edge.type == EdgeType.tested_by:
            tests += 1
        if edge.target:
            tgt_node = store.get_node(edge.target)
            if tgt_node and tgt_node.file_path:
                impact_files.add(tgt_node.file_path)

    return {
        "callers_count": callers,
        "callees_count": callees,
        "tests_count": tests,
        "impact_files_count": len(impact_files),
    }


# ── Role assignment ───────────────────────────────────────────────────────


def _assign_role(
    node_id: str,
    center_id: str,
    store: GraphStore,
) -> str:
    """Assign a role label to a neighbor node."""
    if node_id == center_id:
        return "center"
    node = store.get_node(node_id)
    if node is None:
        return "external_or_unresolved"

    # Check node type
    if node.type == NodeType.test:
        return "test"
    if node.type == NodeType.external_symbol:
        return "external_or_unresolved"

    # Check tags for model/config/persistence
    tags = node.tags or []
    if "model" in tags:
        return "model"
    if "config" in tags or "settings" in tags:
        return "config"
    if "store" in tags or "persistence" in tags:
        return "persistence"

    # Check relationship to center
    for edge in store.get_outgoing_edges(center_id):
        if edge.target == node_id:
            if edge.type == EdgeType.calls:
                return "callee"
            if edge.type == EdgeType.imports:
                return "model" if (tags and "model" in tags) else "reference"
            if edge.type == EdgeType.references:
                return "reference"
    for edge in store.get_incoming_edges(center_id):
        if edge.source == node_id:
            if edge.type == EdgeType.calls:
                return "caller"
            if edge.type == EdgeType.tested_by:
                return "test"
            if edge.type == EdgeType.references:
                return "reference"

    return "neighbor"


# ── Layer assignment ───────────────────────────────────────────────────────


def _assign_layer(file_path: str) -> str:
    """Assign a layer label based on file_path directory heuristics. No LLM.

    Maps directory/name patterns to architectural layers. Pure heuristic —
    no community detection, no ML. Used in compact outputs for lightweight
    grouping of symbols and files.
    """
    normalized = file_path.replace("\\", "/").lower()
    # Order matters: more specific patterns first to avoid false matches
    # (e.g. "codegraph/graph" before "graph/" to prevent matching "codegraph/indexer")
    layer_map: list[tuple[str, str]] = [
        ("codegraph/graph/", "graph"), ("codegraph/graph_", "graph"),
        ("codegraph/indexer", "indexer"), ("indexer/", "indexer"),
        ("codegraph/storage/", "storage"), ("storage/", "storage"),
        ("codegraph/context/", "context"),
        ("codegraph/mcp/", "mcp"), ("mcp_server", "mcp"),
        ("api/", "api"), ("routes", "api"), ("router", "api"),
        ("service", "service"), ("services", "service"),
        ("store/", "storage"),
        ("context/", "context"), ("evidence", "context"),
        ("test", "tests"), ("test_", "tests"),
        ("config", "config"), ("settings", "config"),
        ("model", "models"), ("schema", "models"),
        ("persistence", "persistence"), ("repository", "persistence"),
        ("cli/", "indexer"), ("cli_", "indexer"),
    ]
    for pattern, layer in layer_map:
        if pattern in normalized:
            return layer
    return "unknown"


# ── Payload estimation ─────────────────────────────────────────────────────


def _estimate_payload_tokens(data: Any) -> int:
    """Estimate token count for a response payload using char/4 heuristic."""
    try:
        json_str = json.dumps(data, default=str, ensure_ascii=False)
        return max(len(json_str) // 4, 1)
    except (TypeError, ValueError):
        return 1


# ── Compact whitelist filtering ─────────────────────────────────────────────


def _apply_compact_whitelist(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively filter dict keys to only allow COMPACT_FIELD_WHITELIST fields.

    This is an optional defensive pass — individual serialization functions
    should already only emit whitelisted fields in compact mode. This filter
    provides a safety net against regressions.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key not in COMPACT_FIELD_WHITELIST:
            continue
        if isinstance(value, dict):
            result[key] = _apply_compact_whitelist(value)
        elif isinstance(value, list):
            result[key] = [
                _apply_compact_whitelist(v) if isinstance(v, dict) else v
                for v in value
            ]
        else:
            result[key] = value
    return result


# ── Tool: search_symbols ──────────────────────────────────────────────────


@mcp.tool(name="codegraph_search_symbols")
def search_symbols(
    query: str,
    type: str | None = None,
    types: str | None = None,
    tags: str | None = None,
    paths: str | None = None,
    file_path: str | None = None,
    path_prefix: str | None = None,
    layer: str | None = None,
    include_tests: bool = True,
    exclude_external: bool = True,
    min_score: float = 0.2,
    exact: bool = False,
    fuzzy: bool = True,
    exclude_tests: bool | None = None,
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "relevance",
    response_mode: str = "compact",
    include_explanations: bool = False,
    language_id: str | None = None,
    # Legacy params for backward compat
    type_filter: str | None = None,
    file_filter: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Search for code symbols by name, file path, type, tags, or path glob.

    Use before grep when looking for functions, classes, methods, routes,
    exports, or framework entry points. Prefer this over grep/glob for
    finding where a symbol is defined or referenced in the codebase.

    Args:
        query: Search keyword — symbol name, file path fragment, or docstring keyword
        type: Exact node type, e.g. "function"
        types: Comma-separated node types, e.g. "function,method,class" (default: all)
        tags: Comma-separated tags, e.g. "auth,route" (default: none)
        paths: Comma-separated path glob patterns, e.g. "app/api/**,tests/**"
        file_path: Exact file path
        path_prefix: File path prefix
        layer: Layer label inferred from file path, e.g. "api", "service"
        include_tests: Include test symbols (default true; production sorts first)
        exclude_external: Exclude external symbols (default true)
        min_score: Minimum relevance score (default 0.2)
        exact: If true, only return exact name matches (default false)
        fuzzy: If true, use fuzzy matching (default true)
        exclude_tests: Legacy inverse of include_tests
        limit: Maximum results (default 20, max 100)
        offset: Pagination offset (default 0)
        sort_by: Sort order — "relevance" (default), "confidence", "file_path", "name"
        response_mode: "compact" (default) or "standard"
        include_explanations: If true, include reason text and evidence (default false)
        language_id: Filter by language (e.g. "python"). Default: no filter.
    """
    effective_limit = max(1, min(limit or max_results or 20, 100))
    effective_include_tests = include_tests if exclude_tests is None else not exclude_tests
    include_types_list: list[str] | None = None
    if types:
        include_types_list = [t.strip() for t in types.split(",") if t.strip()]
    if type:
        include_types_list = [*(include_types_list or []), type]
    effective_type_filter = type_filter
    if type and not include_types_list:
        effective_type_filter = type
    if response_mode not in VALID_RESPONSE_MODES:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message=f"Invalid response_mode '{response_mode}'. Valid: {', '.join(sorted(VALID_RESPONSE_MODES))}",
            tool="codegraph_search_symbols",
        )

    try:
        store, cg_dir = _load_store()
        sqlite_path = cg_dir / "index.sqlite"
        query_store: Any = store
        try:
            if sqlite_path.exists():
                query_store = SqliteStore(sqlite_path)
                query_store.initialize()
            result = graph_query.search_symbols(
                query_store,
                query=query,
                type_filter=effective_type_filter,
                types=include_types_list,
                file_filter=file_filter,
                file_path=file_path,
                path_prefix=path_prefix,
                layer=layer,
                include_tests=effective_include_tests,
                exclude_external=exclude_external,
                min_score=min_score,
                limit=effective_limit + offset,
                use_fts=True,
                fuzzy=fuzzy,
                language_id=language_id,
            )
        finally:
            if isinstance(query_store, SqliteStore):
                query_store.close()
    except RuntimeError as e:
        return _respond_error(
            code=ERROR_CODES["INDEX_MISSING"],
            message=str(e),
            tool="codegraph_search_symbols",
        )

    items = result["results"]

    # Parse type filters
    exclude_types_list: list[str] | None = None
    if not effective_include_tests and not include_types_list:
        exclude_types_list = ["test"]
    elif not effective_include_tests and include_types_list:
        exclude_types_list = ["test"] if "test" not in include_types_list else None

    # Parse path filters
    include_paths_list: list[str] | None = None
    if paths:
        include_paths_list = [p.strip() for p in paths.split(",") if p.strip()]

    # Apply tag filter
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        items = [
            item for item in items
            if any(tag in [tt.lower() for tt in item.get("tags", [])] for tag in tag_list)
        ]

    # Apply exact match filter
    if exact:
        query_lower = query.lower().strip()
        items = [item for item in items if item.get("name", "").lower() == query_lower]

    # Shape results
    shape_sort = "preserve" if sort_by == "relevance" else sort_by
    shaped = _apply_result_shaping(
        items,
        limit=effective_limit,
        offset=offset,
        sort_by=shape_sort,
        include_types=include_types_list,
        exclude_types=exclude_types_list,
        include_paths=include_paths_list,
    )

    # Serialize based on response_mode
    serialized_results: list[dict[str, Any]] = []
    for item in shaped["results"]:
        entry: dict[str, Any] = {
            "symbol_id": item["symbol_id"],
            "name": item["name"],
            "type": item["type"],
            "file_path": item["file_path"],
            "line_start": item.get("line_start"),
            "line_end": item.get("line_end"),
            "score": item.get("score"),
            "match_sources": item.get("match_sources", []),
            "layer": item.get("layer"),
        }
        if response_mode == "compact":
            # Add multi-language signals in compact mode
            if item.get("language_id"):
                entry["language_id"] = item["language_id"]
            if item.get("framework_id"):
                entry["framework_id"] = item["framework_id"]
            if item.get("support_level") and item.get("support_level") != "production":
                entry["support_level"] = item["support_level"]
            if item.get("tags"):
                entry["tags"] = item.get("tags")
        elif response_mode == "standard":
            entry["qualified_name"] = item.get("qualified_name")
            entry["signature"] = item.get("signature")
            entry["docstring_excerpt"] = item.get("docstring_excerpt")
            entry["tags"] = item.get("tags", [])
            entry["confidence"] = item.get("confidence", 1.0)
            entry["confidence_level"] = get_confidence_level(item.get("confidence", 1.0))
            if include_explanations:
                entry["reason"] = f"Matched via: {', '.join(item.get('match_sources', []))}"
        entry["truncated"] = item.get("truncated", False)
        serialized_results.append(entry)

    warnings: list[dict[str, Any]] = []
    if result.get("ambiguous"):
        warnings.append(build_warning(
            "ambiguous_symbol_match",
            message="Ambiguous symbol match. Use symbol_id for exact lookup.",
            reason_code="ambiguous_symbol_match",
        ))
    serialized_candidates: list[dict[str, Any]] = []
    if result.get("ambiguous"):
        for item in result.get("candidates", []):
            candidate: dict[str, Any] = {
                "symbol_id": item.get("symbol_id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "file_path": item.get("file_path"),
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
                "score": item.get("score"),
                "match_sources": item.get("match_sources", []),
                "layer": item.get("layer"),
            }
            if response_mode == "standard":
                candidate["qualified_name"] = item.get("qualified_name")
                candidate["signature"] = item.get("signature")
                candidate["docstring_excerpt"] = item.get("docstring_excerpt")
                candidate["tags"] = item.get("tags", [])
                candidate["confidence"] = item.get("confidence", 1.0)
            serialized_candidates.append(candidate)

    return _respond_ok(
        data={
            "query": query,
            "results": serialized_results,
            "ambiguous": bool(result.get("ambiguous")),
            "candidates": serialized_candidates,
            "total": shaped["total"],
            "offset": shaped["offset"],
            "limit": shaped["limit"],
            "has_more": shaped["has_more"],
        },
        tool="codegraph_search_symbols",
        warnings=warnings,
        response_mode=response_mode,
        item_count=len(serialized_results),
        truncated=shaped["has_more"],
        max_items=effective_limit,
    )


# ── Tool: get_symbol ──────────────────────────────────────────────────────


@mcp.tool(name="codegraph_get_symbol")
def get_symbol(
    symbol_id: str,
    resolve: bool = True,
    expected_type: str | None = None,
    path_hint: str | None = None,
    include_source: bool = False,
    source_mode: str = "body",
    max_source_lines: int = 80,
    include_relations: bool = True,
    response_mode: str = "compact",
    include_explanations: bool = False,
) -> dict[str, Any]:
    """Get detailed information about a specific code symbol.

    Use after search_symbols when you need exact metadata, location,
    signature, and docstring for a symbol. Prefer this before Read
    when you only need symbol-level information rather than full file content.

    Supports fuzzy lookup with resolve mode. Returns AMBIGUOUS_SYMBOL
    error when multiple candidates match.

    Args:
        symbol_id: Symbol node ID (e.g. "app/api/auth.py::login")
                   or a symbol name for fuzzy lookup
        resolve: If true, attempt fuzzy resolution when exact ID fails (default true)
        expected_type: Hint for expected node type when resolving (e.g. "function")
        path_hint: Hint for expected file path when resolving (e.g. "app/api")
        include_source: If true, include source code snippet (default false)
        source_mode: "signature", "body", or "surrounding" (default "body")
        max_source_lines: Maximum source lines to return (default 80)
        include_relations: If true, include relations_summary counts (default true)
        response_mode: "compact" (default) or "standard"
        include_explanations: If true, include reason text and evidence (default false)
    """
    if response_mode not in VALID_RESPONSE_MODES:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message=f"Invalid response_mode '{response_mode}'. Valid: {', '.join(sorted(VALID_RESPONSE_MODES))}",
            tool="codegraph_get_symbol",
        )
    if source_mode not in ("signature", "body", "surrounding"):
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message=f"Invalid source_mode '{source_mode}'. Valid: signature, body, surrounding",
            tool="codegraph_get_symbol",
        )

    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code=ERROR_CODES["INDEX_MISSING"],
            message=str(e),
            tool="codegraph_get_symbol",
        )

    if resolve:
        result = _resolve_node_detailed(
            store, symbol_id,
            expected_type=expected_type,
            path_hint=path_hint,
        )
    else:
        node = store.get_node(symbol_id)
        result = {
            "node": node,
            "exact_match": True,
            "match_reason": "exact_id",
            "candidates": [],
        } if node else None

    if result is None:
        return _respond_error(
            code=ERROR_CODES["SYMBOL_NOT_FOUND"],
            message=f"No symbol found matching '{symbol_id}'",
            tool="codegraph_get_symbol",
            details=_get_project_info(),
        )

    # Check for ambiguous match
    if result.get("match_reason") == "ambiguous":
        candidates_out = result["candidates"]
        if response_mode == "compact":
            candidates_out = [
                {
                    "symbol_id": c["symbol_id"],
                    "name": c["name"],
                    "type": c["type"],
                    "file_path": c["file_path"],
                    "reason_code": "partial_id_match",
                }
                for c in candidates_out
            ]
        return _respond_error(
            code=ERROR_CODES["AMBIGUOUS_SYMBOL"],
            message=f"Multiple candidates found for '{symbol_id}'",
            tool="codegraph_get_symbol",
            details={
                "query": symbol_id,
                "candidates": candidates_out,
                "hint": "Use a more specific symbol_id or set expected_type/path_hint to narrow results.",
            },
        )

    node = result["node"]
    if node is None:
        return _respond_error(
            code=ERROR_CODES["SYMBOL_NOT_FOUND"],
            message=f"No symbol found matching '{symbol_id}'",
            tool="codegraph_get_symbol",
            details=_get_project_info(),
        )

    # Serialize symbol
    symbol_data = _serialize_node(node, response_mode)
    symbol_data["exact_match"] = result["exact_match"]
    symbol_data["match_reason"] = result["match_reason"]
    if response_mode != "compact" and include_explanations and result["candidates"]:
        symbol_data["candidates"] = result["candidates"]

    # relations_summary
    relations_summary = {}
    if include_relations:
        relations_summary = _count_relations(store, node.id)

    # source
    source_data: dict[str, Any] = {"included": False, "content": None}
    if include_source and node.location:
        source_data = _read_source_snippet(
            node.file_path,
            node.location.line_start,
            node.location.line_end,
            source_mode=source_mode,
            max_source_lines=max_source_lines,
        )

    data: dict[str, Any] = {
        "symbol": symbol_data,
    }
    if include_relations:
        data["relations_summary"] = relations_summary
    if include_source:
        data["source"] = source_data

    fuzzy_warning = (
        f"Fuzzy fallback used: {result['match_reason']} — verify this is the expected symbol"
        if not result["exact_match"]
        else None
    )
    return _respond_ok(
        data=data,
        tool="codegraph_get_symbol",
        warnings=_collect_warnings(fuzzy_warning),
    )


# ── Tool: get_callers ─────────────────────────────────────────────────────


def _traverse_callers(
    store: GraphStore,
    node_id: str,
    depth: int,
    min_confidence: float,
    include_tests: bool,
    response_mode: ResponseMode = "compact",
    include_explanations: bool = False,
) -> list[dict[str, Any]]:
    """BFS traversal of callers up to *depth*."""
    seen: dict[str, int] = {node_id: 0}
    results: list[dict[str, Any]] = []
    queue: deque[tuple[str, int]] = deque()
    queue.append((node_id, 0))

    while queue:
        current, dist = queue.popleft()
        if dist >= depth:
            continue
        for edge in store.get_incoming_edges(current):
            if edge.type != EdgeType.calls:
                continue
            if edge.confidence < min_confidence:
                continue
            caller_node = store.get_node(edge.source)
            if caller_node is None:
                continue
            if not include_tests and caller_node.type == NodeType.test:
                continue
            if edge.source not in seen:
                seen[edge.source] = dist + 1
                queue.append((edge.source, dist + 1))
                entry = _serialize_node(caller_node, response_mode)
                entry["distance"] = dist + 1
                if response_mode == "compact":
                    edge_res = edge.metadata.resolution if edge.metadata else None
                    edge_info = {
                        "confidence": round(edge.confidence, 4),
                        "resolution": (
                            edge_res.value
                            if edge_res is not None and hasattr(edge_res, "value")
                            else "unresolved"
                        ),
                        "resolution_category": classify_edge_resolution(edge_res) if edge_res is not None else "unresolved",
                        "reason_code": _resolution_to_reason_code(edge_res),
                    }
                    entry.update(edge_info)
                else:
                    entry["edge"] = _serialize_edge(edge, response_mode, include_explanations)
                results.append(entry)

    results.sort(key=lambda r: (r["distance"], r["symbol_id"]))
    return results


@mcp.tool(name="codegraph_get_callers")
def get_callers(
    symbol_id: str | None = None,
    symbol: str | None = None,
    resolve: bool = True,
    expected_type: str | None = None,
    path_hint: str | None = None,
    depth: int = 1,
    max_results: int = 20,
    min_confidence: float = 0.6,
    include_tests: bool = False,
    response_mode: str = "compact",
    include_explanations: bool = False,
    # Result shaping
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "distance",
    include_types: str | None = None,
    exclude_types: str | None = None,
    include_paths: str | None = None,
    exclude_paths: str | None = None,
) -> dict[str, Any]:
    """Get all callers of a symbol — functions that call it.

    Use instead of grep for call chain and reference lookup. Prefer this
    before grep/read for tracing upstream dependencies and understanding
    what depends on a given function or class.

    Input mode A (direct): symbol_id="app/api/auth.py::login"
    Input mode B (fuzzy): symbol="login", resolve=true, expected_type="function", path_hint="app/api"

    Args:
        symbol_id: Exact symbol node ID (mode A)
        symbol: Symbol name for fuzzy resolution (mode B, requires resolve=true)
        resolve: If true, resolve symbol via fuzzy matching (default true)
        expected_type: Hint for expected node type when resolving, e.g. "function"
        path_hint: Hint for expected file path when resolving, e.g. "app/api"
        depth: Call chain traversal depth (default 1)
        max_results: Maximum results to return (default 20)
        min_confidence: Minimum edge confidence threshold (default 0.6)
        include_tests: Whether to include test callers (default false)
        response_mode: "compact" (default) or "standard"
        include_explanations: If true, include reason text and evidence (default false)
        limit: Results per page (default 20)
        offset: Pagination offset (default 0)
        sort_by: "distance" (default), "confidence", "file_path", "name"
        include_types: Comma-separated types to include
        exclude_types: Comma-separated types to exclude
        include_paths: Comma-separated path globs to include
        exclude_paths: Comma-separated path globs to exclude
    """
    if response_mode not in VALID_RESPONSE_MODES:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message=f"Invalid response_mode '{response_mode}'. Valid: {', '.join(sorted(VALID_RESPONSE_MODES))}",
            tool="codegraph_get_callers",
        )

    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code=ERROR_CODES["INDEX_MISSING"],
            message=str(e),
            tool="codegraph_get_callers",
        )

    if not symbol_id and not symbol:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message="Either 'symbol_id' or 'symbol' must be provided.",
            tool="codegraph_get_callers",
        )

    result = _resolve_input_symbol(
        store, symbol_id, symbol, resolve,
        expected_type=expected_type,
        path_hint=path_hint,
    )
    query_str = symbol_id or symbol or ""
    if result is None:
        return _respond_error(
            code=ERROR_CODES["SYMBOL_NOT_FOUND"],
            message=f"No symbol found matching '{query_str}'",
            tool="codegraph_get_callers",
            details=_get_project_info(),
        )

    if result.get("match_reason") == "ambiguous":
        candidates_out = result["candidates"]
        if response_mode == "compact":
            candidates_out = [
                {
                    "symbol_id": c["symbol_id"],
                    "name": c["name"],
                    "type": c["type"],
                    "file_path": c["file_path"],
                    "reason_code": "partial_id_match",
                }
                for c in candidates_out
            ]
        return _respond_error(
            code=ERROR_CODES["AMBIGUOUS_SYMBOL"],
            message=f"Multiple candidates found for '{query_str}'",
            tool="codegraph_get_callers",
            details={"query": query_str, "candidates": candidates_out},
        )

    node = result["node"]
    if node is None:
        return _respond_error(
            code=ERROR_CODES["SYMBOL_NOT_FOUND"],
            message=f"No symbol found matching '{query_str}'",
            tool="codegraph_get_callers",
        )

    all_callers = _traverse_callers(
        store, node.id,
        depth=max(1, depth),
        min_confidence=min_confidence,
        include_tests=include_tests,
        response_mode=response_mode,
        include_explanations=include_explanations,
    )

    # Parse filter params
    inc_types = [t.strip() for t in include_types.split(",") if t.strip()] if include_types else None
    exc_types = [t.strip() for t in exclude_types.split(",") if t.strip()] if exclude_types else None
    inc_paths = [p.strip() for p in include_paths.split(",") if p.strip()] if include_paths else None
    exc_paths = [p.strip() for p in exclude_paths.split(",") if p.strip()] if exclude_paths else None

    effective_limit = max(1, min(limit or max_results, 100))
    shaped = _apply_result_shaping(
        all_callers,
        limit=effective_limit,
        offset=offset,
        sort_by=sort_by,
        include_types=inc_types,
        exclude_types=exc_types,
        include_paths=inc_paths,
        exclude_paths=exc_paths,
    )

    fuzzy_warning = (
        f"Fuzzy fallback used: {result['match_reason']} — verify this is the expected symbol"
        if not result["exact_match"]
        else None
    )
    return _respond_ok(
        data={
            "target": node.id,
            "callers": shaped["results"],
            "total": shaped["total"],
            "offset": shaped["offset"],
            "limit": shaped["limit"],
            "has_more": shaped["has_more"],
        },
        tool="codegraph_get_callers",
        warnings=_collect_warnings(fuzzy_warning),
    )


# ── Tool: get_callees ─────────────────────────────────────────────────────


def _traverse_callees(
    store: GraphStore,
    node_id: str,
    depth: int,
    min_confidence: float,
    edge_types: list[str],
    response_mode: ResponseMode = "compact",
    include_explanations: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """BFS traversal of callees down to *depth*.

    Returns (internal_callees, external_calls).
    """
    seen: dict[str, int] = {node_id: 0}
    internal: list[dict[str, Any]] = []
    external: list[dict[str, Any]] = []
    allowed_types = {EdgeType(t) for t in edge_types if t in {e.value for e in EdgeType}}
    queue: deque[tuple[str, int]] = deque()
    queue.append((node_id, 0))

    while queue:
        current, dist = queue.popleft()
        if dist >= depth:
            continue
        for edge in store.get_outgoing_edges(current):
            if edge.type not in allowed_types:
                continue
            if edge.confidence < min_confidence:
                continue
            callee_node = store.get_node(edge.target)

            if callee_node is None or callee_node.type == NodeType.external_symbol:
                edge_res = edge.metadata.resolution if edge.metadata else None
                ext_entry: dict[str, Any] = {
                    "symbol_id": edge.target,
                    "name": edge.target,
                    "type": "external_symbol",
                    "file_path": "",
                    "distance": dist + 1,
                }
                if response_mode == "compact":
                    ext_entry["confidence"] = round(edge.confidence, 4)
                    ext_entry["resolution"] = edge_res.value if edge_res is not None and hasattr(edge_res, "value") else "unresolved"
                    ext_entry["resolution_category"] = classify_edge_resolution(edge_res) if edge_res is not None else "unresolved"
                    ext_entry["reason_code"] = "external_call"
                else:
                    ext_entry["edge"] = _serialize_edge(edge, response_mode, include_explanations)
                external.append(ext_entry)
                continue

            if edge.target not in seen:
                seen[edge.target] = dist + 1
                queue.append((edge.target, dist + 1))
                entry = _serialize_node(callee_node, response_mode)
                entry["distance"] = dist + 1
                if response_mode == "compact":
                    edge_res = edge.metadata.resolution if edge.metadata else None
                    entry["confidence"] = round(edge.confidence, 4)
                    entry["resolution"] = (
                        edge_res.value
                        if edge_res is not None and hasattr(edge_res, "value")
                        else "unresolved"
                    )
                    entry["resolution_category"] = classify_edge_resolution(edge_res) if edge_res is not None else "unresolved"
                    entry["reason_code"] = _resolution_to_reason_code(edge_res)
                else:
                    entry["edge"] = _serialize_edge(edge, response_mode, include_explanations)
                internal.append(entry)

    internal.sort(key=lambda r: (r["distance"], r["symbol_id"]))
    external.sort(key=lambda r: (r["distance"], r["symbol_id"]))
    return internal, external


@mcp.tool(name="codegraph_get_callees")
def get_callees(
    symbol_id: str | None = None,
    symbol: str | None = None,
    resolve: bool = True,
    expected_type: str | None = None,
    path_hint: str | None = None,
    depth: int = 1,
    max_results: int = 20,
    min_confidence: float = 0.6,
    edge_types: str | None = None,
    response_mode: str = "compact",
    include_explanations: bool = False,
    # Result shaping
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "distance",
    include_types: str | None = None,
    exclude_types: str | None = None,
    include_paths: str | None = None,
    exclude_paths: str | None = None,
) -> dict[str, Any]:
    """Get all callees of a symbol — functions it calls.

    Use instead of grep for call chain and reference lookup. Prefer this
    before reading multiple files to trace downstream call chains and
    external dependencies.

    External/unresolved symbols are separated into ``external_calls``.

    Input mode A (direct): symbol_id="app/api/auth.py::login"
    Input mode B (fuzzy): symbol="login", resolve=true, expected_type="function", path_hint="app/api"

    Args:
        symbol_id: Exact symbol node ID (mode A)
        symbol: Symbol name for fuzzy resolution (mode B, requires resolve=true)
        resolve: If true, resolve symbol via fuzzy matching (default true)
        expected_type: Hint for expected node type when resolving, e.g. "function"
        path_hint: Hint for expected file path when resolving, e.g. "app/api"
        depth: Call chain traversal depth (default 1)
        max_results: Maximum results to return (default 20)
        min_confidence: Minimum edge confidence threshold (default 0.6)
        edge_types: Comma-separated edge types, e.g. "calls,imports" (default "calls")
        response_mode: "compact" (default) or "standard"
        include_explanations: If true, include reason text and evidence (default false)
        limit: Results per page (default 20)
        offset: Pagination offset (default 0)
        sort_by: "distance" (default), "confidence", "file_path", "name"
        include_types: Comma-separated types to include
        exclude_types: Comma-separated types to exclude
        include_paths: Comma-separated path globs to include
        exclude_paths: Comma-separated path globs to exclude
    """
    if response_mode not in VALID_RESPONSE_MODES:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message=f"Invalid response_mode '{response_mode}'. Valid: {', '.join(sorted(VALID_RESPONSE_MODES))}",
            tool="codegraph_get_callees",
        )

    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code=ERROR_CODES["INDEX_MISSING"],
            message=str(e),
            tool="codegraph_get_callees",
        )

    if not symbol_id and not symbol:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message="Either 'symbol_id' or 'symbol' must be provided.",
            tool="codegraph_get_callees",
        )

    result = _resolve_input_symbol(
        store, symbol_id, symbol, resolve,
        expected_type=expected_type,
        path_hint=path_hint,
    )
    query_str = symbol_id or symbol or ""
    if result is None:
        return _respond_error(
            code=ERROR_CODES["SYMBOL_NOT_FOUND"],
            message=f"No symbol found matching '{query_str}'",
            tool="codegraph_get_callees",
            details=_get_project_info(),
        )

    if result.get("match_reason") == "ambiguous":
        candidates_out = result["candidates"]
        if response_mode == "compact":
            candidates_out = [
                {
                    "symbol_id": c["symbol_id"],
                    "name": c["name"],
                    "type": c["type"],
                    "file_path": c["file_path"],
                    "reason_code": "partial_id_match",
                }
                for c in candidates_out
            ]
        return _respond_error(
            code=ERROR_CODES["AMBIGUOUS_SYMBOL"],
            message=f"Multiple candidates found for '{query_str}'",
            tool="codegraph_get_callees",
            details={"query": query_str, "candidates": candidates_out},
        )

    node = result["node"]
    if node is None:
        return _respond_error(
            code=ERROR_CODES["SYMBOL_NOT_FOUND"],
            message=f"No symbol found matching '{query_str}'",
            tool="codegraph_get_callees",
        )

    etypes = [t.strip() for t in (edge_types or "calls").split(",") if t.strip()]
    internal, external = _traverse_callees(
        store, node.id,
        depth=max(1, depth),
        min_confidence=min_confidence,
        edge_types=etypes,
        response_mode=response_mode,
        include_explanations=include_explanations,
    )

    # Parse filter params
    inc_types = [t.strip() for t in include_types.split(",") if t.strip()] if include_types else None
    exc_types = [t.strip() for t in exclude_types.split(",") if t.strip()] if exclude_types else None
    inc_paths = [p.strip() for p in include_paths.split(",") if p.strip()] if include_paths else None
    exc_paths = [p.strip() for p in exclude_paths.split(",") if p.strip()] if exclude_paths else None

    effective_limit = max(1, min(limit or max_results, 100))
    shaped = _apply_result_shaping(
        internal,
        limit=effective_limit,
        offset=offset,
        sort_by=sort_by,
        include_types=inc_types,
        exclude_types=exc_types,
        include_paths=inc_paths,
        exclude_paths=exc_paths,
    )

    fuzzy_warning = (
        f"Fuzzy fallback used: {result['match_reason']} — verify this is the expected symbol"
        if not result["exact_match"]
        else None
    )
    warnings = _collect_warnings(fuzzy_warning)
    if external:
        ext_ids = [e["symbol_id"] for e in external[:5]]
        warnings.append({
            "type": "external_or_unresolved",
            "message": f"{len(external)} external/unresolved callee(s) not included in main results.",
            "external_symbols": ext_ids,
            "reason_code": "external_or_unresolved",
        })

    return _respond_ok(
        data={
            "target": node.id,
            "callees": shaped["results"],
            "external_calls": external[:10],
            "total": shaped["total"],
            "offset": shaped["offset"],
            "limit": shaped["limit"],
            "has_more": shaped["has_more"],
        },
        tool="codegraph_get_callees",
        warnings=warnings,
    )


# ── Tool: get_neighbors ───────────────────────────────────────────────────


@mcp.tool(name="codegraph_get_neighbors")
def get_neighbors(
    symbol_id: str | None = None,
    symbol: str | None = None,
    resolve: bool = True,
    expected_type: str | None = None,
    path_hint: str | None = None,
    depth: int = 1,
    max_nodes: int = 40,
    max_edges: int = 80,
    edge_types: str | None = None,
    min_confidence: float = 0.6,
    direction: str = "both",
    group_by_role: bool = True,
    response_mode: str = "compact",
    include_explanations: bool = False,
) -> dict[str, Any]:
    """Get neighbors of a symbol in the code graph — the primary local-graph tool.

    Use before reading multiple files to understand relationships around
    a symbol. Prefer this over glob/read for exploring what is connected
    to a function, class, or method — callers, callees, tests, models,
    and config dependencies.

    Compact mode returns neighbors grouped by role. Standard mode returns
    full nodes + edges. External/unresolved symbols are always in their
    own group.

    Input mode A (direct): symbol_id="app/api/auth.py::login"
    Input mode B (fuzzy): symbol="login", resolve=true, expected_type="function", path_hint="app/api"

    Args:
        symbol_id: Exact symbol node ID (mode A)
        symbol: Symbol name for fuzzy resolution (mode B, requires resolve=true)
        resolve: If true, resolve symbol via fuzzy matching (default true)
        expected_type: Hint for expected node type when resolving, e.g. "function"
        path_hint: Hint for expected file path when resolving, e.g. "app/api"
        depth: How many hops to traverse (default 1, max 3)
        max_nodes: Maximum nodes to return (default 40, max 100)
        max_edges: Maximum edges to return (default 80, max 200)
        edge_types: Comma-separated edge types, e.g. "calls,tested_by,imports,references"
                    (default "calls,tested_by,imports,references")
        min_confidence: Minimum edge confidence threshold (default 0.6)
        direction: "upstream" (incoming edges), "downstream" (outgoing),
                   or "both" (default)
        group_by_role: In compact mode, group results by role (default true)
        response_mode: "compact" (default) or "standard"
        include_explanations: If true, include reason text and evidence (default false)
    """
    effective_depth = max(1, min(depth, 3))
    effective_max_nodes = max(1, min(max_nodes, 100))
    effective_max_edges = max(1, min(max_edges, 200))
    valid_dirs = {"upstream", "downstream", "both"}
    if direction not in valid_dirs:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message=f"Invalid direction '{direction}'. Must be one of: upstream, downstream, both.",
            tool="codegraph_get_neighbors",
            details={"valid_values": list(valid_dirs)},
        )
    if response_mode not in VALID_RESPONSE_MODES:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message=f"Invalid response_mode '{response_mode}'. Valid: {', '.join(sorted(VALID_RESPONSE_MODES))}",
            tool="codegraph_get_neighbors",
        )

    default_etypes = "calls,tested_by,imports,references"
    etypes_raw = [t.strip() for t in (edge_types or default_etypes).split(",") if t.strip()]
    allowed_types: set[EdgeType] = set()
    for t in etypes_raw:
        try:
            allowed_types.add(EdgeType(t))
        except ValueError:
            return _respond_error(
                code=ERROR_CODES["INVALID_ARGUMENT"],
                message=f"Invalid edge type '{t}'. Valid types: {[e.value for e in EdgeType]}",
                tool="codegraph_get_neighbors",
            )

    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code=ERROR_CODES["INDEX_MISSING"],
            message=str(e),
            tool="codegraph_get_neighbors",
        )

    if not symbol_id and not symbol:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message="Either 'symbol_id' or 'symbol' must be provided.",
            tool="codegraph_get_neighbors",
        )

    result = _resolve_input_symbol(
        store, symbol_id, symbol, resolve,
        expected_type=expected_type,
        path_hint=path_hint,
    )
    query_str = symbol_id or symbol or ""
    if result is None:
        return _respond_error(
            code=ERROR_CODES["SYMBOL_NOT_FOUND"],
            message=f"No symbol found matching '{query_str}'",
            tool="codegraph_get_neighbors",
            details=_get_project_info(),
        )

    if result.get("match_reason") == "ambiguous":
        candidates_out = result["candidates"]
        if response_mode == "compact":
            candidates_out = [
                {
                    "symbol_id": c["symbol_id"],
                    "name": c["name"],
                    "type": c["type"],
                    "file_path": c["file_path"],
                    "reason_code": "partial_id_match",
                }
                for c in candidates_out
            ]
        return _respond_error(
            code=ERROR_CODES["AMBIGUOUS_SYMBOL"],
            message=f"Multiple candidates found for '{query_str}'",
            tool="codegraph_get_neighbors",
            details={"query": query_str, "candidates": candidates_out},
        )

    center_node = result["node"]
    if center_node is None:
        return _respond_error(
            code=ERROR_CODES["SYMBOL_NOT_FOUND"],
            message=f"No symbol found matching '{query_str}'",
            tool="codegraph_get_neighbors",
        )

    # BFS traversal with direction support
    visited_nodes: dict[str, int] = {center_node.id: 0}
    visited_edges_dict: dict[tuple[str, str, str], GraphEdge] = {}
    low_conf_edges: list[GraphEdge] = []
    queue: deque[tuple[str, int]] = deque()
    queue.append((center_node.id, 0))

    while queue:
        current, dist = queue.popleft()
        if dist >= effective_depth:
            continue
        if len(visited_nodes) >= effective_max_nodes:
            break

        edges_to_check: list[GraphEdge] = []
        if direction in ("both", "downstream"):
            edges_to_check.extend(store.get_outgoing_edges(current))
        if direction in ("both", "upstream"):
            edges_to_check.extend(store.get_incoming_edges(current))

        for edge in edges_to_check:
            if edge.type not in allowed_types:
                continue

            neighbor_id = edge.target if edge.source == current else edge.source
            edge_key = (edge.source, edge.target, edge.type.value if hasattr(edge.type, "value") else str(edge.type))

            if edge_key not in visited_edges_dict:
                if edge.confidence >= min_confidence:
                    visited_edges_dict[edge_key] = edge
                else:
                    low_conf_edges.append(edge)

            if edge.confidence >= min_confidence:
                if neighbor_id not in visited_nodes and len(visited_nodes) < effective_max_nodes:
                    visited_nodes[neighbor_id] = dist + 1
                    queue.append((neighbor_id, dist + 1))

    # Build node entries
    nodes_out: list[dict[str, Any]] = []
    for nid, ndist in visited_nodes.items():
        n = store.get_node(nid)
        if n is None:
            # External/unresolved node
            nodes_out.append({
                "symbol_id": nid,
                "name": nid,
                "type": "external_symbol",
                "file_path": "",
                "role": "external_or_unresolved",
                "distance": ndist,
            })
            continue
        if response_mode == "compact":
            entry = _serialize_node(n, "compact")
        else:
            entry = _serialize_node(n, "standard")
        entry["distance"] = ndist
        entry["role"] = _assign_role(nid, center_node.id, store)
        entry["layer"] = _assign_layer(n.file_path)
        nodes_out.append(entry)

    # Build edge entries
    edges_out: list[dict[str, Any]] = []
    for edge in visited_edges_dict.values():
        if response_mode == "compact":
            edges_out.append(_serialize_edge(edge, "compact", include_explanations))
        else:
            edges_out.append(_serialize_edge_full(edge, response_mode, include_explanations))

    # Determine truncation
    truncated = False
    all_possible: set[str] = set()
    for nid in visited_nodes:
        for e in store.get_outgoing_edges(nid):
            if direction in ("both", "downstream") and e.type in allowed_types:
                all_possible.add(e.target)
        for e in store.get_incoming_edges(nid):
            if direction in ("both", "upstream") and e.type in allowed_types:
                all_possible.add(e.source)
    if len(all_possible - set(visited_nodes.keys())) > 0 and len(visited_nodes) >= effective_max_nodes:
        truncated = True

    # Filtered counts (low confidence)
    filtered_counts = {
        "low_confidence_edges": len(low_conf_edges),
    }

    # ── Build response based on response_mode ──────────────────────────
    if response_mode == "compact" and group_by_role:
        groups: dict[str, list[dict[str, Any]]] = {
            "callers": [],
            "callees": [],
            "tests": [],
            "models": [],
            "config": [],
            "persistence": [],
            "external_or_unresolved": [],
        }
        for n in nodes_out:
            role = n.get("role", "neighbor")
            if role in groups:
                groups[role].append(n)
            elif role == "reference":
                # Put references in callees group
                groups["callees"].append(n)
            elif role == "import":
                groups["callees"].append(n)
            elif role == "caller":
                groups["callers"].append(n)
            else:
                groups["callees"].append(n)

        # Remove center from any group
        for g in groups.values():
            g[:] = [n for n in g if n.get("role") != "center"]

        counts = {
            "nodes": len(nodes_out),
            "edges": len(edges_out),
            "callers": len(groups["callers"]),
            "callees": len(groups["callees"]),
            "tests": len(groups["tests"]),
            "models": len(groups["models"]),
            "config": len(groups["config"]),
            "persistence": len(groups["persistence"]),
            "external_or_unresolved": len(groups["external_or_unresolved"]),
            "low_confidence_filtered": filtered_counts["low_confidence_edges"],
        }

        return _respond_ok(
            data={
                "center": center_node.id,
                "groups": {k: v for k, v in groups.items() if v},
                "counts": counts,
                "truncated": truncated,
            },
            tool="codegraph_get_neighbors",
            warnings=_collect_warnings(
                None if result["exact_match"] else
                f"Fuzzy fallback used: {result['match_reason']}"
            ),
        )

    # Standard / non-grouped compact
    nodes_out.sort(key=lambda n: (0 if n.get("role") == "center" else 1, n.get("distance", 0), n.get("name", "")))

    fuzzy_warning = (
        f"Fuzzy fallback used: {result['match_reason']} — verify this is the expected symbol"
        if not result["exact_match"]
        else None
    )
    return _respond_ok(
        data={
            "center": center_node.id,
            "nodes": nodes_out,
            "edges": edges_out,
            "truncated": truncated,
            "filtered_counts": filtered_counts,
            "limits": {
                "depth": effective_depth,
                "max_nodes": effective_max_nodes,
                "min_confidence": min_confidence,
            },
        },
        tool="codegraph_get_neighbors",
        warnings=_collect_warnings(fuzzy_warning),
    )


# ── Tool: get_impact ──────────────────────────────────────────────────────



@mcp.tool(name="codegraph_get_impact")
def get_impact(
    symbol_id: str | None = None,
    symbol: str | None = None,
    resolve: bool = True,
    expected_type: str | None = None,
    path_hint: str | None = None,
    depth: int = 2,
    max_files: int = 30,
    min_confidence: float = 0.6,
    include_tests: bool = True,
    include_possible: bool = False,
    impact_mode: str = "conservative",
    response_mode: str = "compact",
    include_explanations: bool = False,
) -> dict[str, Any]:
    """Analyze the impact of modifying a symbol.

    Use before modifying shared code to understand confirmed and possible
    impact. Prefer this before manual grep/read for tracing what files,
    tests, and downstream callers would be affected by a change.

    Returns confirmed impact, possible impact, risk level with reason codes,
    and separates upstream/downstream/test/external items clearly.

    Returns confirmed impact, possible impact, risk level with reason codes,
    and separates upstream/downstream/test/external items clearly.

    Input mode A (direct): symbol_id="app/api/auth.py::login"
    Input mode B (fuzzy): symbol="login", resolve=true, expected_type="function", path_hint="app/api"

    Args:
        symbol_id: Exact symbol node ID (mode A)
        symbol: Symbol name for fuzzy resolution (mode B, requires resolve=true)
        resolve: If true, resolve symbol via fuzzy matching (default true)
        expected_type: Hint for expected node type when resolving, e.g. "function"
        path_hint: Hint for expected file path when resolving, e.g. "app/api"
        depth: Transitive call-chain depth (default 2, max 5)
        max_files: Maximum files to report (default 30)
        min_confidence: Minimum edge confidence for confirmed impact (default 0.6)
        include_tests: Whether to include related tests (default true)
        include_possible: Whether to include possible/low-confidence impact (default false)
        impact_mode: "conservative" (direct only) or "balanced" (depth=2, models/config)
                     — default "conservative"
        response_mode: "compact" (default) or "standard"
        include_explanations: If true, include reason text and evidence (default false)
    """
    valid_modes = {"conservative", "balanced"}
    if impact_mode not in valid_modes:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message=f"Invalid impact_mode '{impact_mode}'. Valid: conservative, balanced",
            tool="codegraph_get_impact",
        )
    if response_mode not in VALID_RESPONSE_MODES:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message=f"Invalid response_mode '{response_mode}'. Valid: {', '.join(sorted(VALID_RESPONSE_MODES))}",
            tool="codegraph_get_impact",
        )

    # Adjust parameters based on impact_mode
    if impact_mode == "conservative":
        effective_depth = 1
        effective_include_possible = False
    else:  # balanced
        effective_depth = max(1, min(depth, 5))
        effective_include_possible = include_possible

    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code=ERROR_CODES["INDEX_MISSING"],
            message=str(e),
            tool="codegraph_get_impact",
        )

    if not symbol_id and not symbol:
        return _respond_error(
            code=ERROR_CODES["INVALID_ARGUMENT"],
            message="Either 'symbol_id' or 'symbol' must be provided.",
            tool="codegraph_get_impact",
        )

    result = _resolve_input_symbol(
        store, symbol_id, symbol, resolve,
        expected_type=expected_type,
        path_hint=path_hint,
    )
    query_str = symbol_id or symbol or ""
    if result is None:
        return _respond_error(
            code=ERROR_CODES["SYMBOL_NOT_FOUND"],
            message=f"No symbol found matching '{query_str}'",
            tool="codegraph_get_impact",
            details=_get_project_info(),
        )

    if result.get("match_reason") == "ambiguous":
        candidates_out = result["candidates"]
        if response_mode == "compact":
            candidates_out = [
                {
                    "symbol_id": c["symbol_id"],
                    "name": c["name"],
                    "type": c["type"],
                    "file_path": c["file_path"],
                    "reason_code": "partial_id_match",
                }
                for c in candidates_out
            ]
        return _respond_error(
            code=ERROR_CODES["AMBIGUOUS_SYMBOL"],
            message=f"Multiple candidates found for '{query_str}'",
            tool="codegraph_get_impact",
            details={"query": query_str, "candidates": candidates_out},
        )

    center_node = result["node"]
    if center_node is None:
        return _respond_error(
            code=ERROR_CODES["SYMBOL_NOT_FOUND"],
            message=f"No symbol found matching '{query_str}'",
            tool="codegraph_get_impact",
        )

    # Call the impact engine
    impact_result = graph_impact.analyze_impact(
        store, center_node.id, depth=effective_depth, min_confidence=min_confidence
    )

    # ── Risk assessment with reason codes ──────────────────────────────
    risk_data = impact_result.get("risk", {})
    risk_reasons: list[str] = risk_data.get("reasons", [])
    risk_codes: list[str] = [_impact_reason_to_code(r) for r in risk_reasons]
    # Deduplicate while preserving order
    seen_codes: set[str] = set()
    unique_codes: list[str] = []
    for rc in risk_codes:
        if rc not in seen_codes:
            seen_codes.add(rc)
            unique_codes.append(rc)

    risk: dict[str, Any] = {
        "level": risk_data.get("level", "unknown"),
        "reason_codes": unique_codes,
    }
    if response_mode != "compact":
        risk["reasons"] = risk_reasons

    # ── Confirmed impact (compact: grouped structure) ────────────────────
    confirmed = impact_result.get("confirmed_impact", {})
    confirmed_symbols = confirmed.get("symbols", [])
    confirmed_files_list = confirmed.get("files", [])[:max_files]

    # Build confirmed files output
    confirmed_files_out: list[dict[str, Any]] = []
    for f in confirmed_files_list:
        entry: dict[str, Any] = {
            "file_path": f["file_path"],
            "layer": _assign_layer(f["file_path"]),
            "reason_code": _impact_reason_to_code(f.get("reason", "")),
            "confidence": f.get("confidence", 1.0),
        }
        if f.get("priority"):
            entry["priority"] = f["priority"]
        confirmed_files_out.append(entry)

    # Build confirmed symbols output
    confirmed_symbols_out: list[dict[str, Any]] = []
    for s in confirmed_symbols[:20]:
        entry = {
            "symbol_id": s["symbol_id"],
            "name": s.get("name", ""),
            "type": s.get("type", "unknown"),
            "file_path": s.get("file_path", ""),
            "layer": _assign_layer(s.get("file_path", "")),
            "reason_code": s.get("impact_type", "unknown"),
            "confidence": s.get("confidence", 1.0),
            "confidence_level": s.get("confidence_level", "unknown"),
            "distance": s.get("distance", 0),
        }
        confirmed_symbols_out.append(entry)

    # Build confirmed tests
    related_tests = impact_result.get("related_tests", []) if include_tests else []
    related_tests_count = len(related_tests)
    confirmed_tests_out: list[dict[str, Any]] = []
    if related_tests:
        confirmed_tests_out = [
            {
                "symbol_id": t["symbol_id"],
                "name": t.get("name", ""),
                "file_path": t.get("file_path", ""),
                "layer": _assign_layer(t.get("file_path", "")),
                "reason_code": t.get("reason", "test_coverage"),
                "confidence": t.get("confidence", 1.0),
                "confidence_level": t.get("confidence_level", "unknown"),
            }
            for t in related_tests[:20]
        ]

    # ── Possible impact ──────────────────────────────────────────────────
    possible_symbols_out: list[dict[str, Any]] = []
    possible_files_out: list[dict[str, Any]] = []
    if effective_include_possible:
        poss = impact_result.get("possible_impact", {})
        poss_files_list = poss.get("files", [])[:max_files]
        for f in poss_files_list:
            possible_files_out.append({
                "file_path": f["file_path"],
                "layer": _assign_layer(f["file_path"]),
                "reason_code": "low_confidence_edge",
                "confidence": f.get("confidence", 0.5),
                "priority": f.get("priority", "low"),
            })
        possible_symbols_out = poss.get("symbols", [])[:20]

    # ── External / unresolved ────────────────────────────────────────────
    external = impact_result.get("external_or_unresolved", [])
    unresolved_out: list[dict[str, Any]] = []
    external_out: list[dict[str, Any]] = []
    for ext in external:
        ext_type = ext.get("type", "unknown")
        entry = {
            "symbol_id": ext.get("symbol_id", ""),
            "name": ext.get("name", ""),
            "type": ext_type,
            "reason_code": ext.get("category", "external_or_unresolved"),
            "confidence": ext.get("confidence", 0.0),
            "confidence_level": ext.get("confidence_level", "unknown"),
        }
        if ext_type == "external_symbol":
            external_out.append(entry)
        else:
            unresolved_out.append(entry)

    truncated = len(confirmed_files_list) >= max_files

    fuzzy_warning = (
        f"Fuzzy fallback used: {result['match_reason']} — verify this is the expected symbol"
        if not result["exact_match"]
        else None
    )
    warnings = _collect_warnings(fuzzy_warning)

    if response_mode == "compact":
        data: dict[str, Any] = {
            "target": center_node.id,
            "risk": risk,
            "confirmed": {
                "files": confirmed_files_out,
                "symbols": confirmed_symbols_out,
                "tests": confirmed_tests_out,
            },
            "possible": {
                "files": possible_files_out,
                "symbols": possible_symbols_out,
                "unresolved": unresolved_out,
                "external": external_out,
            },
            "truncated": truncated,
        }
    elif response_mode == "full":
        data = {
            "target": center_node.id,
            "risk": risk,
            "confirmed": {
                "files": confirmed_files_out,
                "symbols": confirmed_symbols_out,
                "tests": confirmed_tests_out,
            },
            "possible": {
                "files": possible_files_out,
                "symbols": possible_symbols_out,
                "unresolved": unresolved_out,
                "external": external_out,
            },
            "upstream_callers": impact_result.get("upstream_callers", []),
            "downstream_callees": impact_result.get("downstream_callees", []),
            "truncated": truncated,
        }
    else:  # standard
        data = {
            "target": center_node.id,
            "risk": risk,
            "confirmed_impact": {
                "symbols": confirmed_symbols_out,
                "files": confirmed_files_out,
            },
            "possible_impact": {
                "symbols": possible_symbols_out,
                "files": possible_files_out,
            },
            "upstream_callers": impact_result.get("upstream_callers", []),
            "downstream_callees": impact_result.get("downstream_callees", []),
            "related_tests": related_tests,
            "external_or_unresolved": external,
            "truncated": truncated,
        }

    return _respond_ok(
        data=data,
        tool="codegraph_get_impact",
        warnings=warnings,
        response_mode=response_mode,
        item_count=len(confirmed_files_list) + len(confirmed_symbols),
        truncated=truncated,
        max_items=max_files,
    )


# ── Tool: build_context_pack ──────────────────────────────────────────────


@mcp.tool(name="codegraph_build_context_pack")
def build_context_pack(
    task: str,
    max_tokens: int = 6000,
    depth: int = 2,
    include_tests: bool = True,
    include_code: bool = True,
    mode: str = "summary",
    response_mode: str = "compact",
) -> dict[str, Any]:
    """Build a Context Pack for a natural language task.

    Use this as the first CodeGraph tool for code investigation, bug fixing,
    feature implementation, refactoring, or impact analysis. Prefer this
    before grep/glob/read-heavy exploration. Takes a natural language task
    description and returns entry points, related symbols, call graph,
    impact signals, and tests. Does NOT include reading plans or agent
    instructions.

    Args:
        task: Natural language description of what you need to do
              (e.g. "add rate limiting to the login endpoint")
        max_tokens: Token budget for the context pack (default 6000)
        depth: Call-chain traversal depth (default 2)
        include_tests: Whether to include related tests (default true)
        include_code: Whether to include source code snippets (default true)
        mode: Output mode — "full" (complete JSON), "summary" (key insights only),
              or "markdown" (returns markdown file path) (default "summary")
        response_mode: "compact" or "standard" (default)"
    """
    from codegraph.context.pack_builder import build_context_pack as _build

    # ── Enforce hard max token budget ───────────────────────────────────
    HARD_MAX_TOKENS = 20000
    effective_max_tokens = max(100, min(max_tokens or 6000, HARD_MAX_TOKENS))
    budget_truncated = max_tokens > HARD_MAX_TOKENS

    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code=ERROR_CODES["INDEX_MISSING"],
            message=str(e),
            tool="codegraph_build_context_pack",
        )

    output_dir = cg_dir / "context_packs"
    pack = _build(
        store=store,
        task_description=task,
        max_tokens=effective_max_tokens,
        depth=depth,
        include_tests=include_tests,
        output_dir=str(output_dir),
    )

    pack_dict = json.loads(pack.model_dump_json(exclude_none=True))

    # Determine if pack exceeded budget
    used_tokens = pack_dict.get("token_budget", {}).get("used_tokens", 0)
    pack_max = pack_dict.get("token_budget", {}).get("max_tokens", 0)
    pack_truncated = budget_truncated or (used_tokens > pack_max if pack_max > 0 else False)

    if mode == "summary":
        pack_dict = {
            "pack_id": pack_dict.get("pack_id"),
            "task": pack_dict.get("task", {}),
            "entry_points": [
                {
                    "symbol_id": ep.get("symbol_id"),
                    "name": ep.get("name"),
                    "reason": ep.get("reason"),
                    "file_path": ep.get("file_path"),
                    "layer": _assign_layer(ep.get("file_path", "")),
                    "score": ep.get("score"),
                }
                for ep in pack_dict.get("entry_points", [])
            ],
            "related_symbols": [
                {
                    "symbol_id": rs.get("symbol_id"),
                    "relation": rs.get("relation"),
                    "reason": rs.get("reason"),
                    "confidence": rs.get("confidence"),
                    "confidence_level": rs.get("confidence_level"),
                }
                for rs in pack_dict.get("related_symbols", [])
            ],
            "call_graph": {
                "center": pack_dict.get("call_graph", {}).get("center"),
                "total_nodes": len(pack_dict.get("call_graph", {}).get("nodes", [])),
                "total_edges": len(pack_dict.get("call_graph", {}).get("edges", [])),
            },
            "impact": pack_dict.get("impact"),
            "selected_context": [
                {
                    "context_id": sc.get("context_id"),
                    "symbol_id": sc.get("symbol_id"),
                    "type": sc.get("type"),
                    "priority": sc.get("priority"),
                    "content_mode": sc.get("content_mode"),
                    "relation": sc.get("relation"),
                    "selection_reason": sc.get("selection_reason"),
                    "confidence": sc.get("confidence"),
                    "confidence_level": sc.get("confidence_level"),
                    "resolution": sc.get("resolution"),
                    "evidence": sc.get("evidence"),
                    "estimated_tokens": sc.get("estimated_tokens"),
                    "context_score": sc.get("context_score"),
                }
                for sc in pack_dict.get("selected_context", [])
            ],
            "related_tests": pack_dict.get("related_tests", []),
            "suggested_tests": pack_dict.get("suggested_tests", []),
            "token_budget": pack_dict.get("token_budget", {}),
            "truncated": pack_truncated,
        }
    elif mode == "markdown":
        from codegraph.context.markdown_exporter import save_markdown

        md_path = output_dir / f"{pack.pack_id}.md"
        save_markdown(pack, str(md_path))
        pack_dict = {
            "pack_id": pack.pack_id,
            "markdown_path": str(md_path),
            "format": "markdown",
            "truncated": pack_truncated,
        }

    # Add warnings for truncated budget
    pack_warnings = _collect_warnings()
    if budget_truncated:
        pack_warnings.append({
            "type": "token_budget_truncated",
            "severity": "warning",
            "message": f"Requested max_tokens ({max_tokens}) exceeds hard max ({HARD_MAX_TOKENS}). "
                       f"Clamped to {HARD_MAX_TOKENS}.",
            "reason_code": "payload_truncated",
        })

    if response_mode == "compact":
        # Strip down to essentials — only evidence, no plans/instructions
        pack_dict = {
            "pack_id": pack_dict.get("pack_id"),
            "task": pack_dict.get("task", {}),
            "entry_points": pack_dict.get("entry_points", [])[:5],
            "call_graph": pack_dict.get("call_graph", {}),
            "impact": pack_dict.get("impact"),
            "related_tests_count": len(pack_dict.get("related_tests", [])),
            "selected_context_count": len(pack_dict.get("selected_context", [])),
            "token_budget": pack_dict.get("token_budget", {}),
            "truncated": pack_dict.get("truncated", False),
        }

    # Apply compact whitelist as safety net
    if response_mode == "compact":
        pack_dict = _apply_compact_whitelist(pack_dict)

    item_count = len(pack_dict.get("selected_context", [])) + len(pack_dict.get("entry_points", []))

    return _respond_ok(
        data=pack_dict,
        tool="codegraph_build_context_pack",
        warnings=pack_warnings,
        response_mode=response_mode,
        item_count=item_count,
        truncated=pack_dict.get("truncated", False),
        max_items=HARD_MAX_TOKENS,
    )


# ── Tool: repo_status ─────────────────────────────────────────────────────


@mcp.tool(name="codegraph_repo_status")
def repo_status(
    root: str | None = None,
    response_mode: str = "compact",
) -> dict[str, Any]:
    """Check index freshness and report changed/added/deleted files.

    Use to check whether the CodeGraph index is fresh, stale, missing, or
    healthy before relying on results. Prefer this before assuming search
    results are up-to-date — stale indexes may miss recent changes.

    Returns project_root, index_status, index_health, indexed_at,
    changed/added/deleted file counts, last_incremental_stats,
    validation_status, and a suggested_fix action.

    Args:
        root: Optional project root path override
        response_mode: "compact" (default) or "standard"
    """
    project_root = root or _project_root
    index_status = _build_index_status(project_root)

    if index_status["status"] == "missing":
        return _respond_ok(
            data={
                "project_root": project_root,
                "index_status": "missing",
                "index_health": "ok",
                "indexed_at": None,
                "changed_files_count": 0,
                "added_files_count": 0,
                "deleted_files_count": 0,
                "last_incremental_stats": None,
                "validation_status": None,
                "suggested_fix": "codegraph init",
                "index_files": index_status.get("index_files", {}),
                "stats": index_status.get("stats", {}),
                "fingerprint_health": None,
                "last_change_summary": None,
                "index_health_details": None,
            },
            tool="codegraph_repo_status",
            warnings=[{
                "type": "index_missing",
                "severity": "warning",
                "message": "No CodeGraph index found. Run: codegraph init",
                "reason_code": "index_missing",
            }],
        )

    change_summary = index_status.get("last_change_summary", {})
    changed_count = change_summary.get("structural", 0) + change_summary.get("cosmetic", 0)
    added_count = change_summary.get("added", 0)
    deleted_count = change_summary.get("deleted", 0)
    idx_health = index_status.get("index_health")
    hook = index_status.get("hook", {})
    hook_installed = hook.get("installed", False)
    hook_auto_update = hook.get("auto_update_on_commit", True)
    hook_state = hook.get("state")

    # Build warnings (stale index + hook not installed)
    warn_list: list[dict[str, Any]] = []
    if index_status["status"] == "stale":
        warn_list.append({
            "type": "stale_index",
            "severity": "warning",
            "message": (
                f"Index is stale. Results may not reflect recent file changes. "
                f"Run: {index_status.get('suggested_fix', 'codegraph init --incremental')}"
            ),
            "reason_code": "stale_index",
        })

    if hook_auto_update and not hook_installed:
        warn_list.append({
            "type": "hook_not_installed",
            "severity": "info",
            "message": (
                "auto_update_on_commit is enabled but the post-commit hook "
                "is not installed. Run: codegraph hooks install"
            ),
            "reason_code": "hook_not_installed",
        })

    if response_mode == "compact":
        data: dict[str, Any] = {
            "project_root": project_root,
            "index_status": index_status["status"],
            "index_health": idx_health["status"] if idx_health else "ok",
            "indexed_at": index_status.get("indexed_at"),
            "changed_files_count": changed_count,
            "added_files_count": added_count,
            "deleted_files_count": deleted_count,
            "last_incremental_stats": index_status.get("last_incremental_stats"),
            "validation_status": idx_health["status"] if idx_health else None,
            "suggested_fix": index_status.get("suggested_fix"),
            "hook_installed": hook_installed,
            "hook_auto_update": hook_auto_update,
            "hook_state": hook_state,
        }
    else:
        data = {
            "project_root": project_root,
            "index_status": index_status["status"],
            "index_health": idx_health["status"] if idx_health else "ok",
            "indexed_at": index_status.get("indexed_at"),
            "changed_files_count": changed_count,
            "added_files_count": added_count,
            "deleted_files_count": deleted_count,
            "last_incremental_stats": index_status.get("last_incremental_stats"),
            "validation_status": idx_health["status"] if idx_health else None,
            "suggested_fix": index_status.get("suggested_fix"),
            "index_files": index_status.get("index_files", {}),
            "stats": index_status.get("stats", {}),
            "fingerprint_health": index_status.get("fingerprint_health"),
            "last_change_summary": index_status.get("last_change_summary"),
            "index_health_details": idx_health,
            "hook_status": hook,
        }

    return _respond_ok(
        data=data,
        tool="codegraph_repo_status",
        warnings=warn_list,
    )


# ── Tool: repo_summary ────────────────────────────────────────────────────


@mcp.tool(name="codegraph_repo_summary")
def repo_summary(
    response_mode: str = "compact",
    include_explanations: bool = False,
) -> dict[str, Any]:
    """Get a summary of the indexed repository.

    Use first when entering a repository or checking overall structure
    before glob/grep exploration. Prefer this before glob/grep/read for
    getting an overview of the codebase — file count, symbol breakdown,
    top modules, entry points, test coverage, framework detection, and
    language support levels.

    Args:
        response_mode: "compact" (default) or "standard"
        include_explanations: If true, include detailed explanations
    """
    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code=ERROR_CODES["INDEX_MISSING"],
            message=str(e),
            tool="codegraph_repo_summary",
        )

    nodes = store.all_nodes()
    edges = store.all_edges()

    type_counts: dict[str, int] = {}
    for n in nodes:
        t = n.type.value if isinstance(n.type, NodeType) else str(n.type)
        type_counts[t] = type_counts.get(t, 0) + 1

    files = {n.file_path for n in nodes if n.file_path}
    low_conf = sum(1 for e in edges if is_low_confidence(e.confidence))
    low_conf_ratio = round(low_conf / len(edges), 4) if edges else 0.0

    # Top modules (by file prefix)
    module_counts: dict[str, int] = {}
    for f in files:
        parts = f.replace("\\", "/").split("/")
        if len(parts) >= 2:
            mod = "/".join(parts[:-1])
        else:
            mod = f
        module_counts[mod] = module_counts.get(mod, 0) + 1
    top_modules = sorted(module_counts.items(), key=lambda x: -x[1])[:10]

    # Entry point candidates
    entry_candidates: list[dict[str, Any]] = []
    for n in nodes:
        is_entry = False
        entry_type = ""
        if "route" in n.tags:
            is_entry = True
            entry_type = "route"
        elif n.name == "main" and n.type == NodeType.function:
            is_entry = True
            entry_type = "main"
        elif "entry_point" in n.tags:
            is_entry = True
            entry_type = "entry_point"
        if is_entry and len(entry_candidates) < 20:
            entry_candidates.append({
                "symbol_id": n.id,
                "name": n.name,
                "type": n.type.value if isinstance(n.type, NodeType) else str(n.type),
                "file_path": n.file_path,
                "entry_type": entry_type,
            })

    # Test coverage signal
    test_files = {n.file_path for n in nodes if n.type == NodeType.test}
    tested_symbols: set[str] = set()
    for e in edges:
        if e.type == EdgeType.tested_by:
            tested_symbols.add(e.source)

    repo_info = {}
    metadata_path = cg_dir / "metadata.json"
    if metadata_path.exists():
        try:
            from codegraph.graph.models import IndexMetadata
            meta = IndexMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
            repo_info = {
                "root_path": meta.root_path,
                "indexed_at": meta.indexed_at,
                "schema_version": meta.schema_version,
            }
        except Exception:
            pass

    stats = {
        "files": len(files),
        "symbols": len(nodes),
        "edges": len(edges),
        "functions": type_counts.get("function", 0),
        "classes": type_counts.get("class", 0),
        "methods": type_counts.get("method", 0),
        "tests": type_counts.get("test", 0),
        "routes": sum(1 for n in nodes if "route" in n.tags),
        "modules": type_counts.get("module", 0),
        "low_confidence_edges": low_conf,
        "low_confidence_ratio": low_conf_ratio,
    }

    # Language breakdown
    lang_files: dict[str, set[str]] = {}
    lang_symbols: dict[str, int] = {}
    for n in nodes:
        lid = n.language_id or n.language or "unknown"
        lang_files.setdefault(lid, set()).add(n.file_path)
        lang_symbols[lid] = lang_symbols.get(lid, 0) + 1
    language_breakdown = {
        lid: {"files": len(lang_files.get(lid, set())), "symbols": lang_symbols.get(lid, 0)}
        for lid in sorted(set(list(lang_files.keys()) + list(lang_symbols.keys())))
    }

    framework_files: dict[str, set[str]] = {}
    framework_symbols: dict[str, int] = {}
    framework_edges: dict[str, int] = {}
    for n in nodes:
        fid = n.framework_id or n.metadata.get("framework_id")
        if fid:
            framework_files.setdefault(fid, set()).add(n.file_path)
            framework_symbols[fid] = framework_symbols.get(fid, 0) + 1
    for e in edges:
        fid = None
        if e.metadata and e.metadata.evidence:
            fid = e.metadata.evidence.get("framework_id")
        if fid:
            framework_edges[fid] = framework_edges.get(fid, 0) + 1
    framework_breakdown = {
        fid: {
            "files": len(framework_files.get(fid, set())),
            "symbols": framework_symbols.get(fid, 0),
            "edges": framework_edges.get(fid, 0),
        }
        for fid in sorted(set(framework_files) | set(framework_symbols) | set(framework_edges))
    }

    # Support level breakdown
    support_level_symbols: dict[str, int] = {}
    support_level_files: dict[str, set[str]] = {}
    for n in nodes:
        sl = n.support_level or n.metadata.get("support_level", "production")
        support_level_symbols[sl] = support_level_symbols.get(sl, 0) + 1
        support_level_files.setdefault(sl, set()).add(n.file_path)
    support_level_breakdown = {
        sl: {"files": len(support_level_files.get(sl, set())), "symbols": support_level_symbols.get(sl, 0)}
        for sl in sorted(support_level_symbols.keys())
    }

    # Per-language edge quality
    node_map: dict[str, GraphNode] = {n.id: n for n in nodes}
    edge_quality_by_language: dict[str, dict[str, Any]] = {}
    for lid in sorted(set(n.language_id or n.language or "unknown" for n in nodes)):
        lang_edges = [
            e for e in edges
            if e.source in node_map and (node_map[e.source].language_id or node_map[e.source].language or "unknown") == lid
        ]
        total_le = len(lang_edges)
        if total_le == 0:
            continue
        unresolved_le = sum(
            1 for e in lang_edges
            if e.metadata and e.metadata.resolution and classify_edge_resolution(e.metadata.resolution) == "unresolved"
        )
        low_conf_le = sum(1 for e in lang_edges if is_low_confidence(e.confidence))
        edge_quality_by_language[lid] = {
            "total_edges": total_le,
            "unresolved_edges": unresolved_le,
            "unresolved_ratio": round(unresolved_le / total_le, 4),
            "low_confidence_edges": low_conf_le,
            "low_confidence_ratio": round(low_conf_le / total_le, 4),
        }

    # Suggested warnings from edge quality
    suggested_warnings: list[dict[str, Any]] = []
    for lid, quality in edge_quality_by_language.items():
        if quality["low_confidence_ratio"] > 0.30:
            suggested_warnings.append({
                "type": "high_low_confidence_ratio",
                "language": lid,
                "message": (
                    f"Language '{lid}' has {quality['low_confidence_ratio']:.1%} low-confidence edges. "
                    "Consider improving parser resolution for this language."
                ),
                "severity": "warning" if quality["low_confidence_ratio"] > 0.50 else "info",
            })
        if quality["unresolved_ratio"] > 0.20:
            suggested_warnings.append({
                "type": "high_unresolved_ratio",
                "language": lid,
                "message": (
                    f"Language '{lid}' has {quality['unresolved_ratio']:.1%} unresolved edges. "
                    "External package resolution may need improvement."
                ),
                "severity": "info",
            })

    idx = _build_index_status()
    idx_health = idx.get("index_health")
    index_info = {
        "status": idx["status"],
        "health": idx_health["status"] if idx_health else "ok",
        "indexed_at": idx.get("indexed_at"),
        "suggested_fix": idx.get("suggested_fix"),
    }

    if response_mode == "compact":
        data: dict[str, Any] = {
            "stats": stats,
            "language_breakdown": language_breakdown,
            "framework_breakdown": framework_breakdown,
            "support_level_breakdown": support_level_breakdown,
            "edge_quality_by_language": edge_quality_by_language,
            "top_modules": [{"module": m, "file_count": c} for m, c in top_modules[:5]],
            "entry_point_candidates": entry_candidates[:5],
            "test_coverage_signal": {
                "test_files": len(test_files),
                "tested_symbols": len(tested_symbols),
            },
            "capabilities": _get_capabilities(),
            "index_info": index_info,
        }
        if suggested_warnings:
            data["suggested_warnings"] = suggested_warnings
    elif response_mode == "standard":
        data = {
            "repo": repo_info,
            "stats": stats,
            "language_breakdown": language_breakdown,
            "framework_breakdown": framework_breakdown,
            "support_level_breakdown": support_level_breakdown,
            "edge_quality_by_language": edge_quality_by_language,
            "top_modules": [{"module": m, "file_count": c} for m, c in top_modules],
            "entry_point_candidates": entry_candidates,
            "test_coverage_signal": {
                "test_files": len(test_files),
                "tested_symbols": len(tested_symbols),
            },
            "capabilities": _get_capabilities(),
            "index_info": index_info,
        }
        if suggested_warnings:
            data["suggested_warnings"] = suggested_warnings
    else:  # standard (fallback)
        data = {
            "repo": repo_info,
            "stats": stats,
            "language_breakdown": language_breakdown,
            "framework_breakdown": framework_breakdown,
            "support_level_breakdown": support_level_breakdown,
            "edge_quality_by_language": edge_quality_by_language,
            "top_modules": [{"module": m, "file_count": c} for m, c in top_modules],
            "entry_point_candidates": entry_candidates,
            "test_coverage_signal": {
                "test_files": len(test_files),
                "tested_symbols": len(tested_symbols),
            },
            "capabilities": _get_capabilities(),
            "index_info": index_info,
        }
        if suggested_warnings:
            data["suggested_warnings"] = suggested_warnings

    return _respond_ok(
        data=data,
        tool="codegraph_repo_summary",
        warnings=_collect_warnings(),
    )


def _reload_store() -> None:
    """Reload the global graph store from disk after a watch sync."""
    global _store, _cg_dir
    if _cg_dir is None:
        return
    graph_path = _cg_dir / "graph.json"
    if not graph_path.exists():
        return
    try:
        graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
        new_store = GraphStore()
        new_store.load_from_graph(graph)
        _store = new_store
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    global _watch_manager, _project_root

    parser = argparse.ArgumentParser(description="CodeGraph Explorer MCP Server")
    parser.add_argument(
        "--project-root", "-r",
        help="Project root path (auto-detected from CWD if omitted)",
    )
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        default=os.environ.get("CODEGRAPH_WATCH", "") == "1",
        help="Start file watcher for automatic incremental index sync "
             "(env: CODEGRAPH_WATCH=1)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate setup and exit without starting the MCP server",
    )
    args = parser.parse_args()

    project_root = _resolve_project_root(args.project_root)

    # Pre-load store so we fail fast if no index exists
    try:
        _load_store(project_root)
    except RuntimeError as e:
        _log(f"Error: {e}")
        sys.exit(1)

    # --check mode: validate and exit
    if args.check:
        _log(f"CodeGraph MCP check passed")
        _log(f"Project root: {project_root}")
        _log(f"Index dir:   {_cg_dir}")
        sys.exit(0)

    # Start watch mode if requested
    if args.watch and _cg_dir is not None:
        try:
            from codegraph.indexer.watch import WatchSyncManager

            def _on_sync(result: Any) -> None:
                if result.status in ("updated", "fresh"):
                    _reload_store()

            _watch_manager = WatchSyncManager(
                repo_root=_project_root or str(Path.cwd()),
                on_sync=_on_sync,
            )
            _watch_manager.start()
            _log("Watch mode enabled — index will auto-sync on file changes.")
        except Exception as e:
            _log(f"Warning: Failed to start watch mode: {e}")

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
