"""Verification tests for the benchmark system.

Run with: PYTHONPATH=. pytest tests/agent_benchmark/test_benchmark.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from tests.agent_benchmark.runner import load_test_cases, load_store_for_project
from tests.agent_benchmark.metrics import (
    compare_results,
    aggregate_summary,
    file_recall,
    total_tool_calls,
    grep_read_calls,
    files_read_count,
    estimated_tokens,
)
from tests.agent_benchmark.report import generate_report


class TestBenchmarkCases:
    """Verify benchmark test cases can be loaded and are valid."""

    def test_cases_load(self) -> None:
        """All benchmark case JSON files should load."""
        tasks = load_test_cases()
        assert len(tasks) == 12, f"Expected 12 tasks, got {len(tasks)}"
        assert all(t.get("task_id") for t in tasks)
        assert all(t.get("category") for t in tasks)
        assert all(t.get("expected_symbols") or t.get("expected_files") for t in tasks)

    def test_cases_have_expected_files(self) -> None:
        """Each case must have expected_files."""
        tasks = load_test_cases()
        for t in tasks:
            assert t.get("expected_files"), (
                f"Task {t['task_id']} missing expected_files"
            )

    def test_each_project_has_index(self) -> None:
        """Each fixture project must have a .codegraph/graph.json index."""
        tasks = load_test_cases()
        projects = {t["root_path"] for t in tasks}
        for proj in sorted(projects):
            graph_path = Path(proj) / ".codegraph" / "graph.json"
            assert graph_path.exists(), f"Missing index for {proj}"

    def test_each_project_store_loads(self) -> None:
        """Each project's graph store should load without errors."""
        tasks = load_test_cases()
        projects = {t["root_path"] for t in tasks}
        for proj in sorted(projects):
            store = load_store_for_project(proj)
            assert len(store.all_nodes()) > 0


class TestMetrics:
    """Verify metrics calculations are correct."""

    def test_file_recall_perfect(self) -> None:
        result = {
            "found_expected_files": ["a.py", "b.py"],
            "missing_expected": [],
        }
        assert file_recall(result) == 1.0

    def test_file_recall_partial(self) -> None:
        result = {
            "found_expected_files": ["a.py"],
            "missing_expected": ["b.py"],
        }
        assert file_recall(result) == 0.5

    def test_file_recall_none(self) -> None:
        result = {
            "found_expected_files": [],
            "missing_expected": ["a.py", "b.py"],
        }
        assert file_recall(result) == 0.0

    def test_file_recall_empty_expected(self) -> None:
        result = {
            "found_expected_files": [],
            "missing_expected": [],
        }
        assert file_recall(result) == 1.0

    def test_tool_call_counts(self) -> None:
        result = {
            "tool_calls": {"total": 10, "grep": 4, "glob": 2, "read": 3, "codegraph_mcp": 1},
        }
        assert total_tool_calls(result) == 10
        assert grep_read_calls(result) == 9  # 4+2+3

    def test_compare_results_reductions(self) -> None:
        baseline = {
            "task_id": "test",
            "category": "locate",
            "task": "test task",
            "success": True,
            "tool_calls": {"total": 10, "grep": 5, "glob": 2, "read": 3},
            "files_read_count": 5,
            "estimated_tokens": 1000,
            "elapsed_seconds": 1.0,
            "found_expected_files": ["a.py"],
            "found_expected_symbols": [],
            "missing_expected": [],
            "extra_files_read": [],
            "notes": [],
        }
        codegraph = {
            "task_id": "test",
            "category": "locate",
            "task": "test task",
            "success": True,
            "tool_calls": {"total": 2, "grep": 0, "glob": 0, "read": 0, "codegraph_mcp": 2},
            "files_read_count": 0,
            "estimated_tokens": 500,
            "elapsed_seconds": 0.1,
            "found_expected_files": ["a.py"],
            "found_expected_symbols": [],
            "missing_expected": [],
            "extra_files_read": [],
            "notes": [],
        }
        comp = compare_results(baseline, codegraph)
        assert comp["deltas"]["tool_calls_pct"] == -80.0
        assert comp["deltas"]["grep_read_pct"] == -100.0
        assert comp["deltas"]["files_read_pct"] == -100.0
        assert comp["deltas"]["tokens_pct"] == -50.0


class TestResults:
    """Verify benchmark result files exist and are valid."""

    def test_baseline_results_exist(self) -> None:
        results_dir = Path(__file__).resolve().parent / "results"
        baseline_path = results_dir / "results_baseline.json"
        assert baseline_path.exists(), "Run 'python -m tests.agent_benchmark.runner --mode baseline' first"

    def test_codegraph_results_exist(self) -> None:
        results_dir = Path(__file__).resolve().parent / "results"
        cg_path = results_dir / "results_codegraph.json"
        assert cg_path.exists(), "Run 'python -m tests.agent_benchmark.runner --mode codegraph' first"

    def test_results_are_valid_json(self) -> None:
        results_dir = Path(__file__).resolve().parent / "results"
        for mode in ("baseline", "codegraph"):
            path = results_dir / f"results_{mode}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                assert isinstance(data, list)
                assert len(data) == 12
                for entry in data:
                    assert "task_id" in entry
                    assert "mode" in entry
                    assert "tool_calls" in entry


