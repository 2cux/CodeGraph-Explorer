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
        # main.py::main calls login at distance 1
        assert len(callers) >= 1
        caller_ids = [c[0] for c in callers]
        assert "main.py::main" in caller_ids

    def test_depth_limit(self, populated_store):
        callers = transitive_callers(populated_store, "app/api/auth.py::login", depth=0)
        assert callers == []

    def test_no_callers(self, empty_store):
        callers = transitive_callers(empty_store, "nonexistent", depth=2)
        assert callers == []

    def test_chain_depth(self):
        # Build a caller chain: a -> b -> c -> d
        store = GraphStore()
        for name in ["a", "b", "c", "d"]:
            store.add_node(GraphNode(
                id=f"{name}.py::{name}",
                type=NodeType.function,
                name=name,
                file_path=f"{name}.py",
            ))
        store.add_edge(GraphEdge(type=EdgeType.calls, source="a.py::a", target="b.py::b"))
        store.add_edge(GraphEdge(type=EdgeType.calls, source="b.py::b", target="c.py::c"))
        store.add_edge(GraphEdge(type=EdgeType.calls, source="c.py::c", target="d.py::d"))

        callers = transitive_callers(store, "d.py::d", depth=3)
        assert len(callers) == 3  # a, b, c at distances 3, 2, 1
        distances = {cid: d for cid, d in callers}
        assert distances["c.py::c"] == 1
        assert distances["b.py::b"] == 2
        assert distances["a.py::a"] == 3


class TestTransitiveCallees:
    def test_direct_callees(self, populated_store):
        callees = transitive_callees(populated_store, "app/api/auth.py::login", depth=2)
        assert len(callees) >= 1
        assert callees[0][0] == "app/store/token_store.py::save_token"

    def test_depth_limit(self, populated_store):
        callees = transitive_callees(populated_store, "app/api/auth.py::login", depth=0)
        assert callees == []

    def test_no_callees(self, empty_store):
        callees = transitive_callees(empty_store, "x", depth=2)
        assert callees == []


class TestAnalyzeImpact:
    def test_impact_basic(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login", depth=2)
        assert result["changed_symbol"] == "app/api/auth.py::login"
        assert "affected_symbols" in result
        assert "affected_files" in result
        assert "risk" in result
        assert "recommendations" in result

    def test_impact_includes_self(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        symbols = [s["symbol_id"] for s in result["affected_symbols"]]
        assert "app/api/auth.py::login" in symbols

    def test_impact_includes_callers(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        symbols = [s["symbol_id"] for s in result["affected_symbols"]]
        assert "main.py::main" in symbols

    def test_impact_includes_callees(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        symbols = [s["symbol_id"] for s in result["affected_symbols"]]
        assert "app/store/token_store.py::save_token" in symbols

    def test_impact_risk_level(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        assert result["risk"]["level"] in ("low", "medium", "high", "critical")

    def test_impact_risk_reasons(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        assert len(result["risk"]["reasons"]) > 0
        assert all(isinstance(r, str) for r in result["risk"]["reasons"])

    def test_impact_recommendations(self, populated_store):
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        assert len(result["recommendations"]) > 0
        assert all(isinstance(r, str) for r in result["recommendations"])

    def test_impact_unknown_symbol(self, populated_store):
        result = analyze_impact(populated_store, "nonexistent")
        assert result["risk"]["level"] == "unknown"

    def test_impact_empty_store(self, empty_store):
        result = analyze_impact(empty_store, "x")
        assert result["risk"]["level"] == "unknown"

    def test_impact_sensitive_path_detection(self, populated_store):
        # login/auth path should be detected as sensitive
        result = analyze_impact(populated_store, "app/api/auth.py::login")
        reasons = " ".join(result["risk"]["reasons"]).lower()
        assert any(w in reasons for w in ["sensitive", "security", "auth"])

    def test_impact_warnings_for_low_confidence(self):
        store = GraphStore()
        store.add_node(GraphNode(
            id="test.py::func",
            type=NodeType.function,
            name="func",
            file_path="test.py",
        ))
        store.add_edge(GraphEdge(
            type=EdgeType.calls,
            source="test.py::func",
            target="other.py::other",
            confidence=0.3,
        ))
        result = analyze_impact(store, "test.py::func")
        # Should have low confidence warning
        assert len(result["warnings"]) > 0
        assert any("confidence" in w.lower() for w in result["warnings"])
