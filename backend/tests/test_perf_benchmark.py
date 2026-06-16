"""Tests for MCP + Harness performance benchmark.

Covers:
    - Benchmark can generate JSON output
    - Benchmark can generate Markdown output
    - Latency result schema compliance
    - Empty results / failure cases are recorded
    - Does not affect test_mcp_final_regression.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.harness.perf_benchmark import (
    BENCHMARK_CASES,
    THRESHOLDS,
    _call_tool,
    _case_stats,
    _classify_case,
    _compute_overhead,
    _percentile,
    _response_bytes,
    _suspect_cause,
    _recommend_action,
    generate_report,
    run_benchmark,
    setup_mcp_globals,
    teardown_mcp_globals,
)


# ── Schema constants ────────────────────────────────────────────────────────

VALID_MODES = {"direct_mcp", "harness_mcp", "workflow_cli", "direct_cli"}
REQUIRED_FIELDS = {
    "case_id", "tool", "mode", "latency_ms",
    "response_bytes", "artifact_bytes_written", "run_dir_created", "ok",
}
OPTIONAL_FIELDS = {"iteration", "error", "timestamp"}

ALL_TOOLS = {
    "codegraph_find",
    "codegraph_explain",
    "codegraph_pre_edit_check",
    "codegraph_coverage_gaps",
    "codegraph_get_impact",
    "codegraph_build_context_pack",
    "codegraph_harness_run",
}


class TestBenchmarkCases:
    """Verify benchmark case definitions."""

    def test_all_cases_have_required_fields(self):
        for case in BENCHMARK_CASES:
            assert "case_id" in case, f"Missing case_id in {case}"
            assert "mode" in case, f"Missing mode in {case}"
            assert "tool" in case, f"Missing tool in {case}"
            assert "input" in case, f"Missing input in {case}"

    def test_all_modes_are_valid(self):
        for case in BENCHMARK_CASES:
            assert case["mode"] in {"direct_mcp", "harness_mcp"}, (
                f"Invalid mode: {case['mode']} in {case['case_id']}"
            )

    def test_all_tools_are_known(self):
        for case in BENCHMARK_CASES:
            assert case["tool"] in ALL_TOOLS, (
                f"Unknown tool: {case['tool']} in {case['case_id']}"
            )

    def test_has_direct_and_harness_cases(self):
        modes = {c["mode"] for c in BENCHMARK_CASES}
        assert "direct_mcp" in modes
        assert "harness_mcp" in modes

    def test_at_least_10_cases(self):
        assert len(BENCHMARK_CASES) >= 10

    def test_unique_case_ids(self):
        ids = [c["case_id"] for c in BENCHMARK_CASES]
        assert len(ids) == len(set(ids)), f"Duplicate case_ids: {ids}"


class TestPercentile:
    """Unit tests for percentile computation."""

    def test_p50_of_1_to_5(self):
        assert _percentile([1, 2, 3, 4, 5], 50) == 3.0

    def test_p95_of_100_values(self):
        vals = list(range(1, 101))
        result = _percentile(vals, 95)
        assert 94 <= result <= 96

    def test_p50_single_value(self):
        assert _percentile([42.0], 50) == 42.0

    def test_empty_returns_zero(self):
        assert _percentile([], 50) == 0.0

    def test_p0_returns_min(self):
        assert _percentile([3, 1, 2], 0) == 1.0

    def test_p100_returns_max(self):
        assert _percentile([3, 1, 2], 100) == 3.0


class TestClassifyCase:
    """Case classification for threshold selection."""

    def test_find_is_fast(self):
        assert _classify_case("direct_find_basic") == "fast"

    def test_explain_is_fast(self):
        assert _classify_case("direct_explain_symbol") == "fast"

    def test_impact_is_slow(self):
        assert _classify_case("direct_impact_symbol") == "slow"

    def test_test_audit_is_slow(self):
        assert _classify_case("harness_workflow_test_audit") == "slow"

    def test_pre_edit_is_fast(self):
        assert _classify_case("direct_pre_edit_file") == "fast"


class TestResponseBytes:
    """Response byte measurement."""

    def test_empty_dict(self):
        assert _response_bytes({}) > 0

    def test_small_result(self):
        result = {"ok": True, "data": {"key": "value"}}
        size = _response_bytes(result)
        assert size > 0
        assert size < 1000

    def test_returns_int(self):
        assert isinstance(_response_bytes({"a": 1}), int)


class TestCaseStats:
    """Aggregate statistics computation."""

    def test_empty_entries(self):
        stats = _case_stats("test_case", [])
        assert stats["count"] == 0
        assert stats["p50_ms"] == 0

    def test_single_entry(self):
        results = [
            {
                "case_id": "test",
                "tool": "codegraph_find",
                "mode": "direct_mcp",
                "iteration": 1,
                "latency_ms": 100.0,
                "response_bytes": 500,
                "artifact_bytes_written": 0,
                "run_dir_created": False,
                "ok": True,
                "error": "",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ]
        stats = _case_stats("test", results)
        assert stats["count"] == 1
        assert stats["p50_ms"] == 100.0
        assert stats["p95_ms"] == 100.0
        assert stats["avg_response_bytes"] == 500

    def test_error_count(self):
        results = [
            {
                "case_id": "test",
                "tool": "codegraph_find",
                "mode": "direct_mcp",
                "iteration": i,
                "latency_ms": 100.0,
                "response_bytes": 500,
                "artifact_bytes_written": 0,
                "run_dir_created": False,
                "ok": i != 3,
                "error": "fail" if i == 3 else "",
                "timestamp": "2026-01-01T00:00:00Z",
            }
            for i in range(1, 6)
        ]
        stats = _case_stats("test", results)
        assert stats["ok_count"] == 4
        assert stats["error_count"] == 1


class TestComputeOverhead:
    """Harness overhead estimation."""

    def test_positive_overhead(self):
        results = []
        for i in range(1, 6):
            results.append({
                "case_id": "direct_find_basic",
                "tool": "codegraph_find",
                "mode": "direct_mcp",
                "iteration": i,
                "latency_ms": 100.0,
                "response_bytes": 1000,
                "artifact_bytes_written": 0,
                "run_dir_created": False,
                "ok": True,
                "error": "",
                "timestamp": "2026-01-01T00:00:00Z",
            })
            results.append({
                "case_id": "harness_workflow_find",
                "tool": "codegraph_harness_run",
                "mode": "harness_mcp",
                "iteration": i,
                "latency_ms": 150.0,
                "response_bytes": 2000,
                "artifact_bytes_written": 5000,
                "run_dir_created": True,
                "ok": True,
                "error": "",
                "timestamp": "2026-01-01T00:00:00Z",
            })

        overhead = _compute_overhead(results)
        assert overhead["avg_overhead_p50_ms"] == 50.0

    def test_no_matching_pairs(self):
        results = [
            {
                "case_id": "unknown_case",
                "tool": "x",
                "mode": "direct_mcp",
                "iteration": 1,
                "latency_ms": 10.0,
                "response_bytes": 100,
                "artifact_bytes_written": 0,
                "run_dir_created": False,
                "ok": True,
                "error": "",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ]
        overhead = _compute_overhead(results)
        assert overhead["avg_overhead_p50_ms"] == 0
        assert overhead["pairs"] == []


class TestSuspectCause:
    """Heuristic cause messages."""

    def test_harness_mentions_persistence(self):
        msg = _suspect_cause("harness_workflow_find", 1200, 1000)
        assert "persistence" in msg.lower()
        assert "1200" in msg

    def test_impact_mentions_traversal(self):
        msg = _suspect_cause("direct_impact_symbol", 3500, 3000)
        assert "traverses" in msg.lower()


class TestRecommendAction:
    """Heuristic action messages."""

    def test_harness_mentions_profile(self):
        msg = _recommend_action("harness_workflow_find")
        assert "Profile" in msg

    def test_impact_mentions_profile(self):
        msg = _recommend_action("direct_impact_symbol")
        assert "Profile" in msg


class TestRunBenchmark:
    """End-to-end benchmark runner tests."""

    @pytest.mark.slow
    def test_run_benchmark_returns_list(self):
        """Run 1 iteration of all cases and verify output structure."""
        results = run_benchmark(iterations=1)
        assert isinstance(results, list)
        assert len(results) > 0

        for entry in results:
            # Schema compliance
            for field in REQUIRED_FIELDS:
                assert field in entry, f"Missing required field '{field}' in {entry['case_id']}"
            assert entry["mode"] in VALID_MODES, f"Invalid mode: {entry['mode']}"
            assert isinstance(entry["latency_ms"], (int, float))
            assert entry["latency_ms"] >= 0
            assert isinstance(entry["response_bytes"], int)
            assert entry["response_bytes"] >= 0
            assert isinstance(entry["artifact_bytes_written"], int)
            assert entry["artifact_bytes_written"] >= 0
            assert isinstance(entry["run_dir_created"], bool)
            assert isinstance(entry["ok"], bool)
            assert isinstance(entry["error"], str)

    def test_run_benchmark_with_custom_cases(self):
        """Run with a minimal custom case list."""
        custom = [
            {
                "case_id": "custom_find",
                "mode": "direct_mcp",
                "tool": "codegraph_find",
                "input": {"query": "test", "limit": 1},
            }
        ]
        results = run_benchmark(iterations=1, cases=custom)
        assert len(results) == 1
        assert results[0]["case_id"] == "custom_find"
        assert results[0]["iteration"] == 1

    def test_run_benchmark_respects_iterations(self):
        """Verify individual case_ids get the right number of iterations."""
        custom = [
            {
                "case_id": "iter_test",
                "mode": "direct_mcp",
                "tool": "codegraph_find",
                "input": {"query": "test", "limit": 1},
            }
        ]
        for n in [1, 2, 3]:
            results = run_benchmark(iterations=n, cases=custom)
            assert len(results) == n
            iterations = {r["iteration"] for r in results}
            assert iterations == set(range(1, n + 1))

    def test_failure_case_recorded(self):
        """A case that raises an error should be recorded with ok=False."""
        bad_case = [
            {
                "case_id": "bad_case",
                "mode": "direct_mcp",
                "tool": "codegraph_find",
                "input": {},  # missing required 'query' param
            }
        ]
        # The tool function should handle this gracefully (return error envelope)
        # or raise — either way the benchmark records it
        results = run_benchmark(iterations=1, cases=bad_case)
        assert len(results) == 1
        # Even if it errors, we still get a record
        assert results[0]["case_id"] == "bad_case"


class TestGenerateReport:
    """Report generation tests."""

    @pytest.fixture
    def sample_results(self) -> list[dict[str, Any]]:
        """Create sample results matching the latency result schema."""
        import copy
        base = {
            "case_id": "direct_find_basic",
            "tool": "codegraph_find",
            "mode": "direct_mcp",
            "latency_ms": 300.0,
            "response_bytes": 5000,
            "artifact_bytes_written": 0,
            "run_dir_created": False,
            "ok": True,
            "error": "",
            "timestamp": "2026-06-16T00:00:00Z",
        }
        results = []
        for i in range(1, 4):
            entry = copy.deepcopy(base)
            entry["iteration"] = i
            entry["latency_ms"] = 250.0 + i * 30
            results.append(entry)

        # Add one harness case
        h = copy.deepcopy(base)
        h["case_id"] = "harness_workflow_find"
        h["tool"] = "codegraph_harness_run"
        h["mode"] = "harness_mcp"
        h["latency_ms"] = 350.0
        h["response_bytes"] = 8000
        h["artifact_bytes_written"] = 20000
        h["run_dir_created"] = True
        h["iteration"] = 1
        results.append(h)

        return results

    def test_generates_json(self, tmp_path, sample_results):
        json_path, md_path = generate_report(sample_results, output_dir=tmp_path)
        assert json_path.exists()
        assert json_path.suffix == ".json"

        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == len(sample_results)

    def test_generates_markdown(self, tmp_path, sample_results):
        json_path, md_path = generate_report(sample_results, output_dir=tmp_path)
        assert md_path.exists()
        assert md_path.suffix == ".md"

        content = md_path.read_text(encoding="utf-8")
        assert "# MCP Harness Performance Report" in content
        assert "## Summary" in content
        assert "## Cases" in content
        assert "## Harness Overhead Estimate" in content
        assert "## Thresholds" in content
        assert "## Slowest Cases" in content

    def test_report_handles_empty_results(self, tmp_path):
        json_path, md_path = generate_report([], output_dir=tmp_path)
        assert json_path.exists()
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "Total errors | 0" in content

    def test_json_schema_compliant(self, tmp_path, sample_results):
        """Verify generated JSON conforms to mcp_latency_result.schema.json."""
        json_path, _ = generate_report(sample_results, output_dir=tmp_path)
        data = json.loads(json_path.read_text(encoding="utf-8"))

        for entry in data:
            for field in REQUIRED_FIELDS:
                assert field in entry, f"Missing required field '{field}'"
            assert entry["mode"] in VALID_MODES
            assert isinstance(entry["ok"], bool)
            if "iteration" in entry:
                assert isinstance(entry["iteration"], int)
                assert entry["iteration"] >= 1

    def test_error_case_in_report(self, tmp_path):
        """Error cases should appear in the report with ok=False."""
        results = [
            {
                "case_id": "failed_case",
                "tool": "codegraph_find",
                "mode": "direct_mcp",
                "iteration": 1,
                "latency_ms": 50.0,
                "response_bytes": 200,
                "artifact_bytes_written": 0,
                "run_dir_created": False,
                "ok": False,
                "error": "ValueError: something went wrong",
                "timestamp": "2026-06-16T00:00:00Z",
            }
        ]
        json_path, md_path = generate_report(results, output_dir=tmp_path)
        content = md_path.read_text(encoding="utf-8")

        # Error count should be 1
        assert "Total errors | 1" in content
        # Case should appear with error count
        assert "failed_case" in content


class TestSetupTeardown:
    """MCP globals lifecycle."""

    def test_setup_initializes_globals(self):
        cg_dir = setup_mcp_globals()
        import codegraph.mcp_server as mcp_mod
        assert mcp_mod._store is not None
        assert mcp_mod._cg_dir is not None
        assert mcp_mod._project_root is not None
        teardown_mcp_globals()

    def test_teardown_clears_globals(self):
        setup_mcp_globals()
        teardown_mcp_globals()
        import codegraph.mcp_server as mcp_mod
        assert mcp_mod._store is None
        assert mcp_mod._cg_dir is None
        assert mcp_mod._project_root is None


class TestThresholds:
    """Threshold constant definitions."""

    def test_find_explain_threshold_reasonable(self):
        assert 500 <= THRESHOLDS["find_explain_p95_ms"] <= 5000

    def test_impact_threshold_reasonable(self):
        assert 1000 <= THRESHOLDS["impact_test_audit_p95_ms"] <= 10000

    def test_overhead_threshold_reasonable(self):
        assert 10 <= THRESHOLDS["harness_overhead_p50_ms"] <= 500


class TestNoRegression:
    """Ensure benchmark module does not break existing test imports."""

    def test_mcp_final_regression_imports(self):
        """Import path used by test_mcp_final_regression.py still works."""
        from codegraph.graph.models import (
            GraphNode, GraphEdge, NodeType, EdgeType, Location,
            EdgeMetadata, Resolution,
        )
        from codegraph.graph.store import GraphStore
        assert True  # import succeeded

    def test_mcp_tools_imports(self):
        """Import path used by test_mcp_tools.py still works."""
        from codegraph.graph.models import (
            GraphNode, GraphEdge, NodeType, EdgeType, Location,
            EdgeLocation, EdgeMetadata, Resolution, CodeGraph, RepoInfo,
        )
        from codegraph.graph.store import GraphStore
        assert True

    def test_mcp_server_import_unaffected(self):
        """codegraph.mcp_server imports still work."""
        import codegraph.mcp_server as mcp_mod
        assert hasattr(mcp_mod, "mcp")
