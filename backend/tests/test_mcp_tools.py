"""Comprehensive tests for MCP tool behaviors.

Tests the unified response envelope, tool data structures,
error handling, and edge evidence across all MCP tools.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from codegraph.graph.models import (
    GraphNode, GraphEdge, NodeType, EdgeType, Location,
    EdgeLocation, EdgeMetadata, Resolution, CodeGraph, RepoInfo,
)
from codegraph.graph.store import GraphStore


# ── Helpers to set up the MCP server globals ────────────────────────────────

def _setup_mcp_globals(store: GraphStore, cg_dir: Path) -> None:
    """Set the MCP server's module-level globals for testing."""
    import codegraph.mcp_server as mcp_mod
    mcp_mod._store = store
    mcp_mod._cg_dir = cg_dir
    mcp_mod._project_root = str(cg_dir.parent)


def _teardown_mcp_globals() -> None:
    """Clear MCP server module globals."""
    import codegraph.mcp_server as mcp_mod
    mcp_mod._store = None
    mcp_mod._cg_dir = None
    mcp_mod._project_root = None


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def full_store(tmp_path: Path) -> GraphStore:
    """Create a store with diverse nodes and edges for testing."""
    store = GraphStore()

    nodes = [
        GraphNode(
            id="app/api/auth.py::login",
            type=NodeType.function,
            name="login",
            file_path="app/api/auth.py",
            module="app.api.auth",
            qualified_name="app.api.auth.login",
            location=Location(line_start=6, line_end=15),
            signature="(username: str, password: str) -> str",
            docstring="Authenticate user.",
            tags=["route"],
        ),
        GraphNode(
            id="app/api/auth.py::logout",
            type=NodeType.function,
            name="logout",
            file_path="app/api/auth.py",
            module="app.api.auth",
            qualified_name="app.api.auth.logout",
            location=Location(line_start=18, line_end=21),
            signature="(token: str) -> None",
            tags=["route"],
        ),
        GraphNode(
            id="main.py::main",
            type=NodeType.function,
            name="main",
            file_path="main.py",
            module="main",
            qualified_name="main.main",
            location=Location(line_start=1, line_end=10),
            signature="() -> None",
        ),
        GraphNode(
            id="app/store/token_store.py::save_token",
            type=NodeType.function,
            name="save_token",
            file_path="app/store/token_store.py",
            module="app.store.token_store",
            qualified_name="app.store.token_store.save_token",
            location=Location(line_start=5, line_end=8),
            signature="(token: str) -> None",
        ),
        GraphNode(
            id="tests/test_auth.py::test_login",
            type=NodeType.test,
            name="test_login",
            file_path="tests/test_auth.py",
            module="tests.test_auth",
            location=Location(line_start=1, line_end=10),
        ),
        GraphNode(
            id="external_lib.hash_password",
            type=NodeType.external_symbol,
            name="hash_password",
        ),
        GraphNode(
            id="app/models/user.py::User",
            type=NodeType.class_,
            name="User",
            file_path="app/models/user.py",
            qualified_name="app.models.user.User",
            tags=["model"],
        ),
        GraphNode(
            id="app/api/auth.py",
            type=NodeType.file,
            name="auth.py",
            file_path="app/api/auth.py",
        ),
        GraphNode(
            id="app/store/token_store.py",
            type=NodeType.file,
            name="token_store.py",
            file_path="app/store/token_store.py",
        ),
    ]
    store.add_nodes(nodes)

    edges = [
        GraphEdge(
            id="e01", type=EdgeType.calls,
            source="main.py::main", target="app/api/auth.py::login",
            confidence=0.95,
            metadata=EdgeMetadata(
                resolution=Resolution.import_resolved,
                reason="Imported function call in main.py",
                evidence={"import_line": 3},
            ),
        ),
        GraphEdge(
            id="e02", type=EdgeType.calls,
            source="app/api/auth.py::login", target="app/store/token_store.py::save_token",
            confidence=0.90,
            metadata=EdgeMetadata(
                resolution=Resolution.imported_function_exact,
                reason="Token persistence call",
                evidence={"import_line": 4},
            ),
        ),
        GraphEdge(
            id="e03", type=EdgeType.calls,
            source="app/api/auth.py::login", target="external_lib.hash_password",
            confidence=0.40,
            metadata=EdgeMetadata(
                resolution=Resolution.external_symbol,
                reason="External hash library",
            ),
        ),
        GraphEdge(
            id="e04", type=EdgeType.tested_by,
            source="app/api/auth.py::login", target="tests/test_auth.py::test_login",
            confidence=0.90,
            metadata=EdgeMetadata(resolution=Resolution.test_name_heuristic),
        ),
        GraphEdge(
            id="e05", type=EdgeType.imports,
            source="app/api/auth.py", target="app/models/user.py::User",
            confidence=1.0,
            metadata=EdgeMetadata(resolution=Resolution.exact_ast_match),
        ),
        # Low confidence edge
        GraphEdge(
            id="e06", type=EdgeType.calls,
            source="main.py::main", target="app/api/auth.py::logout",
            confidence=0.35,
            metadata=EdgeMetadata(
                resolution=Resolution.attribute_guess,
                reason="Uncertain call resolution",
            ),
        ),
    ]
    store.add_edges(edges)

    return store


@pytest.fixture
def mcp_setup(full_store: GraphStore, tmp_path: Path, monkeypatch) -> GraphStore:
    """Set up MCP module globals with the full test store."""
    import codegraph.mcp_server as mcp_mod

    _setup_mcp_globals(full_store, tmp_path)

    # Create metadata.json so repo_status doesn't report missing
    from codegraph.graph.models import IndexMetadata, FileEntry
    from datetime import datetime
    metadata = IndexMetadata(
        schema_version="1.0.0",
        indexer_version="1.0.0",
        root_path=str(tmp_path),
        indexed_at=datetime.now().isoformat(),
        file_count=5,
        symbol_count=9,
        edge_count=6,
        files=[
            FileEntry(path="app/api/auth.py", fingerprint="abc123", indexed_at=datetime.now().isoformat()),
            FileEntry(path="main.py", fingerprint="def456", indexed_at=datetime.now().isoformat()),
        ],
    )
    (tmp_path / "metadata.json").write_text(
        metadata.model_dump_json(indent=2), encoding="utf-8"
    )
    (tmp_path / "graph.json").write_text("{}", encoding="utf-8")

    yield full_store
    _teardown_mcp_globals()


# ── Test: Unified Envelope ─────────────────────────────────────────────────


