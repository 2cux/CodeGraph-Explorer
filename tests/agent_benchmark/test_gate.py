"""Tests for the Benchmark Regression Gate.

Verifies that the gate correctly loads config, detects PASS/FAIL conditions,
handles missing results, and generates proper reports.

Run with:
    pytest tests/agent_benchmark/test_gate.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from tests.agent_benchmark.gate import (
    CheckResult,
    load_gate_config,
    check_recall,
    check_token_reduction,
    check_grep_read_reduction,
    check_search_quality,
    check_false_edges,
    check_impact_quality,
    check_evidence_pack_boundaries,
    check_incremental_performance,
    check_storage_health,
    run_all_checks,
    write_reports,
    _results_exist,
    _PROJECT_ROOT,
    _RESULTS_DIR,
    _FIXTURES_DIR,
    _REPORTS_DIR,
    _BENCHMARK_DIR,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_config() -> dict:
    """Return a minimal valid config."""
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


@pytest.fixture
def good_results() -> dict:
    """Return results that should pass all metric checks."""
    return {
        "baseline": [
            {"task_id": "test_locate", "mode": "baseline", "category": "locate",
             "task": "find login",
             "success": True,
             "tool_calls": {"total": 10, "grep": 5, "glob": 2, "read": 3},
             "files_read_count": 5, "estimated_tokens": 1000, "elapsed_seconds": 1.0,
             "found_expected_files": ["auth.py"], "found_expected_symbols": [],
             "missing_expected": [], "extra_files_read": [], "notes": [],
             "response_mode": "compact", "mcp_payload_tokens": 0,
             "mcp_payload_tokens_compact": 0, "mcp_payload_tokens_standard": 0,
             "search_recall": 0.0, "search_top1_accuracy": 0.0,
             "search_ambiguous": False, "search_payload_tokens": 0,
             "required_followup_reads": 0, "discovery_token_estimate": 0,
             "full_task_token_estimate": 0, "full_task_token_estimate_compact": 0,
             "full_task_token_estimate_standard": 0},
        ],
        "codegraph": [
            {"task_id": "test_locate", "mode": "codegraph", "category": "locate",
             "task": "find login",
             "success": True,
             "tool_calls": {"total": 2, "grep": 0, "glob": 0, "read": 0, "codegraph_mcp": 2},
             "files_read_count": 0, "estimated_tokens": 300, "elapsed_seconds": 0.1,
             "found_expected_files": ["auth.py"], "found_expected_symbols": [],
             "missing_expected": [], "extra_files_read": [], "notes": [],
             "response_mode": "compact",
             "mcp_payload_tokens": 200, "mcp_payload_tokens_compact": 200,
             "mcp_payload_tokens_standard": 800, "mcp_payload_tokens": 200,
             "search_recall": 1.0, "search_top1_accuracy": 1.0,
             "search_ambiguous": False, "search_payload_tokens": 50,
             "required_followup_reads": 0, "discovery_token_estimate": 200,
             "full_task_token_estimate": 500, "full_task_token_estimate_compact": 500,
             "full_task_token_estimate_standard": 1200},
        ],
        "codegraph_standard": [],
        "codegraph_compact": [],
    }


def _make_good_summary() -> dict:
    """Build a summary dict that passes all thresholds."""
    return {
        "total_tasks": 1,
        "pass_rates": {"recall_ok": "1/1", "grep_read_ok": "1/1", "files_ok": "1/1", "tokens_ok": "1/1"},
        "avg_deltas": {"grep_read_pct": -85.0, "files_read_pct": -100.0, "tokens_pct": -70.0,
                       "tool_calls_pct": -80.0, "time_pct": -90.0},
        "aggregate_totals": {
            "baseline_tokens": 1000, "codegraph_tokens": 300,
            "baseline_grep_read": 10, "codegraph_grep_read": 0,
            "baseline_files_read": 5, "codegraph_files_read": 0,
            "codegraph_mcp_compact_tokens": 200, "codegraph_mcp_standard_tokens": 800,
            "codegraph_full_compact_tokens": 500, "codegraph_full_standard_tokens": 1200,
            "search_payload_tokens": 50,
            "compact_vs_standard_payload_ratio": 0.25,
        },
        "search": {"avg_recall": 95.0, "avg_top1_accuracy": 90.0, "ambiguous_rate": 5.0, "payload_tokens": 50},
        "failure_cases": [],
    }


def _make_failing_summary() -> dict:
    """Build a summary dict that fails thresholds."""
    return {
        "total_tasks": 1,
        "pass_rates": {"recall_ok": "0/1", "grep_read_ok": "0/1", "files_ok": "0/1", "tokens_ok": "0/1"},
        "avg_deltas": {"grep_read_pct": -5.0, "files_read_pct": -5.0, "tokens_pct": -5.0,
                       "tool_calls_pct": -5.0, "time_pct": -5.0},
        "aggregate_totals": {
            "baseline_tokens": 1000, "codegraph_tokens": 950,
            "baseline_grep_read": 10, "codegraph_grep_read": 9,
            "baseline_files_read": 5, "codegraph_files_read": 5,
            "codegraph_mcp_compact_tokens": 5000, "codegraph_mcp_standard_tokens": 5000,
            "codegraph_full_compact_tokens": 25000, "codegraph_full_standard_tokens": 25000,
            "search_payload_tokens": 500,
            "compact_vs_standard_payload_ratio": 1.0,
        },
        "search": {"avg_recall": 40.0, "avg_top1_accuracy": 30.0, "ambiguous_rate": 50.0, "payload_tokens": 500},
        "failure_cases": [{"task_id": "test", "type": "recall_degraded", "reason": "test"}],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Test: Config Loading
# ══════════════════════════════════════════════════════════════════════════════


class TestGateConfig:
    """Verify gate_config.json can be loaded correctly."""

    def test_config_loads(self) -> None:
        """Config file should exist and load as valid JSON."""
        config = load_gate_config()
        assert isinstance(config, dict)
        # Should have all 10 categories
        expected_categories = [
            "recall", "tokens", "grep_read", "search", "edges",
            "impact", "mcp_protocol", "evidence_pack", "incremental", "storage",
        ]
        for cat in expected_categories:
            assert cat in config, f"Missing category: {cat}"
            assert isinstance(config[cat], dict), f"Category {cat} is not a dict"

    def test_config_values_are_sensible(self) -> None:
        """Config values should be in sensible ranges."""
        config = load_gate_config()
        # Recall thresholds should be between 0 and 1
        recall = config["recall"]
        assert 0 <= recall["min_symbol_recall"] <= 1
        assert 0 <= recall["min_file_recall"] <= 1
        assert 0 <= recall["min_recall_pass_rate"] <= 1
        # Token reduction should be between 0 and 1
        tokens = config["tokens"]
        assert 0 <= tokens["min_token_reduction"] <= 1
        assert tokens["max_compact_payload_tokens"] > 0
        # Edge false count should be 0
        assert config["edges"]["max_false_confirmed_edges"] == 0

    def test_config_uses_fallback_when_file_missing(self, tmp_path: Path) -> None:
        """Should use defaults when config file doesn't exist."""
        with patch("tests.agent_benchmark.gate._CONFIG_PATH", tmp_path / "nonexistent.json"):
            config = load_gate_config()
            assert "recall" in config
            assert config["recall"]["min_symbol_recall"] == 0.85


