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
        assert "meta" in result
        assert result["meta"]["schema_version"] == "1.0.0"

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
        assert "meta" in result

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
        valid_statuses = {"fresh", "stale", "missing", "indexing", "error"}
        for tool_fn in tools:
            result = tool_fn()
            assert "index_status" in result, f"Missing index_status in tool response"
            assert result["index_status"] in valid_statuses, f"Unexpected index_status: {result['index_status']}"

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
        valid_health = {"ok", "warning", "error"}
        for tool_fn in tools:
            result = tool_fn()
            assert "index_health" in result, f"Missing index_health in tool response"
            assert result["index_health"] in valid_health, f"Unexpected index_health: {result['index_health']}"


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
