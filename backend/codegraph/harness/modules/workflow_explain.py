"""Harness module for ``workflow.explain``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.graph.models import EdgeType, NodeType
from codegraph.harness.manifest import manifest_for
from codegraph.harness.module_utils import coerce_bool, load_graph_store
from codegraph.workflow import run_explain
from codegraph.workflow_explain_presenter import (
    build_workflow_explain_markdown,
    build_workflow_explain_result,
)


def run_workflow_explain(project_root: Path, input_data: dict[str, Any]) -> dict[str, Any]:
    """Run the existing explain helpers and normalize harness output."""
    symbol = _normalize_optional_string(input_data.get("symbol"))
    file_path = _normalize_optional_string(input_data.get("file"))
    include_neighbors = coerce_bool(input_data.get("include_neighbors"), default=True)
    include_snippets = coerce_bool(input_data.get("include_snippets"), default=True)
    include_tests = coerce_bool(input_data.get("include_tests"), default=True)
    format_name = str(input_data.get("format", "markdown") or "markdown")
    max_snippet_lines = int(input_data.get("max_snippet_lines", 40))

    if bool(symbol) == bool(file_path):
        raise ValueError("workflow.explain requires exactly one of 'symbol' or 'file'")

    store, _cg_dir = load_graph_store(project_root)
    raw_result = run_explain(
        store=store,
        symbol=symbol,
        file=file_path,
        include_snippet=include_snippets,
        include_tests=include_tests,
        include_relationships=include_neighbors,
        max_snippet_lines=max_snippet_lines,
        project_root=str(project_root),
    )
    if not raw_result.get("ok"):
        raise ValueError(str(raw_result.get("error", "workflow.explain failed")))

    relationships = _derive_relationships(
        store=store,
        explain_result=raw_result,
        include_relationships=include_neighbors,
    )
    return build_workflow_explain_result(
        input_data={
            "symbol": symbol,
            "file": file_path,
            "include_neighbors": include_neighbors,
            "include_snippets": include_snippets,
            "include_tests": include_tests,
            "format": format_name,
        },
        explain_result=raw_result,
        relationships=relationships,
    )


class WorkflowExplainModule:
    """Run the stable explain workflow through the harness runner."""

    manifest = manifest_for("workflow.explain")

    def run(self, ctx, input_data: dict[str, Any]) -> dict[str, Any]:
        normalized_input = {
            "symbol": _normalize_optional_string(input_data.get("symbol")),
            "file": _normalize_optional_string(input_data.get("file")),
            "include_neighbors": coerce_bool(
                input_data.get("include_neighbors"),
                default=True,
            ),
            "include_snippets": coerce_bool(
                input_data.get("include_snippets"),
                default=True,
            ),
            "include_tests": coerce_bool(
                input_data.get("include_tests"),
                default=True,
            ),
            "format": str(input_data.get("format", "markdown") or "markdown"),
            "max_snippet_lines": int(input_data.get("max_snippet_lines", 40)),
        }
        ctx.log_info("loading graph store for workflow.explain")
        ctx.checkpoint(
            "inputs.normalized",
            {
                "symbol": normalized_input["symbol"],
                "file": normalized_input["file"],
                "include_neighbors": normalized_input["include_neighbors"],
                "include_snippets": normalized_input["include_snippets"],
                "include_tests": normalized_input["include_tests"],
                "project_root": str(ctx.project_root),
            },
        )
        result = run_workflow_explain(ctx.project_root, normalized_input)
        ctx.checkpoint(
            "workflow.explain.completed",
            {
                "target_kind": result.get("target", {}).get("kind", "unknown"),
                "confidence": result.get("confidence", "unknown"),
                "evidence": len(result.get("evidence", [])),
                "warnings": len(result.get("warnings", [])),
            },
        )
        ctx.artifact_json("report.json", result)
        ctx.artifact_text("report.md", build_workflow_explain_markdown(result))
        return result


def _normalize_optional_string(value: Any) -> str | None:
    """Normalize optional string inputs."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _derive_relationships(
    *,
    store,
    explain_result: dict[str, Any],
    include_relationships: bool,
) -> dict[str, Any]:
    """Reuse existing relationships helpers for both symbol and file explain."""
    if not include_relationships:
        return _empty_relationships()

    target = explain_result.get("target", {})
    if target.get("kind") == "symbol":
        return dict(explain_result.get("relationships", _empty_relationships()))

    primary_symbols = list(explain_result.get("primary_symbols", []))
    if not primary_symbols:
        return _empty_relationships()

    callers: dict[str, dict[str, Any]] = {}
    callees: dict[str, dict[str, Any]] = {}
    for item in primary_symbols:
        symbol_id = item.get("symbol_id")
        if not symbol_id:
            continue
        _merge_full_relationships_for_symbol(
            store=store,
            symbol_id=symbol_id,
            callers=callers,
            callees=callees,
        )

    return {
        "callers_count": len(callers),
        "callees_count": len(callees),
        "top_callers": _sort_relationship_items(callers.values()),
        "top_callees": _sort_relationship_items(callees.values()),
    }


def _merge_relationship_item(
    bucket: dict[str, dict[str, Any]],
    item: dict[str, Any],
) -> None:
    """Deduplicate relationship rows by symbol id while keeping best confidence."""
    symbol_id = item.get("symbol_id")
    if not symbol_id:
        return
    current = bucket.get(symbol_id)
    if current is None or item.get("confidence", 0.0) > current.get("confidence", 0.0):
        bucket[symbol_id] = dict(item)


def _merge_full_relationships_for_symbol(
    *,
    store,
    symbol_id: str,
    callers: dict[str, dict[str, Any]],
    callees: dict[str, dict[str, Any]],
) -> None:
    """Collect the full caller/callee sets for one symbol before top-k truncation."""
    # Preserve the symbol-level helper semantics while avoiding its top-5 truncation.
    for edge in store.get_incoming_edges(symbol_id):
        if edge.type != EdgeType.calls:
            continue
        caller_node = store.get_node(edge.source)
        if caller_node is None or caller_node.type == NodeType.test:
            continue
        _merge_relationship_item(
            callers,
            {
                "symbol_id": edge.source,
                "name": caller_node.name,
                "type": (
                    caller_node.type.value
                    if isinstance(caller_node.type, NodeType)
                    else str(caller_node.type)
                ),
                "file_path": caller_node.file_path,
                "confidence": edge.confidence,
            },
        )

    for edge in store.get_outgoing_edges(symbol_id):
        if edge.type != EdgeType.calls:
            continue
        callee_node = store.get_node(edge.target)
        if callee_node is None:
            continue
        _merge_relationship_item(
            callees,
            {
                "symbol_id": edge.target,
                "name": callee_node.name,
                "type": (
                    callee_node.type.value
                    if isinstance(callee_node.type, NodeType)
                    else str(callee_node.type)
                ),
                "file_path": callee_node.file_path,
                "confidence": edge.confidence,
            },
        )


def _sort_relationship_items(items) -> list[dict[str, Any]]:
    """Sort and cap relationship rows consistently."""
    return sorted(
        (dict(item) for item in items),
        key=lambda item: (-float(item.get("confidence", 0.0) or 0.0), str(item.get("name", ""))),
    )[:5]


def _empty_relationships() -> dict[str, Any]:
    """Return an empty relationships block."""
    return {
        "callers_count": 0,
        "callees_count": 0,
        "top_callers": [],
        "top_callees": [],
    }
