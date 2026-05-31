"""Tests for impact analysis."""

import pytest
from codegraph.graph.impact import (
    analyze_impact,
    transitive_callers,
    transitive_callees,
)
from codegraph.graph.store import GraphStore
from codegraph.graph.models import (
    GraphNode, GraphEdge, NodeType, EdgeType, Location,
    EdgeLocation, EdgeMetadata, Resolution,
)


class TestTransitiveCallers:
    def test_direct_callers(self, populated_store):
        callers = transitive_callers(populated_store, "app/api/auth.py::login", depth=2)
        assert len(callers) >= 1
        caller_ids = [c[0] for c in callers]
        assert "main.py::main" in caller_ids
        # Check confidence is included
        assert all(len(c) == 3 for c in callers)

    def test_depth_limit(self, populated_store):
        callers = transitive_callers(populated_store, "app/api/auth.py::login", depth=0)
        assert callers == []

    def test_no_callers(self, empty_store):
        callers = transitive_callers(empty_store, "nonexistent", depth=2)
        assert callers == []

    def test_chain_depth(self):
        store = GraphStore()
        for name in ["a", "b", "c", "d"]:
            store.add_node(GraphNode(
                id=f"{name}.py::{name}",
                type=NodeType.function,
                name=name,
                file_path=f"{name}.py",
            ))
        store.add_edge(GraphEdge(type=EdgeType.calls, source="a.py::a", target="b.py::b", confidence=0.9))
        store.add_edge(GraphEdge(type=EdgeType.calls, source="b.py::b", target="c.py::c", confidence=0.9))
        store.add_edge(GraphEdge(type=EdgeType.calls, source="c.py::c", target="d.py::d", confidence=0.9))

        callers = transitive_callers(store, "d.py::d", depth=3)
        assert len(callers) == 3
        distances = {cid: d for cid, d, _ in callers}
        assert distances["c.py::c"] == 1
        assert distances["b.py::b"] == 2
        assert distances["a.py::a"] == 3


class TestTransitiveCallees:
    def test_direct_callees(self, populated_store):
        callees = transitive_callees(populated_store, "app/api/auth.py::login", depth=2)
        assert len(callees) >= 1
        assert callees[0][0] == "app/store/token_store.py::save_token"
        assert len(callees[0]) == 3  # includes confidence

    def test_depth_limit(self, populated_store):
        callees = transitive_callees(populated_store, "app/api/auth.py::login", depth=0)
        assert callees == []

    def test_no_callees(self, empty_store):
        callees = transitive_callees(empty_store, "x", depth=2)
        assert callees == []


class TestAnalyzeImpact:
    def test_impact_basic(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login", depth=2)
        assert "risk" in result
        assert "confirmed_impact" in result
        assert "possible_impact" in result
        assert "upstream_callers" in result
        assert "downstream_callees" in result
        assert "related_tests" in result
        assert "external_or_unresolved" in result

    def test_impact_risk_level(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        assert result["risk"]["level"] in ("low", "medium", "high", "critical", "unknown")

    def test_impact_risk_reasons(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        assert len(result["risk"]["reasons"]) > 0
        assert all(isinstance(r, str) for r in result["risk"]["reasons"])

    def test_impact_confirmed_includes_self(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        symbols = [s["symbol_id"] for s in result["confirmed_impact"]["symbols"]]
        assert "app/api/auth.py::login" in symbols

    def test_impact_confirmed_includes_callers(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        symbols = [s["symbol_id"] for s in result["confirmed_impact"]["symbols"]]
        assert "main.py::main" in symbols

    def test_impact_confirmed_includes_callees(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        symbols = [s["symbol_id"] for s in result["confirmed_impact"]["symbols"]]
        assert "app/store/token_store.py::save_token" in symbols

    def test_impact_confirmed_files(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        files = [f["file_path"] for f in result["confirmed_impact"]["files"]]
        assert "app/api/auth.py" in files

    def test_impact_upstream_callers(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        upstream_ids = [s["symbol_id"] for s in result["upstream_callers"]]
        assert "main.py::main" in upstream_ids

    def test_impact_downstream_callees(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        downstream_ids = [s["symbol_id"] for s in result["downstream_callees"]]
        assert "app/store/token_store.py::save_token" in downstream_ids

    def test_impact_unknown_symbol(self, populated_store):
        result = analyze_impact(populated_store, "nonexistent")
        assert result["risk"]["level"] == "unknown"

    def test_impact_empty_store(self, empty_store):
        result = analyze_impact(empty_store, "x")
        assert result["risk"]["level"] == "unknown"

    def test_impact_sensitive_path_detection(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        reasons = " ".join(result["risk"]["reasons"]).lower()
        assert any(w in reasons for w in ["sensitive", "security", "auth"])

    def test_impact_low_confidence_goes_to_possible(self):
        store = GraphStore()
        store.add_node(GraphNode(
            id="test.py::func",
            type=NodeType.function,
            name="func",
            file_path="test.py",
        ))
        store.add_node(GraphNode(
            id="other.py::other",
            type=NodeType.function,
            name="other",
            file_path="other.py",
        ))
        store.add_node(GraphNode(
            id="ext.py::ext",
            type=NodeType.function,
            name="ext",
            file_path="ext.py",
        ))
        # High confidence edge
        store.add_edge(GraphEdge(
            type=EdgeType.calls,
            source="test.py::func", target="other.py::other",
            confidence=0.9,
        ))
        # Low confidence edge
        store.add_edge(GraphEdge(
            type=EdgeType.calls,
            source="test.py::func", target="ext.py::ext",
            confidence=0.3,
        ))
        result = analyze_impact(store, "test.py::func")
        confirmed_ids = [s["symbol_id"] for s in result["confirmed_impact"]["symbols"]]
        possible_ids = [s["symbol_id"] for s in result["possible_impact"]["symbols"]]

        # High confidence should be in confirmed
        assert "other.py::other" in confirmed_ids
        # Low confidence should be in possible
        assert "ext.py::ext" in possible_ids
        # Low confidence should NOT be in confirmed
        assert "ext.py::ext" not in confirmed_ids

    def test_impact_no_recommendations(self, populated_store):
        """Impact should not return action recommendations."""
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        assert "recommendations" not in result
        # Reasons should be factual, not directive
        for reason in result["risk"]["reasons"]:
            assert "should" not in reason.lower()
            assert "must" not in reason.lower()

    def test_impact_external_unresolved(self):
        store = GraphStore()
        store.add_node(GraphNode(
            id="lib.py::func",
            type=NodeType.function,
            name="func",
            file_path="lib.py",
        ))
        store.add_node(GraphNode(
            id="external_lib.some_func",
            type=NodeType.external_symbol,
            name="some_func",
        ))
        store.add_edge(GraphEdge(
            type=EdgeType.calls,
            source="lib.py::func", target="external_lib.some_func",
            confidence=0.4,
            metadata=EdgeMetadata(resolution=Resolution.external_symbol),
        ))
        result = analyze_impact(store, "lib.py::func")
        assert len(result["external_or_unresolved"]) >= 1
        ext_ids = [e["symbol_id"] for e in result["external_or_unresolved"]]
        assert "external_lib.some_func" in ext_ids
