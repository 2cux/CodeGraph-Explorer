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
from codegraph.indexer.status import detect_status
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

ResponseMode = str  # "compact" | "standard"
VALID_RESPONSE_MODES = {"compact", "standard"}

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
    "supported_edges": ["calls", "imports", "contains", "tested_by", "references"],
    "supports_incremental_index": True,
    "supports_source_snippets": True,
    "supports_impact_modes": True,
    "supports_response_modes": ["compact", "standard"],
    "supports_fuzzy_resolution": True,
    "supports_role_grouping": True,
    "supports_path_glob_filtering": True,
    "supports_reason_codes": True,
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
            "line_start": node.location.line_start if node.location else None,
            "line_end": node.location.line_end if node.location else None,
        }
        return result
    else:  # standard (fallback, same as standard branch)
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
        return base

    elif response_mode == "standard":
        if reason_code:
            base["reason_code"] = reason_code
        if include_explanations:
            base["reason"] = reason or ""
            if evidence:
                base["evidence"] = evidence
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


def _build_index_status() -> dict[str, Any]:
    """Build the index_status block shared by all tool responses.

    Reads from state.json first (for watch-driven state), falling back
    to detect_status for non-watch scenarios.
    """
    cg_dir = _find_codegraph_dir(_project_root)
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

    # Read state.json for watch-driven status
    state_store = IndexStateStore(cg_dir)
    state = state_store.load()
    watch_status = state.get("status", "missing")

    file_store = FileStore(cg_dir)
    metadata = file_store.load_metadata()
    root_path = Path(metadata.root_path) if (metadata and metadata.root_path) else cg_dir.parent

    index_files = {
        "graph_json": (cg_dir / "graph.json").exists(),
        "sqlite": (cg_dir / "index.sqlite").exists(),
        "metadata_json": (cg_dir / "metadata.json").exists(),
    }

    if metadata is None:
        graph_exists = index_files.get("graph_json", False)
        _stats: dict[str, int] = {"files": 0, "symbols": 0, "edges": 0}
        if _store is not None:
            nodes = _store.all_nodes()
            files = {n.file_path for n in nodes if n.file_path}
            _stats = {
                "files": len(files),
                "symbols": len(nodes),
                "edges": _store.edge_count(),
            }
        return {
            "status": "stale" if graph_exists else "missing",
            "indexed_at": None,
            "changed_files": [],
            "added_files": [],
            "deleted_files": [],
            "index_files": index_files,
            "stats": _stats,
        }

    result = detect_status(root_path, metadata)

    # If watch is active, state.json has authority for indexing/error
    if watch_status in ("indexing", "error"):
        result_status = watch_status
    else:
        result_status = result.status

    stats = {"files": 0, "symbols": 0, "edges": 0}
    if _store is not None:
        nodes = _store.all_nodes()
        files = {n.file_path for n in nodes if n.file_path}
        stats = {
            "files": len(files),
            "symbols": len(nodes),
            "edges": _store.edge_count(),
        }

    # Include fingerprint health
    fingerprint_health: dict[str, Any] | None = None
    fp_path = cg_dir / "fingerprints.json"
    if fp_path.exists():
        try:
            from codegraph.indexer.fingerprint import FingerprintStore
            fp_store = FingerprintStore(cg_dir)
            fps = fp_store.load()
            fingerprint_health = {
                "present": True,
                "count": len(fps),
            }
        except Exception:
            fingerprint_health = {"present": False}

    # Include change_summary from state
    last_change_summary = state.get("last_change_summary")
    # Include incremental performance stats
    last_incremental_stats = state.get("last_incremental_stats")

    status_block = {
        "status": result_status,
        "indexed_at": result.indexed_at,
        "changed_files": result.changed_files[:20],
        "added_files": result.added_files[:20],
        "deleted_files": result.deleted_files[:20],
        "index_files": index_files,
        "stats": stats,
    }
    if watch_status == "error":
        status_block["last_error"] = state.get("last_error")
    if fingerprint_health is not None:
        status_block["fingerprint_health"] = fingerprint_health
    if last_change_summary is not None:
        status_block["last_change_summary"] = last_change_summary
    if last_incremental_stats is not None:
        status_block["last_incremental_stats"] = last_incremental_stats

    # Include graph validation health
    index_health: dict[str, Any] | None = None
    if cg_dir is not None:
        try:
            from codegraph.graph.validation import load_validation_report
            vr = load_validation_report(cg_dir)
            if vr is not None:
                index_health = {
                    "status": vr["status"],
                    "generated_at": vr.get("generated_at"),
                    "issue_counts": vr.get("issue_counts", {}),
                }
        except Exception:
            pass
    if index_health is not None:
        status_block["index_health"] = index_health

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
        warnings.append({
            "type": "index_update_failed",
            "severity": "warning",
            "message": "Last incremental index failed. Results may be outdated.",
            "evidence": {"error": str(last_error)},
        })
    elif status == "stale":
        stale_entry = build_stale_index_warning(
            changed_files=index_status.get("changed_files", []),
            added_files=index_status.get("added_files", []),
            deleted_files=index_status.get("deleted_files", []),
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
) -> dict[str, Any]:
    """Wrap a successful tool result in the standard envelope."""
    return {
        "ok": True,
        "tool": tool,
        "data": data,
        "warnings": warnings or [],
        "index_status": _build_index_status(),
        "meta": {"schema_version": SCHEMA_VERSION},
    }


