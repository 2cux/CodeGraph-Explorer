"""Deterministic CLI workflow orchestration.

Reusable helpers for impact analysis, test audit, and other workflows.
MCP tools and CLI commands both delegate to these functions for core logic.

Convention:
- Functions accept plain Python types (lists, not comma-separated strings).
- Functions accept a loaded ``GraphStore`` instance (caller is responsible).
- Functions return plain dicts (no MCP envelope wrapping).
"""

from __future__ import annotations

from typing import Any

from codegraph.graph.models import GraphNode, NodeType
from codegraph.graph.store import GraphStore
from codegraph.graph import impact as graph_impact


def _assign_layer(file_path: str) -> str:
    """Assign a layer label based on file_path directory heuristics."""
    normalized = file_path.replace("\\", "/").lower()
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


def _resolve_symbol(
    store: GraphStore,
    symbol_name: str,
) -> tuple[GraphNode | None, bool]:
    """Resolve a symbol name to a single GraphNode.

    Priority: exact ID > exact name match > partial ID/name match.
    If multiple candidates are found (ambiguity), returns ``(None, True)``.

    Returns:
        Tuple of ``(node, is_ambiguous)``.
        - ``(node, False)`` — single match found.
        - ``(None, False)`` — no match found.
        - ``(None, True)`` — ambiguous (multiple candidates).
    """
    # Exact ID match
    node = store.get_node(symbol_name)
    if node:
        return node, False

    symbol_lower = symbol_name.lower()
    candidates: list[GraphNode] = []

    # Exact name match
    for n in store.all_nodes():
        if n.name.lower() == symbol_lower:
            candidates.append(n)

    # If multiple exact-name matches, ambiguous — return None
    if len(candidates) > 1:
        return None, True
    if len(candidates) == 1:
        return candidates[0], False

    # Partial ID or name match
    for n in store.all_nodes():
        if symbol_lower in n.id.lower():
            candidates.append(n)
        elif n.name and symbol_lower in n.name.lower():
            candidates.append(n)

    # If multiple partial matches, ambiguous — return None
    if len(candidates) > 1:
        return None, True
    if len(candidates) == 1:
        return candidates[0], False

    return None, False


