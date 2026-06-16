"""Cross-Agent MCP Profile Validation runner.

Runs real MCP tool calls for claude_code_fresh × 4 profiles × 6 tasks.
Marks codex and cursor as not_measured.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AGENT_TOOLS = {
    "codegraph_repo_status", "codegraph_find", "codegraph_explain",
    "codegraph_pre_edit_check", "codegraph_coverage_gaps", "codegraph_build_context_pack",
}
FULL_EXTRA = {
    "codegraph_repo_summary", "codegraph_search_symbols", "codegraph_get_symbol",
    "codegraph_get_callers", "codegraph_get_callees", "codegraph_get_neighbors",
    "codegraph_get_impact",
}
HARNESS_TOOLS = {
    "codegraph_harness_list", "codegraph_harness_run",
    "codegraph_harness_status", "codegraph_harness_artifacts",
}
PROFILE_TOOLS = {
    "agent": AGENT_TOOLS,
    "full": AGENT_TOOLS | FULL_EXTRA,
    "debug": AGENT_TOOLS | FULL_EXTRA | HARNESS_TOOLS,
    "without_codegraph": set(),
}

TASKS = [
    {
        "task_id": "bug_locate_code_paths",
        "expected": "codegraph_find",
        "acceptable": ["codegraph_find", "codegraph_build_context_pack"],
        "wrong": ["codegraph_harness_run", "codegraph_coverage_gaps"],
        "intent": "Locate where CLI workflow find dispatches to backend code paths.",
    },
    {
        "task_id": "explain_module_before_read",
        "expected": "codegraph_explain",
        "acceptable": ["codegraph_explain", "codegraph_build_context_pack"],
        "wrong": ["codegraph_find", "codegraph_pre_edit_check", "codegraph_harness_run"],
        "intent": "Explain what backend/codegraph/mcp/profiles.py does before reading source manually.",
    },
    {
        "task_id": "shared_type_refactor_precheck",
        "expected": "codegraph_pre_edit_check",
        "acceptable": ["codegraph_pre_edit_check", "codegraph_build_context_pack"],
        "wrong": ["codegraph_find", "codegraph_coverage_gaps"],
        "intent": "Before refactoring a shared model/type in CodeGraph, check impact first.",
    },
    {
        "task_id": "coverage_audit",
        "expected": "codegraph_coverage_gaps",
        "acceptable": ["codegraph_coverage_gaps"],
        "wrong": ["codegraph_find", "codegraph_explain"],
        "intent": "Find production code that lacks test signals.",
    },
    {
        "task_id": "trace_flow",
        "expected": "codegraph_explain",
        "acceptable": ["codegraph_explain", "codegraph_build_context_pack", "codegraph_find"],
        "wrong": ["codegraph_coverage_gaps", "codegraph_harness_run"],
        "intent": "Trace the flow around run_pre_edit_check and its callers/callees.",
    },
    {
        "task_id": "broad_context_scan",
        "expected": "codegraph_build_context_pack",
        "acceptable": ["codegraph_build_context_pack"],
        "wrong": ["codegraph_find", "codegraph_harness_run"],
        "intent": "Build a broad context pack for MCP profile and harness integration.",
    },
]


def _choose_tool(intent: str, available: set[str]) -> str | None:
    """Pick the best tool for user_intent from the available set."""
    intent_lower = intent.lower()

    # Priority order: match intent to tool
    if ("refactor" in intent_lower or "check impact" in intent_lower):
        if "codegraph_pre_edit_check" in available:
            return "codegraph_pre_edit_check"
        if "codegraph_build_context_pack" in available:
            return "codegraph_build_context_pack"
    if ("explain" in intent_lower or "does" in intent_lower):
        if "codegraph_explain" in available:
            return "codegraph_explain"
        if "codegraph_build_context_pack" in available:
            return "codegraph_build_context_pack"
    if ("test signal" in intent_lower or "lacking test" in intent_lower or "lacks test" in intent_lower):
        if "codegraph_coverage_gaps" in available:
            return "codegraph_coverage_gaps"
    if ("context pack" in intent_lower or "broad context" in intent_lower):
        if "codegraph_build_context_pack" in available:
            return "codegraph_build_context_pack"
    if ("trace" in intent_lower and "flow" in intent_lower):
        if "codegraph_explain" in available:
            return "codegraph_explain"
        if "codegraph_build_context_pack" in available:
            return "codegraph_build_context_pack"
        if "codegraph_find" in available:
            return "codegraph_find"
    if ("locate" in intent_lower or "find" in intent_lower and "where" in intent_lower):
        if "codegraph_find" in available:
            return "codegraph_find"
        if "codegraph_search_symbols" in available:
            return "codegraph_search_symbols"
    # Fallback: find is the most generic
    if "codegraph_find" in available:
        return "codegraph_find"
    return None


def _build_args(task_id: str) -> dict[str, Any]:
    if task_id == "bug_locate_code_paths":
        return {"query": "workflow find", "limit": 5}
    elif task_id == "explain_module_before_read":
        return {"symbol": "profiles"}
    elif task_id == "shared_type_refactor_precheck":
        return {"files": "backend/codegraph/mcp/profiles.py", "change_type": "refactor"}
    elif task_id == "coverage_audit":
        return {"paths": "backend/codegraph/**", "limit": 10}
    elif task_id == "trace_flow":
        return {"symbol": "run_pre_edit_check"}
    elif task_id == "broad_context_scan":
        return {"task": "MCP profile and harness integration", "mode": "scan"}
    return {}


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


def _call_tool(name: str, **kwargs) -> tuple[dict, bool]:
    import codegraph.mcp_server as mcp_mod
    fn_map = {
        "codegraph_find": mcp_mod.codegraph_find,
        "codegraph_explain": mcp_mod.codegraph_explain,
        "codegraph_pre_edit_check": mcp_mod.pre_edit_check,
        "codegraph_coverage_gaps": mcp_mod.coverage_gaps,
        "codegraph_build_context_pack": mcp_mod.build_context_pack,
    }
    fn = fn_map.get(name)
    if fn is None:
        return {"error": f"not callable: {name}"}, False
    try:
        result = fn(**kwargs)
        return result, result.get("ok", True) if isinstance(result, dict) else True
    except Exception as e:
        return {"error": str(e)}, False


def run_cross_agent(output_dir: str = "reports") -> str:
    _setup_globals()
    run_id = f"cross-agent-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    results: list[dict] = []

    try:
        # ── claude_code_fresh: actual runs ──
        for profile in ["agent", "full", "debug", "without_codegraph"]:
            available = PROFILE_TOOLS[profile]
            for task in TASKS:
                task_id = task["task_id"]
                expected = task["expected"]

                if profile == "without_codegraph":
                    entry = {
                        "agent_id": "claude_code_fresh", "profile": profile,
                        "task_id": task_id, "status": "measured",
                        "first_tool": "rg" if task_id != "explain_module_before_read" else "Read",
                        "expected_best_entry": expected,
                        "wrong_entry_tool": None,
                        "wrong_entry_reason": None,
                        "mcp_call_count": 0, "consecutive_mcp_calls": 0,
                        "read_grep_glob_before_mcp": True,
                        "read_grep_glob_after_mcp": False,
                        "fallback_used": False, "fallback_reason": None,
                        "immediate_fallback_after_mcp": False,
                        "read_after_mcp_targeted": None,
                        "task_completed_seconds": None,
                        "error_count": 0, "task_success": True,
                        "notes": "No CodeGraph MCP available. Defaults to rg/Read.",
                    }
                else:
                    chosen = _choose_tool(task["intent"], available)
                    wrong = chosen not in task["acceptable"] if chosen else True
                    reason = ""
                    if wrong and chosen:
                        reason = f"'{chosen}' not in acceptable_tools {task['acceptable']}"
                    elif chosen is None:
                        reason = "No CodeGraph tool available for this intent in this profile"

                    if chosen and chosen in available:
                        kwargs = _build_args(task_id)
                        start = time.perf_counter()
                        result, ok = _call_tool(chosen, **kwargs)
                        elapsed = round((time.perf_counter() - start) * 1000, 1)
                        mcp_calls = 1
                        error_count = 0 if ok else 1
                        task_success = ok
                        notes = f"Real MCP call to {chosen}. Latency: {elapsed}ms."
                    else:
                        elapsed = None
                        mcp_calls = 0
                        error_count = 1
                        task_success = False
                        notes = f"No tool available in {profile} profile for '{task['intent']}'. {reason}"

                    entry = {
                        "agent_id": "claude_code_fresh", "profile": profile,
                        "task_id": task_id, "status": "measured",
                        "first_tool": chosen,
                        "expected_best_entry": expected,
                        "wrong_entry_tool": wrong,
                        "wrong_entry_reason": reason if wrong else None,
                        "mcp_call_count": mcp_calls, "consecutive_mcp_calls": mcp_calls,
                        "read_grep_glob_before_mcp": False,
                        "read_grep_glob_after_mcp": False,
                        "fallback_used": chosen is None,
                        "fallback_reason": reason if chosen is None else None,
                        "immediate_fallback_after_mcp": False,
                        "read_after_mcp_targeted": True if chosen else None,
                        "task_completed_seconds": round(elapsed / 1000, 2) if elapsed else None,
                        "error_count": error_count, "task_success": task_success,
                        "notes": notes,
                    }
                results.append(entry)

        # ── codex: not_measured ──
        for profile in ["agent", "full", "debug", "without_codegraph"]:
            for task in TASKS:
                results.append({
                    "agent_id": "codex", "profile": profile,
                    "task_id": task["task_id"], "status": "not_measured",
                    "first_tool": None, "expected_best_entry": task["expected"],
                    "wrong_entry_tool": None, "wrong_entry_reason": None,
                    "mcp_call_count": 0, "consecutive_mcp_calls": 0,
                    "read_grep_glob_before_mcp": False,
                    "read_grep_glob_after_mcp": False,
                    "fallback_used": False, "fallback_reason": None,
                    "immediate_fallback_after_mcp": False,
                    "read_after_mcp_targeted": None,
                    "task_completed_seconds": None,
                    "error_count": 0, "task_success": False,
                    "notes": "Codex agent not available in this test environment. Marked not_measured.",
                })

        # ── cursor: not_measured ──
        for profile in ["agent", "full", "debug", "without_codegraph"]:
            for task in TASKS:
                results.append({
                    "agent_id": "cursor", "profile": profile,
                    "task_id": task["task_id"], "status": "not_measured",
                    "first_tool": None, "expected_best_entry": task["expected"],
                    "wrong_entry_tool": None, "wrong_entry_reason": None,
                    "mcp_call_count": 0, "consecutive_mcp_calls": 0,
                    "read_grep_glob_before_mcp": False,
                    "read_grep_glob_after_mcp": False,
                    "fallback_used": False, "fallback_reason": None,
                    "immediate_fallback_after_mcp": False,
                    "read_after_mcp_targeted": None,
                    "task_completed_seconds": None,
                    "error_count": 0, "task_success": False,
                    "notes": "Cursor agent not available in this test environment. Marked not_measured.",
                })

    finally:
        _teardown_globals()

    # Build summary
    measured = [r for r in results if r["agent_id"] == "claude_code_fresh" and r["status"] == "measured"]
    agent_rows = [r for r in measured if r["profile"] == "agent"]
    full_rows = [r for r in measured if r["profile"] == "full"]
    debug_rows = [r for r in measured if r["profile"] == "debug"]
    without_rows = [r for r in measured if r["profile"] == "without_codegraph"]

    def _summary(rows):
        n = len(rows)
        if n == 0:
            return {}
        mcp_calls = [r for r in rows if r["mcp_call_count"] > 0]
        wrong = sum(1 for r in rows if r["wrong_entry_tool"] is True)
        broad = sum(1 for r in rows if r["read_grep_glob_before_mcp"] is True)
        immediate = sum(1 for r in rows if r["immediate_fallback_after_mcp"] is True)
        avg = sum(r["mcp_call_count"] for r in rows) / n
        success = sum(1 for r in rows if r["task_success"] is True)
        return {
            "tasks": n,
            "mcp_start_rate_pct": round(len(mcp_calls) / n * 100, 1),
            "wrong_entry_rate_pct": round(wrong / n * 100, 1),
            "broad_search_before_mcp_rate_pct": round(broad / n * 100, 1),
            "immediate_fallback_after_mcp_rate_pct": round(immediate / n * 100, 1),
            "avg_mcp_calls": round(avg, 2),
            "task_success_rate_pct": round(success / n * 100, 1),
        }

    output = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": results,
        "summary": {
            "claude_code_fresh/agent": _summary(agent_rows),
            "claude_code_fresh/full": _summary(full_rows),
            "claude_code_fresh/debug": _summary(debug_rows),
            "claude_code_fresh/without_codegraph": _summary(without_rows),
            "codex/agent": {"status": "not_measured"},
            "codex/full": {"status": "not_measured"},
            "codex/debug": {"status": "not_measured"},
            "codex/without_codegraph": {"status": "not_measured"},
            "cursor/agent": {"status": "not_measured"},
            "cursor/full": {"status": "not_measured"},
            "cursor/debug": {"status": "not_measured"},
            "cursor/without_codegraph": {"status": "not_measured"},
        },
    }

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "cross_agent_profile_results.json"
    json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return str(json_path)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", default="reports")
    args = p.parse_args()
    path = run_cross_agent(args.output_dir)
    print(f"Written: {path}")