def _respond_error(
    code: str,
    message: str,
    tool: str = "",
    details: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Wrap a failed tool result in the standard envelope."""
    return {
        "ok": False,
        "tool": tool,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "warnings": warnings or [],
        "index_status": _build_index_status(),
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
    if sort_by == "confidence":
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


# ── Tool: search_symbols ──────────────────────────────────────────────────


@mcp.tool(name="codegraph_search_symbols")
def search_symbols(
    query: str,
    types: str | None = None,
    tags: str | None = None,
    paths: str | None = None,
    exact: bool = False,
    fuzzy: bool = True,
    exclude_tests: bool = True,
    limit: int = 10,
    offset: int = 0,
    sort_by: str = "relevance",
    response_mode: str = "compact",
    include_explanations: bool = False,
    # Legacy params for backward compat
    type_filter: str | None = None,
    file_filter: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Search for code symbols by name, file path, type, tags, or path glob.

    Args:
        query: Search keyword — symbol name, file path fragment, or docstring keyword
        types: Comma-separated node types, e.g. "function,method,class" (default: all)
        tags: Comma-separated tags, e.g. "auth,route" (default: none)
        paths: Comma-separated path glob patterns, e.g. "app/api/**,tests/**"
        exact: If true, only return exact name matches (default false)
        fuzzy: If true, use fuzzy matching (default true)
        exclude_tests: Exclude test symbols from results (default true)
        limit: Maximum results (default 10)
        offset: Pagination offset (default 0)
        sort_by: Sort order — "relevance" (default), "confidence", "file_path", "name"
        response_mode: "compact" (default) or "standard"
        include_explanations: If true, include reason text and evidence (default false)
    """
    effective_limit = max(1, min(limit or max_results or 10, 100))
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
                type_filter=type_filter,
                file_filter=file_filter,
                limit=effective_limit + offset,
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
    include_types_list: list[str] | None = None
    exclude_types_list: list[str] | None = None
    if types:
        include_types_list = [t.strip() for t in types.split(",") if t.strip()]
    if exclude_tests and not include_types_list:
        exclude_types_list = ["test"]
    elif exclude_tests and include_types_list:
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
    shaped = _apply_result_shaping(
        items,
        limit=effective_limit,
        offset=offset,
        sort_by=sort_by,
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
            "score": item.get("score"),
            "match_sources": item.get("match_sources", []),
        }
        if item.get("tags"):
            entry["tags"] = item["tags"]
        if response_mode == "compact":
            entry["reason_code"] = (
                item.get("match_sources", [None])[0] if item.get("match_sources") else "symbol_name_match"
            )
        elif response_mode == "standard":
            entry["line_start"] = item.get("line_start")
            entry["line_end"] = item.get("line_end")
            if item.get("confidence"):
                entry["confidence"] = item["confidence"]
                entry["confidence_level"] = get_confidence_level(item["confidence"])
            if include_explanations:
                entry["reason"] = f"Matched via: {', '.join(item.get('match_sources', []))}"
        # standard fallback — already covered in the elif branch above
        serialized_results.append(entry)

    return _respond_ok(
        data={
            "query": query,
            "results": serialized_results,
            "total": shaped["total"],
            "offset": shaped["offset"],
            "limit": shaped["limit"],
            "has_more": shaped["has_more"],
        },
        tool="codegraph_search_symbols",
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
    max_nodes: int = 25,
    edge_types: str | None = None,
    min_confidence: float = 0.6,
    direction: str = "both",
    group_by_role: bool = True,
    response_mode: str = "compact",
    include_explanations: bool = False,
) -> dict[str, Any]:
    """Get neighbors of a symbol in the code graph — the primary local-graph tool.

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
        max_nodes: Maximum nodes to return (default 25, max 100)
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
    effective_max = max(1, min(max_nodes, 100))
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
        if len(visited_nodes) >= effective_max:
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
                if neighbor_id not in visited_nodes and len(visited_nodes) < effective_max:
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
    if len(all_possible - set(visited_nodes.keys())) > 0 and len(visited_nodes) >= effective_max:
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
                "max_nodes": effective_max,
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
    }
    if response_mode == "compact":
        risk["reason_codes"] = unique_codes
    else:
        risk["reason_codes"] = unique_codes
        risk["reasons"] = risk_reasons

    # ── Confirmed impact ───────────────────────────────────────────────
    confirmed = impact_result.get("confirmed_impact", {})
    confirmed_symbols = confirmed.get("symbols", [])
    confirmed_files_list = confirmed.get("files", [])[:max_files]

    if response_mode == "compact":
        confirmed_files_out: list[dict[str, Any]] = []
        for f in confirmed_files_list:
            entry: dict[str, Any] = {
                "file_path": f["file_path"],
                "reason_code": _impact_reason_to_code(f.get("reason", "")),
                "confidence": f.get("confidence", 1.0),
            }
            if f.get("priority"):
                entry["priority"] = f["priority"]
            confirmed_files_out.append(entry)

        confirmed_symbols_out: list[dict[str, Any]] = []
        for s in confirmed_symbols[:20]:
            entry = {
                "symbol_id": s["symbol_id"],
                "name": s.get("name", ""),
                "type": s.get("type", "unknown"),
                "file_path": s.get("file_path", ""),
                "reason_code": s.get("impact_type", "unknown"),
                "confidence": s.get("confidence", 1.0),
                "confidence_level": s.get("confidence_level", "unknown"),
                "distance": s.get("distance", 0),
            }
            confirmed_symbols_out.append(entry)
    else:
        confirmed_files_out = confirmed_files_list
        confirmed_symbols_out = confirmed_symbols

    # ── Possible impact ────────────────────────────────────────────────
    possible: dict[str, Any] = {"symbols": [], "files": []}
    if effective_include_possible:
        poss = impact_result.get("possible_impact", {})
        poss_files_list = poss.get("files", [])[:max_files]
        if response_mode == "compact":
            poss_files_out: list[dict[str, Any]] = []
            for f in poss_files_list:
                poss_files_out.append({
                    "file_path": f["file_path"],
                    "reason_code": "low_confidence_edge",
                    "confidence": f.get("confidence", 0.5),
                    "priority": f.get("priority", "low"),
                })
            possible = {"symbols": poss.get("symbols", [])[:20], "files": poss_files_out}
        else:
            possible = {"symbols": poss.get("symbols", []), "files": poss_files_list}

    # ── Related tests ──────────────────────────────────────────────────
    related_tests = impact_result.get("related_tests", []) if include_tests else []
    related_tests_count = len(related_tests)

    # ── External / unresolved ──────────────────────────────────────────
    external = impact_result.get("external_or_unresolved", [])

    # ── Upstream / downstream ──────────────────────────────────────────
    upstream = impact_result.get("upstream_callers", [])
    downstream = impact_result.get("downstream_callees", [])

    fuzzy_warning = (
        f"Fuzzy fallback used: {result['match_reason']} — verify this is the expected symbol"
        if not result["exact_match"]
        else None
    )
    warnings = _collect_warnings(fuzzy_warning)

    truncated = len(confirmed_files_list) >= max_files

    if response_mode == "compact":
        data: dict[str, Any] = {
            "target": center_node.id,
            "risk": risk,
            "confirmed_files": confirmed_files_out,
            "possible_files": possible.get("files", []),
            "related_tests_count": related_tests_count,
            "unresolved_count": len(external),
            "truncated": truncated,
        }
        if include_tests and related_tests:
            # Include test IDs in compact mode for reference
            data["related_test_ids"] = [
                {"symbol_id": t["symbol_id"], "name": t.get("name", "")}
                for t in related_tests[:10]
            ]
    else:
        data = {
            "target": center_node.id,
            "risk": risk,
            "confirmed_impact": {
                "symbols": confirmed_symbols_out,
                "files": confirmed_files_out,
            },
            "possible_impact": possible,
            "upstream_callers": upstream,
            "downstream_callees": downstream,
            "related_tests": related_tests,
            "external_or_unresolved": external,
            "truncated": truncated,
        }

    return _respond_ok(
        data=data,
        tool="codegraph_get_impact",
        warnings=warnings,
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
    response_mode: str = "standard",
) -> dict[str, Any]:
    """Build a Context Pack for a natural language task.

    Provides task-aware code evidence: entry points, related symbols,
    call graph, impact signals, selected context, and tests.
    Does NOT include reading plans or agent instructions.

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
        max_tokens=max_tokens,
        depth=depth,
        include_tests=include_tests,
        output_dir=str(output_dir),
    )

    pack_dict = json.loads(pack.model_dump_json(exclude_none=True))

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
        }
    elif mode == "markdown":
        from codegraph.context.markdown_exporter import save_markdown

        md_path = output_dir / f"{pack.pack_id}.md"
        save_markdown(pack, str(md_path))
        pack_dict = {
            "pack_id": pack.pack_id,
            "markdown_path": str(md_path),
            "format": "markdown",
        }

    if response_mode == "compact":
        # Strip down to essentials
        pack_dict = {
            "pack_id": pack_dict.get("pack_id"),
            "task": pack_dict.get("task", {}),
            "entry_points": pack_dict.get("entry_points", [])[:5],
            "call_graph": pack_dict.get("call_graph", {}),
            "impact": pack_dict.get("impact"),
            "related_tests_count": len(pack_dict.get("related_tests", [])),
            "selected_context_count": len(pack_dict.get("selected_context", [])),
            "token_budget": pack_dict.get("token_budget", {}),
        }

    return _respond_ok(
        data=pack_dict,
        tool="codegraph_build_context_pack",
        warnings=_collect_warnings(),
    )


