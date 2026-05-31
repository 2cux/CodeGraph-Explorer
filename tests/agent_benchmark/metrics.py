"""Metrics calculation for agent benchmark results.

Calculates recall, precision, tool call reduction, file read reduction,
token reduction, and comparison scores between baseline and codegraph modes.
"""

from __future__ import annotations

from typing import Any, Mapping


def symbol_recall(result: dict[str, Any]) -> float:
    """Fraction of expected symbols that were found."""
    expected_count = len(
        result.get("found_expected_symbols", [])
    ) + len(result.get("missing_expected", []))
    if expected_count == 0:
        return 1.0
    # Since missing_expected tracks files, compute proper recall
    found = len(result.get("found_expected_symbols", []))
    if found == 0 and expected_count > 0:
        # Use file-based recall as fallback
        return file_recall(result)
    total_expected = found + len(result.get("missing_expected", []))
    if total_expected == 0:
        return 1.0
    return found / total_expected


def file_recall(result: dict[str, Any]) -> float:
    """Fraction of expected files that were found."""
    found = len(result.get("found_expected_files", []))
    missing = len(result.get("missing_expected", []))
    total = found + missing
    if total == 0:
        return 1.0
    return found / total


def grep_read_calls(result: dict[str, Any]) -> int:
    """Number of grep + glob + read calls."""
    tc = result.get("tool_calls", {})
    return tc.get("grep", 0) + tc.get("glob", 0) + tc.get("read", 0)


def total_tool_calls(result: dict[str, Any]) -> int:
    """Total tool call count."""
    return result.get("tool_calls", {}).get("total", 0)


def files_read_count(result: dict[str, Any]) -> int:
    """Number of files read."""
    return result.get("files_read_count", 0)


def estimated_tokens(result: dict[str, Any]) -> int:
    """Estimated token consumption."""
    return result.get("estimated_tokens", 0)


def elapsed_seconds(result: dict[str, Any]) -> float:
    """Elapsed time in seconds."""
    return result.get("elapsed_seconds", 0.0)


def compare_results(
    baseline: dict[str, Any],
    codegraph: dict[str, Any],
) -> dict[str, Any]:
    """Produce a per-task comparison between baseline and codegraph modes."""

    b_tools = total_tool_calls(baseline)
    cg_tools = total_tool_calls(codegraph)
    b_grep_read = grep_read_calls(baseline)
    cg_grep_read = grep_read_calls(codegraph)
    b_files = files_read_count(baseline)
    cg_files = files_read_count(codegraph)
    b_tokens = estimated_tokens(baseline)
    cg_tokens = estimated_tokens(codegraph)
    b_recall = file_recall(baseline)
    cg_recall = file_recall(codegraph)
    b_time = elapsed_seconds(baseline)
    cg_time = elapsed_seconds(codegraph)

    def pct_change(old: float, new: float) -> float:
        if old == 0:
            return 0.0 if new == 0 else -100.0
        return round((new - old) / old * 100, 1)

    tool_reduction = pct_change(b_tools, cg_tools)
    grep_read_reduction = pct_change(b_grep_read, cg_grep_read)
    files_reduction = pct_change(b_files, cg_files)
    token_reduction = pct_change(b_tokens, cg_tokens)
    time_reduction = pct_change(b_time, cg_time)

    # Pre-compute pass/fail for filter conditions
    recall_ok = cg_recall >= b_recall
    grep_read_ok = cg_grep_read <= b_grep_read
    files_ok = cg_files <= b_files
    tokens_ok = cg_tokens <= b_tokens

    return {
        "task_id": baseline["task_id"],
        "category": baseline.get("category", ""),
        "task": baseline.get("task", ""),
        "baseline": {
            "tool_calls": b_tools,
            "grep_read_calls": b_grep_read,
            "files_read": b_files,
            "tokens": b_tokens,
            "time_s": b_time,
            "file_recall": round(b_recall * 100, 1),
        },
        "codegraph": {
            "tool_calls": cg_tools,
            "grep_read_calls": cg_grep_read,
            "files_read": cg_files,
            "tokens": cg_tokens,
            "time_s": cg_time,
            "file_recall": round(cg_recall * 100, 1),
        },
        "deltas": {
            "tool_calls_pct": tool_reduction,
            "grep_read_pct": grep_read_reduction,
            "files_read_pct": files_reduction,
            "tokens_pct": token_reduction,
            "time_pct": time_reduction,
        },
        "quality": {
            "recall_ok": recall_ok,
            "grep_read_ok": grep_read_ok,
            "files_ok": files_ok,
            "tokens_ok": tokens_ok,
        },
        "failure_cases": _analyze_failures(baseline, codegraph),
    }


