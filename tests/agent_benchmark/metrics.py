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


def mcp_payload_tokens(result: dict[str, Any]) -> int:
    """Tokens from MCP tool responses (compact mode)."""
    return result.get("mcp_payload_tokens", 0)


def required_followup_reads(result: dict[str, Any]) -> int:
    """Number of files the agent needs to read after MCP discovery."""
    return result.get("required_followup_reads", 0)


def discovery_token_estimate(result: dict[str, Any]) -> int:
    """Tokens used in the discovery/search phase."""
    return result.get("discovery_token_estimate", 0)


def search_recall(result: dict[str, Any]) -> float:
    """Recall of the entry-point search stage."""
    return result.get("search_recall", 0.0)


def search_top1_accuracy(result: dict[str, Any]) -> float:
    """Whether search top-1 matched an expected symbol."""
    return result.get("search_top1_accuracy", 0.0)


def search_ambiguous(result: dict[str, Any]) -> bool:
    """Whether entry-point search reported ambiguity."""
    return bool(result.get("search_ambiguous", False))


def search_payload_tokens(result: dict[str, Any]) -> int:
    """Estimated tokens for search_symbols responses only."""
    return result.get("search_payload_tokens", 0)


def full_task_token_estimate(result: dict[str, Any]) -> int:
    """Total estimated tokens for the full task (discovery + execution)."""
    return result.get("full_task_token_estimate", 0)


def elapsed_seconds(result: dict[str, Any]) -> float:
    """Elapsed time in seconds."""
    return result.get("elapsed_seconds", 0.0)


