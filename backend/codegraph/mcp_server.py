"""MCP Server for CodeGraph Explorer.

Provides Model Context Protocol tools for AI coding agents
(Claude Code, Cursor, etc.) to query the code graph directly.

Usage:
    python -m codegraph.mcp_server
    python -m codegraph.mcp_server --project-root /path/to/project

Claude Code config (add to project's .claude/settings.local.json):
    {
      "mcpServers": {
        "codegraph": {
          "command": "python",
          "args": ["-m", "codegraph.mcp_server"],
          "env": {
            "CODEGRAPH_PROJECT_ROOT": "/path/to/project"
          }
        }
      }
    }

Cursor config (add to project's .cursor/mcp.json):
    {
      "mcpServers": {
        "codegraph": {
          "command": "python",
          "args": ["-m", "codegraph.mcp_server"],
          "env": {
            "CODEGRAPH_PROJECT_ROOT": "/path/to/project"
          }
        }
      }
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from codegraph.graph import impact as graph_impact
from codegraph.graph import query as graph_query
from codegraph.graph.models import CodeGraph, GraphNode, NodeType
from codegraph.graph.store import GraphStore
from codegraph.indexer.status import detect_status
from codegraph.storage.file_store import FileStore

# ── MCP Server ────────────────────────────────────────────────────────────

mcp = FastMCP("codegraph-explorer")

_store: GraphStore | None = None
_cg_dir: Path | None = None
_project_root: str | None = None

# ── Unified Response Format ───────────────────────────────────────────────


def _respond_ok(
    data: Any,
    tool: str = "",
    warnings: list[str] | None = None,
) -> str:
    """Wrap a successful tool result in the standard envelope."""
    return json.dumps(
        {
            "ok": True,
            "tool": tool,
            "data": data,
            "warnings": warnings or [],
        },
        indent=2,
        ensure_ascii=False,
    )


def _respond_error(
    code: str,
    message: str,
    tool: str = "",
    details: dict[str, Any] | None = None,
    suggestions: list[str] | None = None,
) -> str:
    """Wrap a failed tool result in the standard envelope."""
    return json.dumps(
        {
            "ok": False,
            "tool": tool,
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            },
            "suggestions": suggestions or [],
        },
        indent=2,
        ensure_ascii=False,
    )


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
    """Load graph into memory (cached after first call)."""
    global _store, _cg_dir, _project_root

    if _store is not None and _cg_dir is not None:
        return _store, _cg_dir

    cg_dir = _find_codegraph_dir(project_root)
    if cg_dir is None:
        searched = project_root or str(Path.cwd())
        raise RuntimeError(
            f"No .codegraph directory found (searched from: {searched}). "
            "Run 'codegraph index <project>' first, or set CODEGRAPH_PROJECT_ROOT."
        )

    graph_path = cg_dir / "graph.json"
    graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))

    store = GraphStore()
    store.load_from_graph(graph)

    _store = store
    _cg_dir = cg_dir
    _project_root = str(cg_dir.parent.resolve())
    return store, cg_dir


def _check_index_status() -> list[str]:
    """Check index freshness and return stale warnings if any."""
    cg_dir = _find_codegraph_dir(_project_root)
    if cg_dir is None:
        return []

    file_store = FileStore(cg_dir)
    metadata = file_store.load_metadata()
    if metadata is None:
        return []

    from pathlib import Path
    root_path = Path(metadata.root_path) if metadata.root_path else cg_dir.parent
    result = detect_status(root_path, metadata)

    if result.is_stale:
        warnings = [{
            "type": "stale_index",
            "message": "Index is stale. Results may be outdated.",
        }]
        if result.changed_files:
            warnings[0]["changed_files"] = result.changed_files[:10]
        if result.added_files:
            warnings[0]["added_files"] = result.added_files[:10]
        if result.deleted_files:
            warnings[0]["deleted_files"] = result.deleted_files[:10]
        return [
            f"Index is stale ({result.total_changes} file(s) changed). "
            f"Run 'codegraph index --incremental' to update."
        ]
    return []


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

    for n in store.all_nodes():
        if n.name.lower() == symbol_lower:
            # Exact name match — best fuzzy result, no further candidates needed
            return {
                "node": n,
                "exact_match": False,
                "match_reason": "exact_name",
                "candidates": [],
            }
        if symbol_lower in n.id.lower():
            candidates.append({
                "symbol_id": n.id,
                "name": n.name,
                "type": n.type.value if isinstance(n.type, NodeType) else str(n.type),
                "file_path": n.file_path,
            })
        elif n.name and symbol_lower in n.name.lower():
            candidates.append({
                "symbol_id": n.id,
                "name": n.name,
                "type": n.type.value if isinstance(n.type, NodeType) else str(n.type),
                "file_path": n.file_path,
            })

    if not candidates:
        return None

    best = candidates[0]
    best_node = store.get_node(best["symbol_id"])
    if best_node is None:
        return None

    return {
        "node": best_node,
        "exact_match": False,
        "match_reason": "partial_id_or_name",
        "candidates": candidates[:max_candidates],
    }


def _node_to_detail(node: GraphNode) -> dict[str, Any]:
    """Serialize a GraphNode to a plain dict."""
    return {
        "id": node.id,
        "name": node.name,
        "type": node.type.value if isinstance(node.type, NodeType) else str(node.type),
        "file_path": node.file_path,
        "module": node.module,
        "qualified_name": node.qualified_name,
        "display_name": node.display_name,
        "signature": node.signature,
        "docstring": node.docstring.split("\n")[0] if node.docstring else None,
        "code_preview": node.code_preview,
        "visibility": node.visibility,
        "tags": node.tags,
        "location": (
            {
                "line_start": node.location.line_start,
                "line_end": node.location.line_end,
                "column_start": node.location.column_start,
                "column_end": node.location.column_end,
            }
            if node.location
            else None
        ),
    }


# ── Tools ─────────────────────────────────────────────────────────────────


@mcp.tool(name="codegraph_search_symbols")
def search_symbols(
    query: str,
    type_filter: str | None = None,
    file_filter: str | None = None,
    limit: int = 30,
    max_results: int | None = None,
) -> str:
    """Search for code symbols by name, file path, or docstring.

    Args:
        query: Search keyword — can be a symbol name, file path fragment, or docstring keyword
        type_filter: Optional — filter by node type (function, class, method, module, file, test, import_)
        file_filter: Optional — filter by file path substring (e.g. "api/auth")
        limit: Maximum results to return (default 30, max 100)
        max_results: Alias for limit (preferred by some agents)
    """
    effective_limit = min(max_results or limit, 100)
    try:
        store, _ = _load_store()
        result = graph_query.search_symbols(
            store,
            query=query,
            type_filter=type_filter,
            file_filter=file_filter,
            limit=effective_limit,
        )
        return _respond_ok(
            data={
                "query": query,
                "total": result["total"],
                "results": result["results"][:effective_limit],
            },
            tool="search_symbols",
        )
    except RuntimeError as e:
        return _respond_error(
            code="NO_INDEX",
            message=str(e),
            tool="search_symbols",
            suggestions=["Run 'codegraph index <project>' first"],
        )


@mcp.tool(name="codegraph_get_symbol")
def get_symbol(symbol_id: str) -> str:
    """Get detailed information about a specific code symbol.

    Supports fuzzy lookup: if an exact ID match fails, the server will
    attempt name-match and partial-ID-match fallbacks. The response
    includes ``exact_match`` and ``match_reason`` so the agent can
    detect when a fallback was used.

    Args:
        symbol_id: Symbol node ID (e.g. "app/api/auth.py::login")
                   or a symbol name for fuzzy lookup
    """
    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code="NO_INDEX",
            message=str(e),
            tool="get_symbol",
            suggestions=["Run 'codegraph index <project>' first"],
        )

    result = _resolve_node_detailed(store, symbol_id)
    if result is None:
        return _respond_error(
            code="SYMBOL_NOT_FOUND",
            message=f"No symbol found matching '{symbol_id}'",
            tool="get_symbol",
            details=_get_project_info(),
            suggestions=[
                "Try codegraph_search_symbols with a broader query",
                "Check the symbol_id format (e.g. 'path/to/file.py::function_name')",
            ],
        )

    node = result["node"]
    detail = _node_to_detail(node)
    detail["exact_match"] = result["exact_match"]
    detail["match_reason"] = result["match_reason"]
    if result["candidates"]:
        detail["candidates"] = result["candidates"]

    return _respond_ok(
        data=detail,
        tool="get_symbol",
        warnings=(
            [f"Fuzzy fallback used: {result['match_reason']} — verify this is the expected symbol"]
            if not result["exact_match"]
            else []
        ),
    )


@mcp.tool(name="codegraph_get_callers")
def get_callers(symbol_id: str) -> str:
    """Get all callers of a symbol — functions that call it.

    Args:
        symbol_id: The symbol's node ID (e.g. "app/api/auth.py::login")
    """
    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code="NO_INDEX",
            message=str(e),
            tool="get_callers",
            suggestions=["Run 'codegraph index <project>' first"],
        )

    result = _resolve_node_detailed(store, symbol_id)
    if result is None:
        return _respond_error(
            code="SYMBOL_NOT_FOUND",
            message=f"No symbol found matching '{symbol_id}'",
            tool="get_callers",
            details=_get_project_info(),
        )

    node = result["node"]
    callers = graph_query.get_callers(store, node.id)
    items = []
    for caller_id, edge_type in callers:
        caller_node = store.get_node(caller_id)
        items.append({
            "node_id": caller_id,
            "name": caller_node.name if caller_node else caller_id,
            "type": (
                caller_node.type.value
                if caller_node and isinstance(caller_node.type, NodeType)
                else (str(caller_node.type) if caller_node else "unknown")
            ),
            "file_path": caller_node.file_path if caller_node else "",
            "edge_type": edge_type,
        })

    return _respond_ok(
        data={
            "symbol_id": node.id,
            "exact_match": result["exact_match"],
            "match_reason": result["match_reason"],
            "callers": items,
            "total": len(items),
        },
        tool="get_callers",
        warnings=(
            [f"Fuzzy fallback used: {result['match_reason']}"]
            if not result["exact_match"]
            else []
        ),
    )


@mcp.tool(name="codegraph_get_callees")
def get_callees(symbol_id: str) -> str:
    """Get all callees of a symbol — functions it calls.

    Args:
        symbol_id: The symbol's node ID (e.g. "app/api/auth.py::login")
    """
    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code="NO_INDEX",
            message=str(e),
            tool="get_callees",
            suggestions=["Run 'codegraph index <project>' first"],
        )

    result = _resolve_node_detailed(store, symbol_id)
    if result is None:
        return _respond_error(
            code="SYMBOL_NOT_FOUND",
            message=f"No symbol found matching '{symbol_id}'",
            tool="get_callees",
            details=_get_project_info(),
        )

    node = result["node"]
    callees = graph_query.get_callees(store, node.id)
    items = []
    for callee_id, edge_type in callees:
        callee_node = store.get_node(callee_id)
        items.append({
            "node_id": callee_id,
            "name": callee_node.name if callee_node else callee_id,
            "type": (
                callee_node.type.value
                if callee_node and isinstance(callee_node.type, NodeType)
                else (str(callee_node.type) if callee_node else "unknown")
            ),
            "file_path": callee_node.file_path if callee_node else "",
            "edge_type": edge_type,
        })

    return _respond_ok(
        data={
            "symbol_id": node.id,
            "exact_match": result["exact_match"],
            "match_reason": result["match_reason"],
            "callees": items,
            "total": len(items),
        },
        tool="get_callees",
        warnings=(
            [f"Fuzzy fallback used: {result['match_reason']}"]
            if not result["exact_match"]
            else []
        ),
    )


@mcp.tool(name="codegraph_get_neighbors")
def get_neighbors(
    symbol_id: str,
    depth: int = 1,
    max_depth: int | None = None,
    include_code: bool = False,
) -> str:
    """Get neighbors of a symbol in the code graph (edges of all types).

    Args:
        symbol_id: The symbol's node ID
        depth: How many hops to traverse (default 1, max 3)
        max_depth: Alias for depth (preferred by some agents)
        include_code: If true, include code_preview in node output (default false)
    """
    effective_depth = max(1, min(max_depth or depth, 3))
    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code="NO_INDEX",
            message=str(e),
            tool="get_neighbors",
            suggestions=["Run 'codegraph index <project>' first"],
        )

    result = _resolve_node_detailed(store, symbol_id)
    if result is None:
        return _respond_error(
            code="SYMBOL_NOT_FOUND",
            message=f"No symbol found matching '{symbol_id}'",
            tool="get_neighbors",
            details=_get_project_info(),
        )

    node = result["node"]
    subgraph = graph_query.get_subgraph(store, node.id, depth=effective_depth)

    nodes_out = []
    for n in subgraph["nodes"]:
        entry = {
            "id": n.id,
            "name": n.name,
            "type": n.type.value if isinstance(n.type, NodeType) else str(n.type),
            "file_path": n.file_path,
        }
        if include_code and n.code_preview:
            entry["code_preview"] = n.code_preview
        nodes_out.append(entry)

    edges_out = []
    for e in subgraph["edges"]:
        edges_out.append({
            "source": e.source,
            "target": e.target,
            "type": e.type.value if hasattr(e.type, "value") else str(e.type),
            "confidence": e.confidence,
        })

    stale_warnings = _check_index_status()
    fuzzy_warnings = (
        [f"Fuzzy fallback used: {result['match_reason']}"]
        if not result["exact_match"]
        else []
    )
    return _respond_ok(
        data={
            "center_node_id": node.id,
            "exact_match": result["exact_match"],
            "match_reason": result["match_reason"],
            "depth": effective_depth,
            "nodes": nodes_out,
            "edges": edges_out,
        },
        tool="get_neighbors",
        warnings=stale_warnings + fuzzy_warnings,
    )


@mcp.tool(name="codegraph_get_impact")
def get_impact(
    symbol_id: str,
    depth: int = 2,
    max_depth: int | None = None,
) -> str:
    """Analyse the impact of modifying a symbol.

    Returns affected symbols, files, risk level, and recommendations.

    Args:
        symbol_id: The symbol's node ID
        depth: Transitive call-chain depth (default 2, max 5)
        max_depth: Alias for depth (preferred by some agents)
    """
    effective_depth = max(1, min(max_depth or depth, 5))
    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code="NO_INDEX",
            message=str(e),
            tool="get_impact",
            suggestions=["Run 'codegraph index <project>' first"],
        )

    result = _resolve_node_detailed(store, symbol_id)
    if result is None:
        return _respond_error(
            code="SYMBOL_NOT_FOUND",
            message=f"No symbol found matching '{symbol_id}'",
            tool="get_impact",
            details=_get_project_info(),
        )

    node = result["node"]
    impact_result = graph_impact.analyze_impact(store, node.id, depth=effective_depth)
    impact_result.pop("changed_symbol_type", None)

    stale_warnings = _check_index_status()
    return _respond_ok(
        data={
            "symbol": node.id,
            "exact_match": result["exact_match"],
            "match_reason": result["match_reason"],
            "affected_symbols": impact_result.get("affected_symbols", []),
            "affected_files": impact_result.get("affected_files", []),
            "risk": impact_result.get("risk", {}),
            "recommendations": impact_result.get("recommendations", []),
            "warnings": impact_result.get("warnings", []),
        },
        tool="get_impact",
        warnings=stale_warnings,
    )


@mcp.tool(name="codegraph_build_context_pack")
def build_context_pack(
    task: str,
    max_tokens: int = 6000,
    depth: int = 2,
    include_tests: bool = True,
    include_code: bool = True,
    mode: str = "summary",
) -> str:
    """Build a Context Pack for a natural language task.

    This is the core differentiated feature of CodeGraph Explorer. It
    analyses the code graph and produces a task-aware context package
    with entry points, call graph, impact analysis, reading plan, and
    agent instructions.

    Args:
        task: Natural language description of what you need to do
              (e.g. "add rate limiting to the login endpoint")
        max_tokens: Token budget for the context pack (default 6000)
        depth: Call-chain traversal depth (default 2)
        include_tests: Whether to include related tests (default true)
        include_code: Whether to include source code snippets (default true)
        mode: Output mode — "full" (complete JSON), "summary" (key insights only),
              or "markdown" (returns markdown file path) (default "full")
    """
    from codegraph.context.pack_builder import build_context_pack as _build

    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code="NO_INDEX",
            message=str(e),
            tool="build_context_pack",
            suggestions=["Run 'codegraph index <project>' first"],
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
        # Return only essential fields to keep the response small
        pack_dict = {
            "pack_id": pack_dict.get("pack_id"),
            "task": pack_dict.get("task", {}),
            "entry_points": [
                {
                    "symbol_id": ep.get("symbol_id"),
                    "name": ep.get("name"),
                    "reason": ep.get("reason"),
                    "file_path": ep.get("file_path"),
                    "importance": ep.get("importance"),
                }
                for ep in pack_dict.get("entry_points", [])
            ],
            "call_graph": {
                "total_nodes": len(pack_dict.get("call_graph", {}).get("nodes", [])),
                "total_edges": len(pack_dict.get("call_graph", {}).get("edges", [])),
            },
            "impact": pack_dict.get("impact"),
            "reading_plan": pack_dict.get("reading_plan"),
            "related_tests": pack_dict.get("related_tests", []),
            "agent_instructions": pack_dict.get("agent_instructions"),
            "token_budget": pack_dict.get("token_budget", {}),
            "optional_context_count": len(pack_dict.get("optional_context", [])),
            "warnings": pack_dict.get("warnings", []),
        }
    elif mode == "markdown":
        # Export to markdown and return the file path
        from codegraph.context.markdown_exporter import save_markdown

        md_path = output_dir / f"{pack.pack_id}.md"
        save_markdown(pack, str(md_path))
        pack_dict = {
            "pack_id": pack.pack_id,
            "markdown_path": str(md_path),
            "format": "markdown",
        }

    stale_warnings = _check_index_status()
    return _respond_ok(
        data=pack_dict,
        tool="build_context_pack",
        warnings=stale_warnings,
    )


@mcp.tool(name="codegraph_repo_status")
def repo_status() -> str:
    """Check index freshness and report changed/added/deleted files.

    Returns index status (fresh/stale/missing), file change details,
    and a recommendation for what to do next.
    """
    cg_dir = _find_codegraph_dir(_project_root)
    if cg_dir is None:
        return _respond_ok(
            data={
                "status": "missing",
                "changed_files": [],
                "added_files": [],
                "deleted_files": [],
                "indexed_at": None,
                "recommendation": "Run 'codegraph index <project>' to create the index.",
            },
            tool="repo_status",
            warnings=["No .codegraph index found — results will be incomplete."],
        )

    file_store = FileStore(cg_dir)
    metadata = file_store.load_metadata()
    from pathlib import Path as _Path
    root_path = _Path(metadata.root_path) if metadata and metadata.root_path else cg_dir.parent
    result = detect_status(root_path, metadata)

    return _respond_ok(
        data={
            "status": result.status,
            "indexed_at": result.indexed_at,
            "changed_files": result.changed_files,
            "added_files": result.added_files,
            "deleted_files": result.deleted_files,
            "recommendation": result.recommendation,
        },
        tool="repo_status",
        warnings=(
            [f"Index is stale — {result.total_changes} file(s) changed."]
            if result.is_stale else []
        ),
    )


@mcp.tool(name="codegraph_repo_summary")
def repo_summary() -> str:
    """Get a summary of the indexed repository.

    Returns file count, symbol count, type breakdown, edge count,
    and low-confidence edge ratio.
    """
    try:
        store, cg_dir = _load_store()
    except RuntimeError as e:
        return _respond_error(
            code="NO_INDEX",
            message=str(e),
            tool="repo_summary",
            suggestions=["Run 'codegraph index <project>' first"],
        )

    nodes = store.all_nodes()
    edges = store.all_edges()

    type_counts: dict[str, int] = {}
    for n in nodes:
        t = n.type.value if isinstance(n.type, NodeType) else str(n.type)
        type_counts[t] = type_counts.get(t, 0) + 1

    files = {n.file_path for n in nodes if n.file_path}
    low_conf = sum(1 for e in edges if e.confidence < 0.6)
    low_conf_ratio = round(low_conf / len(edges), 4) if edges else 0.0

    stale_warnings = _check_index_status()
    return _respond_ok(
        data={
            "project": cg_dir.parent.name,
            "project_root": _project_root or str(cg_dir.parent.resolve()),
            "index_path": str(cg_dir / "graph.json"),
            "file_count": len(files),
            "symbol_count": len(nodes),
            "edge_count": len(edges),
            "type_breakdown": type_counts,
            "low_confidence_edges": low_conf,
            "low_confidence_ratio": low_conf_ratio,
        },
        tool="repo_summary",
        warnings=stale_warnings,
    )


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="CodeGraph Explorer MCP Server")
    parser.add_argument(
        "--project-root", "-r",
        help="Project root path (auto-detected from CWD if omitted)",
    )
    args = parser.parse_args()

    project_root = _resolve_project_root(args.project_root)

    # Pre-load store so we fail fast if no index exists
    try:
        _load_store(project_root)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