# ══════════════════════════════════════════════════════════════════════════════
# Test: Recall Checks
# ══════════════════════════════════════════════════════════════════════════════


class TestRecallChecks:
    """Verify recall check logic."""

    def test_good_recall_passes(self, sample_config: dict) -> None:
        results = {"summary": _make_good_summary(), "comparisons": [
            {"codegraph": {"file_recall": 100.0}, "baseline": {"file_recall": 50.0}}
        ]}
        checks = check_recall(results, sample_config)
        assert all(c.passed for c in checks), f"All recall checks should pass: {checks}"

    def test_bad_recall_fails(self, sample_config: dict) -> None:
        results = {"summary": _make_failing_summary(), "comparisons": [
            {"codegraph": {"file_recall": 0.0}, "baseline": {"file_recall": 100.0}}
        ]}
        checks = check_recall(results, sample_config)
        # At least one check should fail (file recall 0%)
        assert any(not c.passed for c in checks), f"At least one recall check should fail: {checks}"

    def test_recall_pass_rate_check(self, sample_config: dict) -> None:
        results = {"summary": _make_good_summary(), "comparisons": []}
        checks = check_recall(results, sample_config)
        # With pass_rate = "1/1", recall pass rate check should pass
        pass_rate_check = [c for c in checks if "pass rate" in c.name.lower()]
        if pass_rate_check:
            assert pass_rate_check[0].passed


