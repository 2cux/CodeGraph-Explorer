"""MCP + Harness performance benchmark runner.

Measures latency, response size, and artifact bytes for:

* direct_mcp  — MCP tool function called directly (no harness)
* harness_mcp — MCP tool routed through codegraph_harness_run with persist=true

Outputs:
    reports/mcp_harness_perf.json   — raw latency results (schema-compliant)
    reports/mcp_harness_perf.md     — human-readable performance report

Usage::

    python -m codegraph.harness.perf_benchmark [--iterations 5] [--output-dir reports]

No external LLM, no destructive writes, no network calls.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Benchmark case definition ──────────────────────────────────────────────

BENCHMARK_CASES: list[dict[str, Any]] = [
    # ── direct_mcp ──
    {
        "case_id": "direct_find_basic",
        "mode": "direct_mcp",
        "tool": "codegraph_find",
        "input": {"query": "workflow", "limit": 5},
    },
    {
        "case_id": "direct_explain_symbol",
        "mode": "direct_mcp",
        "tool": "codegraph_explain",
        "input": {"symbol": "run_pre_edit_check"},
    },
    {
        "case_id": "direct_pre_edit_file",
        "mode": "direct_mcp",
        "tool": "codegraph_pre_edit_check",
        "input": {
            "files": "backend/codegraph/workflow.py",
            "change_type": "refactor",
        },
    },
    {
        "case_id": "direct_coverage_gaps",
        "mode": "direct_mcp",
        "tool": "codegraph_coverage_gaps",
        "input": {"paths": "backend/codegraph/**", "limit": 20},
    },
    {
        "case_id": "direct_impact_symbol",
        "mode": "direct_mcp",
        "tool": "codegraph_get_impact",
        "input": {"symbol": "run_pre_edit_check"},
    },
    {
        "case_id": "direct_context_scan",
        "mode": "direct_mcp",
        "tool": "codegraph_build_context_pack",
        "input": {"task": "workflow impact", "mode": "scan"},
    },
    # ── harness_mcp ──
    {
        "case_id": "harness_workflow_find",
        "mode": "harness_mcp",
        "tool": "codegraph_harness_run",
        "input": {
            "module_id": "workflow.find",
            "input": {"query": "workflow", "limit": 5},
            "persist": True,
        },
    },
    {
        "case_id": "harness_workflow_impact",
        "mode": "harness_mcp",
        "tool": "codegraph_harness_run",
        "input": {
            "module_id": "workflow.impact",
            "input": {
                "files": ["backend/codegraph/workflow.py"],
                "change_type": "refactor",
            },
            "persist": True,
        },
    },
    {
        "case_id": "harness_workflow_test_audit",
        "mode": "harness_mcp",
        "tool": "codegraph_harness_run",
        "input": {
            "module_id": "workflow.test_audit",
            "input": {"paths": ["backend/codegraph/**"], "limit": 20},
            "persist": True,
        },
    },
    {
        "case_id": "harness_workflow_explain",
        "mode": "harness_mcp",
        "tool": "codegraph_harness_run",
        "input": {
            "module_id": "workflow.explain",
            "input": {"symbol": "run_pre_edit_check"},
            "persist": True,
        },
    },
]

# ── Thresholds ─────────────────────────────────────────────────────────────

THRESHOLDS: dict[str, Any] = {
    "find_explain_p95_ms": 1000,
    "impact_test_audit_p95_ms": 3000,
    "harness_overhead_p50_ms": 100,
}

SLOW_TOOLS = {
    "codegraph_get_impact": "impact",
    "codegraph_harness_run": "depends_on_module",
}


def _classify_case(case_id: str) -> str:
    """Return 'fast' or 'slow' based on case_id heuristic."""
    slow_keywords = ["impact", "test_audit"]
    for kw in slow_keywords:
        if kw in case_id:
            return "slow"
    return "fast"


# ── Tool dispatcher ────────────────────────────────────────────────────────


def _call_direct_mcp(tool: str, input_data: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool function directly (in-process, no stdio)."""
    import codegraph.mcp_server as mcp_mod

    fn_map: dict[str, Any] = {
        "codegraph_find": mcp_mod.codegraph_find,
        "codegraph_explain": mcp_mod.codegraph_explain,
        "codegraph_pre_edit_check": mcp_mod.pre_edit_check,
        "codegraph_coverage_gaps": mcp_mod.coverage_gaps,
        "codegraph_get_impact": mcp_mod.get_impact,
        "codegraph_build_context_pack": mcp_mod.build_context_pack,
    }

    fn = fn_map.get(tool)
    if fn is None:
        raise ValueError(f"Unknown direct_mcp tool: {tool}")
    return fn(**input_data)


