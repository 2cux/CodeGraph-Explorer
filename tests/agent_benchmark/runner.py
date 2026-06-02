"""Benchmark runner — executes baseline and codegraph modes for all test cases.

Usage:
    python -m tests.agent_benchmark.runner --mode baseline
    python -m tests.agent_benchmark.runner --mode codegraph
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from codegraph.graph.models import CodeGraph
from codegraph.graph.store import GraphStore
from codegraph.graph import query as graph_query
from codegraph.graph import impact as graph_impact

# Ensure backend is importable
_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "backend"))

_CASES_DIR = Path(__file__).resolve().parent / "cases"
_RESULTS_DIR = Path(__file__).resolve().parent / "results"
_FIXTURES_BASE = Path(__file__).resolve().parent / "fixtures"


def load_test_cases() -> list[dict[str, Any]]:
    """Load all test case JSON files from the cases directory."""
    all_tasks: list[dict[str, Any]] = []
    for case_file in sorted(_CASES_DIR.glob("*.json")):
        case_data = json.loads(case_file.read_text(encoding="utf-8"))
        project_name = case_data["project"]
        root_path = _FIXTURES_BASE / project_name
        for task in case_data["tasks"]:
            task["project"] = project_name
            task["root_path"] = str(root_path)
        all_tasks.extend(case_data["tasks"])
    return all_tasks


def load_store_for_project(root_path: str) -> GraphStore:
    """Load the graph store for a project's .codegraph directory."""
    cg_dir = Path(root_path) / ".codegraph"
    graph_path = cg_dir / "graph.json"
    if not graph_path.exists():
        raise FileNotFoundError(
            f"No index found at {graph_path}. Run 'codegraph init {root_path}' first."
        )
    graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    store = GraphStore()
    store.load_from_graph(graph)
    return store


def get_project_file_paths(root_path: str) -> list[str]:
    """Get all Python file paths relative to the project root."""
    root = Path(root_path)
    files: list[str] = []
    for py_file in root.rglob("*.py"):
        rel = py_file.relative_to(root).as_posix()
        if not any(p in rel for p in ("__pycache__", ".codegraph")):
            files.append(rel)
    return sorted(files)


# ── Baseline Simulation ────────────────────────────────────────────────────


def run_baseline_locate(task: dict[str, Any]) -> dict[str, Any]:
    """Simulate a baseline agent finding code via grep + read."""
    t0 = time.time()
    tool_calls: dict[str, int] = {"total": 0, "grep": 0, "glob": 0, "read": 0}
    found_files: set[str] = set()
    extra_files: set[str] = set()
    tokens: int = 0

    task_text = task["task"]
    root_path = task["root_path"]
    keywords = _extract_keywords(task_text)

    # Grep for primary keywords
    for kw in keywords[:3]:
        tool_calls["grep"] += 1
        tool_calls["total"] += 1
        tokens += 80
        result_files = _grep_sim(root_path, kw)
        for f in result_files:
            found_files.add(f)
        tokens += 15 * len(result_files)

    # Read files that matched
    for f in list(found_files)[:4]:
        tool_calls["read"] += 1
        tool_calls["total"] += 1
        tokens += _estimate_file_tokens(root_path, f)
    for f in list(found_files)[4:]:
        extra_files.add(f)

    elapsed = time.time() - t0
    return {
        "found_files": sorted(found_files),
        "extra_files_read": sorted(extra_files),
        "tool_calls": tool_calls,
        "files_read_count": min(len(found_files), 4),
        "estimated_tokens": tokens,
        "elapsed_seconds": round(elapsed, 3),
        "found_expected_symbols": [],
        "found_expected_files": sorted(found_files),
        "missing_expected": [],
        "notes": [],
    }


def run_baseline_impact(task: dict[str, Any]) -> dict[str, Any]:
    """Simulate a baseline agent analyzing impact via grep for imports/callers."""
    t0 = time.time()
    tool_calls: dict[str, int] = {"total": 0, "grep": 0, "glob": 0, "read": 0}
    found_files: set[str] = set()
    tokens: int = 0

    task_text = task["task"]
    root_path = task["root_path"]
    keywords = _extract_keywords(task_text)

    # Grep for the target function name
    tool_calls["grep"] += 1
    tool_calls["total"] += 1
    tokens += 80
    main_file_match = _grep_sim(root_path, keywords[0] if keywords else "login")
    found_files.update(main_file_match)
    tokens += 15 * len(main_file_match)

    # Read matching files to find imports
    for f in list(found_files)[:3]:
        tool_calls["read"] += 1
        tool_calls["total"] += 1
        tokens += _estimate_file_tokens(root_path, f)

    # Grep for importers of the file
    for kw in keywords[:2]:
        tool_calls["grep"] += 1
        tool_calls["total"] += 1
        tokens += 80
        importer_files = _grep_sim(root_path, kw)
        found_files.update(importer_files)
        tokens += 15 * len(importer_files)

    # Find test files
    tool_calls["glob"] += 1
    tool_calls["total"] += 1
    tokens += 50
    test_files = _glob_sim(root_path, "**/test_*.py")
    found_files.update(test_files)
    tokens += 15 * len(test_files)

    # Read one test file
    if test_files:
        tool_calls["read"] += 1
        tool_calls["total"] += 1
        tokens += _estimate_file_tokens(root_path, test_files[0])

    elapsed = time.time() - t0
    files_actually_read = min(len(found_files), 4)
    extra_files = sorted(found_files)[files_actually_read:]

    return {
        "found_files": sorted(found_files),
        "extra_files_read": extra_files,
        "tool_calls": tool_calls,
        "files_read_count": files_actually_read,
        "estimated_tokens": tokens,
        "elapsed_seconds": round(elapsed, 3),
        "found_expected_symbols": [],
        "found_expected_files": sorted(found_files),
        "missing_expected": [],
        "notes": [],
    }


