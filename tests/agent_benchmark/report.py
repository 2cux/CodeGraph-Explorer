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


def load_results(mode: str) -> list[dict[str, Any]]:
    """Load benchmark results from a JSON file."""
    path = _RESULTS_DIR / f"results_{mode}.json"
    if not path.exists():
        print(f"Results file not found: {path}")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def generate_report() -> str:
    """Generate the benchmark report as markdown text."""
    baseline = load_results("baseline")
    codegraph = load_results("codegraph")

    if not baseline or not codegraph:
        print("Missing result files. Run both baseline and codegraph first:")
        print("  python -m tests.agent_benchmark.runner --mode baseline")
        print("  python -m tests.agent_benchmark.runner --mode codegraph")
        return ""

    # Build lookup by task_id
    cg_map: dict[str, dict[str, Any]] = {r["task_id"]: r for r in codegraph}
    comparisons: list[dict[str, Any]] = []
    for b in baseline:
        cg = cg_map.get(b["task_id"])
        if cg:
            comparisons.append(compare_results(b, cg))

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

    # ── Per-task results ────────────────────────────────────────────────
    lines.append("## 2. Per-Task Results")
    lines.append("")
    lines.append("| Task | Baseline Calls | CodeGraph Calls | grep/read Δ | Files Read Δ | Token Δ | Recall |")
    lines.append("|---|---|---|---|---|---|---|")
    for c in comparisons:
        bids = c["task_id"]
        b_tc = c["baseline"]["tool_calls"]
        cg_tc = c["codegraph"]["tool_calls"]
        gr_d = f"{c['deltas']['grep_read_pct']:+.0f}%"
        fr_d = f"{c['deltas']['files_read_pct']:+.0f}%"
        tok_d = f"{c['deltas']['tokens_pct']:+.0f}%"
        recall = f"{c['codegraph']['file_recall']:.0f}%"
        lines.append(f"| {bids} | {b_tc} | {cg_tc} | {gr_d} | {fr_d} | {tok_d} | {recall} |")
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
    lines.append("4. **Payload size** — CodeGraph responses include metadata that increases token count for small queries but pays off for large ones.")
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
    if not report:
        print("Failed to generate report.")
        sys.exit(1)

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _REPORTS_DIR / "agent_benchmark.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"Report saved to {out_path}")


if __name__ == "__main__":
    main()