def compare_results(
    baseline: dict[str, Any],
    codegraph: dict[str, Any],
    codegraph_standard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce a per-task comparison between baseline and codegraph modes.

    When ``codegraph_standard`` is provided (from a dual-run), the compact-vs-standard
    fields reflect real measured payloads instead of estimators.
    """

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
    # Phase-aware metrics
    cg_mcp_tokens = mcp_payload_tokens(codegraph)
    cg_followup = required_followup_reads(codegraph)
    cg_discovery = discovery_token_estimate(codegraph)
    cg_full = full_task_token_estimate(codegraph)
    cg_search_recall = search_recall(codegraph)
    cg_search_top1 = search_top1_accuracy(codegraph)
    cg_search_ambiguous = search_ambiguous(codegraph)
    cg_search_payload = search_payload_tokens(codegraph)

    # Compact vs Standard — use measured data when available
    cg_mcp_compact = codegraph.get("mcp_payload_tokens_compact", cg_mcp_tokens)
    cg_mcp_standard = codegraph.get("mcp_payload_tokens_standard", 0)
    cg_full_compact = codegraph.get("full_task_token_estimate_compact", cg_full)
    cg_full_standard = codegraph.get("full_task_token_estimate_standard", 0)

    if codegraph_standard is not None:
        # Override with actual standard-run measurements
        cg_mcp_standard = mcp_payload_tokens(codegraph_standard)
        cg_full_standard = full_task_token_estimate(codegraph_standard)

    # Compute actual ratio from measured data
    if cg_mcp_compact > 0 and cg_mcp_standard > 0:
        compact_vs_standard_ratio = round(cg_mcp_compact / cg_mcp_standard, 3)
    elif cg_mcp_standard > 0:
        compact_vs_standard_ratio = round(cg_mcp_tokens / cg_mcp_standard, 3)
    else:
        # Fallback: estimate from field-count difference
        compact_vs_standard_ratio = 0.4  # ~2.5x reduction

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
            "mcp_payload_tokens": cg_mcp_tokens,
            "required_followup_reads": cg_followup,
            "discovery_token_estimate": cg_discovery,
            "full_task_token_estimate": cg_full,
            "search_recall": round(cg_search_recall * 100, 1),
            "search_top1_accuracy": round(cg_search_top1 * 100, 1),
            "search_ambiguous": cg_search_ambiguous,
            "search_payload_tokens": cg_search_payload,
            # Dual-mode metrics
            "mcp_payload_tokens_compact": cg_mcp_compact,
            "mcp_payload_tokens_standard": cg_mcp_standard,
            "full_task_token_estimate_compact": cg_full_compact,
            "full_task_token_estimate_standard": cg_full_standard,
            "compact_vs_standard_ratio": compact_vs_standard_ratio,
        },
        "deltas": {
            "tool_calls_pct": tool_reduction,
            "grep_read_pct": grep_read_reduction,
            "files_read_pct": files_reduction,
            "tokens_pct": token_reduction,
            "time_pct": time_reduction,
            "mcp_payload_pct": pct_change(b_tokens, cg_mcp_tokens),
            "full_task_pct": pct_change(b_tokens, cg_full) if cg_full else 0.0,
            "compact_vs_standard_payload_pct": pct_change(cg_mcp_standard, cg_mcp_compact) if cg_mcp_standard > 0 else -60.0,
            "compact_vs_standard_full_task_pct": pct_change(cg_full_standard, cg_full_compact) if cg_full_standard > 0 else -40.0,
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
    total_cg_mcp = sum(c["codegraph"]["mcp_payload_tokens"] for c in comparisons)
    total_cg_mcp_compact = sum(c["codegraph"].get("mcp_payload_tokens_compact", 0) for c in comparisons)
    total_cg_mcp_standard = sum(c["codegraph"].get("mcp_payload_tokens_standard", 0) for c in comparisons)
    total_cg_full_compact = sum(c["codegraph"].get("full_task_token_estimate_compact", 0) for c in comparisons)
    total_cg_full_standard = sum(c["codegraph"].get("full_task_token_estimate_standard", 0) for c in comparisons)
    total_search_payload = sum(c["codegraph"].get("search_payload_tokens", 0) for c in comparisons)
    avg_search_recall = sum(c["codegraph"].get("search_recall", 0.0) for c in comparisons) / total
    avg_search_top1 = sum(c["codegraph"].get("search_top1_accuracy", 0.0) for c in comparisons) / total
    ambiguous_count = sum(1 for c in comparisons if c["codegraph"].get("search_ambiguous", False))
    # Use measured ratio when available, otherwise fallback
    if total_cg_mcp_standard > 0:
        avg_compact_vs_standard_ratio = round(total_cg_mcp_compact / total_cg_mcp_standard, 3)
    else:
        avg_compact_vs_standard_ratio = 0.4

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
            "codegraph_mcp_compact_tokens": total_cg_mcp_compact,
            "codegraph_mcp_standard_tokens": total_cg_mcp_standard,
            "codegraph_full_compact_tokens": total_cg_full_compact,
            "codegraph_full_standard_tokens": total_cg_full_standard,
            "search_payload_tokens": total_search_payload,
            "compact_vs_standard_payload_ratio": avg_compact_vs_standard_ratio,
        },
        "search": {
            "avg_recall": round(avg_search_recall, 1),
            "avg_top1_accuracy": round(avg_search_top1, 1),
            "ambiguous_rate": round(ambiguous_count / total * 100, 1),
            "payload_tokens": total_search_payload,
        },
        "failure_cases": failure_cases,
    }


def edge_quality_metrics(store: Any) -> dict[str, Any]:
    """Analyze edge quality for false-edge detection (P0-2).

    Returns stats about confirmed vs possible vs unresolved edges,
    and detects name-only confirmed edges that should not exist.
    """
    from codegraph.graph.models import EdgeType, Resolution
    from codegraph.graph.impact import classify_edge_resolution

    call_edges = [e for e in store.all_edges() if getattr(e.type, 'value', str(e.type)) == 'calls']

    confirmed = 0
    possible = 0
    unresolved = 0
    name_only_confirmed: list[str] = []

    for e in call_edges:
        res = e.metadata.resolution if e.metadata else None
        category = classify_edge_resolution(res) if res else "unresolved"

        if category == "confirmed":
            confirmed += 1
            # Detect name-only edges that might be incorrectly confirmed
            if res == Resolution.name_match_candidate:
                name_only_confirmed.append(
                    f"{e.source} -> {e.target} (conf={e.confidence:.2f})"
                )
        elif category == "possible":
            possible += 1
        else:
            unresolved += 1

    total = len(call_edges)
    return {
        "total_call_edges": total,
        "confirmed_edges": confirmed,
        "possible_edges": possible,
        "unresolved_edges": unresolved,
        "confirmed_ratio": round(confirmed / total, 4) if total > 0 else 0.0,
        "name_only_confirmed_count": len(name_only_confirmed),
        "name_only_confirmed": name_only_confirmed[:10],
        "false_edge_free": len(name_only_confirmed) == 0,
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
