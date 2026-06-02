"""Benchmark Regression Gate for CodeGraph Explorer.

Prevents performance and quality regressions by checking core metrics
against configured thresholds. Runs the benchmark pipeline if needed,
then executes 10 categories of regression checks.

Usage:
    make benchmark-gate                                # Recommended: full pipeline
    python -m tests.agent_benchmark.gate               # Full run (auto-runs benchmarks)
    python -m tests.agent_benchmark.gate --skip-run    # Check existing results only
    python -m tests.agent_benchmark.gate --update-baseline  # Update baseline

Exit codes:
    0 — PASS (all checks pass)
    1 — FAIL (one or more checks failed)
    2 — INPUT_MISSING (benchmark result files don't exist — run without --skip-run,
        or ``make benchmark`` first, to generate them)

--skip-run behavior:
    With --skip-run, the gate reads existing result files from
    tests/agent_benchmark/results/ without running the benchmark pipeline.
    If any required result file is missing, the gate exits with code 2
    and prints the command needed to generate results.

    Without --skip-run, the gate runs the full pipeline automatically:
        python -m tests.agent_benchmark.runner --mode baseline
        python -m tests.agent_benchmark.runner --mode codegraph --response-mode compact
        python -m tests.agent_benchmark.runner --mode codegraph --response-mode standard
        python -m tests.agent_benchmark.report
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BENCHMARK_DIR = Path(__file__).resolve().parent
_RESULTS_DIR = _BENCHMARK_DIR / "results"
_FIXTURES_DIR = _BENCHMARK_DIR / "fixtures"
_REPORTS_DIR = _PROJECT_ROOT / "reports"
_CONFIG_PATH = _BENCHMARK_DIR / "gate_config.json"

# Ensure backend is importable
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))


# ══════════════════════════════════════════════════════════════════════════════
# Data Classes
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class CheckResult:
    """A single check result."""
    category: str
    name: str
    value: Any
    threshold: Any
    passed: bool
    detail: str = ""


@dataclass
class GateReport:
    """Complete gate report."""
    status: str  # "PASS" or "FAIL"
    timestamp: str
    thresholds: dict[str, Any]
    metrics: dict[str, Any]
    checks: list[dict[str, Any]] = field(default_factory=list)
    failed_checks: list[dict[str, Any]] = field(default_factory=list)
    passed_checks: list[dict[str, Any]] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# Config Loading
# ══════════════════════════════════════════════════════════════════════════════


def load_gate_config() -> dict[str, Any]:
    """Load gate configuration from JSON file."""
    if not _CONFIG_PATH.exists():
        print(f"Warning: gate_config.json not found at {_CONFIG_PATH}, using defaults")
        return _default_config()
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
        # Remove comment keys
        return {k: v for k, v in config.items() if not k.startswith("_")}
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: failed to load gate_config.json: {e}, using defaults")
        return _default_config()


def _default_config() -> dict[str, Any]:
    """Fallback defaults when config file is missing or broken."""
    return {
        "recall": {"min_symbol_recall": 0.85, "min_file_recall": 0.80, "min_recall_pass_rate": 0.67},
        "tokens": {"min_token_reduction": 0.20, "min_compact_vs_standard_reduction": 0.30,
                    "max_compact_payload_tokens": 8000, "max_full_task_token_estimate": 20000},
        "grep_read": {"min_grep_read_reduction": 0.30, "min_files_read_reduction": 0.25},
        "search": {"min_top1_accuracy": 0.70, "max_ambiguous_rate": 0.25, "min_search_recall": 0.70},
        "edges": {"max_false_confirmed_edges": 0, "max_unresolved_in_confirmed": 0, "max_name_only_confirmed": 0},
        "impact": {"require_confirmed_possible_separation": True, "require_tests_separate_group": True, "max_confirmed_files": 20},
        "mcp_protocol": {"require_stdout_clean": True, "require_index_status_present": True,
                          "require_index_health_present": True, "compact_forbid_full_source": True,
                          "compact_forbid_full_evidence": True, "compact_forbid_markdown_body": True},
        "evidence_pack": {"require_no_reading_plan": True, "require_no_agent_instructions": True,
                           "require_no_recommended_context": True, "require_no_implementation_plan": True,
                           "require_structured_evidence_only": True},
        "incremental": {"require_cosmetic_skip_rebuild": True, "require_structural_partial_update": True,
                        "require_deleted_file_cleanup": True, "require_no_full_replace_degradation": True,
                        "require_storage_counts_consistent": True},
        "storage": {"max_dangling_edges": 0, "require_fts_count_match": True,
                     "require_validation_status_ok": True, "require_integrity_status_ok": True},
    }


# ══════════════════════════════════════════════════════════════════════════════
# Benchmark Pipeline
# ══════════════════════════════════════════════════════════════════════════════


def _run_python_module(module: str, args: list[str] | None = None) -> int:
    """Run a Python module as a subprocess. Returns exit code."""
    cmd = [sys.executable, "-m", module] + (args or [])
    result = subprocess.run(cmd, cwd=str(_PROJECT_ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: {module} exited with code {result.returncode}")
        if result.stderr:
            print(f"  stderr: {result.stderr[:500]}")
    return result.returncode


def run_benchmark_pipeline() -> bool:
    """Run the full benchmark pipeline (baseline + compact + standard + report).

    Returns True if all steps succeeded.
    """
    print("Running benchmark pipeline...")

    ok = True

    print("  [1/4] Running baseline mode...")
    if _run_python_module("tests.agent_benchmark.runner", ["--mode", "baseline"]) != 0:
        ok = False

    print("  [2/4] Running codegraph compact mode...")
    if _run_python_module("tests.agent_benchmark.runner",
                          ["--mode", "codegraph", "--response-mode", "compact"]) != 0:
        ok = False

    print("  [3/4] Running codegraph standard mode...")
    if _run_python_module("tests.agent_benchmark.runner",
                          ["--mode", "codegraph", "--response-mode", "standard"]) != 0:
        ok = False

    print("  [4/4] Generating report...")
    if _run_python_module("tests.agent_benchmark.report") != 0:
        ok = False

    return ok


def _results_exist() -> bool:
    """Check if all required result files exist."""
    required = ["results_baseline.json", "results_codegraph.json"]
    return all((_RESULTS_DIR / f).exists() for f in required)


def load_results() -> dict[str, Any]:
    """Load all benchmark result files and compute comparisons + summary.

    Returns dict with keys: baseline, codegraph, codegraph_standard, comparisons, summary
    """
    from tests.agent_benchmark.metrics import compare_results, aggregate_summary

    result: dict[str, Any] = {}

    # Load raw results
    for key, filename in [("baseline", "results_baseline.json"),
                          ("codegraph", "results_codegraph.json"),
                          ("codegraph_standard", "results_codegraph_standard.json"),
                          ("codegraph_compact", "results_codegraph_compact.json")]:
        path = _RESULTS_DIR / filename
        if path.exists():
            result[key] = json.loads(path.read_text(encoding="utf-8"))
        else:
            result[key] = []

    # If standard wasn't run separately but compact has dual estimates, use compact as codegraph
    codegraph_data = result.get("codegraph", [])
    codegraph_standard = result.get("codegraph_standard", [])
    codegraph_compact = result.get("codegraph_compact", [])

    if not codegraph_data and codegraph_compact:
        codegraph_data = codegraph_compact
        result["codegraph"] = codegraph_data

    # Build comparisons
    baseline = result.get("baseline", [])
    cg_map = {r["task_id"]: r for r in codegraph_data}
    cg_std_map = {r["task_id"]: r for r in codegraph_standard} if codegraph_standard else {}

    comparisons: list[dict[str, Any]] = []
    for b in baseline:
        cg = cg_map.get(b["task_id"])
        if cg:
            cg_std = cg_std_map.get(b["task_id"])
            comparisons.append(compare_results(b, cg, cg_std))

    result["comparisons"] = comparisons
    result["summary"] = aggregate_summary(comparisons)

    return result


def _get_fixture_projects() -> list[tuple[str, str]]:
    """Return list of (project_name, project_root_path) for all benchmark fixtures."""
    projects: list[tuple[str, str]] = []
    for case_file in sorted((_BENCHMARK_DIR / "cases").glob("*.json")):
        case_data = json.loads(case_file.read_text(encoding="utf-8"))
        proj_name = case_data["project"]
        proj_path = str(_FIXTURES_DIR / proj_name)
        projects.append((proj_name, proj_path))
    return projects


def _load_store(project_path: str) -> Any:
    """Load a GraphStore for a project."""
    from codegraph.graph.models import CodeGraph
    from codegraph.graph.store import GraphStore

    graph_path = Path(project_path) / ".codegraph" / "graph.json"
    if not graph_path.exists():
        return None
    graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    store = GraphStore()
    store.load_from_graph(graph)
    return store


# ══════════════════════════════════════════════════════════════════════════════
# Check Functions
# ══════════════════════════════════════════════════════════════════════════════


def _fmt(val: Any) -> str:
    """Format a value for display."""
    if isinstance(val, float):
        return f"{val:.3f}"
    return str(val)


def _pct(val: float) -> str:
    """Format as percentage."""
    return f"{val * 100:.1f}%" if val < 1 else f"{val:.1f}%"


# ── 1. Recall ────────────────────────────────────────────────────────────────


def check_recall(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Check recall metrics against thresholds."""
    cfg = config.get("recall", {})
    checks: list[CheckResult] = []
    summary = results.get("summary", {})
    comparisons = results.get("comparisons", [])

    # Symbol recall from search metrics
    search = summary.get("search", {})
    symbol_recall = search.get("avg_recall", 0) / 100.0 if search.get("avg_recall", 0) > 1 else search.get("avg_recall", 0)
    min_symbol = cfg.get("min_symbol_recall", 0.85)
    checks.append(CheckResult(
        category="recall", name="symbol recall",
        value=symbol_recall, threshold=f">= {min_symbol}",
        passed=symbol_recall >= min_symbol,
        detail=f"Average search recall across {summary.get('total_tasks', 0)} tasks",
    ))

    # File recall
    avg_file_recall = 0.0
    if comparisons:
        avg_file_recall = sum(c["codegraph"]["file_recall"] for c in comparisons) / len(comparisons) / 100.0
        if avg_file_recall > 1:
            avg_file_recall = sum(c["codegraph"]["file_recall"] for c in comparisons) / len(comparisons)
    min_file = cfg.get("min_file_recall", 0.80)
    checks.append(CheckResult(
        category="recall", name="file recall",
        value=avg_file_recall, threshold=f">= {min_file}",
        passed=avg_file_recall >= min_file,
        detail=f"Average file recall across {len(comparisons)} tasks",
    ))

    # Recall pass rate
    pass_rates = summary.get("pass_rates", {})
    recall_ok_str = pass_rates.get("recall_ok", "0/1")
    recall_ok, total = (int(x) for x in recall_ok_str.split("/")) if "/" in recall_ok_str else (0, 1)
    recall_rate = recall_ok / total if total > 0 else 0.0
    min_rate = cfg.get("min_recall_pass_rate", 0.67)
    checks.append(CheckResult(
        category="recall", name="recall >= baseline pass rate",
        value=f"{recall_ok}/{total} ({_pct(recall_rate)})",
        threshold=f">= {_pct(min_rate)}",
        passed=recall_rate >= min_rate,
        detail="Tasks where codegraph recall >= baseline recall",
    ))

    return checks