def _call_harness_mcp(input_data: dict[str, Any]) -> dict[str, Any]:
    """Call run_harness_module and return the MCP-style result."""
    from codegraph.harness.mcp_tools import run_harness_module
    from codegraph.harness.store import RunStore

    module_id = input_data["module_id"]
    module_input = input_data.get("input") or {}
    persist = input_data.get("persist", True)

    project_root = Path.cwd()
    mcp_result = run_harness_module(
        module_id=module_id,
        input_data=module_input,
        persist=persist,
        project_root=project_root,
    )

    # Measure artifact bytes written
    artifact_bytes = 0
    run_id = mcp_result.get("run_id", "")
    if run_id:
        store = RunStore(project_root=project_root)
        artifacts_dir = store.artifacts_dir(run_id)
        if artifacts_dir.exists():
            for f in artifacts_dir.iterdir():
                if f.is_file():
                    try:
                        artifact_bytes += f.stat().st_size
                    except OSError:
                        pass

    mcp_result["_artifact_bytes_written"] = artifact_bytes
    mcp_result["_run_dir_created"] = bool(run_id and store.base_dir.joinpath(run_id).exists())
    return mcp_result


def _call_tool(case: dict[str, Any]) -> tuple[dict[str, Any], int, bool]:
    """Execute one benchmark case. Returns (result_dict, latency_ms, ok)."""
    mode = case["mode"]
    tool = case["tool"]
    input_data = dict(case.get("input", {}))

    start = time.perf_counter()
    error_text = ""
    result: dict[str, Any] = {}
    ok = True

    try:
        if mode == "direct_mcp":
            result = _call_direct_mcp(tool, input_data)
        elif mode == "harness_mcp":
            result = _call_harness_mcp(input_data)
        else:
            raise ValueError(f"Unknown benchmark mode: {mode}")
    except Exception as exc:
        ok = False
        error_text = f"{type(exc).__name__}: {exc}"

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return result, elapsed_ms, ok, error_text


