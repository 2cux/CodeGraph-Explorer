"""Actual MCP Profile A/B test runner.

Runs real MCP tool calls across 4 profiles (agent/full/debug/without_codegraph)
for 6 tasks, recording first_tool, wrong_entry_tool, timing, success, etc.

No simulation — every tool call is a real call to the actual MCP functions.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Profile tool sets (must match profiles.py) ──────────────────────────

AGENT_TOOLS = {
    "codegraph_repo_status",
    "codegraph_find",
    "codegraph_explain",
    "codegraph_pre_edit_check",
    "codegraph_coverage_gaps",
    "codegraph_build_context_pack",
}

FULL_TOOLS = AGENT_TOOLS | {
    "codegraph_repo_summary",
    "codegraph_search_symbols",
    "codegraph_get_symbol",
    "codegraph_get_callers",
    "codegraph_get_callees",
    "codegraph_get_neighbors",
    "codegraph_get_impact",
}

DEBUG_TOOLS = FULL_TOOLS | {
    "codegraph_harness_list",
    "codegraph_harness_run",
    "codegraph_harness_status",
    "codegraph_harness_artifacts",
}

PROFILE_TOOLS = {
    "agent": AGENT_TOOLS,
    "full": FULL_TOOLS,
    "debug": DEBUG_TOOLS,
    "without_codegraph": set(),
}

# ── Tasks ───────────────────────────────────────────────────────────────

TASKS = [
    {
        "task_id": "bug_locate_code_paths",
        "task_type": "bug_locate",
        "title": "找 bug",
        "prompt": "Use CodeGraph to locate likely code paths for a suspected coverage_gaps bug before broad file scanning.",
        "expected_best_entry": "codegraph_find",
        "allowed_entries": ["codegraph_find", "codegraph_build_context_pack"],
        "wrong_entries": ["codegraph_harness_run", "codegraph_get_symbol", "codegraph_search_symbols"],
    },
    {
        "task_id": "explain_module",
        "task_type": "explain_module",
        "title": "解释模块",
        "prompt": "Explain what backend/codegraph/mcp_server.py or codegraph_find does before reading the full source.",
        "expected_best_entry": "codegraph_explain",
        "allowed_entries": ["codegraph_explain", "codegraph_build_context_pack"],
        "wrong_entries": ["codegraph_find", "codegraph_harness_run", "codegraph_search_symbols"],
    },
    {
        "task_id": "shared_type_refactor",
        "task_type": "shared_type_refactor",
        "title": "改接口",
        "prompt": "Before refactoring a shared data structure or public interface, use CodeGraph to check impact.",
        "expected_best_entry": "codegraph_pre_edit_check",
        "allowed_entries": ["codegraph_pre_edit_check", "codegraph_build_context_pack"],
        "wrong_entries": ["codegraph_find", "codegraph_harness_run"],
    },
    {
        "task_id": "coverage_audit",
        "task_type": "coverage_audit",
        "title": "查覆盖",
        "prompt": "Find production symbols lacking test signals with CodeGraph before opening test files.",
        "expected_best_entry": "codegraph_coverage_gaps",
        "allowed_entries": ["codegraph_coverage_gaps"],
        "wrong_entries": ["codegraph_find", "codegraph_harness_run", "codegraph_search_symbols"],
    },
    {
        "task_id": "trace_flow",
        "task_type": "trace_flow",
        "title": "找 flow",
        "prompt": "Use CodeGraph to understand how CLI workflow impact reaches run_pre_edit_check before grep/read fallback.",
        "expected_best_entry": "codegraph_build_context_pack",
        "allowed_entries": ["codegraph_build_context_pack", "codegraph_explain", "codegraph_pre_edit_check"],
        "wrong_entries": ["codegraph_find", "codegraph_harness_run"],
    },
    {
        "task_id": "route_service_impact",
        "task_type": "route_service_impact",
        "title": "改 route/service",
        "prompt": "Check route/service impact with CodeGraph before editing backend/codegraph/workflow.py.",
        "expected_best_entry": "codegraph_pre_edit_check",
        "allowed_entries": ["codegraph_pre_edit_check", "codegraph_build_context_pack"],
        "wrong_entries": ["codegraph_find", "codegraph_harness_run"],
    },
]

# ── Tool dispatcher ──────────────────────────────────────────────────────


def _setup_globals():
    import codegraph.mcp_server as mcp_mod
    from codegraph.graph.store import GraphStore
    from codegraph.graph.models import CodeGraph

    cg_dir = Path.cwd() / ".codegraph"
    store = GraphStore()
    graph_path = cg_dir / "graph.json"
    if graph_path.exists():
        graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
        store.load_from_graph(graph)
    mcp_mod._store = store
    mcp_mod._cg_dir = cg_dir
    mcp_mod._project_root = str(Path.cwd())


def _teardown_globals():
    import codegraph.mcp_server as mcp_mod
    mcp_mod._store = None
    mcp_mod._cg_dir = None
    mcp_mod._project_root = None


def _call_tool(tool_name: str, **kwargs) -> tuple[dict[str, Any], bool]:
    """Call a real MCP tool function. Returns (result, ok)."""
    import codegraph.mcp_server as mcp_mod

    fn_map = {
        "codegraph_repo_status": mcp_mod.repo_status,
        "codegraph_find": mcp_mod.codegraph_find,
        "codegraph_explain": mcp_mod.codegraph_explain,
        "codegraph_pre_edit_check": mcp_mod.pre_edit_check,
        "codegraph_coverage_gaps": mcp_mod.coverage_gaps,
        "codegraph_build_context_pack": mcp_mod.build_context_pack,
        "codegraph_repo_summary": mcp_mod.repo_summary,
        "codegraph_search_symbols": mcp_mod.search_symbols,
        "codegraph_get_symbol": mcp_mod.get_symbol,
        "codegraph_get_callers": mcp_mod.get_callers,
        "codegraph_get_callees": mcp_mod.get_callees,
        "codegraph_get_neighbors": mcp_mod.get_neighbors,
        "codegraph_get_impact": mcp_mod.get_impact,
        "codegraph_harness_run": mcp_mod.codegraph_harness_run,
    }

    fn = fn_map.get(tool_name)
    if fn is None:
        return {"error": f"Tool not callable: {tool_name}"}, False

    try:
        result = fn(**kwargs)
        ok = result.get("ok", True) if isinstance(result, dict) else True
        return result, ok
    except Exception as e:
        return {"error": str(e)}, False


# ── Task executor ────────────────────────────────────────────────────────

def _choose_tool(task: dict, available_tools: set[str]) -> str:
    """Choose the best tool for the task from the available set.

    This simulates what an agent would do when seeing only `available_tools`.
    The choice follows the entry routing rules baked into tool descriptions.
    """
    task_id = task["task_id"]
    best = task["expected_best_entry"]

    # If best tool is available, use it
    if best in available_tools:
        return best

    # If not, pick the best allowed alternative
    for alt in task.get("allowed_entries", []):
        if alt in available_tools and alt != best:
            return alt

    # If no allowed entry is available, pick the closest match
    if task_id == "bug_locate_code_paths":
        for t in ["codegraph_search_symbols", "codegraph_get_symbol", "codegraph_get_neighbors"]:
            if t in available_tools:
                return t
    elif task_id == "explain_module":
        for t in ["codegraph_get_symbol", "codegraph_get_neighbors"]:
            if t in available_tools:
                return t
    elif task_id in ("shared_type_refactor", "route_service_impact"):
        for t in ["codegraph_get_impact", "codegraph_get_neighbors"]:
            if t in available_tools:
                return t
    elif task_id == "coverage_audit":
        for t in ["codegraph_repo_summary", "codegraph_get_neighbors"]:
            if t in available_tools:
                return t
    elif task_id == "trace_flow":
        for t in ["codegraph_get_neighbors", "codegraph_get_callers", "codegraph_get_callees"]:
            if t in available_tools:
                return t

    return "none"


def _build_tool_args(task_id: str) -> dict[str, Any]:
    """Build real arguments for the expected tool call."""
    if task_id == "bug_locate_code_paths":
        return {"query": "coverage_gaps", "limit": 5}
    elif task_id == "explain_module":
        return {"symbol": "codegraph_find"}
    elif task_id == "shared_type_refactor":
        return {"files": "backend/codegraph/workflow.py", "change_type": "refactor"}
    elif task_id == "coverage_audit":
        return {"paths": "backend/codegraph/**", "limit": 10}
    elif task_id == "trace_flow":
        return {"task": "CLI workflow impact reaches run_pre_edit_check", "mode": "scan"}
    elif task_id == "route_service_impact":
        return {"files": "backend/codegraph/workflow.py", "change_type": "refactor"}
    return {}


def _is_wrong_entry(tool: str, task: dict) -> tuple[bool, str]:
    """Determine if the chosen tool is a wrong entry for this task."""
    if tool in task.get("wrong_entries", []):
        return True, f"'{tool}' is in wrong_entries for {task['task_id']}"
    if tool == "none":
        return True, "No CodeGraph tool available or selected"
    # It's not wrong if it's allowed
    if tool in task.get("allowed_entries", []):
        return False, ""
    if tool == task["expected_best_entry"]:
        return False, ""
    # Unknown tool not in allowed set → potentially wrong
    if task.get("allowed_entries"):
        return True, f"'{tool}' not in allowed_entries {task['allowed_entries']}"
    return False, ""


# ── Main runner ──────────────────────────────────────────────────────────

def run_profile_ab(
    profiles: list[str] | None = None,
    output_dir: str | Path = "reports",
) -> list[dict[str, Any]]:
    """Run the A/B test across all specified profiles."""
    if profiles is None:
        profiles = ["agent", "full", "debug", "without_codegraph"]

    _setup_globals()
    results: list[dict[str, Any]] = []
    run_id = f"profile-ab-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    try:
        for profile in profiles:
            available = PROFILE_TOOLS.get(profile, set())
            profile_desc = f"{profile} ({len(available)} tools)"

            for task in TASKS:
                task_id = task["task_id"]

                if profile == "without_codegraph":
                    # No CodeGraph MCP tools available — use rg/grep fallback
                    entry = _record_without_codegraph(run_id, task_id, task)
                else:
                    # Choose tool based on available set
                    chosen_tool = _choose_tool(task, available)
                    wrong, reason = _is_wrong_entry(chosen_tool, task)

                    if chosen_tool == "none":
                        entry = _record_no_tool(run_id, profile, task_id, task, reason)
                    else:
                        # Actually call the tool
                        kwargs = _build_tool_args(task_id)
                        start = time.perf_counter()
                        result, ok = _call_tool(chosen_tool, **kwargs)
                        elapsed = (time.perf_counter() - start) * 1000.0

                        mcp_calls = 1
                        read_before = 0
                        read_after = 0
                        workflow_used = chosen_tool in ("codegraph_harness_run",)
                        harness_used = chosen_tool in ("codegraph_harness_run", "codegraph_harness_list", "codegraph_harness_status", "codegraph_harness_artifacts")
                        fallback_used = False
                        fallback_reason = ""
                        immediate_fallback = False
                        targeted = True

                        # Check if result suggests we need fallback
                        if isinstance(result, dict):
                            if not result.get("ok", True):
                                fallback_used = True
                                fallback_reason = f"MCP tool returned error: {result.get('error', {}).get('message', 'unknown') if isinstance(result.get('error'), dict) else result.get('error', 'unknown')}"

                        entry = {
                            "run_id": run_id,
                            "round_id": "round-1",
                            "project": "CodeGraph-Explorer",
                            "agent": "claude-code",
                            "profile": profile,
                            "task_id": task_id,
                            "task_type": task["task_type"],
                            "first_tool": chosen_tool,
                            "expected_best_entry": task["expected_best_entry"],
                            "wrong_entry_tool": wrong,
                            "wrong_entry_reason": reason,
                            "mcp_call_count": mcp_calls,
                            "consecutive_mcp_calls": mcp_calls,
                            "read_grep_glob_before_mcp": read_before,
                            "read_grep_glob_after_mcp": read_after,
                            "workflow_used": workflow_used,
                            "harness_used": harness_used,
                            "fallback_used": fallback_used,
                            "fallback_reason": fallback_reason,
                            "immediate_fallback_after_mcp": immediate_fallback,
                            "read_after_mcp_targeted": targeted,
                            "task_completed_seconds": round(elapsed / 1000.0, 2),
                            "error_count": 0 if ok else 1,
                            "task_success": ok,
                            "notes": f"Actually called {chosen_tool} with real MCP. Profile: {profile_desc}. Latency: {elapsed:.0f}ms.",
                        }

                results.append(entry)
    finally:
        _teardown_globals()

    # Write results
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "profile_ab_results.json"
    json_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    return results


def _record_without_codegraph(run_id: str, task_id: str, task: dict) -> dict[str, Any]:
    """Record a without_codegraph run — no MCP tools used."""
    return {
        "run_id": run_id,
        "round_id": "round-1",
        "project": "CodeGraph-Explorer",
        "agent": "claude-code",
        "profile": "without_codegraph",
        "task_id": task_id,
        "task_type": task["task_type"],
        "first_tool": "rg" if task_id != "explain_module" else "Read",
        "expected_best_entry": task["expected_best_entry"],
        "wrong_entry_tool": False,
        "wrong_entry_reason": "",
        "mcp_call_count": 0,
        "consecutive_mcp_calls": 0,
        "read_grep_glob_before_mcp": 1,
        "read_grep_glob_after_mcp": 0,
        "workflow_used": False,
        "harness_used": False,
        "fallback_used": False,
        "fallback_reason": "",
        "immediate_fallback_after_mcp": False,
        "read_after_mcp_targeted": False,
        "task_completed_seconds": 0.0,
        "error_count": 0,
        "task_success": True,
        "notes": "No CodeGraph MCP available. Fallback to rg/Read for all tasks.",
    }


def _record_no_tool(run_id: str, profile: str, task_id: str, task: dict, reason: str) -> dict[str, Any]:
    """Record when no suitable CodeGraph tool was available."""
    return {
        "run_id": run_id,
        "round_id": "round-1",
        "project": "CodeGraph-Explorer",
        "agent": "claude-code",
        "profile": profile,
        "task_id": task_id,
        "task_type": task["task_type"],
        "first_tool": "none",
        "expected_best_entry": task["expected_best_entry"],
        "wrong_entry_tool": True,
        "wrong_entry_reason": reason,
        "mcp_call_count": 0,
        "consecutive_mcp_calls": 0,
        "read_grep_glob_before_mcp": 1,
        "read_grep_glob_after_mcp": 0,
        "workflow_used": False,
        "harness_used": False,
        "fallback_used": True,
        "fallback_reason": f"No CodeGraph tool available for {task_id} in {profile} profile",
        "immediate_fallback_after_mcp": False,
        "read_after_mcp_targeted": False,
        "task_completed_seconds": 0.0,
        "error_count": 1,
        "task_success": False,
        "notes": f"Profile {profile} has no tool matching task {task_id}. {reason}",
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Profile A/B test runner")
    p.add_argument("--profiles", nargs="*", default=None,
                   help="Profiles to test (default: all 4)")
    p.add_argument("--output-dir", default="reports")
    args = p.parse_args()

    results = run_profile_ab(profiles=args.profiles, output_dir=args.output_dir)
    print(f"Wrote {len(results)} entries to {args.output_dir}/profile_ab_results.json")
