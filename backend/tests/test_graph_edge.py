"""Tests for GET /api/graph/edge endpoint and Store.get_edges_between."""

import pytest
from codegraph.graph.store import GraphStore
from codegraph.graph.models import (
    GraphNode, GraphEdge, NodeType, EdgeType, EdgeLocation, EdgeMetadata, Resolution,
)


class TestGetEdgesBetween:
    """Tests for Store.get_edges_between — the data layer backing GET /api/graph/edge."""

    def test_returns_edge_between_source_and_target(self, populated_store):
        edges = populated_store.get_edges_between(
            "main.py::main", "app/api/auth.py::login"
        )
        assert len(edges) == 1
        e = edges[0]
        assert e.source == "main.py::main"
        assert e.target == "app/api/auth.py::login"
        assert hasattr(e.type, "value") and e.type.value == "calls"
        assert e.confidence == 0.95
        assert e.source_location is not None
        assert e.source_location.file_path == "main.py"
        assert e.metadata is not None
        assert hasattr(e.metadata.resolution, "value")

    def test_returns_empty_list_when_edge_not_found(self, populated_store):
        edges = populated_store.get_edges_between(
            "nonexistent::a", "nonexistent::b"
        )
        assert edges == []

    def test_returns_empty_when_target_does_not_match(self, populated_store):
        edges = populated_store.get_edges_between(
            "main.py::main", "nonexistent::b"
        )
        assert edges == []

    def test_filters_by_edge_type(self, populated_store):
        edges = populated_store.get_edges_between(
            "main.py::main", "app/api/auth.py::login", edge_type="calls"
        )
        assert len(edges) == 1

        edges = populated_store.get_edges_between(
            "main.py::main", "app/api/auth.py::login", edge_type="imports"
        )
        assert edges == []

    def test_multiple_edges_between_same_pair(self, empty_store):
        store = empty_store
        store.add_node(GraphNode(id="a::f", type=NodeType.function, name="f", file_path="a"))
        store.add_node(GraphNode(id="b::g", type=NodeType.function, name="g", file_path="b"))

        store.add_edge(GraphEdge(
            id="e1", type=EdgeType.calls, source="a::f", target="b::g",
            confidence=0.9,
            metadata=EdgeMetadata(resolution=Resolution.import_resolved),
        ))
        store.add_edge(GraphEdge(
            id="e2", type=EdgeType.references, source="a::f", target="b::g",
            confidence=0.7,
            metadata=EdgeMetadata(resolution=Resolution.type_hint_resolved),
        ))

        # Without type filter — returns both
        edges = store.get_edges_between("a::f", "b::g")
        assert len(edges) == 2

        # With type filter — returns one
        edges = store.get_edges_between("a::f", "b::g", edge_type="calls")
        assert len(edges) == 1
        assert edges[0].type == EdgeType.calls

    def test_result_contains_confidence_resolution_evidence(self, populated_store):
        edges = populated_store.get_edges_between(
            "main.py::main", "app/api/auth.py::login"
        )
        assert len(edges) == 1
        e = edges[0]
        assert e.confidence is not None
        assert e.confidence >= 0.0
        assert e.metadata is not None
        assert e.metadata.resolution is not None
        # Evidence may be None (not always set), but the field must exist on the model
        assert hasattr(e.metadata, "evidence")

    def test_source_location_in_result(self, populated_store):
        edges = populated_store.get_edges_between(
            "main.py::main", "app/api/auth.py::login"
        )
        e = edges[0]
        assert e.source_location is not None
        assert e.source_location.file_path is not None
        assert e.source_location.line_start is not None


