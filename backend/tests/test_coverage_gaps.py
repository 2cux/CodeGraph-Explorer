"""Tests for coverage_gaps — aggregate test coverage gap analysis.

Verifies that ``compute_coverage_gaps`` correctly identifies production
symbols and files without ``tested_by`` coverage signals, respects filters,
and produces valid summary statistics.
"""

import pytest

from codegraph.graph.models import (
    GraphNode, GraphEdge, NodeType, EdgeType, Location,
    EdgeMetadata, Resolution,
)
from codegraph.graph.store import GraphStore
from codegraph.graph.coverage_gaps import compute_coverage_gaps
from codegraph.graph.test_coverage import (
    is_test_file_path,
    TESTED_BY_HIGH_CONFIDENCE_THRESHOLD,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_node(id: str, type: NodeType, file_path: str, name: str = "") -> GraphNode:
    return GraphNode(
        id=id, type=type, name=name or id.split("::")[-1],
        file_path=file_path, module="",
        qualified_name=id,
        location=Location(line_start=1, line_end=10),
    )


def _make_edge(id: str, type: EdgeType, source: str, target: str,
               confidence: float, resolution: Resolution = Resolution.test_name_heuristic) -> GraphEdge:
    return GraphEdge(
        id=id, type=type, source=source, target=target,
        confidence=confidence,
        metadata=EdgeMetadata(resolution=resolution),
    )


def _build_store(nodes: list[GraphNode], edges: list[GraphEdge]) -> GraphStore:
    store = GraphStore()
    store.load_from_lists(nodes, edges)
    return store


# ═══════════════════════════════════════════════════════════════════════════════
# is_test_file_path unit tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsTestFilePath:
    """Unit tests for is_test_file_path (shared with test_coverage.py)."""

    def test_tests_directory(self):
        assert is_test_file_path("tests/test_auth.py") is True
        assert is_test_file_path("test/test_auth.py") is True
        assert is_test_file_path("project/tests/test_auth.py") is True

    def test_python_test_patterns(self):
        assert is_test_file_path("test_auth.py") is True
        assert is_test_file_path("auth_test.py") is True

    def test_typescript_test_patterns(self):
        assert is_test_file_path("foo.test.ts") is True
        assert is_test_file_path("bar.spec.ts") is True

    def test_go_test_patterns(self):
        assert is_test_file_path("handler_test.go") is True

    def test_java_test_patterns(self):
        assert is_test_file_path("FooTest.java") is True

    def test_production_files_not_tests(self):
        assert is_test_file_path("src/main.py") is False
        assert is_test_file_path("app/services/auth.py") is False
        assert is_test_file_path("backend/codegraph/mcp_server.py") is False

    def test_util_file_in_test_dir(self):
        """Files inside test/ directory are considered test files even without test name."""
        assert is_test_file_path("tests/conftest.py") is True
        assert is_test_file_path("tests/fixtures/helper.py") is True


# ═══════════════════════════════════════════════════════════════════════════════
# compute_coverage_gaps tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeCoverageGaps:
    """Aggregate coverage gap analysis."""

    def test_production_symbols_without_tested_by(self):
        """Production symbols with no tested_by edges appear in symbols_without_tests."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("src/main.py::logout", NodeType.function, "src/main.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        assert result["summary"]["production_symbols_checked"] == 2
        assert result["summary"]["symbols_without_test_signal"] == 2
        assert len(result["symbols_without_tests"]) == 2

    def test_high_confidence_tested_by_excluded_from_gaps(self):
        """Symbols with high-confidence tested_by are NOT in symbols_without_tests."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "src/main.py::login", "tests/test_auth.py::test_login",
                       confidence=0.90, resolution=Resolution.direct_test_call),
        ]
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        assert result["summary"]["production_symbols_checked"] == 1
        assert result["summary"]["symbols_with_high_confidence_tests"] == 1
        assert result["summary"]["symbols_without_test_signal"] == 0
        assert len(result["symbols_without_tests"]) == 0

    def test_test_symbols_excluded_from_production(self):
        """Test node type symbols are not counted as production."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        # Only the function, not the test
        assert result["summary"]["production_symbols_checked"] == 1

    def test_test_file_symbols_excluded_from_production(self):
        """Symbols in test files are excluded even if they have production types."""
        nodes = [
            _make_node("tests/helper.py::setup_data", NodeType.function, "tests/helper.py"),
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        # Only src/main.py::login should be counted
        assert result["summary"]["production_symbols_checked"] == 1

    def test_paths_filter_restricts_scope(self):
        """paths parameter limits which production symbols are checked."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("backend/server.py::start", NodeType.function, "backend/server.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store, paths=["src/**"])
        assert result["summary"]["production_symbols_checked"] == 1
        assert result["symbols_without_tests"][0]["file"] == "src/main.py"

    def test_paths_glob_expands_inside_python(self, tmp_path):
        """Quoted or unexpanded globs should resolve inside Python."""
        target = tmp_path / "backend" / "codegraph" / "graph" / "coverage_gaps.py"
        target.parent.mkdir(parents=True)
        target.write_text("# stub\n", encoding="utf-8")

        nodes = [
            _make_node(
                "backend/codegraph/graph/coverage_gaps.py::audit",
                NodeType.function,
                "backend/codegraph/graph/coverage_gaps.py",
            ),
            _make_node(
                "backend/codegraph/cli/main.py::entry",
                NodeType.function,
                "backend/codegraph/cli/main.py",
            ),
        ]
        store = _build_store(nodes, [])

        result = compute_coverage_gaps(
            store,
            project_root=tmp_path,
            paths=["backend/codegraph/**"],
        )

        assert result["summary"]["production_symbols_checked"] == 2
        assert result["path_resolution"]["resolved_file_count"] == 2
        assert "backend/codegraph/graph/coverage_gaps.py" in result["path_resolution"]["resolved_files_preview"]
        assert "backend/codegraph/cli/main.py" in result["path_resolution"]["resolved_files_preview"]

    def test_exact_file_path_scope_is_supported(self, tmp_path):
        """An exact file path should resolve without shell expansion."""
        target = tmp_path / "backend" / "codegraph" / "graph" / "coverage_gaps.py"
        target.parent.mkdir(parents=True)
        target.write_text("# stub\n", encoding="utf-8")

        nodes = [
            _make_node(
                "backend/codegraph/graph/coverage_gaps.py::audit",
                NodeType.function,
                "backend/codegraph/graph/coverage_gaps.py",
            ),
            _make_node(
                "backend/codegraph/cli/main.py::entry",
                NodeType.function,
                "backend/codegraph/cli/main.py",
            ),
        ]
        store = _build_store(nodes, [])

        result = compute_coverage_gaps(
            store,
            project_root=tmp_path,
            paths=["backend/codegraph/graph/coverage_gaps.py"],
        )

        assert result["summary"]["production_symbols_checked"] == 1
        assert result["symbols_without_tests"][0]["file"] == "backend/codegraph/graph/coverage_gaps.py"

    def test_missing_path_warns_without_crashing_scope(self, tmp_path):
        """A missing path should warn clearly but not break valid path filters."""
        target = tmp_path / "backend" / "codegraph" / "graph" / "coverage_gaps.py"
        target.parent.mkdir(parents=True)
        target.write_text("# stub\n", encoding="utf-8")

        nodes = [
            _make_node(
                "backend/codegraph/graph/coverage_gaps.py::audit",
                NodeType.function,
                "backend/codegraph/graph/coverage_gaps.py",
            ),
        ]
        store = _build_store(nodes, [])

        result = compute_coverage_gaps(
            store,
            project_root=tmp_path,
            paths=[
                "backend/codegraph/missing.py",
                "backend/codegraph/graph/coverage_gaps.py",
            ],
        )

        assert result["summary"]["production_symbols_checked"] == 1
        assert any("missing.py" in warning for warning in result["warnings"])

    def test_path_outside_project_root_warns_and_is_ignored(self, tmp_path):
        """Path scopes must not expand outside the project root."""
        outside_file = tmp_path.parent / "outside.py"
        outside_file.write_text("# outside\n", encoding="utf-8")

        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
        ]
        store = _build_store(nodes, [])

        result = compute_coverage_gaps(
            store,
            project_root=tmp_path,
            paths=[str(outside_file)],
        )

        assert result["summary"]["production_symbols_checked"] == 0
        assert any("escapes the project root" in warning for warning in result["warnings"])

    def test_types_filter_restricts_symbol_types(self):
        """types parameter limits which node types are included."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("src/main.py::User", NodeType.class_, "src/main.py"),
            _make_node("src/main.py::CONFIG", NodeType.module, "src/main.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store, types=["function"])
        assert result["summary"]["production_symbols_checked"] == 1

    def test_include_low_confidence_returns_links(self):
        """When include_low_confidence=true, low_confidence_links are returned."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "src/main.py::login", "tests/test_auth.py::test_login",
                       confidence=0.55, resolution=Resolution.test_file_heuristic),
        ]
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store, include_low_confidence=True)
        assert len(result["low_confidence_links"]) == 1
        assert result["low_confidence_links"][0]["confidence"] == 0.55
        assert result["low_confidence_links"][0]["confidence_level"] == "low"

    def test_low_confidence_not_counted_as_high(self):
        """Low-confidence tested_by does NOT count as high-confidence coverage."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "src/main.py::login", "tests/test_auth.py::test_login",
                       confidence=0.55, resolution=Resolution.test_file_heuristic),
        ]
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store, include_low_confidence=False)
        assert result["summary"]["symbols_with_high_confidence_tests"] == 0
        assert result["summary"]["symbols_with_low_confidence_tests"] == 1
        # Symbol with only low-confidence is still in "without tests" category
        # for the purpose of symbols_without_tests list
        assert result["summary"]["symbols_without_test_signal"] == 0
        assert len(result["symbols_without_tests"]) == 1
        assert result["symbols_without_tests"][0]["symbol"] == "login"

    def test_missing_confidence_is_unknown(self):
        """Edges with exactly 0 confidence go to unknown_confidence bucket."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("tests/test_auth.py::test_login", NodeType.test, "tests/test_auth.py"),
        ]
        edges = [
            GraphEdge(
                id="e1", type=EdgeType.tested_by,
                source="src/main.py::login",
                target="tests/test_auth.py::test_login",
                confidence=0.0,
            ),
        ]
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        assert result["summary"]["symbols_with_unknown_confidence_tests"] == 1
        assert result["summary"]["symbols_with_high_confidence_tests"] == 0
        assert result["summary"]["symbols_with_low_confidence_tests"] == 0
        assert len(result["symbols_without_tests"]) == 1
        assert result["symbols_without_tests"][0]["symbol"] == "login"

    def test_summary_counts(self):
        """Summary has correct aggregate counts."""
        nodes = [
            _make_node("src/a.py::f1", NodeType.function, "src/a.py"),
            _make_node("src/a.py::f2", NodeType.function, "src/a.py"),
            _make_node("src/b.py::g1", NodeType.function, "src/b.py"),
            _make_node("tests/t.py::test_f1", NodeType.test, "tests/t.py"),
            _make_node("tests/t.py::test_f2", NodeType.test, "tests/t.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "src/a.py::f1", "tests/t.py::test_f1",
                       confidence=0.90),
            _make_edge("e2", EdgeType.tested_by,
                       "src/a.py::f2", "tests/t.py::test_f2",
                       confidence=0.50),
        ]
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        s = result["summary"]
        assert s["production_symbols_checked"] == 3
        assert s["symbols_with_high_confidence_tests"] == 1
        assert s["symbols_with_low_confidence_tests"] == 1
        assert s["symbols_with_unknown_confidence_tests"] == 0
        assert s["symbols_without_test_signal"] == 1
        assert s["production_files_checked"] == 2

    def test_message_mentions_heuristic(self):
        """Message must mention this is a heuristic signal, not runtime coverage."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        msg = result["summary"]["message"].lower()
        assert "heuristic" in msg or "not line coverage" in msg or "not runtime" in msg

    def test_symbols_without_tests_respects_limit(self):
        """symbols_without_tests list is capped by limit."""
        nodes = [
            _make_node(f"src/main.py::f{i}", NodeType.function, "src/main.py")
            for i in range(10)
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store, limit=3)
        assert len(result["symbols_without_tests"]) == 3

    def test_files_without_tests_capped(self):
        """files_without_tests list is capped at default limit (20)."""
        nodes = []
        for i in range(30):
            file_path = f"src/module_{i}.py"
            nodes.append(_make_node(f"{file_path}::f", NodeType.function, file_path))
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        # files_without_tests capped at 20 by default
        assert len(result["files_without_tests"]) <= 20
        assert result["summary"]["files_without_test_signal"] == 30

    def test_warnings_present(self):
        """Response includes warnings about heuristic nature."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        assert len(result["warnings"]) >= 1
        has_warning = any(
            "heuristic" in w.lower() or "not runtime" in w.lower()
            or "not line coverage" in w.lower()
            for w in result["warnings"]
        )
        assert has_warning, f"Expected a warning about heuristic signal, got: {result['warnings']}"

    def test_next_recommended_tools_when_gaps_exist(self):
        """When gaps exist, next_recommended_tools includes get_neighbors and get_impact."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        tools = [r["tool"] for r in result["next_recommended_tools"]]
        assert "codegraph_get_neighbors" in tools
        assert "codegraph_get_impact" in tools

    def test_next_recommended_tools_empty_when_no_gaps(self):
        """When all symbols have high-confidence tests, next_recommended_tools is minimal."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("tests/t.py::test_login", NodeType.test, "tests/t.py"),
        ]
        edges = [
            _make_edge("e1", EdgeType.tested_by,
                       "src/main.py::login", "tests/t.py::test_login",
                       confidence=0.90),
        ]
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        # When no gaps, get_neighbors is not needed
        tools = [r["tool"] for r in result["next_recommended_tools"]]
        assert len(tools) == 0 or "codegraph_get_neighbors" not in tools

    def test_confidence_high_when_majority_covered(self):
        """Confidence is 'high' when >= 50% of symbols have high-confidence tests."""
        nodes = []
        edges = []
        for i in range(10):
            nodes.append(_make_node(f"src/main.py::f{i}", NodeType.function, "src/main.py"))
            nodes.append(_make_node(f"tests/t.py::test_f{i}", NodeType.test, "tests/t.py"))
            edges.append(_make_edge(
                f"e{i}", EdgeType.tested_by,
                f"src/main.py::f{i}", f"tests/t.py::test_f{i}",
                confidence=0.90,
            ))
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        assert result["summary"]["confidence"] == "high"

    def test_confidence_low_when_no_tests(self):
        """Confidence is 'unknown' or 'low' when no symbols have tested_by."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        assert result["summary"]["confidence"] in ("unknown", "low")

    def test_files_without_tests_format(self):
        """files_without_tests entries have correct structure."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("src/main.py::logout", NodeType.function, "src/main.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        assert len(result["files_without_tests"]) == 1
        fwt = result["files_without_tests"][0]
        assert fwt["file"] == "src/main.py"
        assert fwt["production_symbols"] == 2
        assert fwt["symbols_without_test_signal"] == 2
        assert "reason" in fwt

    def test_symbol_entry_has_correct_structure(self):
        """Each symbols_without_tests entry has required fields."""
        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        entry = result["symbols_without_tests"][0]
        assert "symbol" in entry
        assert "symbol_id" in entry
        assert "type" in entry
        assert "file" in entry
        assert "reason" in entry
        assert "suggested_next_tool" in entry

    def test_service_controller_component_types_included(self):
        """Service, controller, and component types are all counted as production."""
        nodes = [
            _make_node("src/api.py::authController", NodeType.controller, "src/api.py"),
            _make_node("src/svc.py::authService", NodeType.service, "src/svc.py"),
            _make_node("src/ui.py::LoginButton", NodeType.component, "src/ui.py"),
        ]
        edges: list[GraphEdge] = []
        store = _build_store(nodes, edges)

        result = compute_coverage_gaps(store)
        assert result["summary"]["production_symbols_checked"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests with repo_summary behavior
# ═══════════════════════════════════════════════════════════════════════════════


class TestCoverageGapsIntegration:
    """Integration tests ensuring coverage_gaps and repo_summary cooperate."""

    def test_repo_summary_does_not_contain_full_gaps(self):
        """repo_summary should NOT contain the full gaps list — only summary signal."""
        from codegraph.graph.test_coverage import compute_test_coverage_signal

        nodes = [
            _make_node("src/main.py::login", NodeType.function, "src/main.py"),
            _make_node("tests/t.py::test_login", NodeType.test, "tests/t.py"),
        ]
        edges: list[GraphEdge] = []

        signal = compute_test_coverage_signal(nodes, edges)
        # should have high-level summary fields
        assert "status" in signal
        assert "test_files_detected" in signal
        # should NOT have per-symbol gaps list
        assert "symbols_without_tests" not in signal
        assert "files_without_tests" not in signal
        assert "low_confidence_links" not in signal
        # NOTE: recommended_tool is injected by the MCP repo_summary wrapper,
        # not by compute_test_coverage_signal directly.
