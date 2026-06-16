"""Harness module for ``workflow.find``."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from codegraph.harness.manifest import manifest_for
from codegraph.harness.module_utils import coerce_bool, coerce_str_list, load_graph_store
from codegraph.mcp_server import (
    _collect_warnings,
    _wrap_source_snippet,
    codegraph_find,
    get_symbol,
)
from codegraph.workflow import run_find
from codegraph.workflow_find_presenter import (
    build_workflow_find_markdown,
    build_workflow_find_result,
)

_MCP_HELPER_LOCK = threading.RLock()


def run_workflow_find(project_root: Path, input_data: dict[str, Any]) -> dict[str, Any]:
    """Run the existing find helpers and normalize harness output."""
    normalized_input = _normalize_input(input_data)
    query = normalized_input["query"]
    if not query:
        raise ValueError("workflow.find requires a non-empty 'query'")

    store, cg_dir = load_graph_store(project_root)
    raw_find = run_find(
        store=store,
        query=query,
        types=normalized_input["types"] or None,
        paths=normalized_input["paths"] or None,
        limit=normalized_input["limit"],
        include_tests=normalized_input["include_tests"],
    )
    data: dict[str, Any] = {}
    warnings: list[dict[str, Any] | str] = []
    if not normalized_input["include_tests"]:
        find_response = _call_mcp_helper(
            project_root,
            codegraph_find,
            query,
            types=",".join(normalized_input["types"]) or None,
            paths=",".join(normalized_input["paths"]) or None,
            limit=min(normalized_input["limit"], 20),
            include_details=normalized_input["include_details"],
            include_snippets=normalized_input["include_snippets"],
            mode="review" if normalized_input["include_snippets"] else "quick",
            response_mode="standard",
        )
        if not find_response.get("ok"):
            error = find_response.get("error", {})
            raise ValueError(str(error.get("message", "workflow.find failed")))
        data = dict(find_response.get("data", {}))
        warnings.extend(list(find_response.get("warnings", [])))
    else:
        warnings.extend(_call_mcp_helper(project_root, _collect_warnings))

    enriched_results = _build_enriched_results(
        project_root=project_root,
        search_results=raw_find.get("results", []),
        find_results=data.get("results", []),
        include_details=normalized_input["include_details"],
        include_snippets=normalized_input["include_snippets"],
    )
    total = int(raw_find.get("total", len(enriched_results)) or 0)
    candidates = _build_candidates(
        search_results=raw_find.get("results", []),
        enriched_results=enriched_results,
        limit=normalized_input["limit"],
        candidates_note=data.get("candidates_note"),
    )
    warnings = _normalize_warnings(warnings)
    reason = _build_reason(query=query, total=total, top_result=enriched_results[:1])
    confidence = _derive_confidence(enriched_results[:1])
    next_required_steps = _build_next_required_steps(total=total, warnings=warnings)
    return build_workflow_find_result(
        input_data=normalized_input,
        results=enriched_results,
        candidates=candidates,
        reason=reason,
        confidence=confidence,
        warnings=warnings,
        total=total,
        next_required_steps=next_required_steps,
    )


class WorkflowFindModule:
    """Run the stable find workflow through the harness runner."""

    manifest = manifest_for("workflow.find")

    def run(self, ctx, input_data: dict[str, Any]) -> dict[str, Any]:
        normalized_input = _normalize_input(input_data, caller="mcp_harness")
        if not normalized_input["query"]:
            raise ValueError("workflow.find requires a non-empty 'query'")

        ctx.log_info("loading graph store for workflow.find")
        ctx.checkpoint(
            "inputs.normalized",
            {
                "query": normalized_input["query"],
                "types": normalized_input["types"],
                "paths": normalized_input["paths"],
                "limit": normalized_input["limit"],
                "include_details": normalized_input["include_details"],
                "include_snippets": normalized_input["include_snippets"],
                "include_tests": normalized_input["include_tests"],
                "project_root": str(ctx.project_root),
            },
        )
        result = run_workflow_find(ctx.project_root, normalized_input)
        ctx.checkpoint(
            "workflow.find.completed",
            {
                "results": len(result.get("results", [])),
                "candidates": len(result.get("candidates", [])),
                "confidence": result.get("confidence", "unknown"),
                "warnings": len(result.get("warnings", [])),
            },
        )
        ctx.artifact_json("report.json", result)
        # MCP mode: only generate heavy markdown when explicitly requested.
        # Otherwise write a lightweight summary to satisfy harness invariants.
        if normalized_input.get("format") == "markdown":
            ctx.artifact_text("report.md", build_workflow_find_markdown(result))
        else:
            ctx.artifact_text("report.md", _lightweight_markdown_summary(result))
        return result


def _normalize_input(
    input_data: dict[str, Any],
    caller: str | None = None,
) -> dict[str, Any]:
    """Normalize workflow.find inputs.

    Args:
        input_data: Raw input dict from the caller.
        caller: ``"mcp_harness"`` when called from MCP harness_run;
                ``None`` for CLI / direct callers.

    MCP harness mode applies compact defaults:
    - ``include_details`` defaults to ``False`` (unless explicitly set)
    - ``format`` defaults to ``"json"`` (unless explicitly set)
    - ``limit`` capped at 5 (all callers)

    CLI callers keep the existing defaults:
    - ``include_details`` defaults to ``True``
    - ``format`` defaults to ``"markdown"``
    """
    is_mcp = caller == "mcp_harness"

    # include_details: MCP defaults to False, CLI defaults to True
    if "include_details" in input_data:
        include_details = coerce_bool(input_data["include_details"], default=True)
    else:
        include_details = False if is_mcp else True

    # format: MCP defaults to "json", CLI defaults to "markdown"
    if "format" in input_data:
        fmt = str(input_data["format"] or "markdown")
    else:
        fmt = "json" if is_mcp else "markdown"

    return {
        "query": str(input_data.get("query", "")).strip(),
        "types": coerce_str_list(input_data.get("types")),
        "paths": coerce_str_list(input_data.get("paths")),
        "limit": max(1, min(int(input_data.get("limit", 5) if input_data.get("limit") is not None else 5), 100)),
        "include_details": include_details,
        "include_snippets": coerce_bool(input_data.get("include_snippets"), default=False),
        "include_tests": coerce_bool(input_data.get("include_tests"), default=True),
        "format": fmt,
    }


def _build_enriched_results(
    *,
    project_root: Path,
    search_results: list[dict[str, Any]],
    find_results: list[dict[str, Any]],
    include_details: bool,
    include_snippets: bool,
) -> list[dict[str, Any]]:
    """Merge search/find outputs and enrich with symbol details/snippets."""
    search_by_id = {
        str(item.get("symbol_id") or item.get("id") or ""): item
        for item in search_results
        if item.get("symbol_id") or item.get("id")
    }
    find_by_id = {
        str(item.get("symbol_id") or ""): item
        for item in find_results
        if item.get("symbol_id")
    }

    ordered_ids: list[str] = []
    for item in find_results:
        symbol_id = str(item.get("symbol_id") or "")
        if symbol_id and symbol_id not in ordered_ids:
            ordered_ids.append(symbol_id)
    for item in search_results:
        symbol_id = str(item.get("symbol_id") or item.get("id") or "")
        if symbol_id and symbol_id not in ordered_ids:
            ordered_ids.append(symbol_id)

    file_freshness = {}
    for item in find_results:
        file_path = item.get("file")
        if not file_path:
            continue
        snippet = item.get("snippet")
        declaration = snippet.get("declaration", {}) if isinstance(snippet, dict) else {}
        freshness = declaration.get("freshness")
        if freshness:
            file_freshness[file_path] = freshness

    enriched: list[dict[str, Any]] = []
    for symbol_id in ordered_ids:
        search_item = search_by_id.get(symbol_id, {})
        find_item = find_by_id.get(symbol_id, {})
        item = {
            "symbol_id": symbol_id,
            "symbol": find_item.get("symbol") or search_item.get("name") or symbol_id,
            "type": find_item.get("type") or search_item.get("type") or "?",
            "file": find_item.get("file") or search_item.get("file_path") or "?",
            "line_start": find_item.get("line_start") or search_item.get("line_start"),
            "line_end": find_item.get("line_end") or search_item.get("line_end"),
            "score": float(
                find_item.get("score", search_item.get("score", 0.0)) or 0.0
            ),
            "match_sources": list(search_item.get("match_sources", []) or []),
            "reason": find_item.get("reason") or _match_reason(search_item),
        }

        if include_details or include_snippets:
            detail_result = _call_mcp_helper(
                project_root,
                get_symbol,
                symbol_id,
                resolve=False,
                include_source=include_snippets,
                source_mode="body",
                max_source_lines=40,
                include_relations=False,
                response_mode="standard",
                include_explanations=False,
            )
            if detail_result.get("ok"):
                symbol_data = detail_result.get("data", {}).get("symbol", {})
                if include_details:
                    item["details"] = _build_details(symbol_data)
                if include_snippets:
                    source_data = detail_result.get("data", {}).get("source", {})
                    item["snippet"] = _build_snippet(
                        source_data=source_data,
                        file_path=item["file"],
                        line_start=item.get("line_start"),
                        line_end=item.get("line_end"),
                        freshness=file_freshness.get(item["file"]),
                    )
            else:
                if include_details:
                    item["details"] = find_item.get("details")
                if include_snippets:
                    item["snippet"] = find_item.get("snippet")
        else:
            item["details"] = None
            item["snippet"] = None

        if "details" not in item:
            item["details"] = find_item.get("details") if include_details else None
        if "snippet" not in item:
            item["snippet"] = find_item.get("snippet") if include_snippets else None
        enriched.append(item)
    return enriched


def _build_details(symbol_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize detail fields from ``get_symbol``."""
    return {
        "signature": symbol_data.get("signature"),
        "doc": symbol_data.get("docstring"),
        "framework": symbol_data.get("framework_id"),
        "tags": list(symbol_data.get("tags", []) or []),
        "qualified_name": symbol_data.get("qualified_name"),
        "module": symbol_data.get("module"),
    }