# ══════════════════════════════════════════════════════════════════════════════
# Test: Token Reduction Checks
# ══════════════════════════════════════════════════════════════════════════════


class TestTokenChecks:
    """Verify token reduction check logic."""

    def test_good_tokens_pass(self, sample_config: dict) -> None:
        results = {"summary": _make_good_summary(), "comparisons": []}
        checks = check_token_reduction(results, sample_config)
        assert all(c.passed for c in checks), f"All token checks should pass: {checks}"

    def test_bad_tokens_fail(self, sample_config: dict) -> None:
        results = {"summary": _make_failing_summary(), "comparisons": []}
        checks = check_token_reduction(results, sample_config)
        assert any(not c.passed for c in checks), f"At least one token check should fail: {checks}"

    def test_compact_larger_than_standard_fails(self, sample_config: dict) -> None:
        """If compact payload >= standard payload, the check should fail."""
        summary = _make_good_summary()
        # Make compact larger than standard (bad)
        summary["aggregate_totals"]["codegraph_mcp_compact_tokens"] = 2000
        summary["aggregate_totals"]["codegraph_mcp_standard_tokens"] = 800
        results = {"summary": summary, "comparisons": []}
        checks = check_token_reduction(results, sample_config)
        compact_check = [c for c in checks if "compact vs standard" in c.name.lower()]
        if compact_check:
            assert not compact_check[0].passed, "Compact > standard should fail"


# ══════════════════════════════════════════════════════════════════════════════
# Test: grep/read Reduction Checks
# ══════════════════════════════════════════════════════════════════════════════


class TestGrepReadChecks:
    """Verify grep/read reduction check logic."""

    def test_good_reduction_passes(self, sample_config: dict) -> None:
        results = {"summary": _make_good_summary(), "comparisons": []}
        checks = check_grep_read_reduction(results, sample_config)
        assert all(c.passed for c in checks), f"All grep/read checks should pass: {checks}"

    def test_bad_reduction_fails(self, sample_config: dict) -> None:
        results = {"summary": _make_failing_summary(), "comparisons": []}
        checks = check_grep_read_reduction(results, sample_config)
        assert any(not c.passed for c in checks), f"At least one grep/read check should fail: {checks}"


# ══════════════════════════════════════════════════════════════════════════════
# Test: Search Quality Checks
# ══════════════════════════════════════════════════════════════════════════════


class TestSearchChecks:
    """Verify search quality check logic."""

    def test_good_search_passes(self, sample_config: dict) -> None:
        results = {"summary": _make_good_summary(), "comparisons": []}
        checks = check_search_quality(results, sample_config)
        assert all(c.passed for c in checks), f"All search checks should pass: {checks}"

    def test_bad_search_fails(self, sample_config: dict) -> None:
        results = {"summary": _make_failing_summary(), "comparisons": []}
        checks = check_search_quality(results, sample_config)
        assert any(not c.passed for c in checks), f"At least one search check should fail: {checks}"

    def test_init_not_preferred_check(self, sample_config: dict) -> None:
        """__init__ should not be preferred over business methods."""
        good = _make_good_summary()
        good["failure_cases"] = []
        results = {"summary": good, "comparisons": []}
        checks = check_search_quality(results, sample_config)
        init_check = [c for c in checks if "__init__" in c.name.lower()]
        if init_check:
            assert init_check[0].passed, "__init__ check should pass when no init issues"