def run_pre_edit_check(
    store: GraphStore,
    files: list[str],
    symbols: list[str],
    change_type: str = "unknown",
    description: str | None = None,
    include_tests: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """Core pre-edit impact check logic.

    Reusable by both MCP ``codegraph_pre_edit_check`` and CLI
    ``codegraph workflow impact``.

    Args:
        store: Loaded GraphStore instance.
        files: List of planned file paths (already parsed, not comma-separated).
        symbols: List of planned symbol names (already parsed).
        change_type: One of refactor | bugfix | feature | test | cleanup | unknown.
        description: Optional short description for the report summary.
        include_tests: Whether to include affected tests.
        limit: Maximum results per category.

    Returns:
        Dict with keys: planned_files, planned_symbols, impact_summary,
        affected_callers, affected_files, affected_tests,
        recommended_checks, warnings.
    """
    effective_limit = max(1, min(limit, 200))
    warnings_list: list[dict[str, Any]] = []

    # ── Build planned_files ─────────────────────────────────────────────
    planned_files_out: list[dict[str, Any]] = []
    all_indexed_nodes = list(store.all_nodes())
    node_by_file: dict[str, list[GraphNode]] = {}
    for n in all_indexed_nodes:
        fp = n.file_path
        if fp:
            node_by_file.setdefault(fp, []).append(n)

    for f in files:
        normalized = f.replace("\\", "/")
        matching_nodes: list[GraphNode] = []

        if normalized in node_by_file:
            matching_nodes = node_by_file[normalized]
        else:
            # Try suffix match (relative path match)
            for indexed_fp in node_by_file:
                if indexed_fp.endswith(normalized) or indexed_fp.endswith("/" + normalized):
                    matching_nodes.extend(node_by_file[indexed_fp])

        if not matching_nodes:
            planned_files_out.append({
                "file": f,
                "indexed": False,
                "symbols_found": 0,
            })
            warnings_list.append({
                "type": "file_not_indexed",
                "severity": "warning",
                "message": f"File '{f}' is not indexed. Impact analysis may miss this file.",
                "reason_code": "file_not_indexed",
            })
        else:
            unique_files = list({n.file_path for n in matching_nodes if n.file_path})
            for uf in unique_files:
                file_nodes = [n for n in matching_nodes if n.file_path == uf]
                planned_files_out.append({
                    "file": uf,
                    "indexed": True,
                    "symbols_found": len(file_nodes),
                })

    # ── Resolve planned_symbols ─────────────────────────────────────────
    planned_symbols_out: list[dict[str, Any]] = []
    seen_symbol_ids: set[str] = set()

    for sym_name in symbols:
        node, is_ambiguous = _resolve_symbol(store, sym_name)
        if is_ambiguous:
            warnings_list.append({
                "type": "ambiguous_symbol",
                "severity": "warning",
                "message": (
                    f"Symbol '{sym_name}' is ambiguous — "
                    f"multiple candidates found. "
                    f"Use a fully qualified symbol ID (file.py::symbol) "
                    f"to disambiguate."
                ),
                "reason_code": "ambiguous_symbol",
            })
            continue
        if node is None:
            warnings_list.append({
                "type": "symbol_not_found",
                "severity": "warning",
                "message": f"Symbol '{sym_name}' not found in index.",
                "reason_code": "symbol_not_found",
            })
            continue
        if node.id in seen_symbol_ids:
            continue
        seen_symbol_ids.add(node.id)
        if node.type == NodeType.test and files:
            continue
        planned_symbols_out.append({
            "symbol": node.name,
            "symbol_id": node.id,
            "type": node.type.value if isinstance(node.type, NodeType) else str(node.type),
            "file": node.file_path,
            "line_start": node.location.line_start if node.location else None,
            "line_end": node.location.line_end if node.location else None,
            "reason": "Symbol explicitly listed in planned symbols.",
        })

    # From planned files: collect all non-test symbols from indexed files
    for pf in planned_files_out:
        if not pf.get("indexed"):
            continue
        file_path = pf["file"]
        for n in all_indexed_nodes:
            if n.file_path != file_path:
                continue
            if n.id in seen_symbol_ids:
                continue
            if n.type == NodeType.test:
                continue
            seen_symbol_ids.add(n.id)
            planned_symbols_out.append({
                "symbol": n.name,
                "symbol_id": n.id,
                "type": n.type.value if isinstance(n.type, NodeType) else str(n.type),
                "file": n.file_path,
                "line_start": n.location.line_start if n.location else None,
                "line_end": n.location.line_end if n.location else None,
                "reason": "Symbol is defined in a planned edit file.",
            })

    # ── Run impact analysis for each planned symbol ─────────────────────
    all_callers: list[dict[str, Any]] = []
    all_affected_files: dict[str, dict[str, Any]] = {}
    all_affected_tests: list[dict[str, Any]] = []
    caller_ids: set[str] = set()
    test_ids: set[str] = set()
    risk_levels: list[str] = []
    impact_errors: list[dict[str, Any]] = []

    for ps in planned_symbols_out:
        sym_id = ps["symbol_id"]
        try:
            impact_result = graph_impact.analyze_impact(
                store, sym_id, depth=2, min_confidence=0.6,
            )
        except Exception as exc:
            impact_errors.append({
                "symbol_id": sym_id,
                "error": str(exc),
            })
            warnings_list.append({
                "type": "impact_error",
                "severity": "warning",
                "message": f"Impact analysis failed for '{sym_id}': {exc}",
                "reason_code": "impact_error",
            })
            continue

        # Collect risk level
        risk_data = impact_result.get("risk", {})
        rl = risk_data.get("level", "unknown")
        risk_levels.append(rl)

        # Collect callers from confirmed impact
        confirmed = impact_result.get("confirmed_impact", {})
        for s in confirmed.get("symbols", []):
            if s.get("impact_type") == "upstream_caller":
                sid = s.get("symbol_id", "")
                if sid and sid not in caller_ids:
                    caller_ids.add(sid)
                    all_callers.append({
                        "symbol_id": sid,
                        "name": s.get("name", ""),
                        "type": s.get("type", "unknown"),
                        "file_path": s.get("file_path", ""),
                        "distance": s.get("distance", 0),
                        "confidence": s.get("confidence", 1.0),
                        "confidence_level": s.get("confidence_level", "unknown"),
                    })

        # Collect affected files
        for f in confirmed.get("files", []):
            fp = f.get("file_path", "")
            if fp and fp not in all_affected_files:
                all_affected_files[fp] = {
                    "file_path": fp,
                    "layer": _assign_layer(fp),
                    "priority": f.get("priority", "medium"),
                }

        # Collect tests
        if include_tests:
            for t in impact_result.get("related_tests", []):
                tid = t.get("symbol_id", "")
                if tid and tid not in test_ids:
                    test_ids.add(tid)
                    all_affected_tests.append({
                        "symbol_id": tid,
                        "name": t.get("name", ""),
                        "file_path": t.get("file_path", ""),
                        "confidence": t.get("confidence", 1.0),
                        "confidence_level": t.get("confidence_level", "unknown"),
                    })

    # ── Compute aggregate risk_level ────────────────────────────────────
    if not risk_levels:
        agg_risk = "unknown"
        risk_summary = "No symbols were found in the index for the planned files or symbols."
        risk_confidence = "unknown"
    else:
        risk_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "unknown": 0}
        agg_risk = max(risk_levels, key=lambda r: risk_order.get(r, 0))

        num_callers = len(all_callers)
        num_files = len(all_affected_files)
        num_tests = len(all_affected_tests)
        num_planned = len(planned_symbols_out)

        parts: list[str] = []
        if num_planned > 0:
            parts.append(f"Editing {num_planned} symbol(s)")
        if num_callers > 0:
            parts.append(f"may affect {num_callers} caller(s)")
        if num_files > 0:
            parts.append(f"{num_files} file(s)")
        if num_tests > 0:
            parts.append(f"and {num_tests} test(s)")
        if parts:
            risk_summary = ", ".join(parts) + "."
        else:
            risk_summary = "No callers, files, or tests detected for the planned symbols."

        if num_callers > 0 or num_files > 0:
            risk_confidence = "medium"
        else:
            risk_confidence = "low"

        if impact_errors:
            risk_confidence = "low"

    if not planned_symbols_out:
        agg_risk = "unknown"
        risk_summary = "No symbols could be resolved from the planned files or symbols. Impact cannot be assessed."
        risk_confidence = "unknown"

    # ── Build recommended_checks ────────────────────────────────────────
    recommended_checks: list[dict[str, Any]] = []

    for pf in planned_files_out[:2]:
        if pf.get("indexed"):
            recommended_checks.append({
                "type": "read",
                "target": pf["file"],
                "reason": "Read exact source before editing the planned file.",
            })

    affected_test_files: set[str] = set()
    for t in all_affected_tests[:5]:
        tf = t.get("file_path", "")
        if tf and tf not in affected_test_files:
            affected_test_files.add(tf)
            recommended_checks.append({
                "type": "test",
                "target": tf,
                "reason": "Likely covers affected behavior of planned changes.",
            })

    recommended_checks = recommended_checks[:5]

    # ── Return result ───────────────────────────────────────────────────
    return {
        "change_type": change_type,
        "description": description or "",
        "planned_files": planned_files_out,
        "planned_symbols": planned_symbols_out[:effective_limit],
        "impact_summary": {
            "risk_level": agg_risk,
            "confidence": risk_confidence,
            "summary": f"[pre-edit heuristic] {risk_summary}",
        },
        "affected_callers": all_callers[:effective_limit],
        "affected_files": sorted(
            all_affected_files.values(),
            key=lambda x: (0 if x.get("priority") == "high" else 1, x["file_path"]),
        )[:effective_limit],
        "affected_tests": all_affected_tests[:effective_limit] if include_tests else [],
        "recommended_checks": recommended_checks,
        "impact_errors": impact_errors if impact_errors else [],
        "warnings": warnings_list,
    }