def _response_bytes(result: dict[str, Any]) -> int:
    """Approximate on-wire size of the MCP response."""
    try:
        return len(json.dumps(result, default=str, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return 0


# ── Benchmark runner ───────────────────────────────────────────────────────


def setup_mcp_globals(project_root: Path | None = None) -> Path:
    """Initialize MCP module globals so direct tool calls work in-process."""
    import codegraph.mcp_server as mcp_mod
    from codegraph.graph.store import GraphStore

    root = project_root or Path.cwd()
    cg_dir = root / ".codegraph"

    store = GraphStore()
    try:
        graph_path = cg_dir / "graph.json"
        if graph_path.exists():
            from codegraph.graph.models import CodeGraph
            graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
            store.load_from_graph(graph)
    except Exception:
        # Accept empty store — tools return structured errors
        pass

    mcp_mod._store = store
    mcp_mod._cg_dir = cg_dir
    mcp_mod._project_root = str(root)
    return cg_dir


def teardown_mcp_globals() -> None:
    """Clear MCP module globals."""
    import codegraph.mcp_server as mcp_mod
    mcp_mod._store = None
    mcp_mod._cg_dir = None
    mcp_mod._project_root = None


def run_benchmark(
    iterations: int = 5,
    project_root: Path | None = None,
    cases: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Run all benchmark cases for *iterations* rounds.

    Returns a list of latency result dicts conforming to the
    ``mcp_latency_result.schema.json`` schema.
    """
    if cases is None:
        cases = BENCHMARK_CASES

    root = project_root or Path.cwd()
    cg_dir = setup_mcp_globals(root)
    results: list[dict[str, Any]] = []

    try:
        for iteration in range(1, iterations + 1):
            for case in cases:
                case_id = case["case_id"]
                tool = case["tool"]
                mode = case["mode"]

                result, latency_ms, ok, error_text = _call_tool(case)
                resp_bytes = _response_bytes(result)

                artifact_bytes = 0
                run_dir_created = False
                if mode == "harness_mcp":
                    artifact_bytes = result.get("_artifact_bytes_written", 0)
                    run_dir_created = result.get("_run_dir_created", False)

                entry: dict[str, Any] = {
                    "case_id": case_id,
                    "tool": tool,
                    "mode": mode,
                    "iteration": iteration,
                    "latency_ms": round(latency_ms, 2),
                    "response_bytes": resp_bytes,
                    "artifact_bytes_written": artifact_bytes,
                    "run_dir_created": run_dir_created,
                    "ok": ok,
                    "error": error_text,
                    "timestamp": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                }
                results.append(entry)
    finally:
        teardown_mcp_globals()

    return results


# ── Report generation ──────────────────────────────────────────────────────


def _percentile(values: list[float], p: float) -> float:
    """Compute the *p*-th percentile of *values* using linear interpolation."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (p / 100.0) * (len(sorted_vals) - 1)
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_vals):
        return sorted_vals[f] + c * (sorted_vals[f + 1] - sorted_vals[f])
    return sorted_vals[f]


def _case_stats(
    case_id: str, results: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compute aggregate statistics for one case_id across all iterations."""
    entries = [r for r in results if r["case_id"] == case_id]
    if not entries:
        return {
            "case_id": case_id,
            "count": 0,
            "p50_ms": 0,
            "p95_ms": 0,
            "max_ms": 0,
            "avg_response_bytes": 0,
            "avg_artifact_bytes": 0,
            "ok_count": 0,
            "error_count": 0,
        }

    latencies = [e["latency_ms"] for e in entries]
    resp_bytes = [e["response_bytes"] for e in entries]
    artifact_bytes = [e["artifact_bytes_written"] for e in entries]
    ok_count = sum(1 for e in entries if e["ok"])
    error_count = sum(1 for e in entries if not e["ok"])

    return {
        "case_id": case_id,
        "tool": entries[0]["tool"],
        "mode": entries[0]["mode"],
        "count": len(entries),
        "p50_ms": round(_percentile(latencies, 50), 2),
        "p95_ms": round(_percentile(latencies, 95), 2),
        "max_ms": round(max(latencies), 2),
        "avg_response_bytes": round(statistics.mean(resp_bytes)) if resp_bytes else 0,
        "avg_artifact_bytes": round(statistics.mean(artifact_bytes)) if artifact_bytes else 0,
        "ok_count": ok_count,
        "error_count": error_count,
    }


def _compute_overhead(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate harness overhead by comparing paired direct/harness cases."""
    # Pair cases by suffix: direct_find_basic ↔ harness_workflow_find
    pairs = [
        ("direct_find_basic", "harness_workflow_find"),
        ("direct_explain_symbol", "harness_workflow_explain"),
        ("direct_pre_edit_file", "harness_workflow_impact"),
        ("direct_coverage_gaps", "harness_workflow_test_audit"),
    ]

    overheads: list[float] = []
    pair_details: list[dict[str, Any]] = []

    for direct_id, harness_id in pairs:
        direct_entries = [r for r in results if r["case_id"] == direct_id]
        harness_entries = [r for r in results if r["case_id"] == harness_id]

        if not direct_entries or not harness_entries:
            continue

        direct_p50 = _percentile([e["latency_ms"] for e in direct_entries], 50)
        harness_p50 = _percentile([e["latency_ms"] for e in harness_entries], 50)
        overhead = harness_p50 - direct_p50
        if overhead > 0:
            overheads.append(overhead)

        pair_details.append({
            "direct_case": direct_id,
            "harness_case": harness_id,
            "direct_p50_ms": round(direct_p50, 2),
            "harness_p50_ms": round(harness_p50, 2),
            "overhead_ms": round(overhead, 2),
        })

    return {
        "pairs": pair_details,
        "avg_overhead_p50_ms": round(statistics.mean(overheads), 2) if overheads else 0,
    }


def generate_report(
    results: list[dict[str, Any]],
    output_dir: str | Path = "reports",
) -> tuple[Path, Path]:
    """Generate performance JSON and Markdown reports.

    Returns:
        (json_path, markdown_path)
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ── JSON report ──────────────────────────────────────────────────
    json_path = out / "mcp_harness_perf.json"
    json_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # ── Compute aggregates ───────────────────────────────────────────
    case_ids = sorted({r["case_id"] for r in results})
    stats = [_case_stats(cid, results) for cid in case_ids]

    all_direct = [r for r in results if r["mode"] == "direct_mcp"]
    all_harness = [r for r in results if r["mode"] == "harness_mcp"]

    direct_latencies = [r["latency_ms"] for r in all_direct if r["ok"]]
    harness_latencies = [r["latency_ms"] for r in all_harness if r["ok"]]

    overhead = _compute_overhead(results)

    total_errors = sum(1 for r in results if not r["ok"])
    slowest = sorted(
        [r for r in results if r["ok"]], key=lambda r: r["latency_ms"], reverse=True
    )[:5]

    # ── Threshold checks ─────────────────────────────────────────────
    threshold_results: list[dict[str, Any]] = []
    for s in stats:
        case_id = s["case_id"]
        p95 = s["p95_ms"]
        cat = _classify_case(case_id)
        if cat == "fast":
            target = THRESHOLDS["find_explain_p95_ms"]
            passed = p95 < target
        else:
            target = THRESHOLDS["impact_test_audit_p95_ms"]
            passed = p95 < target

        if not passed:
            threshold_results.append({
                "case_id": case_id,
                "p95_ms": p95,
                "threshold_ms": target,
                "passed": passed,
                "suspected_cause": _suspect_cause(case_id, p95, target),
                "recommended_action": _recommend_action(case_id),
            })

    # ── Markdown report ──────────────────────────────────────────────
    md = _render_markdown(
        stats=stats,
        direct_latencies=direct_latencies,
        harness_latencies=harness_latencies,
        overhead=overhead,
        total_errors=total_errors,
        slowest=slowest,
        threshold_results=threshold_results,
        iterations=len(results) // len(case_ids) if case_ids else 0,
    )

    md_path = out / "mcp_harness_perf.md"
    md_path.write_text(md, encoding="utf-8")

    return json_path, md_path


def _suspect_cause(case_id: str, p95: float, threshold: float) -> str:
    """Heuristic cause description when a threshold is missed."""
    if "harness" in case_id:
        return (
            f"Harness persistence (run dir + artifacts + state.json + events.jsonl) "
            f"adds disk I/O overhead. p95={p95:.0f}ms > threshold={threshold}ms."
        )
    if "impact" in case_id:
        return (
            f"Impact analysis traverses call graph and aggregates method-level "
            f"callers/callees. p95={p95:.0f}ms > threshold={threshold}ms."
        )
    return (
        f"Indexed graph traversal or symbol resolution slower than expected. "
        f"p95={p95:.0f}ms > threshold={threshold}ms."
    )


def _recommend_action(case_id: str) -> str:
    """Heuristic next action when a threshold is missed."""
    if "harness" in case_id:
        return (
            "Profile harness write paths (state.json, events.jsonl, artifact writes). "
            "Consider async/batched writes or lazy artifact flush."
        )
    if "impact" in case_id:
        return (
            "Profile impact traversal depth and graph serialization. "
            "Consider limiting depth or adding result caching."
        )
    return (
        "Profile the specific tool function to identify slow sub-steps. "
        "Consider index-level optimizations."
    )


def _render_markdown(
    *,
    stats: list[dict[str, Any]],
    direct_latencies: list[float],
    harness_latencies: list[float],
    overhead: dict[str, Any],
    total_errors: int,
    slowest: list[dict[str, Any]],
    threshold_results: list[dict[str, Any]],
    iterations: int,
) -> str:
    """Render the full Markdown performance report."""

    direct_p50 = _percentile(direct_latencies, 50)
    direct_p95 = _percentile(direct_latencies, 95)
    harness_p50 = _percentile(harness_latencies, 50)
    harness_p95 = _percentile(harness_latencies, 95)

    lines: list[str] = []

    lines.append("# MCP Harness Performance Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append(f"**Iterations per case:** {iterations}")
    lines.append(f"**Total measurements:** {len(stats) * iterations if stats else 0}")
    lines.append("")

    # ── Summary ──────────────────────────────────────────────────────
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Direct MCP p50 | {direct_p50:.1f} ms |")
    lines.append(f"| Direct MCP p95 | {direct_p95:.1f} ms |")
    lines.append(f"| Harness MCP p50 | {harness_p50:.1f} ms |")
    lines.append(f"| Harness MCP p95 | {harness_p95:.1f} ms |")
    lines.append(f"| Estimated harness overhead p50 | {overhead['avg_overhead_p50_ms']:.1f} ms |")
    lines.append(f"| Total errors | {total_errors} |")
    lines.append("")

    # ── Cases table ──────────────────────────────────────────────────
    lines.append("## Cases")
    lines.append("")
    lines.append(
        "| Case | Tool | Mode | p50 ms | p95 ms | max ms | "
        "Avg resp bytes | Avg artifact bytes | OK | Err |"
    )
    lines.append(
        "|---|---|---:|---:|---:|---:|---:|---:|---:|"
    )
    for s in stats:
        lines.append(
            f"| {s['case_id']} | {s['tool']} | {s['mode']} | "
            f"{s['p50_ms']:.1f} | {s['p95_ms']:.1f} | {s['max_ms']:.1f} | "
            f"{s['avg_response_bytes']} | {s['avg_artifact_bytes']} | "
            f"{s['ok_count']} | {s['error_count']} |"
        )
    lines.append("")

    # ── Harness overhead ─────────────────────────────────────────────
    lines.append("## Harness Overhead Estimate")
    lines.append("")
    lines.append(
        "| Direct Case | Harness Case | Direct p50 | Harness p50 | Overhead ms |"
    )
    lines.append("|---|---|---:|---:|---:|")
    for pair in overhead.get("pairs", []):
        lines.append(
            f"| {pair['direct_case']} | {pair['harness_case']} | "
            f"{pair['direct_p50_ms']:.1f} | {pair['harness_p50_ms']:.1f} | "
            f"{pair['overhead_ms']:.1f} |"
        )
    lines.append(f"| **Average** | | | | **{overhead['avg_overhead_p50_ms']:.1f}** |")
    lines.append("")

    # ── Thresholds ───────────────────────────────────────────────────
    lines.append("## Thresholds")
    lines.append("")
    lines.append(f"- find/explain p95 target: < {THRESHOLDS['find_explain_p95_ms']} ms")
    lines.append(f"- impact/test-audit p95 target: < {THRESHOLDS['impact_test_audit_p95_ms']} ms")
    lines.append(f"- harness persistence overhead target: < {THRESHOLDS['harness_overhead_p50_ms']} ms")
    lines.append("- artifact content should not be returned by default in MCP responses")
    lines.append("")

    if threshold_results:
        lines.append("### Failed Thresholds")
        lines.append("")
        for tr in threshold_results:
            lines.append(f"#### {tr['case_id']}")
            lines.append("")
            lines.append(f"- **p95:** {tr['p95_ms']:.1f} ms (threshold: {tr['threshold_ms']} ms)")
            lines.append(f"- **Suspected cause:** {tr['suspected_cause']}")
            lines.append(f"- **Recommended next action:** {tr['recommended_action']}")
            lines.append("")
    else:
        lines.append("### All thresholds passed ✅")
        lines.append("")

    # ── Slowest cases ────────────────────────────────────────────────
    lines.append("## Slowest Cases")
    lines.append("")
    lines.append("| Case | Tool | Mode | Iteration | Latency ms | Response bytes |")
    lines.append("|---|---|---|---:|---:|")
    for r in slowest:
        lines.append(
            f"| {r['case_id']} | {r['tool']} | {r['mode']} | "
            f"{r['iteration']} | {r['latency_ms']:.1f} | {r['response_bytes']} |"
        )
    lines.append("")

    # ── Notes ────────────────────────────────────────────────────────
    lines.append("## Notes")
    lines.append("")
    lines.append("- Benchmark runs in-process — no stdio/jsonrpc overhead")
    lines.append("- `harness_mcp` latency includes: module execution + state.json + events.jsonl + artifact writes")
    lines.append("- `response_bytes` measures the JSON-serialized MCP response payload size")
    lines.append("- Artifact content is **not** included in MCP responses (on-demand via `codegraph_harness_artifacts`)")
    lines.append("- All measurements are wall-clock; system load may cause variance")
    lines.append("- No tools or code were deleted during this benchmark")
    lines.append("")

    return "\n".join(lines)


# ── CLI entry point ────────────────────────────────────────────────────────


def main() -> None:
    """Run the performance benchmark from the command line."""
    import argparse

    parser = argparse.ArgumentParser(
        description="CodeGraph MCP + Harness performance benchmark",
    )
    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=5,
        help="Number of iterations per case (default: 5)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="reports",
        help="Output directory for reports (default: reports)",
    )
    parser.add_argument(
        "--project-root", "-r",
        type=str,
        default=None,
        help="Project root path (default: CWD)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-case progress output",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root) if args.project_root else Path.cwd()
    output_dir = Path(args.output_dir)

    if not args.quiet:
        print(f"[benchmark] Running {len(BENCHMARK_CASES)} cases × {args.iterations} iterations...")
        print(f"[benchmark] Project root: {project_root}")

    results = run_benchmark(
        iterations=args.iterations,
        project_root=project_root,
    )

    json_path, md_path = generate_report(results, output_dir=output_dir)

    if not args.quiet:
        ok_count = sum(1 for r in results if r["ok"])
        err_count = sum(1 for r in results if not r["ok"])
        print(f"[benchmark] {len(results)} measurements ({ok_count} ok, {err_count} errors)")
        print(f"[benchmark] JSON report: {json_path}")
        print(f"[benchmark] Markdown report: {md_path}")


if __name__ == "__main__":
    main()