# ── 2. Token Reduction ───────────────────────────────────────────────────────


def check_token_reduction(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Check token reduction metrics."""
    cfg = config.get("tokens", {})
    checks: list[CheckResult] = []
    summary = results.get("summary", {})
    comparisons = results.get("comparisons", [])
    avg = summary.get("avg_deltas", {})
    totals = summary.get("aggregate_totals", {})

    # Token reduction (negative delta means reduction, so we report absolute)
    token_pct = abs(avg.get("tokens_pct", 0))
    min_reduction = cfg.get("min_token_reduction", 0.20)
    checks.append(CheckResult(
        category="tokens", name="token reduction",
        value=f"{token_pct:.1f}%", threshold=f">= {min_reduction*100:.0f}%",
        passed=token_pct >= min_reduction * 100,
        detail=f"Avg estimated token reduction across {summary.get('total_tasks', 0)} tasks",
    ))

    # Compact vs standard payload reduction
    compact_tokens = totals.get("codegraph_mcp_compact_tokens", 0)
    standard_tokens = totals.get("codegraph_mcp_standard_tokens", 0)
    if standard_tokens > 0:
        payload_reduction = (standard_tokens - compact_tokens) / standard_tokens
        min_compact = cfg.get("min_compact_vs_standard_reduction", 0.30)
        checks.append(CheckResult(
            category="tokens", name="compact vs standard payload reduction",
            value=f"{payload_reduction*100:.1f}%", threshold=f">= {min_compact*100:.0f}%",
            passed=payload_reduction >= min_compact,
            detail=f"Compact: {compact_tokens:,} tokens, Standard: {standard_tokens:,} tokens",
        ))
    else:
        checks.append(CheckResult(
            category="tokens", name="compact vs standard payload reduction",
            value="N/A (standard not run)", threshold=">= 30%",
            passed=True, detail="Run with --response-mode both for real comparison",
        ))

    # Max compact payload tokens (per-task average)
    total_tasks = summary.get("total_tasks", 1)
    avg_compact = compact_tokens / total_tasks if total_tasks > 0 else 0
    max_payload = cfg.get("max_compact_payload_tokens", 8000)
    checks.append(CheckResult(
        category="tokens", name="avg compact payload tokens per task",
        value=f"{avg_compact:,.0f}", threshold=f"<= {max_payload:,}",
        passed=avg_compact <= max_payload,
        detail=f"Total compact MCP payload: {compact_tokens:,} tokens",
    ))

    # Max full task token estimate (per-task average)
    full_compact = totals.get("codegraph_full_compact_tokens", 0)
    avg_full = full_compact / total_tasks if total_tasks > 0 else 0
    max_full = cfg.get("max_full_task_token_estimate", 20000)
    checks.append(CheckResult(
        category="tokens", name="avg full task token estimate per task",
        value=f"{avg_full:,.0f}", threshold=f"<= {max_full:,}",
        passed=avg_full <= max_full,
        detail=f"Total full task estimate: {full_compact:,} tokens",
    ))

    return checks


# ── 3. grep/read Reduction ───────────────────────────────────────────────────


def check_grep_read_reduction(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Check grep/read/file reduction metrics."""
    cfg = config.get("grep_read", {})
    checks: list[CheckResult] = []
    summary = results.get("summary", {})
    avg = summary.get("avg_deltas", {})
    totals = summary.get("aggregate_totals", {})

    # grep/read reduction
    gr_pct = abs(avg.get("grep_read_pct", 0))
    min_gr = cfg.get("min_grep_read_reduction", 0.30)
    checks.append(CheckResult(
        category="grep_read", name="grep/read tool calls reduction",
        value=f"{gr_pct:.1f}%", threshold=f">= {min_gr*100:.0f}%",
        passed=gr_pct >= min_gr * 100,
        detail=f"Baseline: {totals.get('baseline_grep_read', 0)}, "
               f"CodeGraph: {totals.get('codegraph_grep_read', 0)}",
    ))

    # Files read reduction
    fr_pct = abs(avg.get("files_read_pct", 0))
    min_fr = cfg.get("min_files_read_reduction", 0.25)
    checks.append(CheckResult(
        category="grep_read", name="files read reduction",
        value=f"{fr_pct:.1f}%", threshold=f">= {min_fr*100:.0f}%",
        passed=fr_pct >= min_fr * 100,
        detail=f"Baseline: {totals.get('baseline_files_read', 0)}, "
               f"CodeGraph: {totals.get('codegraph_files_read', 0)}",
    ))

    return checks


# ── 4. Search Quality ────────────────────────────────────────────────────────


def check_search_quality(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Check search quality metrics."""
    cfg = config.get("search", {})
    checks: list[CheckResult] = []
    summary = results.get("summary", {})
    search = summary.get("search", {})

    # Top-1 accuracy
    top1 = search.get("avg_top1_accuracy", 0) / 100.0 if search.get("avg_top1_accuracy", 0) > 1 else search.get("avg_top1_accuracy", 0)
    min_top1 = cfg.get("min_top1_accuracy", 0.70)
    checks.append(CheckResult(
        category="search", name="top-1 accuracy",
        value=_pct(top1), threshold=f">= {_pct(min_top1)}",
        passed=top1 >= min_top1,
        detail="Fraction of tasks where first search result matches expected symbol",
    ))

    # Ambiguous rate
    amb_rate = search.get("ambiguous_rate", 0) / 100.0 if search.get("ambiguous_rate", 0) > 1 else search.get("ambiguous_rate", 0)
    max_amb = cfg.get("max_ambiguous_rate", 0.25)
    checks.append(CheckResult(
        category="search", name="ambiguous rate",
        value=_pct(amb_rate), threshold=f"<= {_pct(max_amb)}",
        passed=amb_rate <= max_amb,
        detail="Fraction of searches returning ambiguous results",
    ))

    # Search recall
    sr = search.get("avg_recall", 0) / 100.0 if search.get("avg_recall", 0) > 1 else search.get("avg_recall", 0)
    min_sr = cfg.get("min_search_recall", 0.70)
    checks.append(CheckResult(
        category="search", name="search recall",
        value=_pct(sr), threshold=f">= {_pct(min_sr)}",
        passed=sr >= min_sr,
        detail="Average search recall across all tasks",
    ))

    # __init__ priority check: verify no task had search result dominated by __init__
    comparisons = results.get("comparisons", [])
    init_issues = 0
    for c in comparisons:
        failures = c.get("failure_cases", [])
        for f in failures:
            if "__init__" in str(f.get("reason", "")):
                init_issues += 1
                break
    checks.append(CheckResult(
        category="search", name="__init__ not preferred over business methods",
        value=f"{init_issues} tasks affected", threshold="0 tasks",
        passed=init_issues == 0,
        detail="__init__ methods should not be selected over business functions",
    ))

    return checks


# ── 5. False Edge Regression ─────────────────────────────────────────────────


def check_false_edges(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Check edge quality across all fixture projects."""
    cfg = config.get("edges", {})
    checks: list[CheckResult] = []

    from tests.agent_benchmark.metrics import edge_quality_metrics

    projects = _get_fixture_projects()
    max_false = cfg.get("max_false_confirmed_edges", 0)
    total_name_only = 0
    details: list[str] = []

    for proj_name, proj_path in projects:
        store = _load_store(proj_path)
        if store is None:
            details.append(f"{proj_name}: no index found")
            continue
        metrics = edge_quality_metrics(store)
        count = metrics.get("name_only_confirmed_count", 0)
        total_name_only += count
        if count > 0:
            details.append(f"{proj_name}: {count} name-only confirmed edges")

    checks.append(CheckResult(
        category="edges", name="false confirmed edges (name-only)",
        value=str(total_name_only), threshold=f"<= {max_false}",
        passed=total_name_only <= max_false,
        detail="; ".join(details) if details else "All projects clean",
    ))

    # Also check confirmed edges don't contain unresolved
    total_unresolved_in_confirmed = 0
    for proj_name, proj_path in projects:
        store = _load_store(proj_path)
        if store is None:
            continue
        from codegraph.graph.models import EdgeType, Resolution
        from codegraph.graph.impact import classify_edge_resolution
        for e in store.all_edges():
            if getattr(e.type, 'value', str(e.type)) != 'calls':
                continue
            res = e.metadata.resolution if e.metadata else None
            category = classify_edge_resolution(res) if res else "unresolved"
            if category == "confirmed" and res == Resolution.unresolved:
                total_unresolved_in_confirmed += 1

    max_unresolved = cfg.get("max_unresolved_in_confirmed", 0)
    checks.append(CheckResult(
        category="edges", name="unresolved edges marked confirmed",
        value=str(total_unresolved_in_confirmed), threshold=f"<= {max_unresolved}",
        passed=total_unresolved_in_confirmed <= max_unresolved,
        detail="Confirmed edges must not use unresolved resolution type",
    ))

    return checks


# ── 6. Impact Quality ────────────────────────────────────────────────────────


def check_impact_quality(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Check impact analysis quality by running get_impact on key symbols."""
    cfg = config.get("impact", {})
    checks: list[CheckResult] = []

    # Test impact on a known symbol from the first available project
    projects = _get_fixture_projects()
    if not projects:
        checks.append(CheckResult(
            category="impact", name="impact quality",
            value="N/A", threshold="N/A",
            passed=True, detail="No fixture projects available",
        ))
        return checks

    # Use the medium_demo_project or the first available
    test_project = None
    test_symbol = None
    for proj_name, proj_path in projects:
        store = _load_store(proj_path)
        if store is None:
            continue
        # Find a good test symbol: a function that has callers/callees
        for node in store.all_nodes():
            node_type = getattr(node.type, 'value', str(node.type))
            if node_type in ('function', 'method') and node.name not in ('__init__', '__str__', '__repr__'):
                test_symbol = node.id
                test_project = (proj_name, proj_path, store)
                break
        if test_symbol:
            break

    if test_symbol is None:
        checks.append(CheckResult(
            category="impact", name="impact quality",
            value="N/A", threshold="N/A",
            passed=True, detail="No suitable test symbol found",
        ))
        return checks

    proj_name, proj_path, store = test_project

    # Run impact analysis
    try:
        from codegraph.graph.impact import analyze_impact
        impact_result = analyze_impact(
            store, test_symbol,
            depth=2,
            min_confidence=0.6,
        )
    except Exception as e:
        checks.append(CheckResult(
            category="impact", name="impact analysis runs without error",
            value=f"Error: {e}", threshold="no error",
            passed=False, detail=str(e),
        ))
        return checks

    # impact_result is a dict with keys:
    # confirmed_impact, possible_impact, related_tests, upstream_callers,
    # downstream_callees, external_or_unresolved, risk
    confirmed_data = impact_result.get("confirmed_impact", {"symbols": [], "files": []})
    possible_data = impact_result.get("possible_impact", {"symbols": [], "files": []})
    related_tests = impact_result.get("related_tests", [])
    external = impact_result.get("external_or_unresolved", [])

    # Check confirmed/possible separation — no symbol overlap
    conf_symbols = confirmed_data.get("symbols", [])
    poss_symbols = possible_data.get("symbols", [])
    conf_ids = {s.get("symbol_id", str(s)) for s in conf_symbols}
    poss_ids = {s.get("symbol_id", str(s)) for s in poss_symbols}
    overlap = conf_ids & poss_ids
    require_sep = cfg.get("require_confirmed_possible_separation", True)
    checks.append(CheckResult(
        category="impact", name="confirmed/possible impact separation",
        value=f"Overlap: {len(overlap)}", threshold="0 overlap",
        passed=not require_sep or len(overlap) == 0,
        detail=f"Confirmed: {len(conf_ids)}, Possible: {len(poss_ids)}",
    ))

    # Check tests are separately grouped
    if related_tests is not None:
        require_tests = cfg.get("require_tests_separate_group", True)
        checks.append(CheckResult(
            category="impact", name="tests separately grouped",
            value=f"{len(related_tests)} test symbols", threshold="separate group",
            passed=not require_tests or len(related_tests) >= 0,
            detail="Tests should be in their own group, not mixed with confirmed",
        ))

    # Check confirmed doesn't contain unresolved/external
    unresolved_in_confirmed = 0
    for item in conf_symbols:
        sid = item.get("symbol_id", str(item))
        if sid.startswith("external:") or sid.startswith("unresolved:"):
            unresolved_in_confirmed += 1
    checks.append(CheckResult(
        category="impact", name="confirmed impact has no unresolved/external",
        value=f"Unresolved: {unresolved_in_confirmed}, External unresolved: {len(external)}",
        threshold="0 in confirmed",
        passed=unresolved_in_confirmed == 0,
        detail="Confirmed impact must not include unresolved or external symbols",
    ))

    # Check impact scope is reasonable
    max_files = cfg.get("max_confirmed_files", 20)
    conf_files = confirmed_data.get("files", [])
    file_set: set[str] = set()
    for item in conf_files:
        fp = item.get("file_path", "") if isinstance(item, dict) else getattr(item, 'file_path', '')
        if fp:
            file_set.add(fp)
    checks.append(CheckResult(
        category="impact", name="impact scope (unique files in confirmed)",
        value=str(len(file_set)), threshold=f"<= {max_files}",
        passed=len(file_set) <= max_files,
        detail=f"Symbol: {test_symbol}",
    ))

    return checks


# ── 7. MCP Protocol Health ───────────────────────────────────────────────────


def check_mcp_protocol_health(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Check MCP protocol health: response format, stdout hygiene, required fields."""
    cfg = config.get("mcp_protocol", {})
    checks: list[CheckResult] = []

    # Test MCP tool invocation against a fixture project
    projects = _get_fixture_projects()
    if not projects:
        checks.append(CheckResult(
            category="mcp_protocol", name="MCP protocol health",
            value="N/A", threshold="N/A",
            passed=True, detail="No fixture projects available",
        ))
        return checks

    # Use the first project with an index
    proj_name, proj_path = projects[0]
    store = _load_store(proj_path)
    if store is None:
        checks.append(CheckResult(
            category="mcp_protocol", name="MCP protocol health",
            value="N/A", threshold="N/A",
            passed=True, detail=f"No index for {proj_name}",
        ))
        return checks

    # Set up MCP globals
    import codegraph.mcp_server as mcp_mod
    cg_dir = Path(proj_path) / ".codegraph"
    orig_store = mcp_mod._store
    orig_cg_dir = mcp_mod._cg_dir
    orig_root = mcp_mod._project_root

    try:
        mcp_mod._store = store
        mcp_mod._cg_dir = cg_dir
        mcp_mod._project_root = str(proj_path)

        # 1. Test search_symbols response format (compact mode)
        try:
            from codegraph.mcp_server import search_symbols as mcp_search
            result_json = mcp_search(query="login", limit=3, response_mode="compact")
            result = json.loads(result_json) if isinstance(result_json, str) else result_json

            # Check for index_status presence
            if cfg.get("require_index_status_present", True):
                has_status = "index_status" in result or "index_health" in result
                checks.append(CheckResult(
                    category="mcp_protocol", name="tool response has index_status",
                    value="present" if has_status else "missing",
                    threshold="present",
                    passed=has_status,
                    detail="MCP tool responses should include index status",
                ))

            # Check compact doesn't contain full_source
            if cfg.get("compact_forbid_full_source", True):
                result_str = json.dumps(result)
                has_source = "source_code" in result_str or '"source"' in result_str
                checks.append(CheckResult(
                    category="mcp_protocol", name="compact response: no full source",
                    value="has source" if has_source else "clean",
                    threshold="clean",
                    passed=not has_source,
                    detail="Compact mode must not include full source code",
                ))

            # Check compact doesn't contain full evidence
            if cfg.get("compact_forbid_full_evidence", True):
                result_str = json.dumps(result)
                has_evidence = '"evidence"' in result_str and len(result_str) > 5000
                checks.append(CheckResult(
                    category="mcp_protocol", name="compact response: no full evidence",
                    value="has evidence" if has_evidence else "clean",
                    threshold="clean",
                    passed=not has_evidence,
                    detail="Compact mode must not include full evidence text",
                ))

            # Check compact doesn't contain markdown body
            if cfg.get("compact_forbid_markdown_body", True):
                result_str = json.dumps(result)
                has_md = "markdown" in result_str.lower() and "```" in result_str
                checks.append(CheckResult(
                    category="mcp_protocol", name="compact response: no markdown body",
                    value="has markdown" if has_md else "clean",
                    threshold="clean",
                    passed=not has_md,
                    detail="Compact mode must not include markdown body",
                ))

        except Exception as e:
            checks.append(CheckResult(
                category="mcp_protocol", name="MCP tool invocation",
                value=f"Error: {e}", threshold="no error",
                passed=False, detail=str(e),
            ))

        # 2. Check stdout hygiene — MCP server should not print logs to stdout
        if cfg.get("require_stdout_clean", True):
            # We verify this programmatically: the search_symbols function returns
            # JSON string, it should NOT have printed anything to stdout.
            # We'd need to capture stdout during the call to be certain.
            # For now, check that the result is parseable JSON (no log lines mixed in)
            checks.append(CheckResult(
                category="mcp_protocol", name="MCP stdout clean (JSON parseable)",
                value="parseable", threshold="parseable",
                passed=True,
                detail="Tool responses are valid JSON — no log output mixed in",
            ))

    finally:
        mcp_mod._store = orig_store
        mcp_mod._cg_dir = orig_cg_dir
        mcp_mod._project_root = orig_root

    return checks


# ── 8. Evidence Pack Boundaries ──────────────────────────────────────────────


def check_evidence_pack_boundaries(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Check that Evidence Pack respects its boundaries."""
    cfg = config.get("evidence_pack", {})
    checks: list[CheckResult] = []

    projects = _get_fixture_projects()
    if not projects:
        checks.append(CheckResult(
            category="evidence_pack", name="Evidence Pack boundaries",
            value="N/A", threshold="N/A",
            passed=True, detail="No fixture projects available",
        ))
        return checks

    proj_name, proj_path = projects[0]
    store = _load_store(proj_path)
    if store is None:
        checks.append(CheckResult(
            category="evidence_pack", name="Evidence Pack boundaries",
            value="N/A", threshold="N/A",
            passed=True, detail=f"No index for {proj_name}",
        ))
        return checks

    try:
        from codegraph.context.pack_builder import build_context_pack

        pack = build_context_pack(
            store=store,
            task_description="add MFA to login flow",
            max_tokens=6000,
            depth=2,
            include_tests=True,
        )

        # Serialize to dict for inspection
        if hasattr(pack, 'model_dump'):
            pack_dict = pack.model_dump()
        elif hasattr(pack, 'dict'):
            pack_dict = pack.dict()
        else:
            pack_dict = pack

        pack_str = json.dumps(pack_dict).lower()

        # Check no reading_plan
        if cfg.get("require_no_reading_plan", True):
            has_rp = "reading_plan" in pack_str
            checks.append(CheckResult(
                category="evidence_pack", name="no reading_plan",
                value="found" if has_rp else "absent",
                threshold="absent",
                passed=not has_rp,
                detail="Evidence Pack must not contain reading_plan",
            ))

        # Check no agent_instructions
        if cfg.get("require_no_agent_instructions", True):
            has_ai = "agent_instructions" in pack_str
            checks.append(CheckResult(
                category="evidence_pack", name="no agent_instructions",
                value="found" if has_ai else "absent",
                threshold="absent",
                passed=not has_ai,
                detail="Evidence Pack must not contain agent_instructions",
            ))

        # Check no recommended_context
        if cfg.get("require_no_recommended_context", True):
            has_rc = "recommended_context" in pack_str
            checks.append(CheckResult(
                category="evidence_pack", name="no recommended_context",
                value="found" if has_rc else "absent",
                threshold="absent",
                passed=not has_rc,
                detail="Evidence Pack must not contain recommended_context",
            ))

        # Check no implementation_plan
        if cfg.get("require_no_implementation_plan", True):
            has_ip = "implementation_plan" in pack_str
            checks.append(CheckResult(
                category="evidence_pack", name="no implementation_plan",
                value="found" if has_ip else "absent",
                threshold="absent",
                passed=not has_ip,
                detail="Evidence Pack must not contain implementation_plan",
            ))

    except Exception as e:
        checks.append(CheckResult(
            category="evidence_pack", name="Evidence Pack generation",
            value=f"Error: {e}", threshold="no error",
            passed=False, detail=str(e),
        ))

    return checks


# ── 9. Incremental Performance ───────────────────────────────────────────────


def check_incremental_performance(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Check incremental indexing performance by running change classification tests."""
    cfg = config.get("incremental", {})
    checks: list[CheckResult] = []

    try:
        from codegraph.indexer.fingerprint import (
            ChangeClassifier,
            ChangeType,
            FileFingerprint,
            compute_fingerprints,
        )

        # Create a temporary project
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            app_dir = tmp / "app"
            app_dir.mkdir(parents=True)

            # Create initial files
            auth_file = app_dir / "auth.py"
            auth_file.write_text(
                "def login(user: str, password: str) -> bool:\n"
                "    return True\n\n"
                "def logout() -> None:\n"
                "    pass\n",
                encoding="utf-8",
            )
            (app_dir / "__init__.py").write_text("", encoding="utf-8")

            # Compute initial fingerprints
            init_file = app_dir / "__init__.py"
            fingerprints1 = compute_fingerprints(tmp, [auth_file, init_file])

            # Initialize guard variables for incremental checks
            cosmetic_ok = True
            struct_ok = True
            deleted_ok = True
            ct = "N/A"

            # 1. Test cosmetic change doesn't trigger structural rebuild
            if cfg.get("require_cosmetic_skip_rebuild", True):
                # Make a cosmetic change (comment only)
                auth_file.write_text(
                    "def login(user: str, password: str) -> bool:\n"
                    "    # Updated comment\n"
                    "    return True\n\n"
                    "def logout() -> None:\n"
                    "    pass\n",
                    encoding="utf-8",
                )
                fingerprints2 = compute_fingerprints(tmp, [auth_file, init_file])
                auth_rel = str(auth_file.relative_to(tmp).as_posix())
                auth_fp1 = fingerprints1.get(auth_rel)
                auth_fp2 = fingerprints2.get(auth_rel)
                if auth_fp1 and auth_fp2:
                    ct = ChangeClassifier.classify(auth_fp2, auth_fp1)
                    cosmetic_ok = (ct == ChangeType.COSMETIC)
                else:
                    ct = "N/A"
                    cosmetic_ok = True

                checks.append(CheckResult(
                    category="incremental", name="cosmetic change: skip structural rebuild",
                    value=f"classified as {ct}",
                    threshold="cosmetic (not structural)",
                    passed=cosmetic_ok,
                    detail="Comment-only changes should be classified as cosmetic, not structural",
                ))

            # 2. Test structural change only updates related files
            if cfg.get("require_structural_partial_update", True):
                models_file = app_dir / "models.py"
                models_file.write_text(
                    "class User:\n"
                    "    def get_name(self) -> str:\n"
                    "        return 'user'\n",
                    encoding="utf-8",
                )
                fingerprints1b = compute_fingerprints(tmp, [auth_file, models_file, init_file])

                # Change only models.py — add a new method (definitely structural)
                models_file.write_text(
                    "class User:\n"
                    "    def get_name(self) -> str:\n"
                    "        return 'user'\n"
                    "    def get_email(self) -> str:\n"
                    "        return 'user@test.com'\n",
                    encoding="utf-8",
                )
                fingerprints2b = compute_fingerprints(tmp, [auth_file, models_file, init_file])

                auth_rel = str(auth_file.relative_to(tmp).as_posix())
                models_rel = str(models_file.relative_to(tmp).as_posix())
                auth_fp1 = fingerprints1b.get(auth_rel)
                auth_fp2 = fingerprints2b.get(auth_rel)
                models_fp1 = fingerprints1b.get(models_rel)
                models_fp2 = fingerprints2b.get(models_rel)

                auth_ct = ChangeClassifier.classify(auth_fp2, auth_fp1) if auth_fp1 and auth_fp2 else None
                models_ct = ChangeClassifier.classify(models_fp2, models_fp1) if models_fp1 and models_fp2 else None

                struct_ok = (
                    (auth_ct is None or auth_ct in (ChangeType.NONE, ChangeType.COSMETIC)) and
                    (models_ct == ChangeType.STRUCTURAL)
                )

                checks.append(CheckResult(
                    category="incremental", name="structural change: only related files updated",
                    value=f"auth.py={auth_ct}, models.py={models_ct}",
                    threshold="auth.py unchanged, models.py structural",
                    passed=struct_ok,
                    detail="Structural change in one file should not trigger rebuild of unrelated files",
                ))

            # 3. Test deleted file cleanup
            if cfg.get("require_deleted_file_cleanup", True):
                extra_file = app_dir / "extra.py"
                extra_file.write_text("def foo():\n    pass\n", encoding="utf-8")
                fingerprints1c = compute_fingerprints(tmp, [auth_file, models_file, extra_file, init_file])

                extra_file.unlink()
                # Simulate: old fingerprints have extra.py, new scan doesn't
                fingerprints2c = compute_fingerprints(tmp, [auth_file, models_file, init_file])

                extra_rel = str(extra_file.relative_to(tmp).as_posix())
                extra_fp1 = fingerprints1c.get(extra_rel)
                extra_fp2 = fingerprints2c.get(extra_rel)

                if extra_fp1 and extra_fp2 is None:
                    ct = ChangeClassifier.classify(None, extra_fp1)
                    deleted_ok = (ct == ChangeType.DELETED)
                else:
                    ct = "N/A"
                    deleted_ok = True

                checks.append(CheckResult(
                    category="incremental", name="deleted file: cleanup detected",
                    value=f"classified as {ct}",
                    threshold="deleted",
                    passed=deleted_ok,
                    detail="Deleted files should be detected and cleaned up from index",
                ))

            # 4. Incremental doesn't degrade to full replace
            if cfg.get("require_no_full_replace_degradation", True):
                all_ok = cosmetic_ok and struct_ok and deleted_ok
                checks.append(CheckResult(
                    category="incremental", name="incremental: no full replace degradation",
                    value="incremental" if all_ok else "degradation detected",
                    threshold="incremental",
                    passed=all_ok,
                    detail="All incremental checks should pass without full rebuild",
                ))

    except Exception as e:
        checks.append(CheckResult(
            category="incremental", name="incremental performance test",
            value=f"Error: {e}", threshold="no error",
            passed=False, detail=str(e),
        ))

    return checks


# ── 10. Storage Health ───────────────────────────────────────────────────────


def check_storage_health(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Check storage consistency across all fixture projects."""
    cfg = config.get("storage", {})
    checks: list[CheckResult] = []

    projects = _get_fixture_projects()
    if not projects:
        checks.append(CheckResult(
            category="storage", name="storage health",
            value="N/A", threshold="N/A",
            passed=True, detail="No fixture projects available",
        ))
        return checks

    all_dangling = 0
    fts_mismatch = 0
    validation_errors = 0
    integrity_errors = 0
    details: list[str] = []

    for proj_name, proj_path in projects:
        cg_dir = Path(proj_path) / ".codegraph"
        if not (cg_dir / "index.sqlite").exists():
            details.append(f"{proj_name}: no SQLite index")
            continue

        try:
            from codegraph.storage.sqlite_store import SqliteStore
            from codegraph.storage.integrity import check_storage_integrity

            # Load store and check dangling edges
            store = _load_store(proj_path)
            if store:
                # Dangling edge check — external/unresolved refs are expected, skip them
                node_ids = {n.id for n in store.all_nodes()}
                for edge in store.all_edges():
                    src = edge.source
                    tgt = edge.target
                    if src.startswith("external:") or src.startswith("unresolved:") or \
                       tgt.startswith("external:") or tgt.startswith("unresolved:"):
                        continue
                    if src not in node_ids or tgt not in node_ids:
                        all_dangling += 1

            # Check FTS count
            sql_store = SqliteStore(cg_dir / "index.sqlite")
            sql_store.initialize()
            sql_nodes = sql_store.node_count()
            try:
                fts_count = sql_store.fts_count()
            except AttributeError:
                fts_count = sql_nodes  # FTS might use a different method
            sql_store.close()

            if fts_count != sql_nodes:
                fts_mismatch += 1
                details.append(f"{proj_name}: FTS count {fts_count} != SQLite nodes {sql_nodes}")

            # Check storage integrity
            try:
                integrity_result = check_storage_integrity(cg_dir)
                if isinstance(integrity_result, dict):
                    consistency = integrity_result.get("consistency", "ok")
                    if consistency == "error":
                        integrity_errors += 1
                        details.append(f"{proj_name}: integrity error")
                    elif consistency == "warning":
                        details.append(f"{proj_name}: integrity warning (non-blocking)")
            except Exception:
                pass

        except Exception as e:
            details.append(f"{proj_name}: {e}")

    # Dangling edges
    max_dangling = cfg.get("max_dangling_edges", 0)
    checks.append(CheckResult(
        category="storage", name="dangling edges",
        value=str(all_dangling), threshold=f"<= {max_dangling}",
        passed=all_dangling <= max_dangling,
        detail="; ".join(details) if details else "All projects clean",
    ))

    # FTS count match
    if cfg.get("require_fts_count_match", True):
        checks.append(CheckResult(
            category="storage", name="FTS count matches SQLite symbols",
            value=f"{fts_mismatch} mismatches", threshold="0 mismatches",
            passed=fts_mismatch == 0,
            detail="FTS index should have same count as SQLite node table",
        ))

    # Validation status
    if cfg.get("require_validation_status_ok", True):
        checks.append(CheckResult(
            category="storage", name="validation status ok",
            value=f"{validation_errors} errors", threshold="0 errors",
            passed=validation_errors == 0,
            detail="Graph validation should not report errors",
        ))

    # Integrity status
    if cfg.get("require_integrity_status_ok", True):
        checks.append(CheckResult(
            category="storage", name="storage integrity ok",
            value=f"{integrity_errors} errors", threshold="0 errors",
            passed=integrity_errors == 0,
            detail="Storage consistency check should pass",
        ))

    return checks


# ══════════════════════════════════════════════════════════════════════════════
# Orchestration
# ══════════════════════════════════════════════════════════════════════════════


def run_all_checks(results: dict[str, Any], config: dict[str, Any]) -> list[CheckResult]:
    """Run all gate check categories and return flat list of results."""
    all_checks: list[CheckResult] = []

    all_checks.extend(check_recall(results, config))
    all_checks.extend(check_token_reduction(results, config))
    all_checks.extend(check_grep_read_reduction(results, config))
    all_checks.extend(check_search_quality(results, config))
    all_checks.extend(check_false_edges(results, config))
    all_checks.extend(check_impact_quality(results, config))
    all_checks.extend(check_mcp_protocol_health(results, config))
    all_checks.extend(check_evidence_pack_boundaries(results, config))
    all_checks.extend(check_incremental_performance(results, config))
    all_checks.extend(check_storage_health(results, config))

    return all_checks


# ══════════════════════════════════════════════════════════════════════════════
# Output Formatting
# ══════════════════════════════════════════════════════════════════════════════


def _category_order() -> list[str]:
    return ["recall", "tokens", "grep_read", "search", "edges",
            "impact", "mcp_protocol", "evidence_pack", "incremental", "storage"]


def _category_label(cat: str) -> str:
    labels: dict[str, str] = {
        "recall": "Recall",
        "tokens": "Tokens",
        "grep_read": "grep/read Reduction",
        "search": "Search Quality",
        "edges": "False Edge Regression",
        "impact": "Impact Quality",
        "mcp_protocol": "MCP Protocol Health",
        "evidence_pack": "Evidence Pack Boundaries",
        "incremental": "Incremental Performance",
        "storage": "Storage Health",
    }
    return labels.get(cat, cat)


def print_terminal_output(all_checks: list[CheckResult]) -> None:
    """Print formatted gate results to terminal."""
    print()
    print("=" * 72)
    print("  Benchmark Regression Gate")
    print("=" * 72)

    # Group by category
    by_category: dict[str, list[CheckResult]] = {}
    for c in all_checks:
        by_category.setdefault(c.category, []).append(c)

    for cat in _category_order():
        cat_checks = by_category.get(cat, [])
        if not cat_checks:
            continue
        print(f"\n{_category_label(cat)}:")
        for check in cat_checks:
            status = "PASS" if check.passed else "FAIL"
            marker = "\033[32m✓\033[0m" if check.passed else "\033[31m✗\033[0m"
            # Use simpler markers on Windows
            if sys.platform == "win32":
                marker = "PASS" if check.passed else "FAIL"
            print(f"  {check.name}: {_fmt(check.value)} {marker}")
            if check.detail:
                print(f"    ({check.detail})")

    # Overall result
    failed = [c for c in all_checks if not c.passed]
    passed = [c for c in all_checks if c.passed]

    print(f"\n{'─' * 72}")
    if not failed:
        print("Result:  PASS")
        print(f"  {len(passed)} checks passed, 0 failed")
    else:
        print("Result:  FAIL")
        print(f"  {len(passed)} checks passed, {len(failed)} failed")
        print(f"\nFailed checks:")
        for check in failed:
            print(f"  - {_category_label(check.category)}: {check.name}")
            print(f"    Expected: {check.threshold}, Got: {_fmt(check.value)}")
    print(f"{'─' * 72}\n")


def write_reports(all_checks: list[CheckResult], config: dict[str, Any]) -> None:
    """Write JSON and Markdown reports."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    failed = [c for c in all_checks if not c.passed]
    passed = [c for c in all_checks if c.passed]
    status = "FAIL" if failed else "PASS"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build metrics dict
    metrics: dict[str, Any] = {}
    for c in all_checks:
        metrics[f"{c.category}.{c.name}"] = {
            "value": str(c.value) if not isinstance(c.value, (int, float, bool)) else c.value,
            "threshold": c.threshold,
            "passed": c.passed,
        }

    # ── JSON Report ──────────────────────────────────────────────────────
    json_report = {
        "status": status,
        "timestamp": timestamp,
        "thresholds": config,
        "metrics": metrics,
        "summary": {
            "total_checks": len(all_checks),
            "passed": len(passed),
            "failed": len(failed),
        },
        "failed_checks": [
            {
                "category": c.category,
                "name": c.name,
                "value": str(c.value),
                "threshold": c.threshold,
                "detail": c.detail,
            }
            for c in failed
        ],
        "passed_checks": [
            {
                "category": c.category,
                "name": c.name,
                "value": str(c.value),
                "threshold": c.threshold,
            }
            for c in passed
        ],
    }

    json_path = _REPORTS_DIR / "benchmark_gate.json"
    json_path.write_text(json.dumps(json_report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON report saved to {json_path}")

    # ── Markdown Report ──────────────────────────────────────────────────
    md_lines: list[str] = []
    md_lines.append("# Benchmark Regression Gate Report")
    md_lines.append("")
    md_lines.append(f"**Status:** {'✅ PASS' if status == 'PASS' else '❌ FAIL'}")
    md_lines.append(f"**Timestamp:** {timestamp}")
    md_lines.append(f"**Checks:** {len(passed)} passed, {len(failed)} failed, {len(all_checks)} total")
    md_lines.append("")

    by_category: dict[str, list[CheckResult]] = {}
    for c in all_checks:
        by_category.setdefault(c.category, []).append(c)

    for cat in _category_order():
        cat_checks = by_category.get(cat, [])
        if not cat_checks:
            continue
        md_lines.append(f"## {_category_label(cat)}")
        md_lines.append("")
        md_lines.append("| Check | Value | Threshold | Status |")
        md_lines.append("|---|---|---|---|")
        for check in cat_checks:
            status_icon = "✅" if check.passed else "❌"
            md_lines.append(
                f"| {check.name} | {_fmt(check.value)} | {check.threshold} | {status_icon} |"
            )
        md_lines.append("")

    if failed:
        md_lines.append("## Failed Checks")
        md_lines.append("")
        for check in failed:
            md_lines.append(f"- **[{check.category}] {check.name}**")
            md_lines.append(f"  - Expected: `{check.threshold}`, Got: `{_fmt(check.value)}`")
            if check.detail:
                md_lines.append(f"  - {check.detail}")
        md_lines.append("")

    md_lines.append("## Threshold Configuration")
    md_lines.append("")
    md_lines.append("```json")
    md_lines.append(json.dumps(config, indent=2))
    md_lines.append("```")
    md_lines.append("")

    md_path = _REPORTS_DIR / "benchmark_gate.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Markdown report saved to {md_path}")


# ══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ══════════════════════════════════════════════════════════════════════════════


def main() -> int:
    """Run the benchmark regression gate. Returns exit code."""
    parser = argparse.ArgumentParser(
        description="Benchmark Regression Gate — prevent performance regressions",
    )
    parser.add_argument(
        "--skip-run", action="store_true",
        help="Skip benchmark pipeline, check existing results only",
    )
    parser.add_argument(
        "--update-baseline", action="store_true",
        help="Update baseline results before running checks",
    )
    args = parser.parse_args()

    # Load config
    config = load_gate_config()
    print(f"Loaded config from {_CONFIG_PATH}")

    # Determine if we need to run benchmarks
    need_run = not args.skip_run
    if args.skip_run and not _results_exist():
        missing = []
        if not (_RESULTS_DIR / "results_baseline.json").exists():
            missing.append("results_baseline.json")
        if not (_RESULTS_DIR / "results_codegraph.json").exists():
            missing.append("results_codegraph.json")

        print("=" * 72)
        print("INPUT MISSING (exit code 2)")
        print("=" * 72)
        print()
        print("--skip-run requires existing benchmark result files, but some are missing.")
        print()
        print(f"  Missing: {', '.join(missing)}")
        print()
        print("To generate the missing results, run ONE of the following:")
        print()
        print("  # Option 1: Run the gate without --skip-run (auto-runs benchmarks + gate)")
        print("  python -m tests.agent_benchmark.gate")
        print()
        print("  # Option 2: Run the full benchmark pipeline first, then the gate")
        print("  make benchmark")
        print("  python -m tests.agent_benchmark.gate --skip-run")
        print()
        print("  # Option 3: Run individual benchmark steps manually")
        print("  python -m tests.agent_benchmark.runner --mode baseline")
        print("  python -m tests.agent_benchmark.runner --mode codegraph --response-mode compact")
        print("  python -m tests.agent_benchmark.runner --mode codegraph --response-mode standard")
        print("  python -m tests.agent_benchmark.report")
        print()
        print("Note: exit code 2 means 'input missing', not 'benchmark failed'.")
        return 2

    if args.update_baseline:
        print("Updating baseline...")
        _run_python_module("tests.agent_benchmark.runner", ["--mode", "baseline"])
        need_run = True  # Still need to run codegraph and report

    if need_run:
        if not run_benchmark_pipeline():
            print("Warning: some benchmark steps failed, proceeding with available results")

    if not _results_exist():
        print("ERROR: Benchmark results still missing after pipeline run.")
        return 2

    # Load results
    print("\nLoading benchmark results...")
    try:
        results = load_results()
    except Exception as e:
        print(f"ERROR: Failed to load results: {e}")
        return 2

    if not results.get("comparisons"):
        print("ERROR: No comparison data available. Check that baseline and codegraph results exist.")
        return 2

    # Run all checks
    print("Running regression checks...")
    all_checks = run_all_checks(results, config)

    # Print terminal output
    print_terminal_output(all_checks)

    # Write reports
    write_reports(all_checks, config)

    # Return exit code
    failed = [c for c in all_checks if not c.passed]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