def run_test_audit(
    store: GraphStore,
    paths: list[str] | None = None,
    types: list[str] | None = None,
    include_low_confidence: bool = True,
    limit: int = 50,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Core test audit logic — wrap ``compute_coverage_gaps`` for CLI workflow.

    Args:
        store: Loaded GraphStore instance.
        paths: Optional list of path glob patterns to restrict scope.
        types: Optional list of node type strings.
        include_low_confidence: Include low-confidence test links.
        limit: Maximum entries in symbols_without_tests.
        project_root: Project root path string.

    Returns:
        Dict with keys: summary, symbols_without_tests, files_without_tests,
        low_confidence_links, warnings.
    """
    from codegraph.graph.coverage_gaps import compute_coverage_gaps

    effective_limit = max(1, min(limit, 100))

    gaps = compute_coverage_gaps(
        store=store,
        project_root=project_root,
        paths=paths,
        types=types,
        include_low_confidence=include_low_confidence,
        limit=effective_limit,
    )

    return {
        "summary": gaps.get("summary", {}),
        "symbols_without_tests": gaps.get("symbols_without_tests", [])[:effective_limit],
        "files_without_tests": gaps.get("files_without_tests", [])[:effective_limit],
        "low_confidence_links": gaps.get("low_confidence_links", [])[:effective_limit] if include_low_confidence else [],
        "warnings": gaps.get("warnings", []),
    }


def run_explain(
    store: GraphStore,
    symbol: str | None = None,
    file: str | None = None,
    include_snippet: bool = True,
    include_tests: bool = True,
    include_relationships: bool = True,
    max_snippet_lines: int = 40,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Core explain logic — wrap ``explain_symbol`` / ``explain_file`` for CLI workflow.

    Exactly one of ``symbol`` or ``file`` must be provided.

    Args:
        store: Loaded GraphStore instance.
        symbol: Symbol name or ID to explain.
        file: File path relative to project root to explain.
        include_snippet: Include source code snippet.
        include_tests: Include test coverage signal.
        include_relationships: Include top callers/callees.
        max_snippet_lines: Maximum snippet lines.
        project_root: Project root for resolving file paths and reading source.

    Returns:
        Dict with the explanation result.
    """
    from codegraph.graph.explain import explain_symbol, explain_file

    if symbol and file:
        return {
            "ok": False,
            "error": "Provide exactly one of --symbol or --file, not both.",
        }
    if not symbol and not file:
        return {
            "ok": False,
            "error": "Provide exactly one of --symbol or --file.",
        }

    if file:
        result = explain_file(
            store=store,
            file_path=file,
            include_tests=include_tests,
            project_root=project_root,
        )
        result["ok"] = True
        result["target_kind"] = "file"
        return result

    # Resolve symbol
    node, is_ambiguous = _resolve_symbol(store, symbol)
    if is_ambiguous:
        return {
            "ok": False,
            "error": (
                f"Symbol '{symbol}' is ambiguous — multiple candidates found. "
                f"Use a fully qualified symbol ID (file.py::symbol) to disambiguate."
            ),
            "reason_code": "ambiguous_symbol",
        }
    if node is None:
        return {
            "ok": False,
            "error": f"Symbol '{symbol}' not found in index.",
            "reason_code": "symbol_not_found",
        }

    # Read source snippet from disk if requested
    source_snippet: dict[str, Any] | None = None
    if include_snippet and project_root and node.file_path:
        from pathlib import Path
        source_path = Path(project_root) / node.file_path
        if source_path.exists():
            try:
                lines = source_path.read_text(encoding="utf-8").splitlines()
                if node.location:
                    start = max(0, node.location.line_start - 1)
                    end = min(len(lines), start + max_snippet_lines)
                    snippet_lines = lines[start:end]
                    source_snippet = {
                        "included": True,
                        "language_id": node.language_id or "unknown",
                        "line_start": node.location.line_start,
                        "line_end": node.location.line_end,
                        "total_lines": min(len(snippet_lines), max_snippet_lines),
                        "lines": snippet_lines,
                    }
            except (OSError, UnicodeDecodeError):
                source_snippet = {"included": False, "reason": "file_read_error"}

    result = explain_symbol(
        store=store,
        node=node,
        include_snippet=include_snippet,
        include_tests=include_tests,
        include_relationships=include_relationships,
        max_snippet_lines=max_snippet_lines,
        project_root=project_root,
        source_snippet=source_snippet,
    )
    result["ok"] = True
    result["target_kind"] = "symbol"
    return result


def run_find(
    store: GraphStore,
    query: str,
    types: list[str] | None = None,
    paths: list[str] | None = None,
    limit: int = 20,
    include_tests: bool = True,
) -> dict[str, Any]:
    """Core find logic — wrap ``search_symbols`` for CLI workflow.

    Args:
        store: Loaded GraphStore instance.
        query: Search keyword — symbol name, file path fragment, or docstring keyword.
        types: Optional list of node type strings to filter.
        paths: Optional list of path glob patterns to restrict scope.
        limit: Maximum results to return.
        include_tests: Whether to include test symbols.

    Returns:
        Dict with keys: query, results, total.
    """
    import fnmatch
    from codegraph.graph.query import search_symbols

    effective_limit = max(1, min(limit, 100))

    result = search_symbols(
        store=store,
        query=query,
        types=types,
        include_tests=include_tests,
        exclude_external=True,
        min_score=0.2,
        limit=effective_limit,
    )

    items = result.get("results", [])
    total = result.get("total", len(items))

    # Apply path glob filtering (post-query, same as MCP tool)
    if paths:
        def _matches_any_glob(file_path: str) -> bool:
            normalized = file_path.replace("\\", "/")
            return any(fnmatch.fnmatch(normalized, p) for p in paths)

        items = [item for item in items if _matches_any_glob(item.get("file_path", ""))]
        total = len(items)

    return {
        "query": query,
        "results": items[:effective_limit],
        "total": total,
    }