def run_baseline_modification_prep(task: dict[str, Any]) -> dict[str, Any]:
    """Simulate a baseline agent preparing context for a modification."""
    t0 = time.time()
    tool_calls: dict[str, int] = {"total": 0, "grep": 0, "glob": 0, "read": 0}
    found_files: set[str] = set()
    tokens: int = 0

    task_text = task["task"]
    root_path = task["root_path"]
    keywords = _extract_keywords(task_text)

    # Grep for multiple keywords
    for kw in keywords[:4]:
        tool_calls["grep"] += 1
        tool_calls["total"] += 1
        tokens += 80
        result_files = _grep_sim(root_path, kw)
        found_files.update(result_files)
        tokens += 15 * len(result_files)

    # Read main matching files
    for f in list(found_files)[:5]:
        tool_calls["read"] += 1
        tool_calls["total"] += 1
        tokens += _estimate_file_tokens(root_path, f)

    # Also check for config and test files
    tool_calls["glob"] += 2
    tool_calls["total"] += 2
    tokens += 100
    config_files = _glob_sim(root_path, "**/config/**/*.py") or _glob_sim(root_path, "**/settings*.py")
    test_files = _glob_sim(root_path, "**/test_*.py")
    found_files.update(config_files)
    found_files.update(test_files)
    tokens += 15 * (len(config_files) + len(test_files))

    elapsed = time.time() - t0
    files_actually_read = min(len(found_files), 5)
    extra_files = sorted(found_files)[files_actually_read:]

    return {
        "found_files": sorted(found_files),
        "extra_files_read": extra_files,
        "tool_calls": tool_calls,
        "files_read_count": files_actually_read,
        "estimated_tokens": tokens,
        "elapsed_seconds": round(elapsed, 3),
        "found_expected_symbols": [],
        "found_expected_files": sorted(found_files),
        "missing_expected": [],
        "notes": [],
    }


def run_baseline_test_discovery(task: dict[str, Any]) -> dict[str, Any]:
    """Simulate a baseline agent discovering tests."""
    t0 = time.time()
    tool_calls: dict[str, int] = {"total": 0, "grep": 0, "glob": 0, "read": 0}
    found_files: set[str] = set()
    tokens: int = 0

    root_path = task["root_path"]
    keywords = _extract_keywords(task["task"])

    # Glob for test files
    tool_calls["glob"] += 1
    tool_calls["total"] += 1
    tokens += 50
    test_files = _glob_sim(root_path, "**/test_*.py")
    found_files.update(test_files)
    tokens += 15 * len(test_files)

    # Grep in test files for the target
    for kw in keywords[:2]:
        tool_calls["grep"] += 1
        tool_calls["total"] += 1
        tokens += 80
        matches = _grep_sim(root_path, kw, file_pattern="test_*.py")
        found_files.update(matches)
        tokens += 15 * len(matches)

    # Read matching test files
    for f in list(found_files)[:3]:
        tool_calls["read"] += 1
        tool_calls["total"] += 1
        tokens += _estimate_file_tokens(root_path, f)

    # Also read the source file
    for kw in keywords[:1]:
        src_files = _grep_sim(root_path, kw)
        src_files = [f for f in src_files if not f.startswith("tests/")]
        for f in src_files[:2]:
            tool_calls["read"] += 1
            tool_calls["total"] += 1
            tokens += _estimate_file_tokens(root_path, f)
            found_files.add(f)
        tokens += 15 * len(src_files)

    elapsed = time.time() - t0
    files_actually_read = min(len(found_files), 5)
    extra_files = sorted(found_files)[files_actually_read:]

    return {
        "found_files": sorted(found_files),
        "extra_files_read": extra_files,
        "tool_calls": tool_calls,
        "files_read_count": files_actually_read,
        "estimated_tokens": tokens,
        "elapsed_seconds": round(elapsed, 3),
        "found_expected_symbols": [],
        "found_expected_files": sorted(found_files),
        "missing_expected": [],
        "notes": [],
    }


BASELINE_RUNNERS = {
    "locate": run_baseline_locate,
    "impact": run_baseline_impact,
    "modification_prep": run_baseline_modification_prep,
    "test_discovery": run_baseline_test_discovery,
}


# ── CodeGraph Mode ─────────────────────────────────────────────────────────


def _collect_symbol_ids(store: GraphStore, data: Any) -> set[str]:
    """Recursively extract symbol IDs from query result data structures."""
    ids: set[str] = set()
    if isinstance(data, dict):
        for key in ("symbol_id", "target", "center", "source"):
            if key in data and isinstance(data[key], str):
                ids.add(data[key])
        for value in data.values():
            ids.update(_collect_symbol_ids(store, value))
    elif isinstance(data, list):
        for item in data:
            ids.update(_collect_symbol_ids(store, item))
    return ids


def _codegraph_search_all(
    store: GraphStore, keywords: list[str], limit: int = 10
) -> dict[str, Any]:
    """Search with ALL keywords and combine results (simulates real agent behavior)."""
    all_results: dict[str, dict[str, Any]] = {}
    ambiguous_count = 0
    payload_tokens = 0
    for kw in keywords[:5]:
        result = graph_query.search_symbols(
            store,
            query=kw,
            limit=limit,
            include_tests=True,
            exclude_external=True,
            min_score=0.2,
        )
        if result.get("ambiguous"):
            ambiguous_count += 1
        compact_payload = [
            {
                "symbol_id": r["symbol_id"],
                "name": r["name"],
                "type": r["type"],
                "file_path": r["file_path"],
                "line_start": r.get("line_start"),
                "line_end": r.get("line_end"),
                "score": r.get("score"),
                "match_sources": r.get("match_sources", []),
                "layer": r.get("layer"),
            }
            for r in result.get("results", [])
        ]
        payload_tokens += _estimate_json_tokens(compact_payload)
        for item in result.get("results", []):
            sid = item["symbol_id"]
            if sid not in all_results:
                all_results[sid] = item
    combined = list(all_results.values())
    return {
        "results": combined,
        "total": len(combined),
        "ambiguous_count": ambiguous_count,
        "search_payload_tokens": payload_tokens,
        "top_symbol": combined[0]["symbol_id"] if combined else None,
    }