def aggregate_summary(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate comparison results across all tasks."""
    if not comparisons:
        return {}

    total = len(comparisons)
    recall_ok = sum(1 for c in comparisons if c["quality"]["recall_ok"])
    grep_ok = sum(1 for c in comparisons if c["quality"]["grep_read_ok"])
    files_ok = sum(1 for c in comparisons if c["quality"]["files_ok"])
    tokens_ok = sum(1 for c in comparisons if c["quality"]["tokens_ok"])

    avg_tool_reduction = sum(c["deltas"]["tool_calls_pct"] for c in comparisons) / total
    avg_grep_reduction = sum(c["deltas"]["grep_read_pct"] for c in comparisons) / total
    avg_files_reduction = sum(c["deltas"]["files_read_pct"] for c in comparisons) / total
    avg_token_reduction = sum(c["deltas"]["tokens_pct"] for c in comparisons) / total
    avg_time_reduction = sum(c["deltas"]["time_pct"] for c in comparisons) / total

    total_b_tokens = sum(c["baseline"]["tokens"] for c in comparisons)
    total_cg_tokens = sum(c["codegraph"]["tokens"] for c in comparisons)
    total_b_files = sum(c["baseline"]["files_read"] for c in comparisons)
    total_cg_files = sum(c["codegraph"]["files_read"] for c in comparisons)
    total_b_tools = sum(c["baseline"]["tool_calls"] for c in comparisons)
    total_cg_tools = sum(c["codegraph"]["tool_calls"] for c in comparisons)
    total_b_grep = sum(c["baseline"]["grep_read_calls"] for c in comparisons)
    total_cg_grep = sum(c["codegraph"]["grep_read_calls"] for c in comparisons)

    # Collect failure cases
    failure_cases: list[dict[str, Any]] = []
    for c in comparisons:
        if c.get("failure_cases"):
            failure_cases.extend(
                {"task_id": c["task_id"], **f} for f in c["failure_cases"]
            )

    return {
        "total_tasks": total,
        "pass_rates": {
            "recall_ok": f"{recall_ok}/{total}",
            "grep_read_ok": f"{grep_ok}/{total}",
            "files_ok": f"{files_ok}/{total}",
            "tokens_ok": f"{tokens_ok}/{total}",
        },
        "avg_deltas": {
            "tool_calls_pct": round(avg_tool_reduction, 1),
            "grep_read_pct": round(avg_grep_reduction, 1),
            "files_read_pct": round(avg_files_reduction, 1),
            "tokens_pct": round(avg_token_reduction, 1),
            "time_pct": round(avg_time_reduction, 1),
        },
        "aggregate_totals": {
            "baseline_tools": total_b_tools,
            "codegraph_tools": total_cg_tools,
            "baseline_grep_read": total_b_grep,
            "codegraph_grep_read": total_cg_grep,
            "baseline_files_read": total_b_files,
            "codegraph_files_read": total_cg_files,
            "baseline_tokens": total_b_tokens,
            "codegraph_tokens": total_cg_tokens,
        },
        "failure_cases": failure_cases,
    }


def _analyze_failures(
    baseline: dict[str, Any],
    codegraph: dict[str, Any],
) -> list[dict[str, Any]]:
    """Identify specific failure reasons for a task."""
    failures: list[dict[str, Any]] = []

    b_recall = file_recall(baseline)
    cg_recall = file_recall(codegraph)
    if cg_recall < b_recall:
        failures.append({
            "type": "recall_degraded",
            "reason": "CodeGraph file recall worse than baseline",
            "baseline_recall": round(b_recall * 100),
            "codegraph_recall": round(cg_recall * 100),
        })

    missing = codegraph.get("missing_expected", [])
    if missing:
        failures.append({
            "type": "missing_expected_files",
            "reason": "Expected files not found by CodeGraph",
            "missing": missing[:10],
        })

    cg_files = files_read_count(codegraph)
    b_files = files_read_count(baseline)
    if cg_files > b_files and b_files > 0:
        failures.append({
            "type": "files_read_increase",
            "reason": "CodeGraph read more files than baseline",
            "baseline_files": b_files,
            "codegraph_files": cg_files,
        })

    cg_tokens = estimated_tokens(codegraph)
    b_tokens = estimated_tokens(baseline)
    if cg_tokens > b_tokens and b_tokens > 0:
        failures.append({
            "type": "token_increase",
            "reason": "CodeGraph used more tokens than baseline",
            "baseline_tokens": b_tokens,
            "codegraph_tokens": cg_tokens,
        })

    notes = codegraph.get("notes", [])
    for note in notes:
        failures.append({"type": "note", "reason": str(note)})

    return failures
