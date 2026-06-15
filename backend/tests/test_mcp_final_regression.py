"""Final regression tests for CodeGraph MCP optimization round (Round 13).

Target tools: repo_summary, repo_status, coverage_gaps, pre_edit_check,
explain, find, get_neighbors, get_impact. Plus common field regression.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.graph.models import (
    GraphNode, GraphEdge, NodeType, EdgeType, Location,
    EdgeMetadata, Resolution,
)
from codegraph.graph.store import GraphStore


# ── Helpers ──────────────────────────────────────────────────────────────────

def _setup_mcp_globals(store: GraphStore, cg_dir: Path) -> None:
    import codegraph.mcp_server as mcp_mod
    mcp_mod._store = store
    mcp_mod._cg_dir = cg_dir
    mcp_mod._project_root = str(cg_dir.parent)


def _teardown_mcp_globals() -> None:
    import codegraph.mcp_server as mcp_mod
    mcp_mod._store = None
    mcp_mod._cg_dir = None
    mcp_mod._project_root = None


# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mcp_setup(tmp_path: Path) -> GraphStore:
    """Set up MCP module globals with test store containing test coverage data."""
    store = GraphStore()

    nodes = [
        GraphNode(
            id="src/server.py::handle_request",
            type=NodeType.function, name="handle_request",
            file_path="src/server.py", module="src.server",
            location=Location(line_start=10, line_end=25),
            signature="(req: Request) -> Response",
            docstring="Handle incoming request.",
        ),
        GraphNode(
            id="src/server.py::start_server",
            type=NodeType.function, name="start_server",
            file_path="src/server.py", module="src.server",
            location=Location(line_start=30, line_end=40),
            signature="(port: int) -> None",
        ),
        GraphNode(
            id="src/models/user.py::User",
            type=NodeType.class_, name="User",
            file_path="src/models/user.py", module="src.models.user",
            location=Location(line_start=1, line_end=20),
            tags=["model"],
        ),
        GraphNode(
            id="tests/test_server.py::test_handle_request",
            type=NodeType.test, name="test_handle_request",
            file_path="tests/test_server.py", module="tests.test_server",
            location=Location(line_start=1, line_end=15),
        ),
        GraphNode(
            id="tests/test_server.py::test_start_server",
            type=NodeType.test, name="test_start_server",
            file_path="tests/test_server.py", module="tests.test_server",
            location=Location(line_start=17, line_end=25),
        ),
        GraphNode(
            id="src/server.py",
            type=NodeType.file, name="server.py", file_path="src/server.py",
        ),
        GraphNode(
            id="tests/test_server.py",
            type=NodeType.file, name="test_server.py", file_path="tests/test_server.py",
        ),
    ]
    store.add_nodes(nodes)

    edges = [
        GraphEdge(
            id="e_tb1", type=EdgeType.tested_by,
            source="src/server.py::handle_request",
            target="tests/test_server.py::test_handle_request",
            confidence=0.95,
            metadata=EdgeMetadata(resolution=Resolution.test_name_heuristic),
        ),
        GraphEdge(
            id="e_tb2", type=EdgeType.tested_by,
            source="src/server.py::start_server",
            target="tests/test_server.py::test_start_server",
            confidence=0.35,
            metadata=EdgeMetadata(resolution=Resolution.attribute_guess),
        ),
        GraphEdge(
            id="e_call", type=EdgeType.calls,
            source="src/server.py::handle_request",
            target="src/models/user.py::User",
            confidence=0.90,
            metadata=EdgeMetadata(resolution=Resolution.imported_function_exact),
        ),
    ]
    store.add_edges(edges)

    # Set up MCP globals
    _setup_mcp_globals(store, tmp_path)

    # Create metadata.json
    from datetime import datetime
    from codegraph.graph.models import IndexMetadata, FileEntry
    metadata = IndexMetadata(
        schema_version="1.0.0", indexer_version="1.0.0",
        root_path=str(tmp_path), indexed_at=datetime.now().isoformat(),
        file_count=4, symbol_count=7, edge_count=3,
        files=[
            FileEntry(path="src/server.py", fingerprint="abc",
                      indexed_at=datetime.now().isoformat()),
            FileEntry(path="src/models/user.py", fingerprint="def",
                      indexed_at=datetime.now().isoformat()),
            FileEntry(path="tests/test_server.py", fingerprint="ghi",
                      indexed_at=datetime.now().isoformat()),
        ],
    )
    (tmp_path / "metadata.json").write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
    (tmp_path / "graph.json").write_text("{}", encoding="utf-8")

    yield store
    _teardown_mcp_globals()


# ── Test: repo_summary coverage signal credibility ───────────────────────────

class TestRepoSummaryCoverageSignal:
    """repo_summary must not return test_files=0 when tests exist."""

    def test_test_files_detected_not_zero(self, mcp_setup):
        from codegraph.graph.test_coverage import compute_test_coverage_signal
        store = mcp_setup
        tc = compute_test_coverage_signal(store.all_nodes(), store.all_edges())
        assert tc["test_files_detected"] > 0

    def test_status_in_valid_set(self, mcp_setup):
        from codegraph.graph.test_coverage import compute_test_coverage_signal
        store = mcp_setup
        tc = compute_test_coverage_signal(store.all_nodes(), store.all_edges())
        assert tc["status"] in ("ok", "low_confidence", "incomplete", "unknown")

    def test_message_present(self, mcp_setup):
        from codegraph.graph.test_coverage import compute_test_coverage_signal
        store = mcp_setup
        tc = compute_test_coverage_signal(store.all_nodes(), store.all_edges())
        assert "message" in tc
        assert len(tc["message"]) > 0

    def test_backward_compat_test_files_not_zero(self, mcp_setup):
        from codegraph.graph.test_coverage import compute_test_coverage_signal
        store = mcp_setup
        tc = compute_test_coverage_signal(store.all_nodes(), store.all_edges())
        assert tc["test_files"] > 0

    def test_recommends_coverage_gaps_tool(self, mcp_setup):
        # recommended_tool is injected by repo_summary MCP wrapper
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        tc = result["data"]["test_coverage_signal"]
        assert tc.get("recommended_tool") == "codegraph_coverage_gaps"


# ── Test: coverage_gaps ──────────────────────────────────────────────────────

class TestCoverageGapsCore:
    """codegraph_coverage_gaps core logic tests."""

    def test_returns_summary_and_gaps(self, mcp_setup):
        from codegraph.graph.coverage_gaps import compute_coverage_gaps
        store = mcp_setup
        result = compute_coverage_gaps(store, limit=10)
        assert result["ok"] is True
        assert isinstance(result["summary"], dict)
        assert "symbols_without_test_signal" in result["summary"]
        assert "symbols_without_tests" in result
        assert "files_without_tests" in result

    def test_test_symbols_not_in_production_gaps(self, mcp_setup):
        from codegraph.graph.coverage_gaps import compute_coverage_gaps
        store = mcp_setup
        result = compute_coverage_gaps(store, limit=50)
        for sym in result.get("symbols_without_tests", []):
            fp = sym.get("file_path", "")
            # File path should not be a test file
            assert "/test" not in fp, f"Test symbol in gaps: {sym.get('name')} at {fp}"

    def test_limit_respected(self, mcp_setup):
        from codegraph.graph.coverage_gaps import compute_coverage_gaps
        store = mcp_setup
        result = compute_coverage_gaps(store, limit=3)
        assert len(result.get("symbols_without_tests", [])) <= 3

    def test_has_warnings_and_next_tools(self, mcp_setup):
        from codegraph.graph.coverage_gaps import compute_coverage_gaps
        store = mcp_setup
        result = compute_coverage_gaps(store, limit=10)
        assert "warnings" in result
        assert "next_recommended_tools" in result

    def test_message_has_content(self, mcp_setup):
        from codegraph.graph.coverage_gaps import compute_coverage_gaps
        store = mcp_setup
        result = compute_coverage_gaps(store, limit=10)
        assert len(result["summary"].get("message", "")) > 0


# ── Test: pre_edit_check ─────────────────────────────────────────────────────

class TestPreEditCheckCore:
    """codegraph_pre_edit_check tests."""

    def test_unindexed_file_returns_warning(self, mcp_setup):
        from codegraph.mcp_server import pre_edit_check
        result = pre_edit_check(files="nonexistent/file.py", change_type="refactor")
        assert result["ok"] is True
        warnings_list = result.get("warnings", [])
        assert any(w.get("reason_code") == "file_not_indexed" for w in warnings_list)

    def test_no_symbols_risk_is_unknown(self, mcp_setup):
        from codegraph.mcp_server import pre_edit_check
        result = pre_edit_check(symbols="nonexistent_symbol_xyz", change_type="bugfix")
        assert result["ok"] is True
        impact = result["data"].get("impact_summary", {})
        assert impact.get("risk_level") == "unknown"

    def test_indexed_file_maps_to_symbols(self, mcp_setup):
        from codegraph.mcp_server import pre_edit_check
        result = pre_edit_check(files="src/server.py", change_type="refactor")
        assert result["ok"] is True
        data = result["data"]
        indexed = [f for f in data["planned_files"] if f.get("indexed")]
        assert len(indexed) > 0

    def test_has_all_required_fields(self, mcp_setup):
        from codegraph.mcp_server import pre_edit_check
        result = pre_edit_check(files="src/server.py", change_type="refactor")
        assert result["ok"] is True
        for key in ("planned_files", "planned_symbols", "impact_summary",
                     "affected_callers", "affected_files", "affected_tests",
                     "recommended_checks"):
            assert key in result["data"], f"Missing: {key}"

    def test_impact_summary_has_pre_edit_prefix(self, mcp_setup):
        from codegraph.mcp_server import pre_edit_check
        result = pre_edit_check(files="src/server.py", change_type="refactor")
        assert "[pre-edit heuristic]" in result["data"]["impact_summary"]["summary"]

    def test_invalid_change_type_error(self, mcp_setup):
        from codegraph.mcp_server import pre_edit_check
        result = pre_edit_check(files="src/server.py", change_type="invalid_type")
        assert result["ok"] is False
        assert "error" in result

    def test_valid_change_types_accepted(self, mcp_setup):
        from codegraph.mcp_server import pre_edit_check, VALID_CHANGE_TYPES
        for ct in VALID_CHANGE_TYPES:
            result = pre_edit_check(symbols="handle_request", change_type=ct)
            assert result["ok"] is True, f"Failed for {ct}"


# ── Test: explain ────────────────────────────────────────────────────────────

class TestExplainCore:
    """codegraph_explain tests."""

    def test_explain_symbol_has_all_blocks(self, mcp_setup):
        from codegraph.graph import explain as graph_explain
        store = mcp_setup
        target = store.get_node("src/server.py::handle_request")
        result = graph_explain.explain_symbol(
            store, target, include_snippet=True, include_tests=True,
            include_relationships=True,
        )
        for key in ("target", "explanation", "evidence",
                     "implementation_signals", "relationships", "test_signal"):
            assert key in result, f"Missing: {key}"

    def test_explain_not_high_confidence_without_docstring(self, mcp_setup):
        from codegraph.graph import explain as graph_explain
        store = mcp_setup
        target = store.get_node("src/server.py::start_server")
        result = graph_explain.explain_symbol(
            store, target, include_snippet=False, include_tests=False,
            include_relationships=False,
        )
        assert result["explanation"]["confidence"] != "high"

    def test_explain_uses_docstring_as_basis(self, mcp_setup):
        from codegraph.graph import explain as graph_explain
        store = mcp_setup
        target = store.get_node("src/server.py::handle_request")
        result = graph_explain.explain_symbol(
            store, target, include_snippet=False, include_tests=False,
            include_relationships=False,
        )
        assert "docstring" in result["explanation"]["basis"]

    def test_explain_file_has_likely_role(self, mcp_setup):
        from codegraph.graph import explain as graph_explain
        store = mcp_setup
        result = graph_explain.explain_file(store, "src/server.py", include_tests=True)
        assert "likely_role" in result
        assert "likely_role_confidence" in result

    def test_explain_symbol_has_evidence(self, mcp_setup):
        from codegraph.graph import explain as graph_explain
        store = mcp_setup
        target = store.get_node("src/server.py::handle_request")
        result = graph_explain.explain_symbol(
            store, target, include_snippet=True, include_tests=True,
            include_relationships=True,
        )
        assert len(result["evidence"]) > 0

    def test_explain_no_args_returns_error(self, mcp_setup):
        from codegraph.mcp_server import codegraph_explain
        result = codegraph_explain()
        assert result["ok"] is False

    def test_explain_nonexistent_symbol_error(self, mcp_setup):
        from codegraph.mcp_server import codegraph_explain
        result = codegraph_explain(symbol="nonexistent_xyz_123")
        assert result["ok"] is False


# ── Test: find ───────────────────────────────────────────────────────────────

class TestFindCore:
    """codegraph_find regression tests."""

    def test_find_results_have_all_fields(self, mcp_setup):
        from codegraph.mcp_server import codegraph_find
        result = codegraph_find("handle_request")
        assert result["ok"] is True
        for entry in result["data"]["results"]:
            for field in ("symbol", "type", "file", "line_start", "line_end", "score"):
                assert field in entry, f"Missing: {field}"

    def test_find_no_results_returns_empty(self, mcp_setup):
        from codegraph.mcp_server import codegraph_find
        result = codegraph_find("nonexistent_xyz_123")
        assert result["ok"] is True
        assert result["data"]["results"] == []

    def test_find_quick_lightweight(self, mcp_setup):
        from codegraph.mcp_server import codegraph_find
        result = codegraph_find("handle_request", mode="quick")
        for entry in result["data"]["results"]:
            assert entry.get("snippet") is None

    def test_find_invalid_mode_error(self, mcp_setup):
        from codegraph.mcp_server import codegraph_find
        result = codegraph_find("handle_request", mode="invalid_mode")
        assert result["ok"] is False

    def test_find_has_summary(self, mcp_setup):
        from codegraph.mcp_server import codegraph_find
        result = codegraph_find("handle_request")
        assert "summary" in result["data"]
        assert len(result["data"]["summary"]) > 0


# ── Test: Common fields ──────────────────────────────────────────────────────

class TestCommonFields:
    """All success responses must include standard envelope fields."""

    def test_repo_summary_has_common_fields(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        self._check(result := repo_summary(), "repo_summary")

    def test_repo_status_has_common_fields(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        self._check(result := repo_status(), "repo_status")

    def test_find_has_common_fields(self, mcp_setup):
        from codegraph.mcp_server import codegraph_find
        self._check(result := codegraph_find("handle_request"), "codegraph_find")

    def test_neighbors_has_common_fields(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        self._check(result := get_neighbors(symbol="handle_request", depth=1),
                     "get_neighbors")

    def test_impact_has_common_fields(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        self._check(result := get_impact(symbol="handle_request"), "get_impact")

    def test_pre_edit_check_has_common_fields(self, mcp_setup):
        from codegraph.mcp_server import pre_edit_check
        self._check(result := pre_edit_check(files="src/server.py", change_type="refactor"),
                     "pre_edit_check")

    def test_explain_has_common_fields(self, mcp_setup):
        from codegraph.mcp_server import codegraph_explain
        self._check(result := codegraph_explain(symbol="handle_request"),
                     "codegraph_explain")

    def _check(self, result: dict, tool_name: str):
        assert "index_status" in result, f"{tool_name}: missing index_status"
        assert "index_health" in result, f"{tool_name}: missing index_health"
        assert "codegraph_session" in result, f"{tool_name}: missing codegraph_session"
        assert "warnings" in result, f"{tool_name}: missing warnings"
        idx = result["index_status"]
        assert isinstance(idx, dict), f"{tool_name}: index_status not dict"
        assert "freshness" in idx
        assert "message" in idx
        health = result["index_health"]
        assert isinstance(health, dict), f"{tool_name}: index_health not dict"
        assert "status" in health
        if result.get("data"):
            assert "next_recommended_tools" in result["data"], (
                f"{tool_name}: data missing next_recommended_tools"
            )
        session = result.get("codegraph_session")
        if session is not None:
            assert "hint" in session

    def test_next_tools_no_fake(self, mcp_setup):
        valid = {
            "codegraph_repo_summary", "codegraph_repo_status",
            "codegraph_search_symbols", "codegraph_get_symbol",
            "codegraph_find", "codegraph_get_callers", "codegraph_get_callees",
            "codegraph_get_neighbors", "codegraph_get_impact",
            "codegraph_pre_edit_check", "codegraph_explain",
            "codegraph_build_context_pack", "codegraph_coverage_gaps",
        }
        from codegraph.mcp_server import codegraph_find
        result = codegraph_find("handle_request")
        for rec in result["data"].get("next_recommended_tools", []):
            assert rec["tool"] in valid, f"Unknown: {rec['tool']}"

    def test_session_no_source_code(self, mcp_setup):
        from codegraph.mcp_server import codegraph_find
        result = codegraph_find("handle_request")
        session_str = str(result.get("codegraph_session", {}))
        assert "def handle_request" not in session_str


# ── Test: get_neighbors and get_impact ───────────────────────────────────────

class TestNeighborsAndImpact:
    """codegraph_get_neighbors and codegraph_get_impact regression."""

    def test_neighbors_has_role_groups(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors(symbol="handle_request", depth=1)
        assert result["ok"] is True
        assert "groups" in result["data"]

    def test_impact_has_risk(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact(symbol="handle_request")
        assert result["ok"] is True
        assert "risk" in result["data"]

    def test_neighbors_nonexistent_returns_error(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors(symbol="nonexistent_xyz_123", depth=1)
        assert "ok" in result