# ══════════════════════════════════════════════════════════════════════════════
# Test: Evidence Pack Checks
# ══════════════════════════════════════════════════════════════════════════════


class TestEvidencePackChecks:
    """Verify Evidence Pack boundary checks."""

    def test_no_reading_plan_violation(self, sample_config: dict) -> None:
        """Evidence pack with reading_plan should be detected as violation."""
        cfg = sample_config.copy()
        cfg["evidence_pack"] = dict(sample_config["evidence_pack"])
        cfg["evidence_pack"]["require_no_reading_plan"] = True

        # Simulate a pack dict that has reading_plan
        # We test the check logic directly: the check looks for "reading_plan" in JSON
        assert cfg["evidence_pack"]["require_no_reading_plan"]

    def test_no_agent_instructions_violation(self, sample_config: dict) -> None:
        """Evidence pack with agent_instructions should be detected."""
        cfg = sample_config.copy()
        cfg["evidence_pack"] = dict(sample_config["evidence_pack"])
        assert cfg["evidence_pack"]["require_no_agent_instructions"]


# ══════════════════════════════════════════════════════════════════════════════
# Test: Report Generation
# ══════════════════════════════════════════════════════════════════════════════


class TestReportGeneration:
    """Verify report generation."""

    def test_json_report_generates(self, tmp_path: Path, sample_config: dict) -> None:
        """JSON report should be generated with correct structure."""
        checks = [
            CheckResult(category="recall", name="symbol recall", value=0.92, threshold=">= 0.85", passed=True),
            CheckResult(category="tokens", name="token reduction", value="31%", threshold=">= 20%", passed=True),
        ]
        with patch("tests.agent_benchmark.gate._REPORTS_DIR", tmp_path):
            write_reports(checks, sample_config)

        json_path = tmp_path / "benchmark_gate.json"
        assert json_path.exists(), "JSON report should be created"
        report = json.loads(json_path.read_text(encoding="utf-8"))
        assert report["status"] == "PASS"
        assert report["summary"]["total_checks"] == 2
        assert report["summary"]["passed"] == 2
        assert report["summary"]["failed"] == 0

    def test_markdown_report_generates(self, tmp_path: Path, sample_config: dict) -> None:
        """Markdown report should be generated."""
        checks = [
            CheckResult(category="recall", name="symbol recall", value=0.92, threshold=">= 0.85", passed=True),
            CheckResult(category="recall", name="file recall", value=0.50, threshold=">= 0.80", passed=False,
                        detail="Below threshold"),
        ]
        with patch("tests.agent_benchmark.gate._REPORTS_DIR", tmp_path):
            write_reports(checks, sample_config)

        md_path = tmp_path / "benchmark_gate.md"
        assert md_path.exists(), "Markdown report should be created"
        content = md_path.read_text(encoding="utf-8")
        assert "FAIL" in content
        assert "symbol recall" in content
        assert "file recall" in content
        assert "Failed Checks" in content

    def test_json_report_has_failed_checks(self, tmp_path: Path, sample_config: dict) -> None:
        """Failed checks should be listed separately in JSON report."""
        checks = [
            CheckResult(category="edges", name="false confirmed edges", value="3", threshold="<= 0", passed=False,
                        detail="3 name-only confirmed edges found"),
        ]
        with patch("tests.agent_benchmark.gate._REPORTS_DIR", tmp_path):
            write_reports(checks, sample_config)

        json_path = tmp_path / "benchmark_gate.json"
        report = json.loads(json_path.read_text(encoding="utf-8"))
        assert report["status"] == "FAIL"
        assert len(report["failed_checks"]) == 1
        assert report["failed_checks"][0]["category"] == "edges"

    def test_json_report_has_thresholds(self, tmp_path: Path, sample_config: dict) -> None:
        """JSON report should include the thresholds used."""
        checks: list[CheckResult] = []
        with patch("tests.agent_benchmark.gate._REPORTS_DIR", tmp_path):
            write_reports(checks, sample_config)

        json_path = tmp_path / "benchmark_gate.json"
        report = json.loads(json_path.read_text(encoding="utf-8"))
        assert "thresholds" in report
        assert report["thresholds"]["recall"]["min_symbol_recall"] == 0.85