class TestEdgeDetailAPI:
    """Tests for GET /api/graph/edge endpoint via FastAPI TestClient."""

    @pytest.fixture
    def client(self, populated_store):
        """Create a TestClient with the graph routes mounted and store injected."""
        from fastapi.testclient import TestClient
        from codegraph.api.main import app
        from codegraph.api import deps

        # Temporarily override the store dependency
        original_init = deps._store
        deps._store = populated_store

        yield TestClient(app)

        deps._store = original_init

    def test_get_edge_returns_ok(self, client):
        resp = client.get("/api/graph/edge", params={
            "source": "main.py::main",
            "target": "app/api/auth.py::login",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "edge" in data
        edge = data["edge"]
        assert edge["source"] == "main.py::main"
        assert edge["target"] == "app/api/auth.py::login"
        assert edge["type"] == "calls"
        assert "confidence" in edge
        assert "confidence_level" in edge
        assert "resolution" in edge
        assert "source_location" in edge

    def test_edge_not_found_returns_error(self, client):
        resp = client.get("/api/graph/edge", params={
            "source": "nonexistent::a",
            "target": "nonexistent::b",
        })
        assert resp.status_code == 200  # logically success, but ok=false
        data = resp.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "EDGE_NOT_FOUND"
        assert "source" in data["error"]["details"]
        assert "target" in data["error"]["details"]

    def test_ambiguous_edge_returns_candidates(self, client, empty_store):
        store = empty_store
        store.add_node(GraphNode(id="a::f", type=NodeType.function, name="f", file_path="a"))
        store.add_node(GraphNode(id="b::g", type=NodeType.function, name="g", file_path="b"))
        store.add_edge(GraphEdge(
            id="e1", type=EdgeType.calls, source="a::f", target="b::g",
            confidence=0.9,
            metadata=EdgeMetadata(resolution=Resolution.import_resolved),
        ))
        store.add_edge(GraphEdge(
            id="e2", type=EdgeType.references, source="a::f", target="b::g",
            confidence=0.7,
            metadata=EdgeMetadata(resolution=Resolution.type_hint_resolved),
        ))

        from codegraph.api import deps
        original_init = deps._store
        deps._store = store

        from fastapi.testclient import TestClient
        from codegraph.api.main import app
        client2 = TestClient(app)

        resp = client2.get("/api/graph/edge", params={
            "source": "a::f",
            "target": "b::g",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "AMBIGUOUS_EDGE"
        assert "candidates" in data["error"]["details"]
        assert len(data["error"]["details"]["candidates"]) == 2

        deps._store = original_init

    def test_ambiguous_edge_disambiguated_by_type(self, client, empty_store):
        store = empty_store
        store.add_node(GraphNode(id="a::f", type=NodeType.function, name="f", file_path="a"))
        store.add_node(GraphNode(id="b::g", type=NodeType.function, name="g", file_path="b"))
        store.add_edge(GraphEdge(
            id="e1", type=EdgeType.calls, source="a::f", target="b::g",
            confidence=0.9,
            metadata=EdgeMetadata(resolution=Resolution.import_resolved),
        ))
        store.add_edge(GraphEdge(
            id="e2", type=EdgeType.references, source="a::f", target="b::g",
            confidence=0.7,
            metadata=EdgeMetadata(resolution=Resolution.type_hint_resolved),
        ))

        from codegraph.api import deps
        original_init = deps._store
        deps._store = store

        from fastapi.testclient import TestClient
        from codegraph.api.main import app
        client2 = TestClient(app)

        resp = client2.get("/api/graph/edge", params={
            "source": "a::f",
            "target": "b::g",
            "type": "calls",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["edge"]["type"] == "calls"

        deps._store = original_init

    def test_response_has_no_reading_plan_or_agent_instructions(self, client):
        resp = client.get("/api/graph/edge", params={
            "source": "main.py::main",
            "target": "app/api/auth.py::login",
        })
        data = resp.json()
        data_str = str(data).lower()
        assert "reading_plan" not in data_str
        assert "agent_instructions" not in data_str
        assert "recommended_strategy" not in data_str
        assert "next_steps" not in data_str

    def test_confidence_level_is_correct(self, client):
        resp = client.get("/api/graph/edge", params={
            "source": "main.py::main",
            "target": "app/api/auth.py::login",
        })
        data = resp.json()
        edge = data["edge"]
        assert edge["confidence"] >= 0.80
        assert edge["confidence_level"] == "high"

    def test_warnings_is_list(self, client):
        resp = client.get("/api/graph/edge", params={
            "source": "main.py::main",
            "target": "app/api/auth.py::login",
        })
        data = resp.json()
        assert isinstance(data["warnings"], list)
