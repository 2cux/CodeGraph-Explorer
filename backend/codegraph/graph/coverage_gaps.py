"""Coverage gaps computation — aggregate test coverage gap analysis.

Computes which production symbols and files lack confident ``tested_by``
coverage signals. Designed as a single-call aggregation tool for agents
that need to audit test coverage without querying each symbol individually.

This is a heuristic graph signal, NOT runtime line coverage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.graph.models import EdgeType, GraphNode, NodeType
from codegraph.graph.store import GraphStore
from codegraph.graph.test_coverage import (
    is_test_file_path,
    TESTED_BY_HIGH_CONFIDENCE_THRESHOLD,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Production symbol types — these are the types we consider "production code"
# ═══════════════════════════════════════════════════════════════════════════════

_PRODUCTION_NODE_TYPES: set[NodeType] = {
    NodeType.function,
    NodeType.method,
    NodeType.class_,
    NodeType.module,
    NodeType.route,
    NodeType.controller,
    NodeType.service,
    NodeType.component,
}

# Default limit for symbols_without_tests
_DEFAULT_SYMBOL_LIMIT = 50

# Default limit for files_without_tests
_DEFAULT_FILE_LIMIT = 20

# Default limit for low_confidence_links
_DEFAULT_LINK_LIMIT = 20


def compute_coverage_gaps(
    store: GraphStore,
    project_root: str | Path | None = None,
    paths: list[str] | None = None,
    types: list[str] | None = None,
    include_low_confidence: bool = True,
    limit: int = _DEFAULT_SYMBOL_LIMIT,
) -> dict[str, Any]:
    """Compute structured test coverage gaps across the entire codebase.

    Args:
        store: The in-memory graph store.
        project_root: Project root for path resolution (not used directly,
                      but passed through for future filesystem checks).
        paths: Optional list of path glob patterns to restrict scope.
        types: Optional list of node type strings to restrict symbol types.
               Defaults to production types: function, method, class, route,
               controller, service, component, module.
        include_low_confidence: If true, include low_confidence_links.
        limit: Maximum entries in ``symbols_without_tests``.

    Returns:
        A structured dict with ``summary``, ``symbols_without_tests``,
        ``files_without_tests``, ``low_confidence_links``, ``warnings``,
        and ``next_recommended_tools``.
    """
    import fnmatch

    # ── Determine active production types ─────────────────────────────────
    if types:
        active_types: set[NodeType] = set()
        for t in types:
            try:
                active_types.add(NodeType(t))
            except ValueError:
                pass  # skip unrecognized types silently
        if not active_types:
            active_types = _PRODUCTION_NODE_TYPES
    else:
        active_types = _PRODUCTION_NODE_TYPES

    # ── Helper: path glob matching ───────────────────────────────────────
    def _matches_path_glob(file_path: str, pattern: str) -> bool:
        normalized = file_path.replace("\\", "/")
        return fnmatch.fnmatch(normalized, pattern)

    def _matches_any_glob(file_path: str, patterns: list[str]) -> bool:
        if not patterns:
            return True  # no filter = match all
        return any(_matches_path_glob(file_path, p) for p in patterns)

    # ── Collect all nodes ─────────────────────────────────────────────────
    all_nodes = store.all_nodes()

    # ── Filter to production symbols ──────────────────────────────────────
    prod_nodes: list[GraphNode] = []
    for n in all_nodes:
        # Must be a production type
        if n.type not in active_types:
            continue
        # Must not be in a test file
        if is_test_file_path(n.file_path):
            continue
        # Must match path glob filter (if provided)
        if not _matches_any_glob(n.file_path, paths or []):
            continue
        prod_nodes.append(n)

    # ── Check tested_by edges for each production symbol ──────────────────
    symbols_high: list[dict[str, Any]] = []      # has high-confidence tests
    symbols_low: list[dict[str, Any]] = []       # has only low-confidence tests
    symbols_unknown: list[dict[str, Any]] = []   # has tested_by but conf <= 0 or missing
    symbols_none: list[dict[str, Any]] = []      # no tested_by edge at all
    low_confidence_links: list[dict[str, Any]] = []

    for node in prod_nodes:
        # Find tested_by edges where this production symbol is the source
        # (tested_by edges go production → test, per codebase convention)
        tested_by_edges = [
            e for e in store.get_outgoing_edges(node.id)
            if e.type == EdgeType.tested_by
        ]

        if not tested_by_edges:
            symbols_none.append(_node_to_gap_entry(node, "No tested_by edge found for this production symbol."))
            continue

        has_high = False
        has_low = False
        has_unknown = False

        for edge in tested_by_edges:
            conf = edge.confidence
            # Get test node info (target is the test symbol)
            test_node = store.get_node(edge.target)
            test_info = _node_to_test_info(test_node, edge.target)

            if conf <= 0:
                has_unknown = True
                if include_low_confidence:
                    low_confidence_links.append({
                        "production_symbol": node.name,
                        "production_symbol_id": node.id,
                        "test_symbol": test_info.get("name", edge.target),
                        "test_symbol_id": edge.target,
                        "confidence": round(conf, 4),
                        "confidence_level": "unknown",
                        "reason": "Confidence is 0 or unset for this tested_by edge.",
                    })
            elif conf >= TESTED_BY_HIGH_CONFIDENCE_THRESHOLD:
                has_high = True
            else:
                has_low = True
                if include_low_confidence:
                    low_confidence_links.append({
                        "production_symbol": node.name,
                        "production_symbol_id": node.id,
                        "test_symbol": test_info.get("name", edge.target),
                        "test_symbol_id": edge.target,
                        "confidence": round(conf, 4),
                        "confidence_level": "low",
                        "reason": "Confidence below high-confidence threshold.",
                    })

        if has_high:
            symbols_high.append(_node_to_gap_entry(node, ""))
        elif has_low and not has_high:
            symbols_low.append(_node_to_gap_entry(
                node,
                "Only low-confidence tested_by edges found for this production symbol."
            ))
        elif has_unknown and not has_high and not has_low:
            symbols_unknown.append(_node_to_gap_entry(
                node,
                "tested_by edge exists but confidence is unknown (0 or unset)."
            ))

    # ── Aggregate per-file stats ─────────────────────────────────────────
    file_stats: dict[str, dict[str, Any]] = {}
    for node in prod_nodes:
        fp = node.file_path
        if fp not in file_stats:
            file_stats[fp] = {
                "file": fp,
                "production_symbols": 0,
                "symbols_with_high_confidence_test": 0,
                "symbols_with_low_confidence_test": 0,
                "symbols_with_unknown_confidence_test": 0,
                "symbols_without_test_signal": 0,
            }
        file_stats[fp]["production_symbols"] += 1

    for entry in symbols_high:
        fp = _entry_file(entry)
        if fp and fp in file_stats:
            file_stats[fp]["symbols_with_high_confidence_test"] += 1
    for entry in symbols_low:
        fp = _entry_file(entry)
        if fp and fp in file_stats:
            file_stats[fp]["symbols_with_low_confidence_test"] += 1
    for entry in symbols_unknown:
        fp = _entry_file(entry)
        if fp and fp in file_stats:
            file_stats[fp]["symbols_with_unknown_confidence_test"] += 1
    for entry in symbols_none:
        fp = _entry_file(entry)
        if fp and fp in file_stats:
            file_stats[fp]["symbols_without_test_signal"] += 1

    # ── Files without test signal ─────────────────────────────────────────
    files_without_tests: list[dict[str, Any]] = []
    for fs in file_stats.values():
        total_prod = fs["production_symbols"]
        covered = (
            fs["symbols_with_high_confidence_test"]
            + fs["symbols_with_low_confidence_test"]
            + fs["symbols_with_unknown_confidence_test"]
        )
        uncovered = fs["symbols_without_test_signal"]
        if uncovered > 0 or covered == 0:
            reason_parts: list[str] = []
            if uncovered > 0:
                reason_parts.append(
                    f"{uncovered}/{total_prod} production symbols have no tested_by signal."
                )
            if covered == 0 and total_prod > 0:
                reason_parts.append("No production symbols in this file have any tested_by coverage.")
            files_without_tests.append({
                "file": fs["file"],
                "production_symbols": total_prod,
                "symbols_with_high_confidence_test": fs["symbols_with_high_confidence_test"],
                "symbols_with_low_confidence_test": fs["symbols_with_low_confidence_test"],
                "symbols_with_unknown_confidence_test": fs["symbols_with_unknown_confidence_test"],
                "symbols_without_test_signal": uncovered,
                "reason": " ".join(reason_parts),
            })

    # Sort files: most uncovered first
    files_without_tests.sort(key=lambda f: -f["symbols_without_test_signal"])

    # ── Summary ───────────────────────────────────────────────────────────
    total_prod = len(prod_nodes)
    high_count = len(symbols_high)
    low_count = len(symbols_low)
    unknown_count = len(symbols_unknown)
    none_count = len(symbols_none)
    total_files = len(file_stats)
    files_with_gaps = len(files_without_tests)

    # Determine summary confidence
    if total_prod == 0:
        summary_confidence = "unknown"
    elif high_count >= total_prod * 0.5:
        summary_confidence = "high"
    elif high_count > 0 or (low_count > 0 and high_count + low_count >= total_prod * 0.3):
        summary_confidence = "medium"
    elif low_count > 0 or unknown_count > 0:
        summary_confidence = "low"
    else:
        summary_confidence = "unknown"

    # Build summary message
    message_parts: list[str] = []
    if none_count > 0:
        message_parts.append(
            f"{none_count} production symbols have no confident tested_by "
            f"coverage signal."
        )
    if low_count > 0:
        message_parts.append(
            f"{low_count} symbols have only low-confidence test links."
        )
    if unknown_count > 0:
        message_parts.append(
            f"{unknown_count} symbols have unknown-confidence test links."
        )
    if not message_parts:
        message_parts.append(
            "All production symbols have high-confidence tested_by coverage."
        )
    message_parts.append(
        "This is a CodeGraph heuristic signal, not line coverage."
    )
    message = " ".join(message_parts)

    # ── Warnings ──────────────────────────────────────────────────────────
    warn_list: list[str] = []
    if total_prod == 0:
        warn_list.append(
            "No production symbols found in the index. "
            "The index may be empty or not yet built."
        )
    else:
        coverage_pct = (high_count + low_count + unknown_count) / total_prod * 100 if total_prod > 0 else 0
        if coverage_pct < 10:
            warn_list.append(
                f"Only {coverage_pct:.0f}% of production symbols have any "
                f"tested_by signal. The index may not have test relationships "
                f"linked. Run codegraph init --force to rebuild."
            )
    warn_list.append(
        "Coverage gaps are based on CodeGraph tested_by edges, "
        "not runtime line coverage."
    )

    # ── next_recommended_tools ────────────────────────────────────────────
    next_tools: list[dict[str, Any]] = []
    if none_count > 0 or low_count > 0:
        next_tools.append({
            "tool": "codegraph_get_neighbors",
            "reason": (
                "Inspect tested_by relationships around a specific "
                "uncovered symbol before reading test files."
            ),
        })
    if none_count > 0:
        next_tools.append({
            "tool": "codegraph_get_impact",
            "reason": (
                "Check impact before adding or changing tests around "
                "shared production code."
            ),
        })

    # ── Build result ──────────────────────────────────────────────────────
    return {
        "ok": True,
        "tool": "codegraph_coverage_gaps",
        "summary": {
            "production_symbols_checked": total_prod,
            "symbols_with_high_confidence_tests": high_count,
            "symbols_with_low_confidence_tests": low_count,
            "symbols_with_unknown_confidence_tests": unknown_count,
            "symbols_without_test_signal": none_count,
            "production_files_checked": total_files,
            "files_without_test_signal": files_with_gaps,
            "confidence": summary_confidence,
            "message": message,
        },
        "symbols_without_tests": symbols_none[:limit],
        "files_without_tests": files_without_tests[:_DEFAULT_FILE_LIMIT],
        "low_confidence_links": low_confidence_links[:_DEFAULT_LINK_LIMIT] if include_low_confidence else [],
        "warnings": warn_list,
        "next_recommended_tools": next_tools,
    }


def _node_to_gap_entry(node: GraphNode, reason: str) -> dict[str, Any]:
    """Serialize a GraphNode to a coverage gap entry with evidence (Req 3.1)."""
    # Build evidence items explaining WHY this symbol was classified as a gap
    evidence: list[dict[str, Any]] = []
    if reason:
        evidence.append({
            "type": "symbol_metadata",
            "symbol": node.name,
            "symbol_id": node.id,
            "file": node.file_path,
            "line": node.location.line_start if node.location else None,
            "confidence": "heuristic",
            "reason": reason,
        })
    evidence.append({
        "type": "edge",
        "symbol": node.name,
        "symbol_id": node.id,
        "file": node.file_path,
        "line": node.location.line_start if node.location else None,
        "confidence": "heuristic",
        "reason": "No confident tested_by edge found — this is a CodeGraph heuristic signal, not runtime line coverage.",
        "provenance": "heuristic",
    })

    result: dict[str, Any] = {
        "symbol": node.name,
        "symbol_id": node.id,
        "type": node.type.value if isinstance(node.type, NodeType) else str(node.type),
        "file": node.file_path,
        "line_start": node.location.line_start if node.location else None,
        "line_end": node.location.line_end if node.location else None,
        "reason": reason,
        "evidence": evidence,
        "suggested_next_tool": "codegraph_get_neighbors" if reason else "",
    }
    # Include enrichment hints when available
    if getattr(node, "enrichment_status", "") == "analyzed":
        if getattr(node, "test_relevance", ""):
            result["enrichment_test_suggestion"] = node.test_relevance
        if getattr(node, "edge_cases", []):
            result["enrichment_risk"] = "Has documented edge cases — higher test priority"
            result["enrichment_edge_cases"] = node.edge_cases
    return result


def _node_to_test_info(test_node: GraphNode | None, fallback_id: str) -> dict[str, str]:
    """Get minimal info about a test node."""
    if test_node:
        return {
            "name": test_node.name,
            "file": test_node.file_path,
        }
    return {
        "name": fallback_id.split("::")[-1] if "::" in fallback_id else fallback_id,
        "file": "",
    }


def _entry_file(entry: dict[str, Any]) -> str:
    """Extract file path from a gap entry dict."""
    return entry.get("file", "")