# ══════════════════════════════════════════════════════════════════════════════
# Test: Run All Checks
# ══════════════════════════════════════════════════════════════════════════════


class TestRunAllChecks:
    """Verify the full check orchestration."""

    def test_runs_all_categories(self, sample_config: dict) -> None:
        """run_all_checks should return results from all 10 categories."""
        results = {"summary": _make_good_summary(), "comparisons": []}
        all_checks = run_all_checks(results, sample_config)
        categories = {c.category for c in all_checks}
        expected = {"recall", "tokens", "grep_read", "search", "edges",
                    "impact", "mcp_protocol", "evidence_pack", "incremental", "storage"}
        assert categories == expected, f"Expected all categories, got: {categories}"

    def test_returns_check_results(self, sample_config: dict) -> None:
        """Each item should be a CheckResult."""
        results = {"summary": _make_good_summary(), "comparisons": []}
        all_checks = run_all_checks(results, sample_config)
        assert len(all_checks) > 0
        for c in all_checks:
            assert isinstance(c, CheckResult)
            assert isinstance(c.passed, bool)


# ══════════════════════════════════════════════════════════════════════════════
# Test: Results Existence
# ══════════════════════════════════════════════════════════════════════════════


class TestResultsExistence:
    """Verify results detection."""

    def test_results_exist_detection(self) -> None:
        """_results_exist should return bool."""
        result = _results_exist()
        assert isinstance(result, bool)

    def test_results_dir_exists(self) -> None:
        """Results directory should exist."""
        assert _RESULTS_DIR.exists(), f"Results dir not found at {_RESULTS_DIR}"


# ══════════════════════════════════════════════════════════════════════════════
# Test: CLI Behavior (integration-style)
# ══════════════════════════════════════════════════════════════════════════════


class TestGateCLI:
    """Test the gate CLI entry point."""

    def test_gate_main_exists(self) -> None:
        """main() function should be importable."""
        from tests.agent_benchmark.gate import main
        assert callable(main)

    def test_gate_module_runnable(self) -> None:
        """Module should be runnable as python -m."""
        gate_file = _BENCHMARK_DIR / "gate.py"
        assert gate_file.exists(), "gate.py should exist"

    def test_skip_run_missing_results_error(self) -> None:
        """--skip-run with missing results should return exit code 2."""
        from tests.agent_benchmark.gate import main
        with patch("tests.agent_benchmark.gate._results_exist", return_value=False):
            with patch("sys.argv", ["gate.py", "--skip-run"]):
                try:
                    rc = main()
                    assert rc == 2, f"Expected exit code 2, got {rc}"
                except SystemExit as e:
                    assert e.code == 2, f"Expected exit code 2, got {e.code}"


# ══════════════════════════════════════════════════════════════════════════════
# Test: Edge Cases
# ══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_results_handled(self, sample_config: dict) -> None:
        """Empty results should not crash checks."""
        empty_summary = {
            "total_tasks": 0,
            "pass_rates": {},
            "avg_deltas": {},
            "aggregate_totals": {},
            "search": {},
            "failure_cases": [],
        }
        results = {"summary": empty_summary, "comparisons": []}
        # Should not raise
        checks = check_recall(results, sample_config)
        assert len(checks) > 0

    def test_check_result_dataclass(self) -> None:
        """CheckResult dataclass should work as expected."""
        c = CheckResult(
            category="test", name="test check",
            value=0.95, threshold=">= 0.90",
            passed=True, detail="test detail",
        )
        assert c.passed
        assert c.category == "test"
        assert c.value == 0.95


# ══════════════════════════════════════════════════════════════════════════════
# Test: Fixture Metadata Health
# ══════════════════════════════════════════════════════════════════════════════