# ── Tool: repo_status ─────────────────────────────────────────────────────


@mcp.tool(name="codegraph_repo_status")
def repo_status(
    root: str | None = None,
    response_mode: str = "compact",
) -> dict[str, Any]:
    """Check index freshness and report changed/added/deleted files.

    Args:
        root: Optional project root path override
        response_mode: "compact" (default) or "standard"
    """
    project_root = root or _project_root
    index_status = _build_index_status()

    if index_status["status"] == "missing":
        return _respond_ok(
            data=index_status,
            tool="codegraph_repo_status",
            warnings=[{
                "type": "index_missing",
                "message": "No .codegraph index found.",
                "reason_code": "stale_index",
            }],
        )

    if response_mode == "compact":
        data = {
            "status": index_status["status"],
            "indexed_at": index_status.get("indexed_at"),
            "index_files": index_status.get("index_files", {}),
            "changed_file_count": len(index_status.get("changed_files", []))
                                + len(index_status.get("added_files", []))
                                + len(index_status.get("deleted_files", [])),
            "stats": index_status.get("stats", {}),
        }
    else:
        data = index_status

    return _respond_ok(
        data=data,
        tool="codegraph_repo_status",
        warnings=(
            [{
                "type": "stale_index",
                "message": f"Index is stale — {len(index_status.get('changed_files', [])) + len(index_status.get('added_files', [])) + len(index_status.get('deleted_files', []))} file(s) changed.",
                "reason_code": "stale_index",
            }]
            if index_status["status"] == "stale"
            else []
        ),
    )