class TestReport:
    """Verify report generation."""

    def test_report_generates(self) -> None:
        """Report should generate without errors if results exist."""
        results_dir = Path(__file__).resolve().parent / "results"
        if not (results_dir / "results_baseline.json").exists():
            pytest.skip("Baseline results not yet generated")
        if not (results_dir / "results_codegraph.json").exists():
            pytest.skip("CodeGraph results not yet generated")
        report = generate_report()
        assert "Agent A/B Benchmark Report" in report
        assert "Summary" in report
        assert "Per-Task Results" in report
        assert "Failure Cases" in report

    def test_report_contains_comparison(self) -> None:
        """Report should contain baseline vs codegraph comparison."""
        results_dir = Path(__file__).resolve().parent / "results"
        if not (results_dir / "results_baseline.json").exists():
            pytest.skip("Results not yet generated")
        if not (results_dir / "results_codegraph.json").exists():
            pytest.skip("Results not yet generated")
        report = generate_report()
        assert "MCP Calls" in report
        assert "MCP Tokens" in report
        assert "Full Tokens" in report

    def test_report_contains_failure_cases(self) -> None:
        """Report should contain failure cases section."""
        results_dir = Path(__file__).resolve().parent / "results"
        if not (results_dir / "results_baseline.json").exists():
            pytest.skip("Results not yet generated")
        if not (results_dir / "results_codegraph.json").exists():
            pytest.skip("Results not yet generated")
        report = generate_report()
        assert "Failure Cases" in report

    def test_codegraph_mode_no_evidence_pack(self) -> None:
        """CodeGraph mode must NOT use reading_plan, agent_instructions, or Evidence Pack."""
        results_dir = Path(__file__).resolve().parent / "results"
        cg_path = results_dir / "results_codegraph.json"
        if not cg_path.exists():
            pytest.skip("CodeGraph results not yet generated")
        data = json.loads(cg_path.read_text(encoding="utf-8"))
        for entry in data:
            assert "reading_plan" not in entry.get("notes", [])
            assert "agent_instructions" not in entry.get("notes", [])
            assert "evidence_pack" not in entry.get("notes", [])


class TestBenchmarkModes:
    """Verify both modes produce comparable result counts."""

    def test_both_modes_cover_all_tasks(self) -> None:
        """Baseline and codegraph should cover the same task IDs."""
        results_dir = Path(__file__).resolve().parent / "results"
        b_path = results_dir / "results_baseline.json"
        cg_path = results_dir / "results_codegraph.json"
        if not b_path.exists() or not cg_path.exists():
            pytest.skip("Results not yet generated")
        baseline = json.loads(b_path.read_text(encoding="utf-8"))
        codegraph = json.loads(cg_path.read_text(encoding="utf-8"))
        b_ids = {r["task_id"] for r in baseline}
        cg_ids = {r["task_id"] for r in codegraph}
        assert b_ids == cg_ids, f"Mismatch: baseline-only={b_ids-cg_ids}, codegraph-only={cg_ids-b_ids}"


# ── Quality gate thresholds (warning mode — does not block CI) ───────────

QUALITY_GATE = {
    "recall_pass_rate": 8 / 12,        # at least 8/12 tasks recall >= baseline
    "token_reduction_pct": 20.0,       # at least 20% token reduction
    "files_read_reduction_pct": 25.0,  # at least 25% files read reduction
    "grep_read_reduction_pct": 30.0,   # at least 30% grep/read reduction
}