def _build_snippet(
    *,
    source_data: dict[str, Any],
    file_path: str,
    line_start: Any,
    line_end: Any,
    freshness: Any,
) -> dict[str, Any] | None:
    """Normalize snippet fields from ``get_symbol``."""
    if not source_data.get("included"):
        return None
    wrapped = _wrap_source_snippet(
        source_data,
        file_path,
        {file_path: freshness} if freshness else None,
    )
    declaration = dict(wrapped.get("declaration", {}))
    if freshness and "freshness" not in declaration:
        declaration["freshness"] = freshness
    return {
        "file": file_path,
        "snippet": wrapped.get("content"),
        "line_start": source_data.get("source_line_start", line_start),
        "line_end": source_data.get("source_line_end", line_end),
        "truncated": bool(wrapped.get("truncated", False)),
        "declaration": declaration,
    }


def _build_candidates(
    *,
    search_results: list[dict[str, Any]],
    enriched_results: list[dict[str, Any]],
    limit: int,
    candidates_note: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build candidate alternatives beyond the selected results."""
    explicit_candidates = candidates_note.get("other_candidates", []) if isinstance(
        candidates_note, dict
    ) else []
    if explicit_candidates:
        return [
            {
                "symbol_id": item.get("symbol_id"),
                "symbol": item.get("symbol") or item.get("name"),
                "type": item.get("type"),
                "file": item.get("file") or item.get("file_path"),
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
                "score": item.get("score"),
                "match_sources": list(item.get("match_sources", []) or []),
            }
            for item in explicit_candidates
        ]

    selected_ids = {item.get("symbol_id") for item in enriched_results}
    candidates: list[dict[str, Any]] = []
    for item in search_results:
        symbol_id = item.get("symbol_id") or item.get("id")
        if symbol_id in selected_ids:
            continue
        candidates.append(
            {
                "symbol_id": symbol_id,
                "symbol": item.get("name"),
                "type": item.get("type"),
                "file": item.get("file_path"),
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
                "score": item.get("score"),
                "match_sources": list(item.get("match_sources", []) or []),
            }
        )
        if len(candidates) >= max(5, limit):
            break
    return candidates


def _build_reason(
    *,
    query: str,
    total: int,
    top_result: list[dict[str, Any]],
) -> str:
    """Build the top-level workflow.find reason string."""
    if total <= 0:
        return (
            f"No indexed symbol matched `{query}` with the current filters. "
            "Broaden the query or remove type/path filters before escalating to manual search."
        )
    best = top_result[0] if top_result else {}
    match_sources = best.get("match_sources", []) or []
    if match_sources:
        return (
            f"Found {total} indexed match(es) for `{query}`. "
            f"Top result matched via {', '.join(match_sources)}."
        )
    return f"Found {total} indexed match(es) for `{query}`."


def _derive_confidence(top_result: list[dict[str, Any]]) -> str:
    """Derive a coarse confidence label from the top result score."""
    if not top_result:
        return "low"
    score = float(top_result[0].get("score", 0.0) or 0.0)
    if score >= 0.95:
        return "high"
    if score >= 0.7:
        return "medium"
    return "low"


def _build_next_required_steps(
    *,
    total: int,
    warnings: list[dict[str, Any]],
) -> list[str]:
    """Build follow-through steps for report consumers."""
    if total > 0:
        return [
            "If you plan to edit this symbol, run workflow.impact.",
            "If you need relationships, run workflow.explain or neighbors.",
        ]
    steps = [
        "Broaden the query or remove type/path filters, then rerun workflow.find.",
        "If the symbol should exist, verify index freshness and rerun codegraph init --incremental if needed.",
    ]
    if warnings:
        steps.append("Review warnings before trusting an empty result set.")
    return steps


def _normalize_warnings(warnings: list[dict[str, Any] | str]) -> list[dict[str, Any]]:
    """Deduplicate warning entries while preserving order."""
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for warning in warnings:
        if isinstance(warning, dict):
            entry = dict(warning)
        else:
            entry = {"message": str(warning)}
        key = (str(entry.get("type", "")), str(entry.get("message", "")))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(entry)
    return normalized


def _match_reason(search_item: dict[str, Any]) -> str:
    """Build a fallback per-result reason from search helper data."""
    match_sources = list(search_item.get("match_sources", []) or [])
    if match_sources:
        return f"Matched via {', '.join(match_sources)}."
    return "Matched by indexed symbol search."


def _lightweight_markdown_summary(result: dict[str, Any]) -> str:
    """Generate a compact markdown summary for MCP harness mode.

    Unlike ``build_workflow_find_markdown``, this does NOT expand
    per-result details, snippets, or heavy enrichment content.
    It satisfies the harness invariant that ``report.md`` must exist
    without the ~800ms cost of full markdown generation.
    """
    query = result.get("query", "?")
    total = result.get("total", 0)
    confidence = result.get("confidence", "unknown")
    results = result.get("results", [])
    candidates = result.get("candidates", [])
    warnings = result.get("warnings", [])

    lines = [
        f"# workflow.find: {query}",
        "",
        f"- **Results:** {len(results)}",
        f"- **Candidates:** {len(candidates)}",
        f"- **Total matches:** {total}",
        f"- **Confidence:** {confidence}",
        "",
    ]

    if results:
        lines.append("## Top Results")
        lines.append("")
        for r in results[:5]:
            symbol_id = r.get("symbol_id", "?")
            symbol = r.get("symbol", "?")
            file_path = r.get("file", "?")
            lines.append(f"- `{symbol}` ({r.get('type', '?')}) — `{symbol_id}`")
            lines.append(f"  File: {file_path}")
        lines.append("")

    if candidates:
        lines.append("## Other Candidates")
        lines.append("")
        for c in candidates[:5]:
            lines.append(f"- `{c.get('symbol', '?')}` — `{c.get('symbol_id', '?')}`")
        lines.append("")

    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in warnings:
            if isinstance(w, dict):
                lines.append(f"- {w.get('message', str(w))}")
            else:
                lines.append(f"- {w}")
        lines.append("")

    lines.append("> **Note:** This is a lightweight summary generated in MCP "
                 "harness mode. Use `format=markdown` or CLI `codegraph workflow "
                 "find` for a full report with details and snippets.")
    return "\n".join(lines)


def _call_mcp_helper(project_root: Path, helper, *args: Any, **kwargs: Any) -> Any:
    """Call an MCP helper against a specific project root."""
    from codegraph import mcp_server as mcp_mod

    # MCP helpers rely on module-level cache and env state; serialize access so
    # one workflow.find run cannot cross-contaminate another project's store.
    with _MCP_HELPER_LOCK:
        previous_cwd = Path.cwd()
        previous_env = os.environ.get("CODEGRAPH_PROJECT_ROOT")
        previous_state = {
            "_store": mcp_mod._store,
            "_cg_dir": mcp_mod._cg_dir,
            "_project_root": mcp_mod._project_root,
            "_resolution_method": mcp_mod._resolution_method,
            "_resolved_cwd": mcp_mod._resolved_cwd,
        }
        os.environ["CODEGRAPH_PROJECT_ROOT"] = str(project_root)
        os.chdir(project_root)
        mcp_mod._store = None
        mcp_mod._cg_dir = None
        mcp_mod._project_root = None
        mcp_mod._resolution_method = "unknown"
        mcp_mod._resolved_cwd = None
        try:
            return helper(*args, **kwargs)
        finally:
            os.chdir(previous_cwd)
            if previous_env is None:
                os.environ.pop("CODEGRAPH_PROJECT_ROOT", None)
            else:
                os.environ["CODEGRAPH_PROJECT_ROOT"] = previous_env
            mcp_mod._store = previous_state["_store"]
            mcp_mod._cg_dir = previous_state["_cg_dir"]
            mcp_mod._project_root = previous_state["_project_root"]
            mcp_mod._resolution_method = previous_state["_resolution_method"]
            mcp_mod._resolved_cwd = previous_state["_resolved_cwd"]