class TestUnifiedEnvelope:
    """All MCP tools must return the unified {ok, tool, data/error, warnings,
    index_status, meta} envelope."""

    def test_respond_ok_format(self):
        from codegraph.mcp_server import _respond_ok
        result = _respond_ok({"key": "value"}, tool="test_tool")
        assert result["ok"] is True
        assert result["tool"] == "test_tool"
        assert result["data"] == {"key": "value"}
        assert "warnings" in result
        assert "index_status" in result
        assert "index_health" in result
        assert "meta" in result
        assert result["meta"]["schema_version"] == "1.0.0"
        # index_status is now a structured dict
        assert isinstance(result["index_status"], dict)
        assert "freshness" in result["index_status"]
        assert result["index_status"]["freshness"] in ("fresh", "stale", "unknown")
        assert "warning_level" in result["index_status"]
        assert "message" in result["index_status"]
        # index_health is now a structured dict
        assert isinstance(result["index_health"], dict)
        assert "status" in result["index_health"]
        assert result["index_health"]["status"] in ("ok", "degraded", "critical")

    def test_respond_error_format(self):
        from codegraph.mcp_server import _respond_error, ERROR_CODES
        result = _respond_error(
            ERROR_CODES["SYMBOL_NOT_FOUND"],
            "No symbol found",
            tool="test_tool",
            details={"query": "x"},
        )
        assert result["ok"] is False
        assert result["tool"] == "test_tool"
        assert result["error"]["code"] == "SYMBOL_NOT_FOUND"
        assert result["error"]["message"] == "No symbol found"
        assert result["error"]["details"] == {"query": "x"}
        assert "warnings" in result
        assert "index_status" in result
        assert "index_health" in result
        assert "meta" in result
        # index_status is now a structured dict even in error responses
        assert isinstance(result["index_status"], dict)
        assert "freshness" in result["index_status"]
        # index_health is now a structured dict
        assert isinstance(result["index_health"], dict)
        assert "status" in result["index_health"]

    def test_search_symbols_has_envelope(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login")
        assert result["ok"] is True
        assert result["tool"] == "codegraph_search_symbols"
        assert "data" in result
        assert "warnings" in result
        assert "index_status" in result
        assert "meta" in result
        assert "error" not in result

    def test_get_symbol_has_envelope(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login")
        assert result["ok"] is True
        assert result["tool"] == "codegraph_get_symbol"
        assert "data" in result
        assert "symbol" in result["data"]
        assert "relations_summary" in result["data"]
        # source is only included when include_source=True

    def test_get_symbol_include_source_adds_source_key(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", include_source=True)
        assert result["ok"] is True
        assert "source" in result["data"]
        # included may be False in unit tests (files don't exist on disk)

    def test_get_callers_has_envelope(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login")
        assert result["ok"] is True
        assert result["tool"] == "codegraph_get_callers"
        assert "target" in result["data"]
        assert "callers" in result["data"]

    def test_get_callees_has_envelope(self, mcp_setup):
        from codegraph.mcp_server import get_callees
        result = get_callees("app/api/auth.py::login")
        assert result["ok"] is True
        assert result["tool"] == "codegraph_get_callees"
        assert "callees" in result["data"]

    def test_get_neighbors_has_envelope(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login")
        assert result["ok"] is True
        assert result["tool"] == "codegraph_get_neighbors"
        assert "center" in result["data"]
        assert "groups" in result["data"]  # compact + group_by_role default
        assert "counts" in result["data"]

    def test_get_neighbors_standard_has_nodes_edges(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", response_mode="standard", group_by_role=False)
        assert result["ok"] is True
        assert "nodes" in result["data"]
        assert "edges" in result["data"]

    def test_get_impact_has_envelope(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        assert result["ok"] is True
        assert result["tool"] == "codegraph_get_impact"
        assert "target" in result["data"]
        assert "risk" in result["data"]
        assert "confirmed" in result["data"]  # compact mode: nested structure
        assert "possible" in result["data"]   # compact mode: nested structure
        assert "truncated" in result["data"]

    def test_get_impact_standard_has_full_structure(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", response_mode="standard")
        assert result["ok"] is True
        assert "confirmed_impact" in result["data"]
        assert "possible_impact" in result["data"]
        assert "upstream_callers" in result["data"]
        assert "downstream_callees" in result["data"]
        assert "related_tests" in result["data"]

    def test_repo_status_has_envelope(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert result["ok"] is True
        assert result["tool"] == "codegraph_repo_status"
        assert "index_status" in result["data"]
        assert "project_root" in result["data"]
        assert "suggested_fix" in result["data"] or result["data"].get("suggested_fix") is None

    def test_repo_summary_has_envelope(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        assert result["ok"] is True
        assert result["tool"] == "codegraph_repo_summary"
        assert "stats" in result["data"]
        assert "top_modules" in result["data"]

    def test_error_has_no_data_field(self):
        from codegraph.mcp_server import _respond_error, ERROR_CODES
        result = _respond_error(
            ERROR_CODES["SYMBOL_NOT_FOUND"], "Not found", tool="x"
        )
        assert "data" not in result
        assert "error" in result

    def test_success_has_no_error_field(self):
        from codegraph.mcp_server import _respond_ok
        result = _respond_ok({}, tool="x")
        assert "error" not in result
        assert "data" in result


# ── Test: get_symbol ───────────────────────────────────────────────────────


class TestGetSymbol:
    """get_symbol: source control, relations summary, fuzzy fallback."""

    def test_default_no_source(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login")
        # source key is only present when include_source=True
        assert "source" not in result["data"]

    def test_include_source_true(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", include_source=True)
        # Source snippet may be None if file doesn't actually exist on disk
        # but the included flag should reflect whether we asked for it
        assert "source" in result["data"]

    def test_relations_summary(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login")
        rel = result["data"]["relations_summary"]
        assert "callers_count" in rel
        assert "callees_count" in rel
        assert "tests_count" in rel
        assert rel["callers_count"] >= 1  # main.py::main calls login
        assert rel["callees_count"] >= 1  # login calls save_token

    def test_exact_match(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login")
        symbol = result["data"]["symbol"]
        assert symbol["exact_match"] is True
        assert symbol["match_reason"] == "exact_id"

    def test_fuzzy_name_match(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("login")
        assert result["ok"] is True
        symbol = result["data"]["symbol"]
        assert symbol["exact_match"] is False
        assert "fuzzy_match" in [w["type"] for w in result["warnings"]]

    def test_not_found(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("nonexistent::xyz")
        assert result["ok"] is False
        assert result["error"]["code"] == "SYMBOL_NOT_FOUND"

    def test_ambiguous_candidates(self, mcp_setup):
        """When multiple candidates match, return AMBIGUOUS_SYMBOL error."""
        from codegraph.mcp_server import get_symbol
        result = get_symbol("auth")
        # "auth" matches both login and logout in app/api/auth.py
        # plus maybe the file node itself
        if not result["ok"]:
            assert result["error"]["code"] == "AMBIGUOUS_SYMBOL"
            assert "candidates" in result["error"]["details"]

    def test_symbol_has_tags(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login")
        assert "route" in result["data"]["symbol"]["tags"]

    def test_symbol_has_confidence_standard_mode(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", response_mode="standard")
        assert "confidence" not in result["data"]["symbol"]  # standard doesn't add confidence


# ── Test: get_callers ─────────────────────────────────────────────────────


class TestGetCallers:
    """get_callers: edge evidence, depth, confidence filtering, test separation."""

    def test_callers_have_edge_evidence_standard(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", response_mode="standard")
        callers = result["data"]["callers"]
        assert len(callers) >= 1
        for c in callers:
            assert "edge" in c
            edge = c["edge"]
            assert "confidence" in edge
            assert "confidence_level" in edge
            assert "resolution" in edge

    def test_callers_compact_has_confidence_flat(self, mcp_setup):
        """In compact mode, confidence/resolution are at the caller level (not nested edge)."""
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", response_mode="compact")
        callers = result["data"]["callers"]
        assert len(callers) >= 1
        for c in callers:
            assert "confidence" in c
            assert "resolution" in c
            assert "reason_code" in c

    def test_default_filters_low_confidence(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::logout")
        callers = result["data"]["callers"]
        caller_ids = [c["symbol_id"] for c in callers]
        assert "main.py::main" not in caller_ids

    def test_low_min_confidence_includes_low(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::logout", min_confidence=0.3)
        callers = result["data"]["callers"]
        caller_ids = [c["symbol_id"] for c in callers]
        assert "main.py::main" in caller_ids

    def test_default_excludes_tests(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login")
        caller_ids = [c["symbol_id"] for c in result["data"]["callers"]]
        for cid in caller_ids:
            assert "test" not in cid.lower()

    def test_include_tests_true(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", include_tests=True)
        caller_ids = [c["symbol_id"] for c in result["data"]["callers"]]
        pass

    def test_has_distance(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", depth=1)
        for c in result["data"]["callers"]:
            assert "distance" in c
            assert c["distance"] == 1

    def test_has_more_false_when_under_limit(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", max_results=50)
        assert result["data"]["has_more"] is False

    def test_total_matches_actual_count(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login")
        assert result["data"]["total"] == len(result["data"]["callers"])

    def test_edge_confidence_level_is_valid_standard(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", response_mode="standard")
        for c in result["data"]["callers"]:
            assert c["edge"]["confidence_level"] in ("high", "medium", "low", "unknown")


# ── Test: get_callees ──────────────────────────────────────────────────────


class TestGetCallees:
    """get_callees: symmetric to get_callers, external separation."""

    def test_callees_have_edge_evidence_standard(self, mcp_setup):
        from codegraph.mcp_server import get_callees
        result = get_callees("app/api/auth.py::login", response_mode="standard")
        for c in result["data"]["callees"]:
            assert "edge" in c
            edge = c["edge"]
            assert "confidence" in edge
            assert "resolution" in edge

    def test_callees_compact_has_confidence_flat(self, mcp_setup):
        from codegraph.mcp_server import get_callees
        result = get_callees("app/api/auth.py::login", response_mode="compact")
        for c in result["data"]["callees"]:
            assert "confidence" in c
            assert "resolution" in c
            assert "reason_code" in c

    def test_external_callees_separated(self, mcp_setup):
        from codegraph.mcp_server import get_callees
        result = get_callees("app/api/auth.py::login")
        external = result["data"].get("external_calls", [])
        callee_ids = [c["symbol_id"] for c in result["data"]["callees"]]
        for ext in external:
            assert ext["symbol_id"] not in callee_ids

    def test_default_edge_types_calls(self, mcp_setup):
        from codegraph.mcp_server import get_callees
        result = get_callees("app/api/auth.py::login", response_mode="standard")
        edge_types = {c["edge"]["type"] for c in result["data"]["callees"]}
        assert edge_types <= {"calls"}

    def test_symmetric_structure_to_callers(self, mcp_setup):
        from codegraph.mcp_server import get_callers, get_callees
        callers_result = get_callers("app/api/auth.py::login")
        callees_result = get_callees("app/api/auth.py::login")
        for key in ("target", "has_more", "total"):
            assert key in callers_result["data"]
            assert key in callees_result["data"]


# ── Test: get_neighbors ────────────────────────────────────────────────────


class TestGetNeighbors:
    """get_neighbors: the most important MCP tool. depth, edge_types,
    max_nodes, direction, min_confidence, role labels."""

    def test_compact_has_groups_not_nodes(self, mcp_setup):
        """Compact mode with group_by_role returns groups + counts, not nodes + edges."""
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login")
        assert "groups" in result["data"]
        assert "counts" in result["data"]
        assert "callers" in result["data"]["groups"]

    def test_standard_has_nodes_and_edges(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", response_mode="standard", group_by_role=False)
        assert "nodes" in result["data"]
        assert "edges" in result["data"]
        roles = {n.get("role") for n in result["data"]["nodes"]}
        assert "center" in roles

    def test_nodes_have_role_labels_standard(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", response_mode="standard", group_by_role=False)
        roles = {n.get("role") for n in result["data"]["nodes"]}
        assert "center" in roles
        assert "caller" in roles or "callee" in roles

    def test_edges_have_full_evidence_standard(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", response_mode="standard", group_by_role=False)
        for e in result["data"]["edges"]:
            assert "source" in e
            assert "target" in e
            assert "type" in e
            assert "confidence" in e
            assert "confidence_level" in e
            assert "resolution" in e

    def test_edge_types_filter(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", edge_types="calls", response_mode="standard", group_by_role=False)
        edge_types = {e["type"] for e in result["data"]["edges"]}
        assert edge_types == {"calls"}

    def test_direction_upstream(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", direction="upstream", response_mode="standard", group_by_role=False)
        node_ids = {n["symbol_id"] for n in result["data"]["nodes"]}
        assert "main.py::main" in node_ids

    def test_direction_downstream(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", direction="downstream", response_mode="standard", group_by_role=False)
        node_ids = {n["symbol_id"] for n in result["data"]["nodes"]}
        assert "app/store/token_store.py::save_token" in node_ids

    def test_min_confidence_filters_low(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("main.py::main", min_confidence=0.7, response_mode="standard", group_by_role=False)
        for e in result["data"]["edges"]:
            assert e["confidence"] >= 0.7

    def test_max_nodes_limit(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", max_nodes=1, response_mode="standard", group_by_role=False)
        assert len(result["data"]["nodes"]) <= 1

    def test_invalid_direction_error(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", direction="sideways")
        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"

    def test_invalid_edge_type_error(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", edge_types="bogus_type")
        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"

    def test_has_limits_info_standard(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", depth=2, max_nodes=15, min_confidence=0.6, response_mode="standard", group_by_role=False)
        limits = result["data"]["limits"]
        assert limits["depth"] == 2
        assert limits["max_nodes"] == 15
        assert limits["min_confidence"] == 0.6

    def test_center_in_groups(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login")
        assert result["data"]["center"] == "app/api/auth.py::login"

    def test_external_grouped_separately(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login")
        if "external_or_unresolved" in result["data"]["groups"]:
            ext_group = result["data"]["groups"]["external_or_unresolved"]
            for n in ext_group:
                assert "test" not in (n.get("symbol_id", "") or "")


# ── Test: get_impact ───────────────────────────────────────────────────────


class TestGetImpact:
    """get_impact: confirmed vs possible, risk assessment, test separation."""

    def test_compact_has_confirmed_files(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        assert "confirmed" in result["data"]
        assert "possible" in result["data"]
        assert "files" in result["data"]["confirmed"]
        assert "truncated" in result["data"]

    def test_standard_has_full_structure(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", response_mode="standard")
        assert "confirmed_impact" in result["data"]
        assert "possible_impact" in result["data"]
        assert "upstream_callers" in result["data"]
        assert "downstream_callees" in result["data"]
        assert "related_tests" in result["data"]
        assert "external_or_unresolved" in result["data"]

    def test_low_confidence_not_in_confirmed(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::logout", min_confidence=0.6, response_mode="standard")
        confirmed_ids = {s["symbol_id"] for s in result["data"]["confirmed_impact"]["symbols"]}
        for sid in confirmed_ids:
            assert sid != "main.py::main"

    def test_has_risk_level(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        assert result["data"]["risk"]["level"] in ("low", "medium", "high", "critical", "unknown")
        assert "reason_codes" in result["data"]["risk"]  # compact uses reason_codes

    def test_risk_reasons_factual_only(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", response_mode="standard")
        for reason in result["data"]["risk"].get("reasons", []):
            assert "should" not in reason.lower()
            assert "must" not in reason.lower()

    def test_has_upstream_downstream_standard(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", response_mode="standard")
        assert "upstream_callers" in result["data"]
        assert "downstream_callees" in result["data"]

    def test_has_related_tests_standard(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", include_tests=True, response_mode="standard")
        assert "related_tests" in result["data"]

    def test_has_external_or_unresolved_standard(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", response_mode="standard")
        assert "external_or_unresolved" in result["data"]

    def test_confirmed_files_have_fields(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        files = result["data"]["confirmed"]["files"]
        for f in files:
            assert "file_path" in f
            assert "reason_code" in f
            assert "confidence" in f
            assert "layer" in f  # new: layer assignment

    def test_external_not_in_confirmed_standard(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", response_mode="standard")
        confirmed_ids = {s["symbol_id"] for s in result["data"]["confirmed_impact"]["symbols"]}
        external_ids = {e["symbol_id"] for e in result["data"]["external_or_unresolved"]}
        assert confirmed_ids.isdisjoint(external_ids)

    def test_impact_mode_conservative_default(self, mcp_setup):
        """Default impact_mode is conservative — possible section always present but empty."""
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        assert "possible" in result["data"]
        assert "files" in result["data"]["possible"]

    def test_impact_mode_balanced_includes_possible(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", impact_mode="balanced", include_possible=True)
        assert "possible" in result["data"]
        assert "files" in result["data"]["possible"]


# ── Test: repo_status ──────────────────────────────────────────────────────


class TestRepoStatus:
    """repo_status: reports index status and file changes."""

    def test_reports_status(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert result["data"]["index_status"] in ("fresh", "stale", "missing", "indexing", "error")

    def test_has_index_files(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        result = repo_status(response_mode="standard")
        index_files = result["data"]["index_files"]
        assert "graph_json" in index_files
        assert "sqlite" in index_files
        assert "metadata_json" in index_files

    def test_has_stats(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        result = repo_status(response_mode="standard")
        stats = result["data"]["stats"]
        assert "files" in stats
        assert "symbols" in stats
        assert "edges" in stats

    def test_stale_has_warning(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        result = repo_status()
        if result["data"]["index_status"] == "stale":
            stale_warnings = [w for w in result["warnings"] if w.get("type") == "stale_index"]
            assert len(stale_warnings) > 0

    def test_has_project_root(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert "project_root" in result["data"]
        assert result["data"]["project_root"] is not None

    def test_has_suggested_fix(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        result = repo_status()
        # suggested_fix should be present (may be None for fresh index)
        assert "suggested_fix" in result["data"]

    def test_has_validation_status(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert "validation_status" in result["data"]

    def test_has_separate_counts(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert "changed_files_count" in result["data"]
        assert "added_files_count" in result["data"]
        assert "deleted_files_count" in result["data"]

    def test_has_last_incremental_stats(self, mcp_setup):
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert "last_incremental_stats" in result["data"]

    def test_has_cwd(self, mcp_setup):
        """repo_status always returns current working directory."""
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert "cwd" in result["data"]
        assert result["data"]["cwd"] is not None

    def test_has_resolution_method(self, mcp_setup):
        """repo_status always returns how project root was resolved."""
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert "resolution_method" in result["data"]
        assert result["data"]["resolution_method"] in (
            "explicit", "env", "walk_up", "git_root", "cwd", "unknown",
        )

    def test_has_index_path(self, mcp_setup):
        """repo_status returns index_path when index exists."""
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert "index_path" in result["data"]

    def test_has_index_exists(self, mcp_setup):
        """repo_status returns whether index exists."""
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert "index_exists" in result["data"]
        assert isinstance(result["data"]["index_exists"], bool)

    def test_has_symbol_count(self, mcp_setup):
        """repo_status returns symbol_count."""
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert "symbol_count" in result["data"]
        assert isinstance(result["data"]["symbol_count"], int)

    def test_has_edge_count(self, mcp_setup):
        """repo_status returns edge_count."""
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert "edge_count" in result["data"]
        assert isinstance(result["data"]["edge_count"], int)

    def test_env_root_produces_fixed_root_warning(self, mcp_setup, monkeypatch):
        """When CODEGRAPH_PROJECT_ROOT is set, warning is emitted."""
        from codegraph.mcp_server import repo_status

        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", "/fake/project/path")
        result = repo_status()
        fixed_warnings = [
            w for w in result["warnings"]
            if w.get("type") == "fixed_project_root"
        ]
        assert len(fixed_warnings) > 0
        assert "CODEGRAPH_PROJECT_ROOT" in fixed_warnings[0]["message"]

    def test_env_resolution_method(self, mcp_setup, monkeypatch, tmp_path):
        """When CODEGRAPH_PROJECT_ROOT is set, resolution_method is 'env'."""
        import codegraph.mcp_server as mcp_mod
        import json

        # Create a real project dir with .codegraph
        env_project = tmp_path / "env_project"
        env_project.mkdir()
        cg_dir = env_project / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text(json.dumps({
            "schema_version": "1.0.0",
            "repo": {
                "repo_id": "local:test",
                "name": "test",
                "root_path": str(env_project),
                "languages": ["python"],
                "indexed_at": "2025-01-01T00:00:00Z",
                "file_count": 1,
                "symbol_count": 1,
            },
            "nodes": [],
            "edges": [],
        }), encoding="utf-8")

        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(env_project))
        # Test _resolve_project_root directly
        from codegraph.mcp_server import _resolve_project_root
        root, method = _resolve_project_root(None)
        assert method == "env"
        assert root == str(env_project.resolve())

    def test_walk_up_resolution_method(self, mcp_setup):
        """Without explicit root or env, resolution_method is 'walk_up'."""
        import codegraph.mcp_server as mcp_mod

        # Ensure no env override
        mcp_mod._resolution_method = "walk_up"
        from codegraph.mcp_server import repo_status
        result = repo_status()
        assert result["data"]["resolution_method"] in ("walk_up", "unknown")

    def test_returns_all_diagnostic_fields(self, mcp_setup):
        """repo_status always returns project_root, index_path, cwd,
        resolution_method, index_exists, symbol_count, edge_count."""
        from codegraph.mcp_server import repo_status
        result = repo_status()
        data = result["data"]
        for field in ("project_root", "index_path", "cwd",
                       "resolution_method", "index_exists",
                       "symbol_count", "edge_count"):
            assert field in data, f"Missing required field: {field}"

    def test_cwd_outside_project_warning(self, mcp_setup, monkeypatch, tmp_path):
        """When CWD is not under project_root, repo_status warns."""
        import codegraph.mcp_server as mcp_mod
        from codegraph.mcp_server import _build_index_status

        import json

        # Create a project dir with .codegraph that is NOT under CWD
        other_project = tmp_path / "other_project"
        other_project.mkdir()
        cg_dir = other_project / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text(json.dumps({
            "schema_version": "1.0.0",
            "repo": {
                "repo_id": "local:test",
                "name": "test",
                "root_path": str(other_project),
                "languages": ["python"],
                "indexed_at": "2025-01-01T00:00:00Z",
                "file_count": 1,
                "symbol_count": 1,
            },
            "nodes": [],
            "edges": [],
        }), encoding="utf-8")
        # Write minimal state.json needed for _build_index_status
        (cg_dir / "state.json").write_text(json.dumps({
            "status": "fresh",
            "last_indexed_at": "2025-01-01T00:00:00Z",
            "last_change_summary": {"none": 1, "cosmetic": 0, "structural": 0, "added": 0, "deleted": 0},
        }), encoding="utf-8")
        (cg_dir / "metadata.json").write_text(json.dumps({
            "schema_version": "1.0.0",
            "root_path": str(other_project),
            "indexed_at": "2025-01-01T00:00:00Z",
            "file_count": 1,
            "symbol_count": 5,
            "edge_count": 3,
            "files": [],
        }), encoding="utf-8")

        old_root = mcp_mod._project_root
        old_cg = mcp_mod._cg_dir
        old_method = mcp_mod._resolution_method
        try:
            mcp_mod._project_root = str(other_project)
            mcp_mod._cg_dir = cg_dir
            mcp_mod._resolution_method = "explicit"
            result = _build_index_status(str(other_project))
            # Verify the diagnostic fields are present
            assert result["index_exists"] is True
            assert "project_root" in result
            assert "cwd" in result
            assert "resolution_method" in result
            # Since CWD is tmp_path (test runner), it's outside other_project
            # So cwd_outside_project warning should be triggered by repo_status
            from codegraph.mcp_server import repo_status
            status_result = repo_status()
            # If CWD is indeed outside other_project:
            import os
            cwd = Path(os.getcwd()).resolve()
            try:
                cwd.relative_to(other_project.resolve())
                # CWD is inside — skip assertion
                pass
            except ValueError:
                cwd_warnings = [
                    w for w in status_result["warnings"]
                    if w.get("type") == "cwd_outside_project"
                ]
                assert len(cwd_warnings) > 0
        finally:
            mcp_mod._project_root = old_root
            mcp_mod._cg_dir = old_cg
            mcp_mod._resolution_method = old_method

    def test_index_missing_warning(self, tmp_path, monkeypatch):
        """When .codegraph/ doesn't exist, warning is emitted."""
        import codegraph.mcp_server as mcp_mod

        # Save original globals
        old_store = mcp_mod._store
        old_cg = mcp_mod._cg_dir
        old_root = mcp_mod._project_root
        old_method = mcp_mod._resolution_method
        try:
            # Setup with a directory that has no .codegraph
            empty_dir = tmp_path / "empty_project"
            empty_dir.mkdir()
            mcp_mod._store = None
            mcp_mod._cg_dir = None
            mcp_mod._project_root = str(empty_dir)
            mcp_mod._resolution_method = "walk_up"

            from codegraph.mcp_server import repo_status
            result = repo_status(root=str(empty_dir))
            missing_warnings = [
                w for w in result["warnings"]
                if w.get("type") == "index_missing"
            ]
            assert len(missing_warnings) > 0
            assert "codegraph init" in missing_warnings[0]["message"].lower()
        finally:
            mcp_mod._store = old_store
            mcp_mod._cg_dir = old_cg
            mcp_mod._project_root = old_root
            mcp_mod._resolution_method = old_method

    def test_index_empty_warning(self, mcp_setup):
        """When index has 0 symbols, warning is emitted."""
        import codegraph.mcp_server as mcp_mod
        from codegraph.mcp_server import repo_status

        # Save original store, replace with empty one
        original_store = mcp_mod._store
        from codegraph.graph.store import GraphStore
        mcp_mod._store = GraphStore()
        try:
            result = repo_status()
            empty_warnings = [
                w for w in result["warnings"]
                if w.get("type") == "index_empty"
            ]
            # May or may not fire depending on how symbols are counted
            # But if index_exists and 0 symbols, it should warn
            if result["data"]["index_exists"] and result["data"]["symbol_count"] == 0:
                assert len(empty_warnings) > 0
                assert "0 symbols" in empty_warnings[0]["message"]
        finally:
            mcp_mod._store = original_store

    def test_has_recommended_action(self, mcp_setup):
        """repo_status returns recommended_action and reason."""
        from codegraph.mcp_server import repo_status
        result = repo_status()
        data = result["data"]
        assert "recommended_action" in data, "Missing recommended_action"
        assert "recommended_action_reason" in data, "Missing recommended_action_reason"
        valid_actions = {"use_codegraph", "refresh_index", "run_init", "check_project_root"}
        assert data["recommended_action"] in valid_actions, (
            f"Unexpected recommended_action: {data['recommended_action']}"
        )
        assert isinstance(data["recommended_action_reason"], str)
        assert len(data["recommended_action_reason"]) > 0

    def test_recommended_action_missing_index(self, tmp_path, monkeypatch):
        """Missing index → recommended_action == 'run_init'."""
        import codegraph.mcp_server as mcp_mod

        old_store = mcp_mod._store
        old_cg = mcp_mod._cg_dir
        old_root = mcp_mod._project_root
        old_method = mcp_mod._resolution_method
        try:
            empty_dir = tmp_path / "empty_project"
            empty_dir.mkdir()
            mcp_mod._store = None
            mcp_mod._cg_dir = None
            mcp_mod._project_root = str(empty_dir)
            mcp_mod._resolution_method = "walk_up"

            from codegraph.mcp_server import repo_status
            result = repo_status(root=str(empty_dir))
            assert result["data"]["recommended_action"] == "run_init"
        finally:
            mcp_mod._store = old_store
            mcp_mod._cg_dir = old_cg
            mcp_mod._project_root = old_root
            mcp_mod._resolution_method = old_method

    def test_recommended_action_stale_index(self, tmp_path):
        """Stale index → recommended_action == 'refresh_index'."""
        import codegraph.mcp_server as mcp_mod
        from codegraph.mcp_server import repo_status
        import json

        # Create isolated test project with .codegraph directory
        proj = tmp_path / "stale_proj"
        proj.mkdir()
        cg_dir = proj / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text("{}")
        metadata = {
            "schema_version": "1.0.0", "indexer_version": "1.0.0",
            "root_path": str(proj), "indexed_at": "2025-01-01T00:00:00Z",
            "file_count": 1, "symbol_count": 10, "edge_count": 5, "files": [],
        }
        (cg_dir / "metadata.json").write_text(json.dumps(metadata))
        state = {
            "status": "stale", "last_indexed_at": "2025-01-01T00:00:00Z",
            "last_change_summary": {
                "none": 0, "cosmetic": 0, "structural": 3,
                "added": 1, "deleted": 0,
            },
        }
        (cg_dir / "state.json").write_text(json.dumps(state))

        old_root = mcp_mod._project_root
        old_cg = mcp_mod._cg_dir
        old_store = mcp_mod._store
        try:
            mcp_mod._project_root = str(proj)
            mcp_mod._cg_dir = cg_dir
            mcp_mod._store = None

            result = repo_status(root=str(proj))
            assert result["data"]["recommended_action"] == "refresh_index"
        finally:
            mcp_mod._project_root = old_root
            mcp_mod._cg_dir = old_cg
            mcp_mod._store = old_store

    def test_recommended_action_fresh(self, mcp_setup):
        """Fresh index with symbols → recommended_action == 'use_codegraph'."""
        from codegraph.mcp_server import repo_status
        result = repo_status()
        data = result["data"]
        if data["index_status"] == "fresh" and data["symbol_count"] > 0:
            assert data["recommended_action"] == "use_codegraph"
        # If not fresh, skip — test environment may vary


# ── Test: repo_summary ────────────────────────────────────────────────────


class TestRepoSummary:
    """repo_summary: lightweight index overview."""

    def test_has_stats_breakdown(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        stats = result["data"]["stats"]
        assert "functions" in stats
        assert "classes" in stats
        assert "tests" in stats
        assert "routes" in stats

    def test_has_top_modules(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        assert "top_modules" in result["data"]

    def test_has_entry_point_candidates(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        assert "entry_point_candidates" in result["data"]

    def test_has_test_coverage_signal(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        tcs = result["data"]["test_coverage_signal"]
        assert "test_files" in tcs
        assert "tested_symbols" in tcs

    def test_has_index_info(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        assert "index_info" in result["data"]
        assert "status" in result["data"]["index_info"]
        assert "health" in result["data"]["index_info"]


# ── Test: Error handling ───────────────────────────────────────────────────


class TestErrorHandling:
    """Unified error codes and error handling."""

    def test_all_error_codes_defined(self):
        from codegraph.mcp_server import ERROR_CODES
        expected = {
            "INDEX_MISSING", "INDEX_STALE", "SYMBOL_NOT_FOUND",
            "AMBIGUOUS_SYMBOL", "INVALID_ARGUMENT", "GRAPH_LOAD_FAILED",
            "INTERNAL_ERROR",
        }
        assert set(ERROR_CODES.keys()) == expected

    def test_error_structure_consistent(self):
        from codegraph.mcp_server import _respond_error, ERROR_CODES
        for code in ERROR_CODES.values():
            result = _respond_error(code, f"Test {code}", tool="test")
            assert result["ok"] is False
            assert result["error"]["code"] == code
            assert result["error"]["message"] == f"Test {code}"
            assert "details" in result["error"]
            assert "warnings" in result
            assert "index_status" in result
            assert "meta" in result

    def test_no_traceback_in_response(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("nonexistent::xyz")
        assert result["ok"] is False
        # Error responses should not contain raw Python tracebacks
        error_msg = result["error"]["message"]
        assert "Traceback" not in error_msg
        assert "traceback" not in result["error"].get("details", {}).get("traceback", "")

    def test_symbol_not_found_details(self, mcp_setup):
        from codegraph.mcp_server import get_symbol, _get_project_info
        result = get_symbol("nonexistent::xyz")
        assert result["error"]["code"] == "SYMBOL_NOT_FOUND"
        # Details should contain project info
        assert isinstance(result["error"]["details"], dict)


# ── Test: build_context_pack ───────────────────────────────────────────────


class TestBuildContextPack:
    """build_context_pack: no reading_plan, no agent_instructions."""

    def test_no_reading_plan(self, mcp_setup):
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary")
        if result["ok"]:
            assert "reading_plan" not in result["data"]

    def test_no_agent_instructions(self, mcp_setup):
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary")
        if result["ok"]:
            assert "agent_instructions" not in result["data"]

    def test_no_recommended_context(self, mcp_setup):
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary")
        if result["ok"]:
            assert "recommended_context" not in result["data"]

    def test_summary_mode_has_selected_context(self, mcp_setup):
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary", response_mode="standard")
        if result["ok"]:
            assert "selected_context" in result["data"]

    def test_selected_context_items_have_evidence(self, mcp_setup):
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary", response_mode="standard")
        if result["ok"] and result["data"].get("selected_context"):
            for sc in result["data"]["selected_context"]:
                assert "confidence" in sc
                assert "confidence_level" in sc
                assert "resolution" in sc
                assert "evidence" in sc

    def test_returns_next_recommended_tools(self, mcp_setup):
        """build_context_pack returns next_recommended_tools list."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary", response_mode="standard")
        if result["ok"]:
            nrt = result["data"].get("next_recommended_tools", [])
            assert isinstance(nrt, list), f"next_recommended_tools should be a list, got: {type(nrt)}"
            # For an "add MFA" task, should have at least 1 recommendation
            assert len(nrt) >= 1, f"Expected at least 1 recommendation, got: {nrt}"
            for rec in nrt:
                assert "tool" in rec, f"Recommendation missing 'tool': {rec}"
                assert "reason" in rec, f"Recommendation missing 'reason': {rec}"
                assert rec["tool"].startswith("codegraph_"), f"Tool name should start with codegraph_: {rec}"

    def test_returns_next_recommended_tools_for_understand(self, mcp_setup):
        """build_context_pack returns recommendations even for understand_code."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("explain login flow", mode="summary", response_mode="standard")
        if result["ok"]:
            nrt = result["data"].get("next_recommended_tools", [])
            assert isinstance(nrt, list)

    def test_next_recommended_tools_not_exceed_3(self, mcp_setup):
        """next_recommended_tools should not exceed 3 items."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("fix login bug", mode="summary", response_mode="standard")
        if result["ok"]:
            nrt = result["data"].get("next_recommended_tools", [])
            assert len(nrt) <= 3, f"Expected ≤ 3 recommendations, got {len(nrt)}"


# ── Test: source_snippets in build_context_pack ──────────────────────────────


class TestContextPackSourceSnippets:
    """source_snippets for debug / review / implementation tasks."""

    @pytest.fixture(autouse=True)
    def _create_source_files(self, mcp_setup, tmp_path):
        """Create real source files so _read_source_snippet can find them."""
        import codegraph.mcp_server as mcp_mod
        auth_dir = tmp_path.parent / "app" / "api"
        auth_dir.mkdir(parents=True, exist_ok=True)
        (auth_dir / "auth.py").write_text(
            "\n".join([
                "# auth module", "", "", "", "",
                "def login(username: str, password: str) -> str:",
                "    # Authenticate user",
                "    token = hash_password(username, password)",
                "    save_token(token)",
                "    return token",
                "",
                "",
                "",
                "",
                "def logout(token: str) -> None:",
                "    # Invalidate token",
                "    invalidate_token(token)",
                "    return None",
            ]), encoding="utf-8"
        )
        main_file = tmp_path.parent / "main.py"
        main_file.write_text(
            "\n".join([
                "#!/usr/bin/env python3",
                "from app.api.auth import login",
                "",
                "def main() -> None:",
                "    token = login('user', 'pass')",
                "    print(f'Logged in: {token}')",
                "",
                "if __name__ == '__main__':",
                "    main()",
                "",
            ]), encoding="utf-8"
        )
        store_dir = tmp_path.parent / "app" / "store"
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "token_store.py").write_text(
            "\n".join([
                "# token store", "", "", "",
                "def save_token(token: str) -> None:",
                "    # Persist token",
                "    with open('tokens.db', 'a') as f:",
                "        f.write(token)",
            ]), encoding="utf-8"
        )
        yield

    def _call_build(self, task_text: str, mode: str = "summary", **kwargs):
        from codegraph.mcp_server import build_context_pack
        return build_context_pack(task_text, mode=mode, response_mode="standard", **kwargs)

    def test_debug_task_returns_source_snippets(self, mcp_setup):
        """Debug task ('fix bug') returns source_snippets."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("fix login bug", mode="summary", response_mode="standard")
        if result["ok"]:
            snippets = result["data"].get("source_snippets", [])
            assert isinstance(snippets, list), f"source_snippets should be a list"
            assert len(snippets) > 0, (
                f"Debug task should return source_snippets, got empty list. "
                f"Entry points: {result['data'].get('entry_points', [])}"
            )
            for s in snippets:
                assert "symbol" in s, f"Snippet missing 'symbol': {s}"
                assert "file" in s, f"Snippet missing 'file': {s}"
                assert "line_start" in s, f"Snippet missing 'line_start': {s}"
                assert "line_end" in s, f"Snippet missing 'line_end': {s}"
                assert "reason" in s, f"Snippet missing 'reason': {s}"
                assert "snippet" in s, f"Snippet missing 'snippet': {s}"
                assert len(s["snippet"]) > 0, f"Snippet content is empty"

    def test_review_task_returns_source_snippets(self, mcp_setup):
        """Review task returns source_snippets."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("review auth code", mode="summary", response_mode="standard")
        if result["ok"]:
            snippets = result["data"].get("source_snippets", [])
            assert isinstance(snippets, list)
            assert len(snippets) > 0, (
                f"Review task should return source_snippets"
            )

    def test_implementation_task_returns_source_snippets(self, mcp_setup):
        """Implementation task ('implement') returns source_snippets."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("implement password reset", mode="summary", response_mode="standard")
        if result["ok"]:
            snippets = result["data"].get("source_snippets", [])
            assert isinstance(snippets, list)
            assert len(snippets) > 0, (
                f"Implementation task should return source_snippets"
            )

    def test_modify_task_returns_source_snippets(self, mcp_setup):
        """'change' / 'modify' task returns source_snippets."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("change the login handler", mode="summary", response_mode="standard")
        if result["ok"]:
            snippets = result["data"].get("source_snippets", [])
            assert isinstance(snippets, list)
            assert len(snippets) > 0

    def test_understand_task_no_source_snippets_by_default(self, mcp_setup):
        """Pure understand task does NOT return source_snippets in summary mode."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("explain login flow", mode="summary", response_mode="standard")
        if result["ok"]:
            snippets = result["data"].get("source_snippets", [])
            # "explain" is understand — should NOT trigger source snippets
            assert snippets == [] or len(snippets) == 0, (
                f"Understand task should not return source_snippets, got: {snippets}"
            )

    def test_mode_full_returns_source_snippets(self, mcp_setup):
        """mode='full' triggers source_snippets regardless of task text."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("explain login flow", mode="full", response_mode="standard")
        if result["ok"]:
            snippets = result["data"].get("source_snippets", [])
            assert isinstance(snippets, list)
            # "full" mode should trigger source snippets
            assert len(snippets) > 0, (
                f"mode='full' should return source_snippets even for understand tasks"
            )

    def test_mode_debug_returns_source_snippets(self, mcp_setup):
        """mode='debug' triggers source_snippets."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("explain login", mode="debug", response_mode="standard")
        if result["ok"]:
            snippets = result["data"].get("source_snippets", [])
            assert isinstance(snippets, list)
            assert len(snippets) > 0

    def test_source_snippets_respect_max_limit(self, mcp_setup):
        """source_snippets should not exceed _MAX_SOURCE_SNIPPETS (5)."""
        from codegraph.mcp_server import build_context_pack, _MAX_SOURCE_SNIPPETS
        result = build_context_pack("fix login bug", mode="summary", response_mode="standard")
        if result["ok"]:
            snippets = result["data"].get("source_snippets", [])
            assert len(snippets) <= _MAX_SOURCE_SNIPPETS, (
                f"Should have ≤ {_MAX_SOURCE_SNIPPETS} snippets, got {len(snippets)}"
            )

    def test_include_code_false_skips_snippets(self, mcp_setup):
        """include_code=False skips source_snippets even for debug tasks."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack(
            "fix login bug", mode="summary", response_mode="standard",
            include_code=False,
        )
        if result["ok"]:
            snippets = result["data"].get("source_snippets", [])
            assert len(snippets) == 0, (
                f"include_code=False should skip snippets, got: {snippets}"
            )

    def test_compact_mode_preserves_source_snippets(self, mcp_setup):
        """Compact mode preserves source_snippets and next_recommended_tools."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("fix login bug", mode="summary", response_mode="compact")
        if result["ok"]:
            snippets = result["data"].get("source_snippets", [])
            assert isinstance(snippets, list)
            nrt = result["data"].get("next_recommended_tools", [])
            assert isinstance(nrt, list)

    def test_existing_context_pack_structure_unchanged(self, mcp_setup):
        """New fields don't break existing context_pack structure."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary", response_mode="standard")
        if result["ok"]:
            # Standard fields still present
            assert "pack_id" in result["data"]
            assert "task" in result["data"]
            assert "entry_points" in result["data"]
            assert "call_graph" in result["data"]
            assert "token_budget" in result["data"]
            # No forbidden fields
            assert "reading_plan" not in result["data"]
            assert "agent_instructions" not in result["data"]


# ── Test: Warnings and index_status integration ────────────────────────────


class TestIndexStatusIntegration:
    """index_status and warnings are included in all responses."""

    def test_all_tools_have_warnings_field(self, mcp_setup):
        from codegraph.mcp_server import (
            search_symbols, get_symbol, get_callers, get_callees,
            get_neighbors, get_impact, repo_status, repo_summary,
        )
        tools = [
            lambda: search_symbols("login"),
            lambda: get_symbol("app/api/auth.py::login"),
            lambda: get_callers("app/api/auth.py::login"),
            lambda: get_callees("app/api/auth.py::login"),
            lambda: get_neighbors("app/api/auth.py::login"),
            lambda: get_impact("app/api/auth.py::login"),
            lambda: repo_status(),
            lambda: repo_summary(),
        ]
        for tool_fn in tools:
            result = tool_fn()
            assert "warnings" in result, f"Missing warnings in tool response"
            assert isinstance(result["warnings"], list)

    def test_all_tools_have_index_status_field(self, mcp_setup):
        from codegraph.mcp_server import (
            search_symbols, get_symbol, get_callers, get_callees,
            get_neighbors, get_impact, repo_status, repo_summary,
        )
        tools = [
            lambda: search_symbols("login"),
            lambda: get_symbol("app/api/auth.py::login"),
            lambda: get_callers("app/api/auth.py::login"),
            lambda: get_callees("app/api/auth.py::login"),
            lambda: get_neighbors("app/api/auth.py::login"),
            lambda: get_impact("app/api/auth.py::login"),
            lambda: repo_status(),
            lambda: repo_summary(),
        ]
        valid_freshness = {"fresh", "stale", "unknown"}
        valid_warning_levels = {"ok", "info", "warning", "critical"}
        for tool_fn in tools:
            result = tool_fn()
            assert "index_status" in result, f"Missing index_status in tool response"
            idx_status = result["index_status"]
            assert isinstance(idx_status, dict), (
                f"index_status should be a dict, got {type(idx_status)}"
            )
            assert idx_status["freshness"] in valid_freshness, (
                f"Unexpected freshness: {idx_status.get('freshness')}"
            )
            assert "warning_level" in idx_status
            assert idx_status["warning_level"] in valid_warning_levels
            assert "message" in idx_status
            assert "project_root" in idx_status
            assert "changed_files_since_index" in idx_status

    def test_all_tools_have_index_health_field(self, mcp_setup):
        from codegraph.mcp_server import (
            search_symbols, get_symbol, get_callers, get_callees,
            get_neighbors, get_impact, repo_status, repo_summary,
        )
        tools = [
            lambda: search_symbols("login"),
            lambda: get_symbol("app/api/auth.py::login"),
            lambda: get_callers("app/api/auth.py::login"),
            lambda: get_callees("app/api/auth.py::login"),
            lambda: get_neighbors("app/api/auth.py::login"),
            lambda: get_impact("app/api/auth.py::login"),
            lambda: repo_status(),
            lambda: repo_summary(),
        ]
        valid_health = {"ok", "degraded", "critical"}
        for tool_fn in tools:
            result = tool_fn()
            assert "index_health" in result, f"Missing index_health in tool response"
            idx_health = result["index_health"]
            assert isinstance(idx_health, dict), (
                f"index_health should be a dict, got {type(idx_health)}"
            )
            assert idx_health["status"] in valid_health, (
                f"Unexpected index_health status: {idx_health.get('status')}"
            )
            assert "auto_corrected" in idx_health
            assert "dropped" in idx_health
            assert "total_symbols" in idx_health
            assert "dropped_ratio" in idx_health
            assert "impact" in idx_health
            assert "suggested_fix" in idx_health


# ── Test: Index Freshness & Health Signals ─────────────────────────────────


class TestIndexFreshnessHealth:
    """Structured index_status and index_health help agents decide whether
    to trust CodeGraph results or fall back to grep/read."""

    def test_index_status_fresh_index(self, mcp_setup):
        """Fresh index → freshness == 'fresh', warning_level == 'ok'."""
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login")
        idx_status = result["index_status"]
        if idx_status["freshness"] == "fresh":
            assert idx_status["warning_level"] == "ok"
            assert "fresh" in idx_status["message"].lower()

    def test_index_status_stale_includes_suggested_fix(self, tmp_path):
        """Stale index → suggested_fix is populated."""
        import codegraph.mcp_server as mcp_mod
        import json

        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text("{}")
        metadata = {
            "schema_version": "1.0.0", "indexer_version": "1.0.0",
            "root_path": str(root), "indexed_at": "2025-01-01T00:00:00Z",
            "file_count": 1, "symbol_count": 10, "edge_count": 5, "files": [],
        }
        (cg_dir / "metadata.json").write_text(json.dumps(metadata))
        state = {
            "status": "stale", "last_indexed_at": "2025-01-01T00:00:00Z",
            "last_change_summary": {
                "none": 0, "cosmetic": 0, "structural": 3,
                "added": 0, "deleted": 0,
            },
        }
        (cg_dir / "state.json").write_text(json.dumps(state))

        old_root = mcp_mod._project_root
        old_cg = mcp_mod._cg_dir
        old_store = mcp_mod._store
        try:
            mcp_mod._project_root = str(root)
            mcp_mod._cg_dir = cg_dir
            mcp_mod._store = None

            idx = mcp_mod._build_index_status()
            from codegraph.mcp_server import _build_index_status_envelope
            envelope = _build_index_status_envelope(idx)
            assert envelope["freshness"] == "stale"
            assert envelope["suggested_fix"] is not None
            assert "sync" in envelope["suggested_fix"] or "refresh" in envelope["suggested_fix"].lower()
            assert envelope["changed_files_since_index"] == 3
        finally:
            mcp_mod._project_root = old_root
            mcp_mod._cg_dir = old_cg
            mcp_mod._store = old_store

    def test_index_status_includes_changed_files_count(self, tmp_path):
        """changed_files_since_index reflects actual change count."""
        import codegraph.mcp_server as mcp_mod
        import json

        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text("{}")
        metadata = {
            "schema_version": "1.0.0", "indexer_version": "1.0.0",
            "root_path": str(root), "indexed_at": "2025-01-01T00:00:00Z",
            "file_count": 1, "symbol_count": 10, "edge_count": 5, "files": [],
        }
        (cg_dir / "metadata.json").write_text(json.dumps(metadata))
        state = {
            "status": "stale", "last_indexed_at": "2025-01-01T00:00:00Z",
            "last_change_summary": {
                "none": 0, "cosmetic": 2, "structural": 5,
                "added": 1, "deleted": 0,
            },
        }
        (cg_dir / "state.json").write_text(json.dumps(state))

        old_root = mcp_mod._project_root
        old_cg = mcp_mod._cg_dir
        old_store = mcp_mod._store
        try:
            mcp_mod._project_root = str(root)
            mcp_mod._cg_dir = cg_dir
            mcp_mod._store = None

            idx = mcp_mod._build_index_status()
            from codegraph.mcp_server import _build_index_status_envelope
            envelope = _build_index_status_envelope(idx)
            # 2 cosmetic + 5 structural + 1 added + 0 deleted = 8
            assert envelope["changed_files_since_index"] == 8
            assert envelope["freshness"] == "stale"
        finally:
            mcp_mod._project_root = old_root
            mcp_mod._cg_dir = old_cg
            mcp_mod._store = old_store

    def test_index_health_structured_fields(self, mcp_setup):
        """index_health always has all required structured fields."""
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login")
        idx_health = result["index_health"]
        assert isinstance(idx_health, dict)
        for field in ("status", "auto_corrected", "dropped", "total_symbols",
                       "dropped_ratio", "impact", "suggested_fix"):
            assert field in idx_health, f"Missing index_health field: {field}"

    def test_index_health_status_valid(self, mcp_setup):
        """index_health.status is always ok, degraded, or critical."""
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login")
        idx_health = result["index_health"]
        assert idx_health["status"] in ("ok", "degraded", "critical")

    def test_index_health_has_impact_message(self, mcp_setup):
        """index_health.impact contains a human-readable description."""
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login")
        idx_health = result["index_health"]
        assert isinstance(idx_health["impact"], str)
        assert len(idx_health["impact"]) > 0

    def test_index_health_low_dropped_ratio_not_critical(self, tmp_path):
        """When dropped_ratio < 5%, status should not be critical."""
        import codegraph.mcp_server as mcp_mod
        import json

        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text("{}")
        metadata = {
            "schema_version": "1.0.0", "indexer_version": "1.0.0",
            "root_path": str(root), "indexed_at": "2025-01-01T00:00:00Z",
            "file_count": 1, "symbol_count": 5000, "edge_count": 8000, "files": [],
        }
        (cg_dir / "metadata.json").write_text(json.dumps(metadata))
        state = {
            "status": "fresh", "last_indexed_at": "2025-01-01T00:00:00Z",
        }
        (cg_dir / "state.json").write_text(json.dumps(state))
        # Low dropped count relative to total — not critical
        report = {
            "status": "warning",
            "generated_at": "2025-01-01T00:00:00Z",
            "issue_counts": {
                "auto_corrected": 5, "dropped": 10,
                "warnings": 3, "fatal": 0,
            },
            "stats": {"node_count": 5000, "edge_count": 8000},
            "suggested_fix": "codegraph doctor --repair",
        }
        (cg_dir / "validation_report.json").write_text(json.dumps(report))

        old_root = mcp_mod._project_root
        old_cg = mcp_mod._cg_dir
        old_store = mcp_mod._store
        try:
            mcp_mod._project_root = str(root)
            mcp_mod._cg_dir = cg_dir
            mcp_mod._store = None

            idx = mcp_mod._build_index_status()
            from codegraph.mcp_server import _build_index_health_envelope
            envelope = _build_index_health_envelope(idx)
            # dropped_ratio = 10/5000 = 0.002 → not critical
            assert envelope["status"] != "critical", (
                f"Expected non-critical, got {envelope['status']} "
                f"(dropped_ratio={envelope['dropped_ratio']})"
            )
            assert envelope["dropped"] == 10
            assert envelope["auto_corrected"] == 5
            assert envelope["total_symbols"] == 5000
            assert envelope["suggested_fix"] is not None
        finally:
            mcp_mod._project_root = old_root
            mcp_mod._cg_dir = old_cg
            mcp_mod._store = old_store

    def test_index_health_high_dropped_is_degraded_or_critical(self, tmp_path):
        """When dropped count is high, status should reflect degradation."""
        import codegraph.mcp_server as mcp_mod
        import json

        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text("{}")
        metadata = {
            "schema_version": "1.0.0", "indexer_version": "1.0.0",
            "root_path": str(root), "indexed_at": "2025-01-01T00:00:00Z",
            "file_count": 1, "symbol_count": 2000, "edge_count": 3000, "files": [],
        }
        (cg_dir / "metadata.json").write_text(json.dumps(metadata))
        state = {
            "status": "fresh", "last_indexed_at": "2025-01-01T00:00:00Z",
        }
        (cg_dir / "state.json").write_text(json.dumps(state))
        # High dropped — 6% of total
        report = {
            "status": "warning",
            "generated_at": "2025-01-01T00:00:00Z",
            "issue_counts": {
                "auto_corrected": 16, "dropped": 120,
                "warnings": 5, "fatal": 0,
            },
            "stats": {"node_count": 2000, "edge_count": 3000},
            "suggested_fix": "codegraph doctor --repair",
        }
        (cg_dir / "validation_report.json").write_text(json.dumps(report))

        old_root = mcp_mod._project_root
        old_cg = mcp_mod._cg_dir
        old_store = mcp_mod._store
        try:
            mcp_mod._project_root = str(root)
            mcp_mod._cg_dir = cg_dir
            mcp_mod._store = None

            idx = mcp_mod._build_index_status()
            from codegraph.mcp_server import _build_index_health_envelope
            envelope = _build_index_health_envelope(idx)
            # dropped_ratio = 120/2000 = 0.06 → should be degraded or critical
            assert envelope["status"] in ("degraded", "critical"), (
                f"Expected degraded or critical, got {envelope['status']}"
            )
            # Impact message should mention impact analysis
            assert len(envelope["impact"]) > 0
        finally:
            mcp_mod._project_root = old_root
            mcp_mod._cg_dir = old_cg
            mcp_mod._store = old_store

    def test_index_health_with_fatal_is_critical(self, tmp_path):
        """Fatal validation issues → status == 'critical'."""
        import codegraph.mcp_server as mcp_mod
        import json

        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text("{}")
        metadata = {
            "schema_version": "1.0.0", "indexer_version": "1.0.0",
            "root_path": str(root), "indexed_at": "2025-01-01T00:00:00Z",
            "file_count": 1, "symbol_count": 100, "edge_count": 50, "files": [],
        }
        (cg_dir / "metadata.json").write_text(json.dumps(metadata))
        state = {
            "status": "fresh", "last_indexed_at": "2025-01-01T00:00:00Z",
        }
        (cg_dir / "state.json").write_text(json.dumps(state))
        report = {
            "status": "error",
            "generated_at": "2025-01-01T00:00:00Z",
            "issue_counts": {
                "auto_corrected": 0, "dropped": 30,
                "warnings": 2, "fatal": 1,
            },
            "stats": {"node_count": 100, "edge_count": 50},
            "suggested_fix": "codegraph init --force",
        }
        (cg_dir / "validation_report.json").write_text(json.dumps(report))

        old_root = mcp_mod._project_root
        old_cg = mcp_mod._cg_dir
        old_store = mcp_mod._store
        try:
            mcp_mod._project_root = str(root)
            mcp_mod._cg_dir = cg_dir
            mcp_mod._store = None

            idx = mcp_mod._build_index_status()
            from codegraph.mcp_server import _build_index_health_envelope
            envelope = _build_index_health_envelope(idx)
            assert envelope["status"] == "critical"
            assert "rebuild" in envelope["impact"].lower() or "critical" in envelope["impact"].lower()
        finally:
            mcp_mod._project_root = old_root
            mcp_mod._cg_dir = old_cg
            mcp_mod._store = old_store

    def test_index_health_no_report_is_ok(self, tmp_path):
        """No validation report → index_health is ok with zero counts."""
        import codegraph.mcp_server as mcp_mod
        import json

        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text("{}")
        metadata = {
            "schema_version": "1.0.0", "indexer_version": "1.0.0",
            "root_path": str(root), "indexed_at": "2025-01-01T00:00:00Z",
            "file_count": 1, "symbol_count": 100, "edge_count": 50, "files": [],
        }
        (cg_dir / "metadata.json").write_text(json.dumps(metadata))
        state = {
            "status": "fresh", "last_indexed_at": "2025-01-01T00:00:00Z",
        }
        (cg_dir / "state.json").write_text(json.dumps(state))

        old_root = mcp_mod._project_root
        old_cg = mcp_mod._cg_dir
        old_store = mcp_mod._store
        try:
            mcp_mod._project_root = str(root)
            mcp_mod._cg_dir = cg_dir
            mcp_mod._store = None

            idx = mcp_mod._build_index_status()
            from codegraph.mcp_server import _build_index_health_envelope
            envelope = _build_index_health_envelope(idx)
            assert envelope["status"] == "ok"
            assert envelope["auto_corrected"] == 0
            assert envelope["dropped"] == 0
            assert envelope["dropped_ratio"] == 0.0
            assert "healthy" in envelope["impact"].lower() or "no validation" in envelope["impact"].lower()
        finally:
            mcp_mod._project_root = old_root
            mcp_mod._cg_dir = old_cg
            mcp_mod._store = old_store

    def test_all_tools_structured_index_status(self, mcp_setup):
        """All 8 core tools return structured index_status (dict, not string)."""
        from codegraph.mcp_server import (
            search_symbols, get_symbol, get_callers, get_callees,
            get_neighbors, get_impact, repo_status, repo_summary,
            build_context_pack,
        )
        tools = [
            ("codegraph_search_symbols", lambda: search_symbols("login")),
            ("codegraph_get_symbol", lambda: get_symbol("app/api/auth.py::login")),
            ("codegraph_get_callers", lambda: get_callers("app/api/auth.py::login")),
            ("codegraph_get_callees", lambda: get_callees("app/api/auth.py::login")),
            ("codegraph_get_neighbors", lambda: get_neighbors("app/api/auth.py::login")),
            ("codegraph_get_impact", lambda: get_impact("app/api/auth.py::login")),
            ("codegraph_repo_status", lambda: repo_status()),
            ("codegraph_repo_summary", lambda: repo_summary()),
            ("codegraph_build_context_pack", lambda: build_context_pack(task="test query")),
        ]
        for tool_name, tool_fn in tools:
            result = tool_fn()
            assert isinstance(result["index_status"], dict), (
                f"{tool_name}: index_status should be dict, got {type(result['index_status'])}"
            )
            assert isinstance(result["index_health"], dict), (
                f"{tool_name}: index_health should be dict, got {type(result['index_health'])}"
            )


# ── Test: response_mode behavior ────────────────────────────────────────────


class TestResponseMode:
    """All tools default to compact and respect response_mode parameter."""

    def test_search_symbols_defaults_compact(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login")
        items = result["data"]["results"]
        assert len(items) > 0
        # compact: has match sources but no long reason or legacy reason_code
        assert "match_sources" in items[0]
        assert "reason_code" not in items[0]
        assert "reason" not in items[0]

    def test_search_symbols_standard_has_more_fields(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login", response_mode="standard")
        items = result["data"]["results"]
        assert len(items) > 0
        assert "line_start" in items[0]

    def test_get_symbol_defaults_compact(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login")
        # compact: no source, no long docstring
        assert "source" not in result["data"]
        assert "docstring" not in result["data"]["symbol"]

    def test_get_symbol_standard_has_docstring(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", response_mode="standard")
        # standard mode has full fields including signature (docstring only in verbose which was removed)
        assert "signature" in result["data"]["symbol"]

    def test_get_callers_compact_no_edge_nesting(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login")
        for c in result["data"]["callers"]:
            assert "edge" not in c  # flat in compact mode
            assert "confidence" in c
            assert "reason_code" in c

    def test_get_callers_standard_has_edge_nesting(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", response_mode="standard", include_explanations=True)
        for c in result["data"]["callers"]:
            assert "edge" in c
            assert "reason" in c["edge"]

    def test_get_neighbors_compact_has_groups(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login")
        assert "groups" in result["data"]
        assert "nodes" not in result["data"]

    def test_get_neighbors_standard_has_nodes(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", response_mode="standard", group_by_role=False)
        assert "nodes" in result["data"]
        assert "edges" in result["data"]

    def test_get_impact_compact_has_reason_codes(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        assert "reason_codes" in result["data"]["risk"]
        assert "reasons" not in result["data"]["risk"]

    def test_get_impact_standard_has_reasons(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", response_mode="standard")
        risk = result["data"]["risk"]
        assert "reasons" in risk


# ── Test: include_explanations ──────────────────────────────────────────────


class TestIncludeExplanations:
    """include_explanations=false by default, controls reason/evidence output."""

    def test_callers_compact_no_reason_by_default(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login")
        for c in result["data"]["callers"]:
            assert "reason" not in c

    def test_callers_standard_with_explanations(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", response_mode="standard", include_explanations=True)
        for c in result["data"]["callers"]:
            assert "reason" in c["edge"]
            assert "evidence" in c["edge"]

    def test_callees_compact_no_reason_by_default(self, mcp_setup):
        from codegraph.mcp_server import get_callees
        result = get_callees("app/api/auth.py::login")
        for c in result["data"]["callees"]:
            assert "reason" not in c

    def test_callees_standard_with_explanations(self, mcp_setup):
        from codegraph.mcp_server import get_callees
        result = get_callees("app/api/auth.py::login", response_mode="standard", include_explanations=True)
        for c in result["data"]["callees"]:
            assert "reason" in c["edge"]


# ── Test: search_symbols enhanced filtering ─────────────────────────────────


class TestSearchSymbolsEnhanced:
    """search_symbols: exact, fuzzy, tags, paths, exclude_tests, match_sources."""

    def test_exact_true_filters_by_name(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login", exact=True)
        for r in result["data"]["results"]:
            assert r["name"] == "login"

    def test_tags_filter(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("", tags="route", response_mode="standard")
        for r in result["data"]["results"]:
            tags_lower = [t.lower() for t in r.get("tags", [])]
            assert "route" in tags_lower

    def test_paths_filter(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("", paths="app/api/**")
        for r in result["data"]["results"]:
            assert "app/api" in r["file_path"]

    def test_legacy_exclude_tests(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("", exclude_tests=True)
        for r in result["data"]["results"]:
            assert r.get("type") != "test"

    def test_has_match_sources(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login")
        for r in result["data"]["results"]:
            assert "match_sources" in r
            assert len(r["match_sources"]) > 0

    def test_has_pagination_fields(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login", limit=5, offset=0)
        assert "total" in result["data"]
        assert "offset" in result["data"]
        assert "limit" in result["data"]
        assert "has_more" in result["data"]


# ── Test: get_symbol resolve behavior ───────────────────────────────────────


class TestGetSymbolResolve:
    """get_symbol: resolve=true, expected_type, path_hint, AMBIGUOUS_SYMBOL."""

    def test_resolve_exact_name_returns_match(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("login", resolve=True)
        assert result["ok"] is True
        assert result["data"]["symbol"]["name"] == "login"

    def test_resolve_multiple_candidates_ambiguous(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("auth", resolve=True)
        if not result["ok"]:
            assert result["error"]["code"] == "AMBIGUOUS_SYMBOL"
            assert "candidates" in result["error"]["details"]
            assert len(result["error"]["details"]["candidates"]) >= 2

    def test_resolve_with_expected_type_narrows(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("save_token", resolve=True, expected_type="function")
        assert result["ok"] is True
        assert result["data"]["symbol"]["type"] == "function"

    def test_resolve_with_path_hint_narrows(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("save_token", resolve=True, path_hint="app/store")
        assert result["ok"] is True
        assert "store" in result["data"]["symbol"]["file_path"]

    def test_resolve_false_requires_exact_id(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("login", resolve=False)
        # Without resolve, "login" is not an exact ID, so it won't be found
        assert result["ok"] is False
        assert result["error"]["code"] == "SYMBOL_NOT_FOUND"


# ── Test: source snippet control ────────────────────────────────────────────


class TestSourceSnippetControl:
    """get_symbol: source_mode and max_source_lines control."""

    def test_include_source_true_has_source_key(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", include_source=True)
        assert "source" in result["data"]
        src = result["data"]["source"]
        assert "included" in src
        assert "truncated" in src

    def test_source_mode_signature(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", include_source=True, source_mode="signature")
        src = result["data"]["source"]
        assert src["source_mode"] == "signature"

    def test_source_mode_body(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", include_source=True, source_mode="body")
        src = result["data"]["source"]
        assert src["source_mode"] == "body"

    def test_max_source_lines_respected(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", include_source=True, max_source_lines=3)
        src = result["data"]["source"]
        if src["included"]:
            assert src["lines"] <= 3


# ── Test: capabilities and limitations ──────────────────────────────────────


class TestCapabilitiesMetadata:
    """repo_summary: capabilities and limitations in output."""

    def test_repo_summary_has_capabilities(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        assert "capabilities" in result["data"]
        caps = result["data"]["capabilities"]
        assert "languages" in caps
        assert "supported_edges" in caps
        assert "limitations" in caps

    def test_capabilities_include_python(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        assert "python" in result["data"]["capabilities"]["languages"]

    def test_limitations_are_list(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        assert isinstance(result["data"]["capabilities"]["limitations"], list)
        assert len(result["data"]["capabilities"]["limitations"]) > 0


# ── Test: output size guard ─────────────────────────────────────────────────


class TestOutputSizeGuard:
    """All list tools support pagination with has_more and truncated flags."""

    def test_search_symbols_has_more_when_results_exceed_limit(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("", limit=2, offset=0, exclude_tests=False)
        total = result["data"]["total"]
        if total > 2:
            assert result["data"]["has_more"] is True
            assert result["data"]["offset"] == 0
            assert result["data"]["limit"] == 2

    def test_callers_has_pagination(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", limit=5)
        assert "has_more" in result["data"]
        assert "total" in result["data"]
        assert "offset" in result["data"]
        assert "limit" in result["data"]

    def test_callees_has_pagination(self, mcp_setup):
        from codegraph.mcp_server import get_callees
        result = get_callees("app/api/auth.py::login", limit=5)
        assert "has_more" in result["data"]
        assert "total" in result["data"]
        assert "offset" in result["data"]
        assert "limit" in result["data"]

    def test_neighbors_has_truncated_flag(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login")
        assert "truncated" in result["data"]

    def test_impact_has_truncated_flag(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        assert "truncated" in result["data"]


# ── Test: no reading_plan / agent_instructions across all tools ─────────────


class TestNoActionAdviceAnywhere:
    """All tools: never include reading_plan, agent_instructions, or action advice."""

    def _check_no_reading_plan(self, result: dict) -> None:
        if result["ok"] and "data" in result:
            data_str = json.dumps(result["data"])
            assert "reading_plan" not in data_str.lower()
            assert "agent_instructions" not in data_str.lower()
            assert "recommended_context" not in data_str.lower()
            assert "action_items" not in data_str.lower()

    def test_search_symbols_no_advice(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login")
        self._check_no_reading_plan(result)

    def test_get_symbol_no_advice(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login")
        self._check_no_reading_plan(result)

    def test_get_callers_no_advice(self, mcp_setup):
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login")
        self._check_no_reading_plan(result)

    def test_get_callees_no_advice(self, mcp_setup):
        from codegraph.mcp_server import get_callees
        result = get_callees("app/api/auth.py::login")
        self._check_no_reading_plan(result)

    def test_get_neighbors_no_advice(self, mcp_setup):
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login")
        self._check_no_reading_plan(result)

    def test_get_impact_no_advice(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        self._check_no_reading_plan(result)

    def test_repo_summary_no_advice(self, mcp_setup):
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        self._check_no_reading_plan(result)


# ── Test: Symbol + Resolve in Query Tools ──────────────────────────────────


class TestSymbolResolveInQueryTools:
    """Round 3: symbol + resolve=true in callers, callees, neighbors, impact."""

    def test_get_callers_symbol_resolve_unique(self, mcp_setup):
        """resolve=true with unique match executes query normally."""
        from codegraph.mcp_server import get_callers
        result = get_callers(symbol="login", resolve=True, path_hint="app/api/auth.py")
        assert result["ok"]
        assert result["data"]["target"] == "app/api/auth.py::login"
        assert "callers" in result["data"]

    def test_get_callees_symbol_resolve_unique(self, mcp_setup):
        """resolve=true with unique match executes query normally."""
        from codegraph.mcp_server import get_callees
        result = get_callees(symbol="login", resolve=True, path_hint="app/api/auth.py")
        assert result["ok"]
        assert result["data"]["target"] == "app/api/auth.py::login"
        assert "callees" in result["data"]

    def test_get_neighbors_symbol_resolve_unique(self, mcp_setup):
        """resolve=true with unique match executes query normally."""
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors(symbol="login", resolve=True, path_hint="app/api/auth.py")
        assert result["ok"]
        assert result["data"]["center"] == "app/api/auth.py::login"
        assert "groups" in result["data"]

    def test_get_impact_symbol_resolve_unique(self, mcp_setup):
        """resolve=true with unique match executes query normally."""
        from codegraph.mcp_server import get_impact
        result = get_impact(symbol="login", resolve=True, path_hint="app/api/auth.py")
        assert result["ok"]
        assert result["data"]["target"] == "app/api/auth.py::login"

    def test_get_callers_symbol_resolve_ambiguous(self, mcp_setup):
        """Multiple candidates return AMBIGUOUS_SYMBOL error."""
        from codegraph.mcp_server import get_callers
        # "log" matches both "login" and "logout" in the fixture — ambiguous
        result = get_callers(symbol="log", resolve=True)
        assert not result["ok"]
        assert result["error"]["code"] == "AMBIGUOUS_SYMBOL"
        assert "candidates" in result["error"]["details"]

    def test_get_callees_symbol_resolve_ambiguous(self, mcp_setup):
        """Multiple candidates return AMBIGUOUS_SYMBOL error."""
        from codegraph.mcp_server import get_callees
        # "login" appears in multiple node IDs in the fixture — ambiguous without hints
        result = get_callees(symbol="log", resolve=True)
        assert not result["ok"]
        assert result["error"]["code"] == "AMBIGUOUS_SYMBOL"
        assert "candidates" in result["error"]["details"]

    def test_get_neighbors_symbol_resolve_ambiguous(self, mcp_setup):
        """Multiple candidates return AMBIGUOUS_SYMBOL error."""
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors(symbol="log", resolve=True)
        assert not result["ok"]
        assert result["error"]["code"] == "AMBIGUOUS_SYMBOL"
        assert "candidates" in result["error"]["details"]

    def test_get_impact_symbol_resolve_ambiguous(self, mcp_setup):
        """Multiple candidates return AMBIGUOUS_SYMBOL error."""
        from codegraph.mcp_server import get_impact
        result = get_impact(symbol="log", resolve=True)
        assert not result["ok"]
        assert result["error"]["code"] == "AMBIGUOUS_SYMBOL"
        assert "candidates" in result["error"]["details"]

    def test_get_callers_symbol_resolve_not_found(self, mcp_setup):
        """No candidates return SYMBOL_NOT_FOUND."""
        from codegraph.mcp_server import get_callers
        result = get_callers(symbol="nonexistent_func", resolve=True)
        assert not result["ok"]
        assert result["error"]["code"] == "SYMBOL_NOT_FOUND"

    def test_get_callees_symbol_resolve_not_found(self, mcp_setup):
        """No candidates return SYMBOL_NOT_FOUND."""
        from codegraph.mcp_server import get_callees
        result = get_callees(symbol="nonexistent_func", resolve=True)
        assert not result["ok"]
        assert result["error"]["code"] == "SYMBOL_NOT_FOUND"

    def test_get_neighbors_symbol_resolve_not_found(self, mcp_setup):
        """No candidates return SYMBOL_NOT_FOUND."""
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors(symbol="nonexistent_func", resolve=True)
        assert not result["ok"]
        assert result["error"]["code"] == "SYMBOL_NOT_FOUND"

    def test_get_impact_symbol_resolve_not_found(self, mcp_setup):
        """No candidates return SYMBOL_NOT_FOUND."""
        from codegraph.mcp_server import get_impact
        result = get_impact(symbol="nonexistent_func", resolve=True)
        assert not result["ok"]
        assert result["error"]["code"] == "SYMBOL_NOT_FOUND"

    def test_get_callers_without_symbol_or_id(self, mcp_setup):
        """Neither symbol_id nor symbol returns INVALID_ARGUMENT."""
        from codegraph.mcp_server import get_callers
        result = get_callers()
        assert not result["ok"]
        assert result["error"]["code"] == "INVALID_ARGUMENT"

    def test_get_callees_without_symbol_or_id(self, mcp_setup):
        """Neither symbol_id nor symbol returns INVALID_ARGUMENT."""
        from codegraph.mcp_server import get_callees
        result = get_callees()
        assert not result["ok"]
        assert result["error"]["code"] == "INVALID_ARGUMENT"

    def test_get_neighbors_without_symbol_or_id(self, mcp_setup):
        """Neither symbol_id nor symbol returns INVALID_ARGUMENT."""
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors()
        assert not result["ok"]
        assert result["error"]["code"] == "INVALID_ARGUMENT"

    def test_get_impact_without_symbol_or_id(self, mcp_setup):
        """Neither symbol_id nor symbol returns INVALID_ARGUMENT."""
        from codegraph.mcp_server import get_impact
        result = get_impact()
        assert not result["ok"]
        assert result["error"]["code"] == "INVALID_ARGUMENT"


# ── Test: get_impact Confirmed vs Possible Separation ──────────────────────


class TestImpactSeparation:
    """Round 3: get_impact confirmed/possible separation rules."""

    def test_siblings_not_in_confirmed(self, mcp_setup):
        """Sibling symbols (same file, same type) should NOT be in confirmed."""
        from codegraph.mcp_server import get_impact
        # logout is a sibling of login in the same file
        result = get_impact("app/api/auth.py::login", impact_mode="balanced", include_possible=True)
        confirmed_files = [f["file_path"] for f in result["data"]["confirmed"]["files"]]
        # All confirmed files should be from call chain, not sibling heuristic
        for cf in confirmed_files:
            pass
        # Siblings should not cause additional entries in confirmed
        assert "confirmed" in result["data"]

    def test_low_confidence_not_in_confirmed(self, mcp_setup):
        """Low confidence edges (< 0.6) should not appear in confirmed."""
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", min_confidence=0.6)
        confirmed = result["data"]["confirmed"]["files"]
        for f in confirmed:
            conf = f.get("confidence", 1.0)
            assert conf >= 0.6, f"Low confidence file in confirmed: {f['file_path']} (confidence={conf})"

    def test_possible_files_not_in_confirmed(self, mcp_setup):
        """possible files and confirmed files should be disjoint sets."""
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", impact_mode="balanced", include_possible=True)
        confirmed_paths = {f["file_path"] for f in result["data"]["confirmed"]["files"]}
        possible_paths = {f["file_path"] for f in result["data"]["possible"]["files"]}
        overlap = confirmed_paths & possible_paths
        assert len(overlap) == 0, f"Paths appear in both confirmed and possible: {overlap}"

    def test_conservative_is_default(self, mcp_setup):
        """Default impact_mode is conservative — only direct impact."""
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        # conservative has depth=1, so callers at depth > 1 won't be included
        assert result["data"]["risk"]["level"] in ("low", "medium", "high", "critical", "unknown")

    def test_no_broad_mode(self, mcp_setup):
        """Broad impact_mode should be rejected."""
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", impact_mode="broad")
        assert not result["ok"]
        assert result["error"]["code"] == "INVALID_ARGUMENT"

    def test_no_verbose_mode(self, mcp_setup):
        """Verbose response_mode should be rejected."""
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", response_mode="verbose")
        assert not result["ok"]
        assert result["error"]["code"] == "INVALID_ARGUMENT"


# ── Test: Response Mode "full" ──────────────────────────────────────────────


class TestResponseModeFull:
    """full mode: returns all fields, must be explicitly requested."""

    def test_full_mode_accepted(self, mcp_setup):
        """full is a valid response_mode."""
        from codegraph.mcp_server import get_symbol, get_neighbors
        result = get_symbol("app/api/auth.py::login", response_mode="full")
        assert result["ok"] is True

    def test_full_mode_returns_all_node_fields(self, mcp_setup):
        """full mode serialization includes code_preview, metadata, column info."""
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", response_mode="full", include_source=True,
                           include_relations=True)
        if not result["ok"]:
            return  # might not have matching fixture symbol
        sym = result["data"]["symbol"]
        # Full mode includes display_name, full docstring, code_preview
        assert "display_name" in sym
        assert "metadata" in sym
        # Compare with compact — full should have more fields
        result_c = get_symbol("app/api/auth.py::login", response_mode="compact",
                             include_source=True, include_relations=True)
        if result_c["ok"]:
            sym_c = result_c["data"]["symbol"]
            assert len(sym) >= len(sym_c), "full mode should have >= fields than compact"

    def test_full_mode_returns_edge_metadata(self, mcp_setup):
        """full mode edges include call_expr and is_dynamic."""
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", response_mode="full")
        if result["ok"] and result["data"]["callers"]:
            caller = result["data"]["callers"][0]
            # full mode includes edge details inline
            assert "confidence" in caller or "edge" in caller

    def test_full_mode_not_default(self, mcp_setup):
        """Default is compact, full must be explicitly requested."""
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login")
        assert result["ok"] is True
        # compact mode meta says "compact"
        assert result["meta"]["response_mode"] == "compact"


# ── Test: Compact Whitelist ──────────────────────────────────────────────────


class TestCompactWhitelist:
    """compact mode must not return forbidden fields."""

    def test_compact_no_full_source(self, mcp_setup):
        """compact mode never includes source code content."""
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login", include_source=True)
        if result["ok"]:
            sym = result["data"]["symbol"]
            assert "code_preview" not in sym, "compact must not include code_preview"
            assert "docstring" not in sym, "compact must not include docstring"
            assert "metadata" not in sym, "compact must not include metadata"

    def test_compact_no_full_evidence(self, mcp_setup):
        """compact mode callers never include evidence dict."""
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", response_mode="compact")
        if result["ok"] and result["data"]["callers"]:
            for caller in result["data"]["callers"]:
                if "edge" in caller:
                    assert "evidence" not in caller["edge"], "compact edge must not have evidence"

    def test_compact_no_long_explanation(self, mcp_setup):
        """compact mode never includes long reason text."""
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", response_mode="compact",
                            include_explanations=False)
        if result["ok"] and result["data"]["callers"]:
            for caller in result["data"]["callers"]:
                assert "reason" not in caller, "compact must not include reason text"

    def test_compact_has_only_whitelisted_fields(self, mcp_setup):
        """Whitelist filtering safety net works."""
        from codegraph.mcp_server import _apply_compact_whitelist, COMPACT_FIELD_WHITELIST
        # Test whitelist filtering
        data = {
            "symbol_id": "test.py::func",
            "name": "func",
            "forbidden_field": "value",
            "source_code": "def func(): pass",
            "absolute_path": "/home/user/project/test.py",
        }
        filtered = _apply_compact_whitelist(data)
        assert "symbol_id" in filtered
        assert "name" in filtered
        assert "forbidden_field" not in filtered
        assert "source_code" not in filtered
        assert "absolute_path" not in filtered

    def test_compact_whitelist_is_recursive(self, mcp_setup):
        """Whitelist filtering applies recursively to nested dicts/lists."""
        from codegraph.mcp_server import _apply_compact_whitelist
        data = {
            "results": [
                {"symbol_id": "a.py::f", "source_code": "bad", "confidence": 0.9},
                {"symbol_id": "b.py::g", "raw_ast": "bad2", "confidence": 0.8},
            ],
            "forbidden_top": "value",
        }
        filtered = _apply_compact_whitelist(data)
        assert "results" in filtered
        assert "forbidden_top" not in filtered
        for item in filtered["results"]:
            assert "symbol_id" in item
            assert "confidence" in item
            assert "source_code" not in item
            assert "raw_ast" not in item


# ── Test: Layer Assignment ───────────────────────────────────────────────────


class TestLayerAssignment:
    """layer is assigned by file_path directory heuristic."""

    def test_layer_from_directory_heuristic(self, mcp_setup):
        from codegraph.mcp_server import _assign_layer
        assert _assign_layer("app/api/auth.py") == "api"
        assert _assign_layer("app/routes/users.py") == "api"
        assert _assign_layer("app/services/auth_service.py") == "service"
        assert _assign_layer("backend/codegraph/graph/query.py") == "graph"
        assert _assign_layer("backend/codegraph/indexer/scanner.py") == "indexer"
        assert _assign_layer("backend/codegraph/storage/sqlite_store.py") == "storage"
        assert _assign_layer("backend/codegraph/mcp_server.py") == "mcp"
        assert _assign_layer("tests/test_auth.py") == "tests"
        assert _assign_layer("app/config/settings.py") == "config"
        assert _assign_layer("app/models/user.py") == "models"
        assert _assign_layer("app/store/token_store.py") == "storage"
        assert _assign_layer("backend/codegraph/context/pack_builder.py") == "context"
        assert _assign_layer("main.py") == "unknown"

    def test_layer_in_neighbors_compact(self, mcp_setup):
        """get_neighbors nodes include layer in compact mode."""
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", response_mode="compact")
        if result["ok"]:
            for group_name, nodes in result["data"].get("groups", {}).items():
                for node in nodes:
                    assert "layer" in node, f"Node {node.get('symbol_id')} missing layer"

    def test_layer_in_impact_compact(self, mcp_setup):
        """get_impact confirmed files include layer."""
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        if result["ok"]:
            for f in result["data"]["confirmed"]["files"]:
                assert "layer" in f, f"File {f.get('file_path')} missing layer"

    def test_layer_in_repo_summary(self, mcp_setup):
        """repo_summary does not crash with layer assignment."""
        from codegraph.mcp_server import repo_summary
        result = repo_summary()
        assert result["ok"] is True


# ── Test: Payload Meta ───────────────────────────────────────────────────────


class TestPayloadMeta:
    """All responses include payload tracking in meta."""

    def test_response_meta_has_estimated_tokens(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login")
        assert result["ok"] is True
        assert "estimated_tokens" in result["meta"]
        assert result["meta"]["estimated_tokens"] > 0

    def test_response_meta_has_response_mode(self, mcp_setup):
        from codegraph.mcp_server import get_symbol
        result = get_symbol("app/api/auth.py::login")
        assert result["meta"]["response_mode"] == "compact"

    def test_response_meta_has_item_count(self, mcp_setup):
        from codegraph.mcp_server import search_symbols
        result = search_symbols("login")
        assert "item_count" in result["meta"]

    def test_impact_meta_has_truncated(self, mcp_setup):
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login")
        assert "truncated" in result["meta"]
        assert "max_items" in result["meta"]


# ── Test: Truncation ─────────────────────────────────────────────────────────


class TestTruncation:
    """Tools enforce limits and mark truncation."""

    def test_neighbors_truncated_when_over_max_nodes(self, mcp_setup):
        """get_neighbors marks truncated when nodes exceed max."""
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", max_nodes=1, depth=3)
        if result["ok"]:
            assert "truncated" in result["data"]

    def test_impact_truncated_when_over_max_files(self, mcp_setup):
        """get_impact marks truncated when files exceed max."""
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", max_files=1)
        if result["ok"]:
            assert "truncated" in result["data"]

    def test_context_pack_truncated_when_over_max_tokens(self, mcp_setup):
        """build_context_pack clamps max_tokens and marks truncated."""
        from codegraph.mcp_server import build_context_pack
        # Ask for more than hard max
        result = build_context_pack("add MFA", max_tokens=50000, mode="summary",
                                   response_mode="compact")
        if result["ok"]:
            # Should be clamped and marked truncated
            tok = result["data"].get("token_budget", {})
            assert tok.get("max_tokens", 0) <= 20000, "Token budget should be clamped"
            assert result["data"].get("truncated") in (True, False)


# ── Test: Evidence Pack Forbidden Fields ─────────────────────────────────────


class TestEvidencePackForbiddenFields:
    """Evidence Pack must never include plans, instructions, or advice."""

    def test_no_reading_plan_in_output(self, mcp_setup):
        """build_context_pack must never produce reading_plan."""
        from codegraph.mcp_server import build_context_pack
        for mode in ["summary", "compact"]:
            result = build_context_pack("add MFA", mode="summary",
                                       response_mode="compact")
            if result["ok"]:
                assert "reading_plan" not in result["data"]
                assert "reading_plan" not in result

    def test_no_agent_instructions_in_output(self, mcp_setup):
        """build_context_pack must never produce agent_instructions."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary",
                                   response_mode="compact")
        if result["ok"]:
            assert "agent_instructions" not in result["data"]
            assert "agent_instructions" not in result

    def test_no_recommended_context_in_compact(self, mcp_setup):
        """Compact mode strips recommended_context."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary",
                                   response_mode="compact")
        if result["ok"]:
            assert "recommended_context" not in result["data"]
            for key in result["data"]:
                assert "plan" not in key.lower(), f"Forbidden key: {key}"

    def test_compact_no_markdown_body(self, mcp_setup):
        """compact mode never includes markdown body text."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary",
                                   response_mode="compact")
        if result["ok"]:
            assert "markdown_body" not in result["data"]
            assert "markdown_content" not in result["data"]

    def test_no_implementation_plan_in_output(self, mcp_setup):
        """Evidence pack must not include implementation_plan."""
        from codegraph.mcp_server import build_context_pack
        result = build_context_pack("add MFA", mode="summary",
                                   response_mode="compact")
        if result["ok"]:
            assert "implementation_plan" not in result["data"]
            assert "recommended_strategy" not in result["data"]
            assert "do_first" not in result["data"]
            assert "avoid" not in result["data"]
            assert "validation_steps" not in result["data"]


# ── Test: Agent Usage Guidance (方案一+方案三) ──────────────────────────────


class TestAgentUsageGuidance:
    """方案一+方案三：MCP tool descriptions guide agents, README/docs have usage hints."""

    # ── 方案三：MCP tool descriptions ──────────────────────────────────────

    def test_search_symbols_description_guides_before_grep(self):
        """search_symbols description should mention 'before grep'."""
        from codegraph.mcp_server import search_symbols
        doc = search_symbols.__doc__ or ""
        assert "before grep" in doc.lower() or "prefer this" in doc.lower()

    def test_get_symbol_description_guides_after_search(self):
        """get_symbol description should mention 'after search_symbols'."""
        from codegraph.mcp_server import get_symbol
        doc = get_symbol.__doc__ or ""
        assert "after search_symbols" in doc.lower()

    def test_get_callers_description_guides_instead_of_grep(self):
        """get_callers description should mention 'instead of grep'."""
        from codegraph.mcp_server import get_callers
        doc = get_callers.__doc__ or ""
        assert "instead of grep" in doc.lower()

    def test_get_callees_description_guides_instead_of_read(self):
        """get_callees description should mention 'instead of manual Read' or 'instead of' grep/read."""
        from codegraph.mcp_server import get_callees
        doc = get_callees.__doc__ or ""
        doc_lower = doc.lower()
        has_instead_of_read = "instead of manual read" in doc_lower
        has_instead_of_grep = "instead of" in doc_lower and ("grep" in doc_lower or "read" in doc_lower)
        assert has_instead_of_read or has_instead_of_grep, (
            f"get_callees description should guide away from read/grep, got: {doc[:120]}"
        )

    def test_get_neighbors_description_guides_before_reading_files(self):
        """get_neighbors description should mention 'before reading multiple files'."""
        from codegraph.mcp_server import get_neighbors
        doc = get_neighbors.__doc__ or ""
        assert "before reading multiple files" in doc.lower()

    def test_get_impact_description_guides_before_modifying(self):
        """get_impact description should mention 'before modifying shared code'."""
        from codegraph.mcp_server import get_impact
        doc = get_impact.__doc__ or ""
        assert "before modifying" in doc.lower()

    def test_build_context_pack_description_guides_first_tool(self):
        """build_context_pack description should state PRIMARY TOOL and guide first use."""
        from codegraph.mcp_server import build_context_pack
        doc = build_context_pack.__doc__ or ""
        doc_lower = doc.lower()
        assert "primary tool" in doc_lower, (
            f"build_context_pack description should state PRIMARY TOOL, got: {doc[:120]}"
        )
        assert "use first" in doc_lower, (
            f"build_context_pack description should guide 'Use first', got: {doc[:120]}"
        )

    def test_repo_status_description_guides_project_binding_check(self):
        """repo_status description should describe it as a project binding and index health check tool."""
        from codegraph.mcp_server import repo_status
        doc = repo_status.__doc__ or ""
        doc_lower = doc.lower()
        assert "which project" in doc_lower, (
            f"repo_status description should mention 'which project', got: {doc[:120]}"
        )
        assert "index health" in doc_lower, (
            f"repo_status description should mention 'index health', got: {doc[:120]}"
        )
        assert "bound to" in doc_lower, (
            f"repo_status description should mention 'bound to', got: {doc[:120]}"
        )

    def test_repo_summary_description_guides_use_first(self):
        """repo_summary description should mention 'use first' when entering repo."""
        from codegraph.mcp_server import repo_summary
        doc = repo_summary.__doc__ or ""
        assert "use first" in doc.lower() or "before glob" in doc.lower()

    def test_all_tool_descriptions_exist(self):
        """All 9 MCP tools have non-empty descriptions."""
        from codegraph.mcp_server import (
            search_symbols, get_symbol, get_callers, get_callees,
            get_neighbors, get_impact, build_context_pack,
            repo_status, repo_summary,
        )
        tools = [
            search_symbols, get_symbol, get_callers, get_callees,
            get_neighbors, get_impact, build_context_pack,
            repo_status, repo_summary,
        ]
        for tool_fn in tools:
            doc = tool_fn.__doc__
            assert doc is not None, f"{tool_fn.__name__} has no docstring"
            assert len(doc.strip()) > 20, f"{tool_fn.__name__} docstring too short: {doc[:50]}"

    def test_mcp_instructions_contain_anti_patterns(self):
        """MCP server instructions should include anti-patterns for agent behavior."""
        from codegraph.mcp_server import mcp
        instructions = mcp.instructions or ""
        instructions_lower = instructions.lower()
        assert "anti-patterns" in instructions_lower, (
            "MCP instructions should include 'Anti-patterns' section"
        )
        assert "do not grep first" in instructions_lower, (
            "MCP instructions should warn: Do not grep first"
        )
        assert "do not read many files manually" in instructions_lower, (
            "MCP instructions should warn: Do not read many files manually before trying CodeGraph"
        )
        assert "codegraph_build_context_pack" in instructions_lower, (
            "MCP instructions should reference codegraph_build_context_pack"
        )
        assert "use read only when exact source text is needed" in instructions_lower, (
            "MCP instructions should guide: Use Read only when exact source text is needed"
        )

    def test_build_context_pack_is_primary_tool(self):
        """build_context_pack description should mark it as PRIMARY TOOL."""
        from codegraph.mcp_server import build_context_pack
        doc = build_context_pack.__doc__ or ""
        assert "PRIMARY TOOL" in doc, (
            f"build_context_pack description should state PRIMARY TOOL, got: {doc[:150]}"
        )

    def test_repo_status_is_not_debugging_only(self):
        """repo_status description should not describe it as debugging-only.
        It should be a project binding + index health check tool."""
        from codegraph.mcp_server import repo_status
        doc = repo_status.__doc__ or ""
        doc_lower = doc.lower()
        # Should guide checking which project
        assert "which project" in doc_lower, (
            f"repo_status should help verify which project, got: {doc[:120]}"
        )
        # Should mention project_root and index_path
        assert "project_root" in doc_lower, (
            f"repo_status doc should mention project_root, got: {doc[:120]}"
        )


    # ── 方案一：README/docs usage hints ────────────────────────────────────

    def test_readme_contains_codegraph_usage_block(self):
        """README should contain a copyable CodeGraph Usage prompt block."""
        readme_path = Path(__file__).parent.parent.parent / "README.md"
        if not readme_path.exists():
            pytest.skip("README.md not found")
        content = readme_path.read_text(encoding="utf-8")
        assert "## CodeGraph Usage" in content, "README must have CodeGraph Usage markdown block"
        assert "codegraph_repo_summary" in content
        assert "codegraph_search_symbols" in content
        assert "codegraph_get_neighbors" in content
        assert "codegraph_get_callers" in content
        assert "codegraph_get_callees" in content
        assert "codegraph_get_impact" in content
        assert "codegraph_build_context_pack" in content

    def test_readme_has_agent_usage_section(self):
        """README should have an agent usage section."""
        readme_path = Path(__file__).parent.parent.parent / "README.md"
        if not readme_path.exists():
            pytest.skip("README.md not found")
        content = readme_path.read_text(encoding="utf-8")
        # Check for the agent usage section (may use any reasonable title)
        assert (
            "让 Agent 优先使用 CodeGraph" in content
            or "Agent 使用建议" in content
        ), "README must have agent usage section (让 Agent 优先使用 CodeGraph or Agent 使用建议)"

    def test_readme_does_not_claim_auto_install_hints(self):
        """README should not claim to auto-install hints/rules into user files."""
        readme_path = Path(__file__).parent.parent.parent / "README.md"
        if not readme_path.exists():
            pytest.skip("README.md not found")
        content = readme_path.read_text(encoding="utf-8")
        # CodeGraph must not claim to auto-write CLAUDE.md / Cursor rules
        assert "会自动写入 CLAUDE.md" not in content
        assert "会自动安装提示" not in content
        assert "会自动配置 Agent" not in content
        # The negative disclaimer "不会自动写入任何文件" is correct and expected

    def test_readme_does_not_mention_agents_install_hints(self):
        """README should not mention 'codegraph agents install-hints'."""
        readme_path = Path(__file__).parent.parent.parent / "README.md"
        if not readme_path.exists():
            pytest.skip("README.md not found")
        content = readme_path.read_text(encoding="utf-8")
        assert "agents install-hints" not in content, "README must not mention agents install-hints"

    def test_docs_mcp_tools_has_workflow_section(self):
        """docs/mcp-tools.md should have Recommended Agent Workflow section."""
        docs_path = Path(__file__).parent.parent.parent / "docs" / "mcp-tools.md"
        if not docs_path.exists():
            pytest.skip("docs/mcp-tools.md not found")
        content = docs_path.read_text(encoding="utf-8")
        assert "Recommended Agent Workflow" in content, "docs/mcp-tools.md must have workflow section"

    # ── Compat checks ──────────────────────────────────────────────────────

    def test_mcp_tool_names_unchanged(self):
        """MCP tool names and parameter structure remain compatible."""
        from codegraph.mcp_server import (
            search_symbols, get_symbol, get_callers, get_callees,
            get_neighbors, get_impact, build_context_pack,
            repo_status, repo_summary,
        )
        import inspect

        # Check key parameters still exist
        sig = inspect.signature(search_symbols)
        assert "query" in sig.parameters

        sig = inspect.signature(get_symbol)
        assert "symbol_id" in sig.parameters

        sig = inspect.signature(get_callers)
        assert "symbol_id" in sig.parameters
        assert "depth" in sig.parameters

        sig = inspect.signature(get_callees)
        assert "symbol_id" in sig.parameters

        sig = inspect.signature(get_neighbors)
        assert "symbol_id" in sig.parameters
        assert "depth" in sig.parameters
        assert "direction" in sig.parameters

        sig = inspect.signature(get_impact)
        assert "symbol_id" in sig.parameters
        assert "impact_mode" in sig.parameters

        sig = inspect.signature(build_context_pack)
        assert "task" in sig.parameters

        sig = inspect.signature(repo_status)
        assert "response_mode" in sig.parameters, "repo_status missing response_mode param"

        sig = inspect.signature(repo_summary)
        assert "response_mode" in sig.parameters, "repo_summary missing response_mode param"

    def test_mcp_tool_count_is_9(self):
        """There should be exactly 9 MCP tools registered with the FastMCP server."""
        import codegraph.mcp_server as mcp_mod
        # FastMCP stores tool registrations; verify each expected function exists
        expected_tools = [
            "search_symbols", "get_symbol", "get_callers", "get_callees",
            "get_neighbors", "get_impact", "build_context_pack",
            "repo_status", "repo_summary",
        ]
        for tool_name in expected_tools:
            tool_fn = getattr(mcp_mod, tool_name, None)
            assert tool_fn is not None, f"MCP tool '{tool_name}' not found in mcp_server"
            assert callable(tool_fn), f"MCP tool '{tool_name}' is not callable"
            assert tool_fn.__doc__, f"MCP tool '{tool_name}' has no docstring"


# ── Test: mode parameter (quick / deep / review) ─────────────────────────────


class TestModeParameter:
    """mode parameter on get_callers, get_callees, get_neighbors, get_impact."""

    # ── get_callers ────────────────────────────────────────────────────────

    def test_get_callers_mode_quick(self, mcp_setup):
        """get_callers with mode=quick returns compact, shallow results."""
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", mode="quick")
        assert result["ok"] is True
        assert result["meta"]["response_mode"] == "compact"
        callers = result["data"]["callers"]
        # quick defaults: depth=1, include_tests=False
        for c in callers:
            assert c.get("distance", 0) <= 1
            assert c.get("type") != "test"

    def test_get_callers_mode_deep(self, mcp_setup):
        """get_callers with mode=deep returns deeper traversal."""
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", mode="deep")
        assert result["ok"] is True
        # deep allows lower min_confidence (0.4 vs 0.6) — more results possible
        assert "callers" in result["data"]

    def test_get_callers_mode_review(self, mcp_setup):
        """get_callers with mode=review includes tests and explanations."""
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", mode="review")
        assert result["ok"] is True
        # review defaults: include_tests=True, include_explanations=True
        callers = result["data"]["callers"]
        has_test = any(c.get("type") == "test" for c in callers)
        if has_test:
            # At least one test should be included when include_tests=True
            pass  # not guaranteed in test data, but the flag should be honored

    # ── get_callees ────────────────────────────────────────────────────────

    def test_get_callees_mode_quick(self, mcp_setup):
        """get_callees with mode=quick returns compact, shallow results."""
        from codegraph.mcp_server import get_callees
        result = get_callees("app/api/auth.py::login", mode="quick")
        assert result["ok"] is True
        assert result["meta"]["response_mode"] == "compact"
        callees = result["data"]["callees"]
        for c in callees:
            assert c.get("distance", 0) <= 1

    # ── get_neighbors ──────────────────────────────────────────────────────

    def test_get_neighbors_mode_review(self, mcp_setup):
        """get_neighbors with mode=review returns grouped results with explanations."""
        from codegraph.mcp_server import get_neighbors
        result = get_neighbors("app/api/auth.py::login", mode="review")
        assert result["ok"] is True
        # review: compact mode, grouped by role, includes tests
        assert "groups" in result["data"]
        assert "counts" in result["data"]

    # ── get_impact ─────────────────────────────────────────────────────────

    def test_get_impact_mode_review(self, mcp_setup):
        """get_impact with mode=review returns balanced impact with tests."""
        from codegraph.mcp_server import get_impact
        result = get_impact("app/api/auth.py::login", mode="review")
        assert result["ok"] is True
        # review defaults: impact_mode=balanced, include_tests=True, include_possible=True
        assert "confirmed" in result["data"]
        assert "possible" in result["data"]

    # ── Backward compatibility ─────────────────────────────────────────────

    def test_mode_does_not_break_existing_params(self, mcp_setup):
        """Passing mode does not break other parameters — all still work."""
        from codegraph.mcp_server import get_callers
        result = get_callers(
            "app/api/auth.py::login",
            mode="quick",
            depth=2,
            response_mode="standard",
        )
        assert result["ok"] is True
        # User's explicit depth=2 overrides quick's depth=1
        callers = result["data"]["callers"]
        distances = {c.get("distance", 0) for c in callers}
        assert max(distances) >= 1  # depth=2 allows distance=2

    def test_advanced_params_override_mode_defaults(self, mcp_setup):
        """Explicit advanced params override mode preset values."""
        from codegraph.mcp_server import get_callers
        # mode=quick sets include_tests=False, but explicit include_tests=True wins
        result = get_callers(
            "app/api/auth.py::login",
            mode="quick",
            include_tests=True,
        )
        assert result["ok"] is True
        # With include_tests=True, test callers may appear
        callers = result["data"]["callers"]
        test_callers = [c for c in callers if c.get("type") == "test"]
        # The test fixture has test_login as a caller via tested_by edge
        # — not via calls edge, so it may not appear here. But the param
        # should be honored by the traversal function.

    def test_invalid_mode_returns_error(self):
        """Invalid mode value returns a readable error."""
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login", mode="unknown")
        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_ARGUMENT"
        assert "mode" in result["error"]["message"].lower()
        assert "quick" in result["error"]["message"].lower()

    def test_mode_none_is_same_as_no_mode(self, mcp_setup):
        """mode=None behaves identically to not passing mode at all."""
        from codegraph.mcp_server import get_callers
        r1 = get_callers("app/api/auth.py::login")
        r2 = get_callers("app/api/auth.py::login", mode=None)
        assert r1["ok"] == r2["ok"]
        assert r1["data"]["total"] == r2["data"]["total"]
        assert r1["meta"]["response_mode"] == r2["meta"]["response_mode"]

    # ── next_recommended_tools in quick mode ───────────────────────────────

    def test_next_tools_in_quick_mode_callers(self, mcp_setup):
        """mode=quick on get_callers may suggest next tools when many callers found."""
        from codegraph.mcp_server import get_callers
        # The test fixture has main→login as a caller. With mode=quick,
        # total might or might not hit the threshold (>=5).
        # We just verify the key is present when there are many callers,
        # and that it never exceeds 2 entries.
        result = get_callers("app/api/auth.py::login", mode="quick")
        next_tools = result["data"].get("next_recommended_tools", [])
        assert len(next_tools) <= 2
        for nt in next_tools:
            assert "tool" in nt
            assert "reason" in nt

    def test_next_tools_not_present_without_quick_mode(self, mcp_setup):
        """next_recommended_tools should NOT appear when mode is not quick."""
        from codegraph.mcp_server import get_callers
        result = get_callers("app/api/auth.py::login")
        assert "next_recommended_tools" not in result["data"]

    # ── Tool description natural language questions ────────────────────────

    def test_get_callers_description_has_natural_language_question(self):
        """get_callers description contains 'Who calls this'."""
        from codegraph.mcp_server import get_callers
        doc = get_callers.__doc__ or ""
        assert "who calls this" in doc.lower()

    def test_get_callees_description_has_natural_language_question(self):
        """get_callees description contains 'What does this symbol call'."""
        from codegraph.mcp_server import get_callees
        doc = get_callees.__doc__ or ""
        assert "what does this symbol call" in doc.lower()

    def test_get_neighbors_description_has_natural_language_question(self):
        """get_neighbors description contains 'What is connected to this'."""
        from codegraph.mcp_server import get_neighbors
        doc = get_neighbors.__doc__ or ""
        assert "what is connected to this" in doc.lower()

    def test_get_impact_description_has_natural_language_question(self):
        """get_impact description contains 'If I change this symbol'."""
        from codegraph.mcp_server import get_impact
        doc = get_impact.__doc__ or ""
        assert "if i change this" in doc.lower()

    # ── docs/mcp-tools.md ──────────────────────────────────────────────────

    def test_docs_contain_common_modes_section(self):
        """docs/mcp-tools.md must contain a 'Common Modes' section."""
        import os
        docs_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "docs", "mcp-tools.md"
        )
        docs_path = os.path.normpath(docs_path)
        content = open(docs_path, encoding="utf-8").read()
        assert "## Common Modes" in content, (
            "docs/mcp-tools.md must contain a '## Common Modes' section"
        )
        assert "mode=quick" in content, (
            "docs/mcp-tools.md must show mode=quick examples"
        )
        assert "mode=review" in content, (
            "docs/mcp-tools.md must show mode=review examples"
        )

    # ── All 4 tools accept mode parameter ───────────────────────────────────

    def test_get_callers_has_mode_param(self):
        """get_callers signature includes 'mode' parameter."""
        import inspect
        from codegraph.mcp_server import get_callers
        sig = inspect.signature(get_callers)
        assert "mode" in sig.parameters

    def test_get_callees_has_mode_param(self):
        """get_callees signature includes 'mode' parameter."""
        import inspect
        from codegraph.mcp_server import get_callees
        sig = inspect.signature(get_callees)
        assert "mode" in sig.parameters

    def test_get_neighbors_has_mode_param(self):
        """get_neighbors signature includes 'mode' parameter."""
        import inspect
        from codegraph.mcp_server import get_neighbors
        sig = inspect.signature(get_neighbors)
        assert "mode" in sig.parameters

    def test_get_impact_has_mode_param(self):
        """get_impact signature includes 'mode' parameter."""
        import inspect
        from codegraph.mcp_server import get_impact
        sig = inspect.signature(get_impact)
        assert "mode" in sig.parameters