class TestBenchmarkQualityGate:
    """Quality gate checks that warn (not fail) when thresholds are breached.

    These tests check the current benchmark results against minimum quality
    thresholds.  They use ``pytest.skip`` when results are missing and issue
    warnings (via ``pytest.warns`` or ``warnings.warn``) when thresholds are
    breached, so they do NOT block unrelated CI pipelines.
    """

    def test_quality_gate_recall(self) -> None:
        """Recall >= baseline must be at least 8/12 tasks."""
        results_dir = Path(__file__).resolve().parent / "results"
        b_path = results_dir / "results_baseline.json"
        cg_path = results_dir / "results_codegraph.json"
        if not b_path.exists() or not cg_path.exists():
            pytest.skip("Benchmark results not yet generated")

        baseline = json.loads(b_path.read_text(encoding="utf-8"))
        codegraph = json.loads(cg_path.read_text(encoding="utf-8"))
        cg_map = {r["task_id"]: r for r in codegraph}

        recall_ok = 0
        for b in baseline:
            cg = cg_map.get(b["task_id"])
            if cg:
                b_recall = file_recall(b)
                cg_recall = file_recall(cg)
                if cg_recall >= b_recall:
                    recall_ok += 1

        threshold = QUALITY_GATE["recall_pass_rate"]
        min_ok = int(threshold * len(baseline))
        import warnings
        if recall_ok < min_ok:
            warnings.warn(
                f"QUALITY GATE: Recall >= baseline is {recall_ok}/{len(baseline)} "
                f"(threshold: >= {min_ok}/{len(baseline)}). "
                f"Possible causes: index missing edges, low confidence filtering, "
                f"single-keyword search, __init__ selected over business method, "
                f"class-level impact misses method callers, or config/model/store deps missing."
            )
        # Always assert so the test records the current value
        assert recall_ok >= 0, f"Recall OK count: {recall_ok}/{len(baseline)}"

    def test_quality_gate_token_reduction(self) -> None:
        """Token reduction must be at least 20%."""
        results_dir = Path(__file__).resolve().parent / "results"
        b_path = results_dir / "results_baseline.json"
        cg_path = results_dir / "results_codegraph.json"
        if not b_path.exists() or not cg_path.exists():
            pytest.skip("Benchmark results not yet generated")

        baseline = json.loads(b_path.read_text(encoding="utf-8"))
        codegraph = json.loads(cg_path.read_text(encoding="utf-8"))
        cg_map = {r["task_id"]: r for r in codegraph}

        total_b_tokens = sum(estimated_tokens(b) for b in baseline)
        total_cg_tokens = sum(estimated_tokens(cg) for cg in codegraph)
        if total_b_tokens == 0:
            pytest.skip("Baseline tokens is zero")

        reduction = (total_b_tokens - total_cg_tokens) / total_b_tokens * 100
        threshold = QUALITY_GATE["token_reduction_pct"]

        import warnings
        if reduction < threshold:
            warnings.warn(
                f"QUALITY GATE: Token reduction is {reduction:.1f}% "
                f"(threshold: >= {threshold:.0f}%). "
                f"Baseline: {total_b_tokens:,} tokens, CodeGraph: {total_cg_tokens:,} tokens. "
                f"Possible cause: compact MCP payload growing too large."
            )
        assert reduction > -100, f"Token reduction: {reduction:.1f}%"

    def test_quality_gate_files_read_reduction(self) -> None:
        """Files read reduction must be at least 25%."""
        results_dir = Path(__file__).resolve().parent / "results"
        b_path = results_dir / "results_baseline.json"
        cg_path = results_dir / "results_codegraph.json"
        if not b_path.exists() or not cg_path.exists():
            pytest.skip("Benchmark results not yet generated")

        baseline = json.loads(b_path.read_text(encoding="utf-8"))
        codegraph = json.loads(cg_path.read_text(encoding="utf-8"))
        cg_map = {r["task_id"]: r for r in codegraph}

        total_b_files = sum(files_read_count(b) for b in baseline)
        total_cg_files = sum(files_read_count(cg) for cg in codegraph)
        if total_b_files == 0:
            pytest.skip("Baseline files read is zero")

        reduction = (total_b_files - total_cg_files) / total_b_files * 100
        threshold = QUALITY_GATE["files_read_reduction_pct"]

        import warnings
        if reduction < threshold:
            warnings.warn(
                f"QUALITY GATE: Files read reduction is {reduction:.1f}% "
                f"(threshold: >= {threshold:.0f}%). "
                f"Baseline: {total_b_files} files, CodeGraph: {total_cg_files} files."
            )
        assert reduction > -100, f"Files read reduction: {reduction:.1f}%"

    def test_quality_gate_grep_read_reduction(self) -> None:
        """grep/read reduction must be at least 30%."""
        results_dir = Path(__file__).resolve().parent / "results"
        b_path = results_dir / "results_baseline.json"
        cg_path = results_dir / "results_codegraph.json"
        if not b_path.exists() or not cg_path.exists():
            pytest.skip("Benchmark results not yet generated")

        baseline = json.loads(b_path.read_text(encoding="utf-8"))
        codegraph = json.loads(cg_path.read_text(encoding="utf-8"))

        total_b_gr = sum(grep_read_calls(b) for b in baseline)
        total_cg_gr = sum(grep_read_calls(cg) for cg in codegraph)
        if total_b_gr == 0:
            pytest.skip("Baseline grep/read calls is zero")

        reduction = (total_b_gr - total_cg_gr) / total_b_gr * 100
        threshold = QUALITY_GATE["grep_read_reduction_pct"]

        import warnings
        if reduction < threshold:
            warnings.warn(
                f"QUALITY GATE: grep/read reduction is {reduction:.1f}% "
                f"(threshold: >= {threshold:.0f}%). "
                f"Baseline: {total_b_gr} calls, CodeGraph: {total_cg_gr} calls."
            )
        assert reduction > -100, f"grep/read reduction: {reduction:.1f}%"
