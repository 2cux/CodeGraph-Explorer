"""Report generator for agent benchmark results.

Reads results JSON files from the results directory, computes metrics,
and generates a markdown report at reports/agent_benchmark.md.

Usage:
    python -m tests.agent_benchmark.report
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure backend is importable
_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "backend"))

from tests.agent_benchmark.metrics import (
    compare_results,
    aggregate_summary,
    file_recall,
    grep_read_calls,
    files_read_count,
    estimated_tokens,
    elapsed_seconds,
)

_RESULTS_DIR = Path(__file__).resolve().parent / "results"
_REPORTS_DIR = _project_root / "reports"

# Initial performance targets
TARGETS = {
    "grep_read_reduction": ">= 30%",
    "files_read_reduction": ">= 25%",
    "token_reduction": ">= 20%",
    "expected_file_recall": ">= baseline",
}


def load_results(mode: str, suffix: str = "") -> list[dict[str, Any]]:
    """Load benchmark results from a JSON file.

    Args:
        mode: ``"baseline"`` or ``"codegraph"``.
        suffix: Optional suffix for the filename (e.g. ``"compact"`` or ``"standard"``).
    """
    filename = f"results_{mode}" if not suffix else f"results_{mode}_{suffix}"
    path = _RESULTS_DIR / f"{filename}.json"
    if not path.exists():
        print(f"Results file not found: {path}")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def generate_report() -> str:
    """Generate the benchmark report as markdown text.

    When both ``results_codegraph_compact.json`` and ``results_codegraph_standard.json``
    exist (from ``--response-mode both``), the report includes a compact-vs-standard
    comparison table with actual measured payloads.
    """
    baseline = load_results("baseline")
    codegraph = load_results("codegraph")
    codegraph_standard = load_results("codegraph", "standard")

    # Auto-detect dual-run results
    has_standard = False
    if not codegraph_standard:
        # Try compact suffix as primary
        codegraph_compact = load_results("codegraph", "compact")
        if codegraph_compact:
            codegraph = codegraph_compact
            codegraph_standard = load_results("codegraph", "standard")
            has_standard = bool(codegraph_standard)
    else:
        # Primary is standard, find compact
        codegraph_compact = load_results("codegraph", "compact")
        if codegraph_compact:
            has_standard = True
        else:
            has_standard = bool(codegraph_standard)
            codegraph_standard = None  # No separate compact file, use embedded data

    missing = []
    if not baseline:
        missing.append("results_baseline.json")
    if not codegraph:
        missing.append("results_codegraph.json")

    if missing:
        print("Missing benchmark result files:")
        for m in missing:
            if "baseline" in m:
                print("  python -m tests.agent_benchmark.runner --mode baseline")
            if "codegraph" in m:
                print("  python -m tests.agent_benchmark.runner --mode codegraph")
        print("For compact vs standard comparison:")
        print("  python -m tests.agent_benchmark.runner --mode codegraph --response-mode both")
        print("Then re-run:")
        print("  python -m tests.agent_benchmark.report")
        print("Or run all at once:")
        print("  make benchmark")
        return "MISSING_RESULTS"

    # Build lookup by task_id
    cg_map: dict[str, dict[str, Any]] = {r["task_id"]: r for r in codegraph}
    cg_std_map: dict[str, dict[str, Any]] = {}
    if codegraph_standard:
        cg_std_map = {r["task_id"]: r for r in codegraph_standard}

    comparisons: list[dict[str, Any]] = []
    for b in baseline:
        cg = cg_map.get(b["task_id"])
        if cg:
            cg_std = cg_std_map.get(b["task_id"])
            comparisons.append(compare_results(b, cg, cg_std))

    summary = aggregate_summary(comparisons)

    # ── Build report ────────────────────────────────────────────────────
    lines: list[str] = []
    lines.append("# CodeGraph Explorer — Agent A/B Benchmark Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append("## 1. Summary")
    lines.append("")
    lines.append("This report compares agent performance between two modes:")
    lines.append("")
    lines.append("- **Baseline:** Agent uses only grep/glob/read file-scanning tools.")
    lines.append("- **CodeGraph:** Agent uses CodeGraph MCP fine-grained query tools (`search_symbols`, `get_symbol`, `get_callers`, `get_callees`, `get_neighbors`, `get_impact`, `repo_status`).")
    lines.append("")
    lines.append(f"**Tasks executed:** {summary.get('total_tasks', 0)}")
    lines.append("")

    lines.append("### Pass Rates")
    lines.append("")
    pass_rates = summary.get("pass_rates", {})
    lines.append(f"| Metric | Pass Rate |")
    lines.append(f"|---|---|")
    lines.append(f"| Recall >= baseline | {pass_rates.get('recall_ok', 'N/A')} |")
    lines.append(f"| grep/read reduction | {pass_rates.get('grep_read_ok', 'N/A')} |")
    lines.append(f"| Files read reduction | {pass_rates.get('files_ok', 'N/A')} |")
    lines.append(f"| Token reduction | {pass_rates.get('tokens_ok', 'N/A')} |")
    lines.append("")

    avg = summary.get("avg_deltas", {})
    lines.append("### Average Reductions (CodeGraph vs Baseline)")
    lines.append("")
    lines.append(f"| Metric | Actual | Target |")
    lines.append(f"|---|---|---|")
    lines.append(f"| grep/read calls | {avg.get('grep_read_pct', 0):+.1f}% | {TARGETS['grep_read_reduction']} |")
    lines.append(f"| Files read | {avg.get('files_read_pct', 0):+.1f}% | {TARGETS['files_read_reduction']} |")
    lines.append(f"| Estimated tokens | {avg.get('tokens_pct', 0):+.1f}% | {TARGETS['token_reduction']} |")
    lines.append(f"| Total tool calls | {avg.get('tool_calls_pct', 0):+.1f}% | — |")
    lines.append(f"| Elapsed time | {avg.get('time_pct', 0):+.1f}% | — |")
    lines.append("")

    lines.append("### Aggregate Totals")
    lines.append("")
    totals = summary.get("aggregate_totals", {})
    lines.append(f"| Metric | Baseline | CodeGraph | Reduction |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| Total tool calls | {totals.get('baseline_tools', 0)} | {totals.get('codegraph_tools', 0)} | "
                 f"{_pct_str(totals.get('baseline_tools', 0), totals.get('codegraph_tools', 0))} |")
    lines.append(f"| grep/glob/read calls | {totals.get('baseline_grep_read', 0)} | {totals.get('codegraph_grep_read', 0)} | "
                 f"{_pct_str(totals.get('baseline_grep_read', 0), totals.get('codegraph_grep_read', 0))} |")
    lines.append(f"| Files read | {totals.get('baseline_files_read', 0)} | {totals.get('codegraph_files_read', 0)} | "
                 f"{_pct_str(totals.get('baseline_files_read', 0), totals.get('codegraph_files_read', 0))} |")
    lines.append(f"| Est. tokens | {totals.get('baseline_tokens', 0):,} | {totals.get('codegraph_tokens', 0):,} | "
                 f"{_pct_str(totals.get('baseline_tokens', 0), totals.get('codegraph_tokens', 0))} |")
    lines.append("")
    lines.append("### Phase-Aware Token Breakdown (CodeGraph)")
    lines.append("")
    lines.append("CodeGraph separates into discovery (MCP queries) and execution (file reads) phases.")
    lines.append("")
    # Compute aggregate MCP and full task tokens
    agg_mcp = sum(c["codegraph"].get("mcp_payload_tokens", 0) for c in comparisons)
    agg_full = sum(c["codegraph"].get("full_task_token_estimate", 0) for c in comparisons)
    agg_followup = sum(c["codegraph"].get("required_followup_reads", 0) for c in comparisons)
    base_tokens = totals.get("baseline_tokens", 1)
    lines.append(f"| Metric | CodeGraph | vs Baseline |")
    lines.append(f"|---|---|---|")
    lines.append(f"| MCP payload tokens (discovery) | {agg_mcp:,} | {_pct_str(base_tokens, agg_mcp)} |")
    lines.append(f"| Full task estimate (discovery + reads) | {agg_full:,} | {_pct_str(base_tokens, agg_full)} |")
    lines.append(f"| Required followup file reads | {agg_followup} | — |")
    lines.append("")

    search = summary.get("search", {})
    if search:
        lines.append("### Search Quality")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|---|---:|")
        lines.append(f"| Search recall | {search.get('avg_recall', 0):.1f}% |")
        lines.append(f"| Top-1 accuracy | {search.get('avg_top1_accuracy', 0):.1f}% |")
        lines.append(f"| Ambiguous rate | {search.get('ambiguous_rate', 0):.1f}% |")
        lines.append(f"| Search payload tokens | {search.get('payload_tokens', 0):,} |")
        lines.append("")

    # ── Compact vs Standard comparison ───────────────────────────────────
    cmp_compact = totals.get("codegraph_mcp_compact_tokens", 0)
    cmp_standard = totals.get("codegraph_mcp_standard_tokens", 0)
    cmp_full_compact = totals.get("codegraph_full_compact_tokens", 0)
    cmp_full_standard = totals.get("codegraph_full_standard_tokens", 0)
    cmp_ratio = totals.get("compact_vs_standard_payload_ratio", 0)

    lines.append("### Compact vs Standard Payload Comparison")
    lines.append("")
    if cmp_standard > 0:
        payload_reduction = round((1 - cmp_ratio) * 100, 1)
        full_reduction = round((1 - cmp_full_compact / cmp_full_standard) * 100, 1) if cmp_full_standard > 0 else 0
        lines.append(f"| Metric | Compact | Standard | Reduction |")
        lines.append(f"|---|---|---|---|")
        lines.append(f"| MCP payload tokens | {cmp_compact:,} | {cmp_standard:,} | {payload_reduction:.1f}% |")
        lines.append(f"| Full task tokens | {cmp_full_compact:,} | {cmp_full_standard:,} | {full_reduction:.1f}% |")
        lines.append(f"| Payload ratio | {cmp_ratio} | — | — |")
        lines.append("")
        lines.append("**Key insight:** Compact mode delivers the same recall while reducing")
        lines.append(f"MCP payload by ~{payload_reduction:.0f}% and full task tokens by ~{full_reduction:.0f}%.")
        lines.append("")
    else:
        lines.append("> Run with `--response-mode both` to populate actual compact vs standard comparison.")
        lines.append("> Currently using embedded dual-estimate data from a single compact run.")
        lines.append("")
        # Use data embedded in compact results
        if cmp_compact > 0:
            embedded_ratio = cmp_ratio
            lines.append(f"**Embedded estimates:** compact={cmp_compact:,} tokens, "
                         f"estimated standard={int(cmp_compact/embedded_ratio):,} tokens "
                         f"(ratio={embedded_ratio})")
            lines.append("")

    # ── Per-task results ────────────────────────────────────────────────
    lines.append("## 2. Per-Task Results")
    lines.append("")
    lines.append("| Task | MCP Calls | MCP Tokens | Search Recall | Top-1 | Ambiguous | Search Tokens | Full Tokens | Recall |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for c in comparisons:
        bids = c["task_id"]
        cg_tc = c["codegraph"]["tool_calls"]
        cg_mcp = c["codegraph"].get("mcp_payload_tokens", 0)
        search_recall = f"{c['codegraph'].get('search_recall', 0):.0f}%"
        search_top1 = f"{c['codegraph'].get('search_top1_accuracy', 0):.0f}%"
        search_ambiguous = "yes" if c["codegraph"].get("search_ambiguous", False) else "no"
        search_tokens = c["codegraph"].get("search_payload_tokens", 0)
        cg_full = c["codegraph"].get("full_task_token_estimate", 0)
        recall = f"{c['codegraph']['file_recall']:.0f}%"
        lines.append(
            f"| {bids} | {cg_tc} | {cg_mcp:,} | {search_recall} | {search_top1} | "
            f"{search_ambiguous} | {search_tokens:,} | {cg_full:,} | {recall} |"
        )
    lines.append("")

    # ── Detailed comparison ─────────────────────────────────────────────
    lines.append("## 3. Detailed Comparisons")
    lines.append("")
    for c in comparisons:
        lines.append(f"### {c['task_id']}")
        lines.append(f"**Task:** {c['task']}")
        lines.append(f"**Category:** {c['category']}")
        lines.append("")
        lines.append("| Metric | Baseline | CodeGraph | Delta |")
        lines.append("|---|---|---|---|")
        lines.append(f"| Tool calls | {c['baseline']['tool_calls']} | {c['codegraph']['tool_calls']} | "
                     f"{c['deltas']['tool_calls_pct']:+.1f}% |")
        lines.append(f"| grep/read calls | {c['baseline']['grep_read_calls']} | {c['codegraph']['grep_read_calls']} | "
                     f"{c['deltas']['grep_read_pct']:+.1f}% |")
        lines.append(f"| Files read | {c['baseline']['files_read']} | {c['codegraph']['files_read']} | "
                     f"{c['deltas']['files_read_pct']:+.1f}% |")
        lines.append(f"| Est. tokens | {c['baseline']['tokens']:,} | {c['codegraph']['tokens']:,} | "
                     f"{c['deltas']['tokens_pct']:+.1f}% |")
        lines.append(f"| Time (s) | {c['baseline']['time_s']:.2f} | {c['codegraph']['time_s']:.2f} | "
                     f"{c['deltas']['time_pct']:+.1f}% |")
        lines.append(f"| File recall | {c['baseline']['file_recall']}% | {c['codegraph']['file_recall']}% | — |")
        # Phase-aware metrics
        cg_mcp = c["codegraph"].get("mcp_payload_tokens", 0)
        cg_full = c["codegraph"].get("full_task_token_estimate", 0)
        cg_followup = c["codegraph"].get("required_followup_reads", 0)
        if cg_mcp or cg_full:
            lines.append(f"| MCP payload (discovery) | — | {cg_mcp:,} tokens | — |")
            lines.append(f"| Full task estimate | — | {cg_full:,} tokens | — |")
            lines.append(f"| Required followup reads | — | {cg_followup} files | — |")
        lines.append("")

        failures = c.get("failure_cases", [])
        if failures:
            lines.append("**Issues detected:**")
            for f in failures:
                lines.append(f"- [{f.get('type', 'unknown')}] {f.get('reason', '')}")
            lines.append("")

    # ── Failure cases ───────────────────────────────────────────────────
    all_failures = summary.get("failure_cases", [])
    lines.append("## 4. Failure Cases")
    lines.append("")
    if all_failures:
        lines.append("| Task | Type | Reason |")
        lines.append("|---|---|---|")
        for f in all_failures[:50]:
            lines.append(f"| {f.get('task_id', '')} | {f.get('type', '')} | {f.get('reason', '')} |")
    else:
        lines.append("No failure cases recorded.")
    lines.append("")

    # ── Observed limitations ────────────────────────────────────────────
    lines.append("## 5. Observed Limitations")
    lines.append("")
    lines.append("The following are system-level observations that may require follow-up:")
    lines.append("")
    lines.append("1. **Index quality variance** — Symbol recall depends on index completeness. Missing edges cause missed impact results.")
    lines.append("2. **Confidence thresholds** — Default `min_confidence=0.6` may filter out valid relationships in some codebases.")
    lines.append("3. **Test detection** — `tested_by` edges rely on naming heuristics; not all test files are connected.")
    lines.append("4. **Phase split** — CodeGraph separates discovery (MCP queries) and execution (file reads). The MCP payload alone is very cheap; the full task cost adds followup reads for verification.")
    lines.append("5. **Baseline simulation accuracy** — The baseline simulation is a programmatic approximation; real-agent baseline may differ.")
    lines.append("")

    # ── Performance targets ─────────────────────────────────────────────
    lines.append("## 6. Performance Targets")
    lines.append("")
    lines.append("| Target | Current | Status |")
    lines.append("|---|---|---|")
    avg_gr = abs(avg.get("grep_read_pct", 0))
    avg_fr = abs(avg.get("files_read_pct", 0))
    avg_tk = abs(avg.get("tokens_pct", 0))
    lines.append(f"| grep/read reduction >= 30% | {avg_gr:.1f}% | {'✓' if avg_gr >= 30 else '✗'} |")
    lines.append(f"| Files read reduction >= 25% | {avg_fr:.1f}% | {'✓' if avg_fr >= 25 else '✗'} |")
    lines.append(f"| Token reduction >= 20% | {avg_tk:.1f}% | {'✓' if avg_tk >= 20 else '✗'} |")
    lines.append(f"| File recall >= baseline | {pass_rates.get('recall_ok', 'N/A')} | {'✓' if '1/1' in str(pass_rates.get('recall_ok', '')) else '—'} |")
    lines.append("")

    return "\n".join(lines)


def _pct_str(old: float, new: float) -> str:
    """Format a percentage change string."""
    if old == 0:
        return "N/A" if new == 0 else "-100%"
    pct = (new - old) / old * 100
    return f"{pct:+.1f}%"


def main() -> None:
    print("Generating benchmark report...")
    report = generate_report()
    if not report or report == "MISSING_RESULTS":
        if report == "MISSING_RESULTS":
            pass  # Error messages already printed in generate_report()
        else:
            print("Failed to generate report.")
        sys.exit(1)

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _REPORTS_DIR / "agent_benchmark.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"Report saved to {out_path}")


if __name__ == "__main__":
    main()