# ── Tool: repo_summary ────────────────────────────────────────────────────


@mcp.tool(name="codegraph_repo_summary")
def repo_summary(
    response_mode: str = "compact",
    include_explanations: bool = False,
) -> dict[str, Any]:
    """Get a summary of the indexed repository.

    Returns file count, symbol count, type breakdown, edge count,
    low-confidence edge ratio, top modules, entry point candidates,
    test coverage signal, and capability metadata.

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

    if response_mode == "compact":
        data: dict[str, Any] = {
            "stats": stats,
            "top_modules": [{"module": m, "file_count": c} for m, c in top_modules[:5]],
            "entry_point_candidates": entry_candidates[:5],
            "test_coverage_signal": {
                "test_files": len(test_files),
                "tested_symbols": len(tested_symbols),
            },
            "capabilities": _get_capabilities(),
            "index_status": _build_index_status(),
        }
    elif response_mode == "standard":
        data = {
            "repo": repo_info,
            "stats": stats,
            "top_modules": [{"module": m, "file_count": c} for m, c in top_modules],
            "entry_point_candidates": entry_candidates,
            "test_coverage_signal": {
                "test_files": len(test_files),
                "tested_symbols": len(tested_symbols),
            },
            "capabilities": _get_capabilities(),
            "index_status": _build_index_status(),
        }
    else:  # standard
        data = {
            "repo": repo_info,
            "stats": stats,
            "top_modules": [{"module": m, "file_count": c} for m, c in top_modules],
            "entry_point_candidates": entry_candidates,
            "test_coverage_signal": {
                "test_files": len(test_files),
                "tested_symbols": len(tested_symbols),
            },
            "capabilities": _get_capabilities(),
            "index_status": _build_index_status(),
        }

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