def _pick_best_symbol(search_result: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the best symbol for impact/neighbors queries.

    Preserves relevance order from search but deprioritizes __init__ methods,
    file/module/import/external_symbol node types.
    """
    results = search_result.get("results", [])
    if not results:
        return None

    usable_types = {"function", "method", "class"}
    # First pass: pick first function/method/class that isn't __init__
    for r in results:
        t = r.get("type", "")
        name = r.get("name", "")
        if t in usable_types and name != "__init__":
            return r

    # Second pass: include __init__ methods
    for r in results:
        t = r.get("type", "")
        if t in usable_types:
            return r

    # Fallback: first result of any type
    return results[0]


# Keep old name for backward compat
_codegraph_search_best = _codegraph_search_all


def run_codegraph_locate(
    store: GraphStore, task: dict[str, Any], response_mode: str = "compact"
) -> dict[str, Any]:
    """Run codegraph locate: search_symbols with all keywords + get_symbol for top hits.

    Always computes both compact and standard MCP payload estimates from the
    same query results so callers can compare mode costs without re-executing.
    """
    t0 = time.time()
    tool_calls: dict[str, int] = {"total": 0, "grep": 0, "glob": 0, "read": 0, "codegraph_mcp": 0}
    found_symbols: set[str] = set()
    found_files: set[str] = set()
    mcp_compact: int = 0
    mcp_standard: int = 0

    keywords = _extract_keywords(task["task"])

    # 1. search_symbols with all keywords combined
    tool_calls["codegraph_mcp"] += 1
    tool_calls["total"] += 1
    search_result = _codegraph_search_all(store, keywords, limit=10)
    # Compact token estimation: only count essential fields
    compact_search = [
        {"symbol_id": r["symbol_id"], "name": r["name"], "type": r["type"], "file_path": r["file_path"]}
        for r in search_result.get("results", [])
    ]
    mcp_compact += _estimate_json_tokens(compact_search)
    # Standard token estimation: includes signature, confidence, tags, layer
    standard_search = [
        {
            "symbol_id": r["symbol_id"], "name": r["name"], "type": r["type"],
            "file_path": r["file_path"], "line_start": r.get("line_start"),
            "line_end": r.get("line_end"), "module": r.get("module"),
            "signature": r.get("signature", ""), "docstring": r.get("docstring", ""),
            "confidence": r.get("confidence"), "tags": r.get("tags", []),
            "layer": _assign_benchmark_layer(r.get("file_path", "")),
        }
        for r in search_result.get("results", [])
    ]
    mcp_standard += _estimate_json_tokens(standard_search)
    for item in search_result.get("results", []):
        found_symbols.add(item["symbol_id"])
        found_files.add(item["file_path"])

    # 2. get_symbol for top 2 non-module results
    top_count = 0
    for item in search_result.get("results", []):
        if item.get("type") not in ("module", "file", "import", "external_symbol") and top_count < 2:
            tool_calls["codegraph_mcp"] += 1
            tool_calls["total"] += 1
            node = store.get_node(item["symbol_id"])
            if node:
                # Compact: minimal fields
                compact_node = {
                    "symbol_id": node.id, "name": node.name, "type": node.type.value,
                    "file_path": node.file_path,
                }
                mcp_compact += _estimate_json_tokens(compact_node)
                # Standard: full node
                standard_node = {
                    "symbol_id": node.id, "name": node.name, "type": node.type.value,
                    "file_path": node.file_path,
                    "line_start": node.location.line_start if node.location else None,
                    "line_end": node.location.line_end if node.location else None,
                    "module": node.module,
                    "signature": node.signature, "docstring": node.docstring,
                    "tags": node.tags,
                }
                mcp_standard += _estimate_json_tokens(standard_node)
                found_files.add(node.file_path)
            top_count += 1

    # Pick primary estimate based on response_mode
    mcp_payload = mcp_compact if response_mode == "compact" else mcp_standard
    discovery = mcp_payload
    followup_reads = max(1, len(found_files) // 3)
    followup_tokens = 0
    for f in sorted(found_files)[:followup_reads]:
        followup_tokens += _estimate_file_tokens(task["root_path"], f)

    full_task = mcp_payload + followup_tokens
    elapsed = time.time() - t0

    return {
        "found_files": sorted(found_files),
        "found_symbols": sorted(found_symbols),
        "extra_files_read": [],
        "tool_calls": tool_calls,
        "files_read_count": 0,
        "estimated_tokens": full_task,
        "elapsed_seconds": round(elapsed, 3),
        "notes": [],
        "response_mode": response_mode,
        "mcp_payload_tokens": mcp_payload,
        "mcp_payload_tokens_compact": mcp_compact,
        "mcp_payload_tokens_standard": mcp_standard,
        "search_symbols_found": [r["symbol_id"] for r in search_result.get("results", [])],
        "search_top_symbol": search_result.get("top_symbol"),
        "search_ambiguous": search_result.get("ambiguous_count", 0) > 0,
        "search_payload_tokens": search_result.get("search_payload_tokens", 0),
        "required_followup_reads": followup_reads,
        "discovery_token_estimate": discovery,
        "full_task_token_estimate": full_task,
        "full_task_token_estimate_compact": mcp_compact + followup_tokens,
        "full_task_token_estimate_standard": mcp_standard + followup_tokens,
    }


def run_codegraph_impact(
    store: GraphStore, task: dict[str, Any], response_mode: str = "compact"
) -> dict[str, Any]:
    """Run codegraph impact: search_symbols with all keywords + get_impact for best hits.

    Always computes both compact and standard MCP payload estimates from the
    same query results so callers can compare mode costs without re-executing.
    """
    t0 = time.time()
    tool_calls: dict[str, int] = {"total": 0, "grep": 0, "glob": 0, "read": 0, "codegraph_mcp": 0}
    found_symbols: set[str] = set()
    found_files: set[str] = set()
    mcp_compact: int = 0
    mcp_standard: int = 0

    keywords = _extract_keywords(task["task"])

    # 1. search_symbols with all keywords
    tool_calls["codegraph_mcp"] += 1
    tool_calls["total"] += 1
    search_result = _codegraph_search_all(store, keywords, limit=5)
    compact_search = [
        {"symbol_id": r["symbol_id"], "name": r["name"], "type": r["type"], "file_path": r["file_path"]}
        for r in search_result.get("results", [])
    ]
    mcp_compact += _estimate_json_tokens(compact_search)
    standard_search = [
        {
            "symbol_id": r["symbol_id"], "name": r["name"], "type": r["type"],
            "file_path": r["file_path"], "line_start": r.get("line_start"),
            "line_end": r.get("line_end"), "signature": r.get("signature", ""),
            "confidence": r.get("confidence"), "tags": r.get("tags", []),
        }
        for r in search_result.get("results", [])
    ]
    mcp_standard += _estimate_json_tokens(standard_search)
    for item in search_result.get("results", []):
        found_symbols.add(item["symbol_id"])
        found_files.add(item["file_path"])

    # 2. get_impact for best result (balanced mode: depth=2)
    top = _pick_best_symbol(search_result)
    if top:
        tool_calls["codegraph_mcp"] += 1
        tool_calls["total"] += 1
        impact_result = graph_impact.analyze_impact(
            store, top["symbol_id"], depth=2
        )
        # Compact impact: minimal fields only
        compact_impact = {
            "target": top["symbol_id"],
            "risk": impact_result.get("risk", {}),
            "confirmed": {
                "files": [
                    {"file_path": f["file_path"], "layer": _assign_benchmark_layer(f.get("file_path", ""))}
                    for f in impact_result.get("confirmed_impact", {}).get("files", [])
                ],
                "symbols": [
                    {"symbol_id": s["symbol_id"], "name": s.get("name", "")}
                    for s in impact_result.get("confirmed_impact", {}).get("symbols", [])
                ],
                "tests": [
                    {"symbol_id": t["symbol_id"], "file_path": t.get("file_path", "")}
                    for t in impact_result.get("related_tests", [])
                ],
            },
            "possible": impact_result.get("possible_impact", {}),
            "related_tests_count": len(impact_result.get("related_tests", [])),
        }
        mcp_compact += _estimate_json_tokens(compact_impact)
        # Standard impact: full file/symbol details
        standard_impact = {
            "target": top["symbol_id"],
            "risk": impact_result.get("risk", {}),
            "confirmed": {
                "files": [
                    {"file_path": f["file_path"], "symbol_id": f.get("symbol_id", ""),
                     "name": f.get("name", ""), "type": f.get("type", ""),
                     "confidence": f.get("confidence"), "reason_code": f.get("reason_code", "impact"),
                     "layer": _assign_benchmark_layer(f.get("file_path", ""))}
                    for f in impact_result.get("confirmed_impact", {}).get("files", [])
                ],
                "symbols": [
                    {"symbol_id": s["symbol_id"], "name": s.get("name", ""),
                     "type": s.get("type", ""), "file_path": s.get("file_path", ""),
                     "confidence": s.get("confidence")}
                    for s in impact_result.get("confirmed_impact", {}).get("symbols", [])
                ],
                "tests": [
                    {"symbol_id": t["symbol_id"], "name": t.get("name", ""),
                     "type": t.get("type", ""), "file_path": t.get("file_path", "")}
                    for t in impact_result.get("related_tests", [])
                ],
            },
            "possible": impact_result.get("possible_impact", {}),
        }
        mcp_standard += _estimate_json_tokens(standard_impact)
        for f in impact_result.get("confirmed_impact", {}).get("files", []):
            found_files.add(f["file_path"])
        for s in impact_result.get("confirmed_impact", {}).get("symbols", []):
            found_symbols.add(s["symbol_id"])
        for t in impact_result.get("related_tests", []):
            if t.get("file_path"):
                found_files.add(t["file_path"])
            if t.get("symbol_id"):
                found_symbols.add(t["symbol_id"])

    mcp_payload = mcp_compact if response_mode == "compact" else mcp_standard
    discovery = mcp_payload
    followup_reads = max(1, len(found_files) // 3)
    followup_tokens = 0
    for f in sorted(found_files)[:followup_reads]:
        followup_tokens += _estimate_file_tokens(task["root_path"], f)

    full_task = mcp_payload + followup_tokens
    elapsed = time.time() - t0

    return {
        "found_files": sorted(found_files),
        "found_symbols": sorted(found_symbols),
        "extra_files_read": [],
        "tool_calls": tool_calls,
        "files_read_count": 0,
        "estimated_tokens": full_task,
        "elapsed_seconds": round(elapsed, 3),
        "notes": [],
        "response_mode": response_mode,
        "mcp_payload_tokens": mcp_payload,
        "mcp_payload_tokens_compact": mcp_compact,
        "mcp_payload_tokens_standard": mcp_standard,
        "search_symbols_found": [r["symbol_id"] for r in search_result.get("results", [])],
        "search_top_symbol": search_result.get("top_symbol"),
        "search_ambiguous": search_result.get("ambiguous_count", 0) > 0,
        "search_payload_tokens": search_result.get("search_payload_tokens", 0),
        "required_followup_reads": followup_reads,
        "discovery_token_estimate": discovery,
        "full_task_token_estimate": full_task,
        "full_task_token_estimate_compact": mcp_compact + followup_tokens,
        "full_task_token_estimate_standard": mcp_standard + followup_tokens,
    }


def run_codegraph_modification_prep(
    store: GraphStore, task: dict[str, Any], response_mode: str = "compact"
) -> dict[str, Any]:
    """Run codegraph modification prep: search_symbols + get_neighbors + follow-up reads.

    Always computes both compact and standard MCP payload estimates from the
    same query results so callers can compare mode costs without re-executing.
    """
    t0 = time.time()
    tool_calls: dict[str, int] = {"total": 0, "grep": 0, "glob": 0, "read": 0, "codegraph_mcp": 0}
    found_symbols: set[str] = set()
    found_files: set[str] = set()
    mcp_compact: int = 0
    mcp_standard: int = 0

    keywords = _extract_keywords(task["task"])

    # 1. search_symbols with all keywords
    tool_calls["codegraph_mcp"] += 1
    tool_calls["total"] += 1
    search_result = _codegraph_search_all(store, keywords, limit=10)
    compact_search = [
        {"symbol_id": r["symbol_id"], "name": r["name"], "type": r["type"], "file_path": r["file_path"]}
        for r in search_result.get("results", [])
    ]
    mcp_compact += _estimate_json_tokens(compact_search)
    standard_search = [
        {
            "symbol_id": r["symbol_id"], "name": r["name"], "type": r["type"],
            "file_path": r["file_path"], "line_start": r.get("line_start"),
            "signature": r.get("signature", ""), "confidence": r.get("confidence"),
            "tags": r.get("tags", []),
        }
        for r in search_result.get("results", [])
    ]
    mcp_standard += _estimate_json_tokens(standard_search)
    for item in search_result.get("results", []):
        found_symbols.add(item["symbol_id"])
        found_files.add(item["file_path"])

    # 2. get_neighbors for best hit
    top = _pick_best_symbol(search_result)
    if top:
        tool_calls["codegraph_mcp"] += 1
        tool_calls["total"] += 1
        neighbors = _get_neighbors_bfs(store, top["symbol_id"], depth=2)
        # Compact neighbors: summary only
        compact_neighbors = {
            "center": neighbors["center"],
            "node_count": len(neighbors["nodes"]),
            "edge_count": len(neighbors["edges"]),
        }
        mcp_compact += _estimate_json_tokens(compact_neighbors)
        # Standard neighbors: full node/edge lists
        standard_neighbors = {
            "center": neighbors["center"],
            "nodes": [
                {"symbol_id": nid}
                for nid in neighbors.get("nodes", [])
            ],
            "edges": neighbors.get("edges", []),
        }
        mcp_standard += _estimate_json_tokens(standard_neighbors)
        for nid in neighbors.get("nodes", []):
            found_symbols.add(nid)
            node = store.get_node(nid) if isinstance(nid, str) else None
            if node and node.file_path:
                found_files.add(node.file_path)

        # 3. Also run get_impact for the same symbol to get model/config/test deps
        tool_calls["codegraph_mcp"] += 1
        tool_calls["total"] += 1
        impact_result = graph_impact.analyze_impact(store, top["symbol_id"], depth=2)
        # Compact impact
        compact_impact = {
            "confirmed_files": [
                {"file_path": f["file_path"], "layer": _assign_benchmark_layer(f.get("file_path", ""))}
                for f in impact_result.get("confirmed_impact", {}).get("files", [])
            ],
            "relevant_tests": len(impact_result.get("related_tests", [])),
        }
        mcp_compact += _estimate_json_tokens(compact_impact)
        # Standard impact
        standard_impact = {
            "confirmed_files": [
                {"file_path": f["file_path"], "name": f.get("name", ""),
                 "confidence": f.get("confidence"),
                 "reason_code": f.get("reason_code", "impact")}
                for f in impact_result.get("confirmed_impact", {}).get("files", [])
            ],
            "possible_files": [
                {"file_path": f.get("file_path", ""), "name": f.get("name", "")}
                for f in impact_result.get("possible_impact", {}).get("files", [])
            ],
            "tests": [
                {"symbol_id": t["symbol_id"], "file_path": t.get("file_path", "")}
                for t in impact_result.get("related_tests", [])
            ],
        }
        mcp_standard += _estimate_json_tokens(standard_impact)
        for f in impact_result.get("confirmed_impact", {}).get("files", []):
            found_files.add(f["file_path"])
        for s in impact_result.get("confirmed_impact", {}).get("symbols", []):
            found_symbols.add(s["symbol_id"])
        for t in impact_result.get("related_tests", []):
            if t.get("file_path"):
                found_files.add(t["file_path"])

    # 4. File reads for execution phase (same for both modes)
    discovery_mcp_compact = mcp_compact
    discovery_mcp_standard = mcp_standard
    discovery_files_to_read = min(len(found_files), 3)
    read_tokens = 0
    for f in sorted(found_files)[:discovery_files_to_read]:
        tool_calls["read"] += 1
        tool_calls["total"] += 1
        read_tokens += _estimate_file_tokens(task["root_path"], f)

    mcp_payload = mcp_compact if response_mode == "compact" else mcp_standard
    discovery = mcp_payload
    total_tokens = mcp_payload + read_tokens
    elapsed = time.time() - t0

    return {
        "found_files": sorted(found_files),
        "found_symbols": sorted(found_symbols),
        "extra_files_read": [],
        "tool_calls": tool_calls,
        "files_read_count": discovery_files_to_read,
        "estimated_tokens": total_tokens,
        "elapsed_seconds": round(elapsed, 3),
        "notes": [],
        "response_mode": response_mode,
        "mcp_payload_tokens": mcp_payload,
        "mcp_payload_tokens_compact": mcp_compact,
        "mcp_payload_tokens_standard": mcp_standard,
        "search_symbols_found": [r["symbol_id"] for r in search_result.get("results", [])],
        "search_top_symbol": search_result.get("top_symbol"),
        "search_ambiguous": search_result.get("ambiguous_count", 0) > 0,
        "search_payload_tokens": search_result.get("search_payload_tokens", 0),
        "required_followup_reads": discovery_files_to_read,
        "discovery_token_estimate": discovery,
        "full_task_token_estimate": total_tokens,
        "full_task_token_estimate_compact": discovery_mcp_compact + read_tokens,
        "full_task_token_estimate_standard": discovery_mcp_standard + read_tokens,
    }


def run_codegraph_test_discovery(
    store: GraphStore, task: dict[str, Any], response_mode: str = "compact"
) -> dict[str, Any]:
    """Run codegraph test discovery: search_symbols + get_neighbors (tested_by) + get_impact (tests).

    Always computes both compact and standard MCP payload estimates from the
    same query results so callers can compare mode costs without re-executing.
    """
    t0 = time.time()
    tool_calls: dict[str, int] = {"total": 0, "grep": 0, "glob": 0, "read": 0, "codegraph_mcp": 0}
    found_symbols: set[str] = set()
    found_files: set[str] = set()
    mcp_compact: int = 0
    mcp_standard: int = 0

    keywords = _extract_keywords(task["task"])

    # 1. search_symbols with all keywords
    tool_calls["codegraph_mcp"] += 1
    tool_calls["total"] += 1
    search_result = _codegraph_search_all(store, keywords, limit=10)
    compact_search = [
        {"symbol_id": r["symbol_id"], "name": r["name"], "type": r["type"], "file_path": r["file_path"]}
        for r in search_result.get("results", [])
    ]
    mcp_compact += _estimate_json_tokens(compact_search)
    standard_search = [
        {
            "symbol_id": r["symbol_id"], "name": r["name"], "type": r["type"],
            "file_path": r["file_path"], "line_start": r.get("line_start"),
            "signature": r.get("signature", ""), "confidence": r.get("confidence"),
            "tags": r.get("tags", []),
        }
        for r in search_result.get("results", [])
    ]
    mcp_standard += _estimate_json_tokens(standard_search)
    for item in search_result.get("results", []):
        found_symbols.add(item["symbol_id"])
        found_files.add(item["file_path"])

    # 2. get_impact with include_tests=true for best result (balanced mode)
    top = _pick_best_symbol(search_result)
    if top:
        tool_calls["codegraph_mcp"] += 1
        tool_calls["total"] += 1
        impact_result = graph_impact.analyze_impact(
            store, top["symbol_id"], depth=2
        )
        # Compact impact: minimal test info
        compact_impact = {
            "target": top["symbol_id"],
            "related_tests": [
                {"symbol_id": t["symbol_id"], "file_path": t.get("file_path", "")}
                for t in impact_result.get("related_tests", [])
            ],
        }
        mcp_compact += _estimate_json_tokens(compact_impact)
        # Standard impact: full test info
        standard_impact = {
            "target": top["symbol_id"],
            "confirmed": {
                "files": [
                    {"file_path": f["file_path"], "name": f.get("name", ""),
                     "confidence": f.get("confidence"), "layer": _assign_benchmark_layer(f.get("file_path", ""))}
                    for f in impact_result.get("confirmed_impact", {}).get("files", [])
                ],
            },
            "tests": [
                {"symbol_id": t["symbol_id"], "name": t.get("name", ""),
                 "type": t.get("type", ""), "file_path": t.get("file_path", ""),
                 "confidence": t.get("confidence")}
                for t in impact_result.get("related_tests", [])
            ],
        }
        mcp_standard += _estimate_json_tokens(standard_impact)
        for f in impact_result.get("confirmed_impact", {}).get("files", []):
            found_files.add(f["file_path"])
        for s in impact_result.get("confirmed_impact", {}).get("symbols", []):
            found_symbols.add(s["symbol_id"])
        for t in impact_result.get("related_tests", []):
            if t.get("symbol_id"):
                found_symbols.add(t["symbol_id"])
            if t.get("file_path"):
                found_files.add(t["file_path"])

    # 3. Also search for test files directly via keywords
    tool_calls["codegraph_mcp"] += 1
    tool_calls["total"] += 1
    test_keywords = [k for k in keywords if "test" in k]
    if not test_keywords:
        test_keywords = ["test_" + kw for kw in keywords[:2]]
    for tk in test_keywords[:2]:
        test_search = graph_query.search_symbols(store, query=tk, limit=10)
        for item in test_search.get("results", []):
            found_symbols.add(item["symbol_id"])
            found_files.add(item["file_path"])
        # Compact test search
        mcp_compact += _estimate_json_tokens(
            [{"symbol_id": r["symbol_id"], "type": r["type"], "file_path": r["file_path"]}
             for r in test_search.get("results", [])]
        )
        # Standard test search
        mcp_standard += _estimate_json_tokens(
            [{"symbol_id": r["symbol_id"], "name": r["name"], "type": r["type"],
              "file_path": r["file_path"], "line_start": r.get("line_start"),
              "signature": r.get("signature", "")}
             for r in test_search.get("results", [])]
        )

    mcp_payload = mcp_compact if response_mode == "compact" else mcp_standard
    discovery = mcp_payload
    followup_reads = max(1, len(found_files) // 4)
    followup_tokens = 0
    for f in sorted(found_files)[:followup_reads]:
        followup_tokens += _estimate_file_tokens(task["root_path"], f)

    full_task = mcp_payload + followup_tokens
    elapsed = time.time() - t0

    return {
        "found_files": sorted(found_files),
        "found_symbols": sorted(found_symbols),
        "extra_files_read": [],
        "tool_calls": tool_calls,
        "files_read_count": 0,
        "estimated_tokens": full_task,
        "elapsed_seconds": round(elapsed, 3),
        "notes": [],
        "response_mode": response_mode,
        "mcp_payload_tokens": mcp_payload,
        "mcp_payload_tokens_compact": mcp_compact,
        "mcp_payload_tokens_standard": mcp_standard,
        "search_symbols_found": [r["symbol_id"] for r in search_result.get("results", [])],
        "search_top_symbol": search_result.get("top_symbol"),
        "search_ambiguous": search_result.get("ambiguous_count", 0) > 0,
        "search_payload_tokens": search_result.get("search_payload_tokens", 0),
        "required_followup_reads": followup_reads,
        "discovery_token_estimate": discovery,
        "full_task_token_estimate": full_task,
        "full_task_token_estimate_compact": mcp_compact + followup_tokens,
        "full_task_token_estimate_standard": mcp_standard + followup_tokens,
    }


CODEGRAPH_RUNNERS = {
    "locate": run_codegraph_locate,
    "impact": run_codegraph_impact,
    "modification_prep": run_codegraph_modification_prep,
    "test_discovery": run_codegraph_test_discovery,
}


def _assign_benchmark_layer(file_path: str) -> str:
    """Assign a layer label based on file_path directory heuristics.

    Mirrors ``mcp_server._assign_layer`` for benchmark token estimation.
    """
    normalized = file_path.replace("\\", "/").lower()
    # Order matters: more specific patterns first
    layer_map = [
        ("codegraph/graph/", "graph"),
        ("codegraph/indexer", "indexer"),
        ("codegraph/storage/", "storage"),
        ("codegraph/context/", "context"),
        ("codegraph/mcp/", "mcp"),
        ("api/", "api"), ("routes", "api"), ("router", "api"),
        ("service", "service"), ("services", "service"),
        ("graph/", "graph"), ("graph_", "graph"),
        ("indexer", "indexer"), ("index/", "indexer"),
        ("storage/", "storage"), ("store/", "storage"),
        ("context/", "context"), ("evidence", "context"),
        ("mcp/", "mcp"), ("mcp_server", "mcp"),
        ("test", "tests"), ("test_", "tests"),
        ("config", "config"), ("settings", "config"),
        ("model", "models"), ("schema", "models"),
        ("persistence", "persistence"), ("repository", "persistence"),
    ]
    for pattern, layer in layer_map:
        if pattern in normalized:
            return layer
    return "unknown"


# ── Helpers ─────────────────────────────────────────────────────────────────


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful code-relevant keywords from a task description."""
    stop = {
        "find", "where", "is", "the", "a", "an", "for", "what", "if",
        "i", "change", "may", "be", "to", "in", "of", "are", "related",
        "how", "can", "does", "do", "prepare", "context", "adding",
        "flow", "files", "tests", "module", "this", "that", "it", "on",
        "at", "by", "with", "from", "about", "all", "any", "been",
        "but", "could", "did", "each", "few", "get", "got", "had",
        "has", "her", "him", "his", "its", "just", "like", "made",
        "make", "more", "much", "not", "now", "one", "only", "or",
        "other", "out", "over", "say", "she", "so", "some", "such",
        "than", "then", "their", "them", "there", "these", "they",
        "use", "was", "we", "were", "which", "who", "will", "would",
        "you", "also", "and", "but", "does", "during", "into", "no",
        "our", "should", "still", "up", "very", "way",
    }
    # Domain-significant terms get boosted priority
    domain_boost = {
        "login", "token", "auth", "mfa", "user", "password",
        "service", "store", "model", "config", "repository",
        "middleware", "route", "admin", "health", "logout",
        "validate", "session", "role", "verify", "profile",
        "register", "search", "hash", "email", "rate",
    }
    # Strip trailing punctuation but preserve dots in identifiers (e.g. AuthService.login_user)
    cleaned = text.lower().rstrip(".!?")
    words = cleaned.split()
    filtered: list[str] = []
    for w in words:
        w = w.strip(",;:()[]\"'`")
        # Keep dots that are parts of identifiers (AuthService.login_user)
        if w not in stop and len(w) > 1:
            filtered.append(w)
        # Also add dot-separated parts as individual keywords
        if "." in w and len(w) < 60:  # plausible identifier
            parts = [p.strip() for p in w.split(".") if len(p.strip()) > 1 and p.strip() not in stop]
            filtered.extend(parts)
    # Score: domain terms first, then longer words
    def _score(w: str) -> int:
        s = 100 if w in domain_boost else 0
        s += len(w)
        return -s  # negative so sorted() puts highest first
    filtered.sort(key=_score)
    return filtered


def _grep_sim(root_path: str, query: str, file_pattern: str = "*.py") -> list[str]:
    """Simulate grep: find files containing a query string."""
    root = Path(root_path)
    results: list[str] = []
    q = query.lower()
    for py_file in root.rglob(file_pattern):
        rel = py_file.relative_to(root).as_posix()
        if any(p in rel for p in ("__pycache__", ".codegraph")):
            continue
        content = py_file.read_text(encoding="utf-8").lower()
        if q in content:
            results.append(rel)
    return sorted(results)


def _glob_sim(root_path: str, pattern: str) -> list[str]:
    """Simulate glob: find files matching a pattern."""
    root = Path(root_path)
    import fnmatch
    results: list[str] = []
    for py_file in root.rglob("*.py"):
        rel = py_file.relative_to(root).as_posix()
        if any(p in rel for p in ("__pycache__", ".codegraph")):
            continue
        if fnmatch.fnmatch(rel, pattern):
            results.append(rel)
    return sorted(results)


def _estimate_file_tokens(root_path: str, file_path: str) -> int:
    """Estimate token count for reading a file."""
    full = Path(root_path) / file_path
    if not full.exists():
        return 0
    content = full.read_text(encoding="utf-8")
    return len(content) // 4  # rough char-to-token estimate


def _estimate_json_tokens(obj: Any) -> int:
    """Estimate tokens from a JSON-serializable object."""
    return len(json.dumps(obj, default=str, ensure_ascii=False)) // 4


def _estimate_node_tokens(node) -> int:
    """Estimate tokens from a GraphNode."""
    data = {
        "symbol_id": node.id,
        "name": node.name,
        "type": node.type.value if hasattr(node.type, "value") else str(node.type),
        "file_path": node.file_path,
        "signature": node.signature,
        "docstring": node.docstring,
    }
    return _estimate_json_tokens(data)


def _get_neighbors_bfs(store: GraphStore, center_id: str, depth: int = 1) -> dict[str, Any]:
    """BFS traversal to get local subgraph (simulates get_neighbors MCP call)."""
    from collections import deque

    nodes: list[str] = []
    edges: list[dict[str, Any]] = []
    seen: dict[str, int] = {center_id: 0}
    queue: deque[tuple[str, int]] = deque()
    queue.append((center_id, 0))

    while queue:
        current, dist = queue.popleft()
        if dist >= depth:
            continue
        for edge in store.get_outgoing_edges(current):
            neighbor = edge.target
            edges.append({"source": edge.source, "target": edge.target, "type": str(edge.type.value)})
            if neighbor not in seen:
                seen[neighbor] = dist + 1
                nodes.append(neighbor)
                queue.append((neighbor, dist + 1))
        for edge in store.get_incoming_edges(current):
            neighbor = edge.source
            edges.append({"source": edge.source, "target": edge.target, "type": str(edge.type.value)})
            if neighbor not in seen:
                seen[neighbor] = dist + 1
                nodes.append(neighbor)
                queue.append((neighbor, dist + 1))

    return {"center": center_id, "nodes": nodes, "edges": edges}


# ── Main ────────────────────────────────────────────────────────────────────


def run_benchmark(mode: str = "baseline", response_mode: str = "compact") -> list[dict[str, Any]]:
    """Run all test cases in the specified mode. Returns list of result dicts."""
    tasks = load_test_cases()
    results: list[dict[str, Any]] = []

    for task in tasks:
        task_id = task["task_id"]
        category = task["category"]
        root_path = task["root_path"]

        store = None
        if mode == "codegraph":
            store = load_store_for_project(root_path)

        if mode == "baseline":
            runner = BASELINE_RUNNERS.get(category)
        else:
            runner = CODEGRAPH_RUNNERS.get(category)

        if runner is None:
            print(f"[SKIP] {task_id}: unsupported category '{category}'")
            continue

        try:
            if mode == "baseline":
                outcome = runner(task)
            else:
                outcome = runner(store, task, response_mode=response_mode)

            result = {
                "task_id": task_id,
                "mode": mode,
                "category": category,
                "task": task["task"],
                "project": task["project"],
                "success": True,
                "found_expected_symbols": [],
                "found_expected_files": [],
                "missing_expected": [],
                "extra_files_read": outcome.get("extra_files_read", []),
                "tool_calls": outcome["tool_calls"],
                "files_read_count": outcome.get("files_read_count", 0),
                "estimated_tokens": outcome.get("estimated_tokens", 0),
                "elapsed_seconds": outcome.get("elapsed_seconds", 0),
                "notes": outcome.get("notes", []),
                "response_mode": outcome.get("response_mode", response_mode),
                # Phase-aware metrics
                "mcp_payload_tokens": outcome.get("mcp_payload_tokens", 0),
                "mcp_payload_tokens_compact": outcome.get("mcp_payload_tokens_compact", 0),
                "mcp_payload_tokens_standard": outcome.get("mcp_payload_tokens_standard", 0),
                "search_recall": 0.0,
                "search_top1_accuracy": 0.0,
                "search_ambiguous": bool(outcome.get("search_ambiguous", False)),
                "search_payload_tokens": outcome.get("search_payload_tokens", 0),
                "required_followup_reads": outcome.get("required_followup_reads", 0),
                "discovery_token_estimate": outcome.get("discovery_token_estimate", 0),
                "full_task_token_estimate": outcome.get("full_task_token_estimate", 0),
                "full_task_token_estimate_compact": outcome.get("full_task_token_estimate_compact", 0),
                "full_task_token_estimate_standard": outcome.get("full_task_token_estimate_standard", 0),
            }

            # Compare against expected
            expected_symbols = task.get("expected_symbols", [])
            expected_files = task.get("expected_files", [])
            found_symbols = outcome.get("found_symbols", [])
            found_files_set = outcome.get("found_files", [])

            result["found_expected_symbols"] = [
                s for s in expected_symbols
                if any(_fuzzy_match(s, f) for f in found_symbols)
            ]
            result["found_expected_files"] = [
                f for f in expected_files
                if any(_fuzzy_path_match(f, ff) for ff in found_files_set)
            ]
            result["missing_expected"] = [
                f for f in expected_files
                if not any(_fuzzy_path_match(f, ff) for ff in found_files_set)
            ]
            search_found = outcome.get("search_symbols_found", [])
            if expected_symbols:
                found_by_search = [
                    s for s in expected_symbols
                    if any(_fuzzy_match(s, f) for f in search_found)
                ]
                result["search_recall"] = round(len(found_by_search) / len(expected_symbols), 4)
                top_symbol = outcome.get("search_top_symbol")
                result["search_top1_accuracy"] = (
                    1.0
                    if top_symbol and any(_fuzzy_match(s, top_symbol) for s in expected_symbols)
                    else 0.0
                )
            else:
                result["search_recall"] = 1.0
                result["search_top1_accuracy"] = 1.0

            results.append(result)
            print(f"[OK] {mode:10s} | {task_id:40s} | files={len(found_files_set):2d} | tokens={outcome.get('estimated_tokens', 0):5d}")

        except Exception as e:
            results.append({
                "task_id": task_id,
                "mode": mode,
                "category": category,
                "task": task["task"],
                "project": task["project"],
                "success": False,
                "error": str(e),
                "found_expected_symbols": [],
                "found_expected_files": [],
                "missing_expected": task.get("expected_files", []),
                "extra_files_read": [],
                "tool_calls": {"total": 0, "grep": 0, "glob": 0, "read": 0, "codegraph_mcp": 0},
                "files_read_count": 0,
                "estimated_tokens": 0,
                "elapsed_seconds": 0,
                "notes": [f"Error: {e}"],
                "response_mode": response_mode,
                "mcp_payload_tokens": 0,
                "mcp_payload_tokens_compact": 0,
                "mcp_payload_tokens_standard": 0,
                "search_recall": 0.0,
                "search_top1_accuracy": 0.0,
                "search_ambiguous": False,
                "search_payload_tokens": 0,
                "required_followup_reads": 0,
                "discovery_token_estimate": 0,
                "full_task_token_estimate": 0,
                "full_task_token_estimate_compact": 0,
                "full_task_token_estimate_standard": 0,
            })
            print(f"[ERR] {mode:10s} | {task_id:40s} | {e}")

    return results


def _fuzzy_match(a: str, b: str) -> bool:
    """Check if two symbol IDs refer to the same thing."""
    a_norm = a.lower().replace("::", ".").replace("_", "")
    b_norm = b.lower().replace("::", ".").replace("_", "")
    if a_norm == b_norm:
        return True
    if a_norm.endswith(b_norm) or b_norm.endswith(a_norm):
        return True
    # Check file_path::symbol_name match
    if "::" in a and "::" in b:
        a_file, a_name = a.rsplit("::", 1)
        b_file, b_name = b.rsplit("::", 1)
        if a_file == b_file and a_name.lower() == b_name.lower():
            return True
    # Check if one contains the other
    if a_norm in b_norm or b_norm in a_norm:
        return True
    return False


def _fuzzy_path_match(a: str, b: str) -> bool:
    """Check if two file paths refer to the same file."""
    a_norm = a.replace("\\", "/").lower()
    b_norm = b.replace("\\", "/").lower()
    if a_norm == b_norm:
        return True
    if a_norm.endswith(b_norm) or b_norm.endswith(a_norm):
        return True
    if a_norm in b_norm or b_norm in a_norm:
        return True
    return False


def save_results(results: list[dict[str, Any]], mode: str, suffix: str = "") -> Path:
    """Save benchmark results to a JSON file.

    Args:
        results: The list of result dicts.
        mode: ``"baseline"`` or ``"codegraph"``.
        suffix: Optional suffix for the filename (e.g. ``"compact"`` or ``"standard"``).
    """
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"results_{mode}"
    if suffix:
        filename = f"{filename}_{suffix}"
    out_path = _RESULTS_DIR / f"{filename}.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="CodeGraph Agent Benchmark Runner")
    parser.add_argument(
        "--mode", choices=["baseline", "codegraph", "both"],
        default="baseline",
        help="Benchmark mode: baseline (grep/glob/read), codegraph (MCP tools), or both",
    )
    parser.add_argument(
        "--response-mode", choices=["compact", "standard", "both"],
        default="compact",
        help="MCP response_mode for codegraph runs (compact, standard, or both for dual-run comparison)",
    )
    parser.add_argument(
        "--project",
        help="Run only for a specific project (e.g. simple_auth_project)",
    )
    args = parser.parse_args()

    modes = ["baseline", "codegraph"] if args.mode == "both" else [args.mode]

    for mode in modes:
        if mode == "codegraph" and args.response_mode == "both":
            # Dual-run: compact first, then standard
            for resp_mode in ("compact", "standard"):
                print(f"\n{'='*60}")
                print(f"Running benchmark in CODEGRAPH mode (response_mode={resp_mode})")
                print(f"{'='*60}\n")
                results = run_benchmark(mode, response_mode=resp_mode)
                save_results(results, mode, suffix=resp_mode)

                summary = {
                    "total": len(results),
                    "ok": sum(1 for r in results if r["success"]),
                    "errors": sum(1 for r in results if not r["success"]),
                }
                print(f"\nSummary ({resp_mode}): {summary['ok']}/{summary['total']} OK, {summary['errors']} errors")
        else:
            resp_mode = args.response_mode if mode == "codegraph" else "compact"
            print(f"\n{'='*60}")
            print(f"Running benchmark in {mode.upper()} mode")
            if mode == "codegraph":
                print(f"Response mode: {resp_mode}")
            print(f"{'='*60}\n")
            results = run_benchmark(mode, response_mode=resp_mode)
            save_results(results, mode)

            summary = {
                "total": len(results),
                "ok": sum(1 for r in results if r["success"]),
                "errors": sum(1 for r in results if not r["success"]),
            }
            print(f"\nSummary: {summary['ok']}/{summary['total']} OK, {summary['errors']} errors")


if __name__ == "__main__":
    main()