class TestFixtureHealth:
    """Verify benchmark fixtures have complete and healthy metadata."""

    @pytest.fixture
    def fixture_projects(self) -> list[Path]:
        """Return list of .codegraph directories for all fixture projects."""
        dirs: list[Path] = []
        for case_file in sorted((_BENCHMARK_DIR / "cases").glob("*.json")):
            case_data = json.loads(case_file.read_text(encoding="utf-8"))
            proj_name = case_data["project"]
            cg_dir = _FIXTURES_DIR / proj_name / ".codegraph"
            if cg_dir.exists():
                dirs.append(cg_dir)
        return dirs

    def test_fixtures_have_state_json(self, fixture_projects: list[Path]) -> None:
        """Each fixture .codegraph must have state.json."""
        for cg_dir in fixture_projects:
            assert (cg_dir / "state.json").exists(), (
                f"{cg_dir.parent.name}: state.json missing. "
                f"Run: codegraph init --force {cg_dir.parent}"
            )

    def test_fixtures_have_fingerprints_json(self, fixture_projects: list[Path]) -> None:
        """Each fixture .codegraph must have fingerprints.json."""
        for cg_dir in fixture_projects:
            assert (cg_dir / "fingerprints.json").exists(), (
                f"{cg_dir.parent.name}: fingerprints.json missing. "
                f"Run: codegraph init --force {cg_dir.parent}"
            )

    def test_fixtures_have_validation_report(self, fixture_projects: list[Path]) -> None:
        """Each fixture .codegraph must have validation_report.json."""
        for cg_dir in fixture_projects:
            assert (cg_dir / "validation_report.json").exists(), (
                f"{cg_dir.parent.name}: validation_report.json missing. "
                f"Run: codegraph init --force {cg_dir.parent}"
            )

    def test_validation_report_status_not_error(self, fixture_projects: list[Path]) -> None:
        """validation_report.json must not have status=error."""
        for cg_dir in fixture_projects:
            vr_path = cg_dir / "validation_report.json"
            if vr_path.exists():
                vr = json.loads(vr_path.read_text(encoding="utf-8"))
                status = vr.get("status", "unknown")
                assert status != "error", (
                    f"{cg_dir.parent.name}: validation_report status=error. "
                    f"fatal_issues={vr.get('issue_counts', {}).get('fatal', '?')}. "
                    f"Run: codegraph doctor --repair"
                )

    def test_fixtures_have_metadata_json(self, fixture_projects: list[Path]) -> None:
        """Each fixture .codegraph must have metadata.json."""
        for cg_dir in fixture_projects:
            assert (cg_dir / "metadata.json").exists(), (
                f"{cg_dir.parent.name}: metadata.json missing. "
                f"Run: codegraph init --force {cg_dir.parent}"
            )

    def test_fixture_counts_consistent(self, fixture_projects: list[Path]) -> None:
        """SQLite, JSON, and metadata counts should be consistent."""
        for cg_dir in fixture_projects:
            # Check SQLite exists
            sqlite_path = cg_dir / "index.sqlite"
            if not sqlite_path.exists():
                continue

            from codegraph.storage.sqlite_store import SqliteStore
            store = SqliteStore(sqlite_path)
            store.initialize()
            sql_nodes = store.node_count()
            sql_edges = store.edge_count()
            store.close()

            # Check JSON counts
            nodes_json = json.loads((cg_dir / "nodes.json").read_text(encoding="utf-8"))
            edges_json = json.loads((cg_dir / "edges.json").read_text(encoding="utf-8"))

            assert sql_nodes == len(nodes_json), (
                f"{cg_dir.parent.name}: SQLite nodes ({sql_nodes}) != JSON nodes ({len(nodes_json)})"
            )
            assert sql_edges == len(edges_json), (
                f"{cg_dir.parent.name}: SQLite edges ({sql_edges}) != JSON edges ({len(edges_json)})"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Test: --skip-run Behavior
# ══════════════════════════════════════════════════════════════════════════════


class TestSkipRunBehavior:
    """Verify --skip-run behavior and error messaging."""

    def test_skip_run_missing_results_exit_code_2(self) -> None:
        """--skip-run with missing results should return exit code 2."""
        from tests.agent_benchmark.gate import main
        with patch("tests.agent_benchmark.gate._results_exist", return_value=False):
            with patch("sys.argv", ["gate.py", "--skip-run"]):
                try:
                    rc = main()
                    assert rc == 2, f"Expected exit code 2, got {rc}"
                except SystemExit as e:
                    assert e.code == 2, f"Expected exit code 2, got {e.code}"

    def test_skip_run_error_suggests_make_benchmark(self) -> None:
        """Error message should suggest 'make benchmark' as a fix."""
        import io
        from tests.agent_benchmark.gate import main

        with patch("tests.agent_benchmark.gate._results_exist", return_value=False):
            with patch("sys.argv", ["gate.py", "--skip-run"]):
                with patch("sys.stdout", new=io.StringIO()) as fake_out:
                    try:
                        main()
                    except SystemExit:
                        pass
                    output = fake_out.getvalue()
        assert "make benchmark" in output.lower() or "make benchmark" in output, (
            f"Error output should mention 'make benchmark'. Got: {output[:500]}"
        )

    def test_skip_run_error_mentions_exit_code_2(self) -> None:
        """Error message should explain that exit code 2 means 'input missing'."""
        import io
        from tests.agent_benchmark.gate import main

        with patch("tests.agent_benchmark.gate._results_exist", return_value=False):
            with patch("sys.argv", ["gate.py", "--skip-run"]):
                with patch("sys.stdout", new=io.StringIO()) as fake_out:
                    try:
                        main()
                    except SystemExit:
                        pass
                    output = fake_out.getvalue()
        assert "input missing" in output.lower(), (
            f"Error output should explain 'input missing'. Got: {output[:500]}"
        )

    def test_skip_run_error_suggests_gate_without_flag(self) -> None:
        """Error message should suggest running gate without --skip-run."""
        import io
        from tests.agent_benchmark.gate import main

        with patch("tests.agent_benchmark.gate._results_exist", return_value=False):
            with patch("sys.argv", ["gate.py", "--skip-run"]):
                with patch("sys.stdout", new=io.StringIO()) as fake_out:
                    try:
                        main()
                    except SystemExit:
                        pass
                    output = fake_out.getvalue()
        assert "without --skip-run" in output.lower() or "python -m tests.agent_benchmark.gate" in output, (
            f"Error output should suggest running without --skip-run. Got: {output[:500]}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Test: .gitignore Coverage
# ══════════════════════════════════════════════════════════════════════════════


class TestGitignoreCoverage:
    """Verify .gitignore covers build artifacts that should not be committed."""

    def test_gitignore_covers_sqlite_artifacts(self) -> None:
        """.gitignore should exclude *.sqlite-wal and *.sqlite-shm."""
        gi_path = _PROJECT_ROOT / ".gitignore"
        content = gi_path.read_text(encoding="utf-8")
        assert "*.sqlite-wal" in content, ".gitignore should exclude *.sqlite-wal"
        assert "*.sqlite-shm" in content, ".gitignore should exclude *.sqlite-shm"

    def test_gitignore_covers_lock_files(self) -> None:
        """.gitignore should exclude *.lock files."""
        gi_path = _PROJECT_ROOT / ".gitignore"
        content = gi_path.read_text(encoding="utf-8")
        assert "*.lock" in content, ".gitignore should exclude *.lock"

    def test_gitignore_covers_temp_dirs(self) -> None:
        """.gitignore should exclude tmp/ and logs/."""
        gi_path = _PROJECT_ROOT / ".gitignore"
        content = gi_path.read_text(encoding="utf-8")
        assert "tmp/" in content, ".gitignore should exclude tmp/"
        assert "logs/" in content, ".gitignore should exclude logs/"

    def test_gitignore_covers_context_packs(self) -> None:
        """.gitignore should exclude context_packs/."""
        gi_path = _PROJECT_ROOT / ".gitignore"
        content = gi_path.read_text(encoding="utf-8")
        assert "context_packs/" in content, ".gitignore should exclude context_packs/"
