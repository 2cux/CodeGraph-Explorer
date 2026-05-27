"""Tests for graph data models and store."""

import pytest
from pydantic import ValidationError

from codegraph.graph.models import (
    GraphNode, GraphEdge, CodeGraph, RepoInfo,
    NodeType, EdgeType, Location, EdgeLocation, EdgeMetadata, Resolution,
)
from codegraph.graph.store import GraphStore


# ── NodeType ──────────────────────────────────────────────────────────────


class TestNodeType:
    def test_values(self):
        assert NodeType.function.value == "function"
        assert NodeType.class_.value == "class"
        assert NodeType.method.value == "method"
        assert NodeType.file.value == "file"
        assert NodeType.module.value == "module"
        assert NodeType.test.value == "test"
        assert NodeType.import_.value == "import"
        assert NodeType.external_symbol.value == "external_symbol"

    def test_node_type_str_repr(self):
        assert str(NodeType.function) == "NodeType.function"


# ── EdgeType ──────────────────────────────────────────────────────────────


class TestEdgeType:
    def test_values(self):
        assert EdgeType.calls.value == "calls"
        assert EdgeType.contains.value == "contains"
        assert EdgeType.imports.value == "imports"
        assert EdgeType.inherits.value == "inherits"
        assert EdgeType.defined_in.value == "defined_in"
        assert EdgeType.references.value == "references"
        assert EdgeType.tested_by.value == "tested_by"


# ── Resolution ────────────────────────────────────────────────────────────


class TestResolution:
    def test_values(self):
        assert Resolution.exact_ast_match.value == "exact_ast_match"
        assert Resolution.unresolved.value == "unresolved"


# ── Location ──────────────────────────────────────────────────────────────


class TestLocation:
    def test_create(self):
        loc = Location(line_start=1, line_end=10)
        assert loc.line_start == 1
        assert loc.line_end == 10
        assert loc.column_start is None
        assert loc.column_end is None

    def test_create_with_columns(self):
        loc = Location(line_start=1, line_end=10, column_start=0, column_end=42)
        assert loc.column_start == 0
        assert loc.column_end == 42

    def test_line_start_required(self):
        with pytest.raises(ValidationError):
            Location(line_end=10)

    def test_line_end_required(self):
        with pytest.raises(ValidationError):
            Location(line_start=1)


# ── GraphNode ─────────────────────────────────────────────────────────────


class TestGraphNode:
    def test_create_minimal(self):
        node = GraphNode(id="test.py", type=NodeType.file, name="test.py")
        assert node.id == "test.py"
        assert node.type == NodeType.file
        assert node.name == "test.py"
        assert node.file_path == ""
        assert node.module == ""

    def test_create_full(self):
        node = GraphNode(
            id="app/api/auth.py::login",
            type=NodeType.function,
            name="login",
            file_path="app/api/auth.py",
            module="app.api.auth",
            qualified_name="app.api.auth.login",
            location=Location(line_start=6, line_end=9),
            signature="(username: str, password: str) -> str",
            docstring="Authenticate a user.",
            code_preview="def login(...):\n    ...",
            visibility="public",
            tags=["auth"],
        )
        assert node.visibility == "public"
        assert node.tags == ["auth"]
        assert node.signature is not None

    def test_defaults(self):
        node = GraphNode(id="x.py", type=NodeType.file, name="x.py")
        assert node.visibility == "public"
        assert node.tags == []
        assert node.metadata == {}

    def test_display_name_defaults_to_blank(self):
        node = GraphNode(id="x.py", type=NodeType.file, name="x.py")
        assert node.display_name == ""


# ── GraphEdge ─────────────────────────────────────────────────────────────


class TestGraphEdge:
    def test_create_minimal(self):
        edge = GraphEdge(
            type=EdgeType.calls,
            source="a.py::foo",
            target="b.py::bar",
        )
        assert edge.type == EdgeType.calls
        assert edge.source == "a.py::foo"
        assert edge.target == "b.py::bar"
        assert edge.confidence == 1.0

    def test_create_full(self):
        edge = GraphEdge(
            id="edge_0001",
            type=EdgeType.calls,
            source="a.py::foo",
            target="b.py::bar",
            confidence=0.95,
            source_location=EdgeLocation(file_path="a.py", line_start=10, line_end=10),
            metadata=EdgeMetadata(
                call_expr="foo",
                resolution=Resolution.import_resolved,
            ),
        )
        assert edge.id == "edge_0001"
        assert edge.confidence == 0.95
        assert edge.metadata is not None
        assert edge.metadata.call_expr == "foo"
        assert edge.metadata.resolution == Resolution.import_resolved

    def test_confidence_range(self):
        edge = GraphEdge(
            type=EdgeType.calls, source="a", target="b", confidence=0.0
        )
        assert edge.confidence == 0.0

    def test_edge_without_location(self):
        edge = GraphEdge(type=EdgeType.imports, source="a.py", target="b.py")
        assert edge.source_location is None


# ── GraphStore ────────────────────────────────────────────────────────────


class TestGraphStore:
    def test_empty_store(self, empty_store):
        assert empty_store.node_count() == 0
        assert empty_store.edge_count() == 0
        assert empty_store.all_nodes() == []
        assert empty_store.all_edges() == []

    def test_add_node(self, empty_store):
        node = GraphNode(id="test.py", type=NodeType.file, name="test.py")
        empty_store.add_node(node)
        assert empty_store.node_count() == 1
        assert empty_store.get_node("test.py") is node

    def test_add_multiple_nodes(self, sample_nodes):
        store = GraphStore()
        store.add_nodes(sample_nodes)
        assert store.node_count() == 8

    def test_get_node_nonexistent(self, empty_store):
        assert empty_store.get_node("nonexistent") is None

    def test_add_edge(self, empty_store):
        edge = GraphEdge(type=EdgeType.calls, source="a", target="b")
        empty_store.add_edge(edge)
        assert empty_store.edge_count() == 1

    def test_add_edges(self, sample_edges):
        store = GraphStore()
        store.add_edges(sample_edges)
        assert store.edge_count() == 4

    def test_get_outgoing_edges(self, populated_store):
        edges = populated_store.get_outgoing_edges("main.py::main")
        assert len(edges) == 2
        ids = {e.target for e in edges}
        assert ids == {"app/api/auth.py::login", "app/api/auth.py::logout"}

    def test_get_incoming_edges(self, populated_store):
        edges = populated_store.get_incoming_edges("app/api/auth.py::login")
        assert len(edges) == 1
        assert edges[0].source == "main.py::main"

    def test_get_neighbors(self, populated_store):
        neighbors = populated_store.get_neighbors("app/api/auth.py::login")
        neighbor_ids = {n.id for n, _ in neighbors}
        assert "main.py::main" in neighbor_ids
        assert "app/store/token_store.py::save_token" in neighbor_ids

    def test_search_nodes(self, populated_store):
        results = populated_store.search_nodes("login")
        assert len(results) >= 1
        assert any(n.id == "app/api/auth.py::login" for n in results)

    def test_search_nodes_empty_query(self, populated_store):
        results = populated_store.search_nodes("")
        assert len(results) == 8  # all nodes

    def test_search_nodes_no_match(self, populated_store):
        results = populated_store.search_nodes("zzz_not_there")
        assert results == []

    def test_load_from_graph(self, sample_nodes, sample_edges):
        graph = CodeGraph(
            schema_version="1.0.0",
            repo=RepoInfo(repo_id="test", name="test", root_path="/test"),
            nodes=sample_nodes,
            edges=sample_edges,
        )
        store = GraphStore()
        store.load_from_graph(graph)
        assert store.node_count() == 8
        assert store.edge_count() == 4

    def test_load_from_lists(self, sample_nodes, sample_edges):
        store = GraphStore()
        store.load_from_lists(sample_nodes, sample_edges)
        assert store.node_count() == 8
        assert store.edge_count() == 4

    def test_clear(self, populated_store):
        populated_store.clear()
        assert populated_store.node_count() == 0
        assert populated_store.edge_count() == 0
        assert populated_store.all_nodes() == []
        assert populated_store.all_edges() == []


# ── CodeGraph top-level ───────────────────────────────────────────────────


class TestCodeGraph:
    def test_create_minimal(self):
        graph = CodeGraph(
            repo=RepoInfo(repo_id="test", name="test", root_path="/test"),
        )
        assert graph.schema_version == "1.0.0"
        assert graph.nodes == []
        assert graph.edges == []

    def test_serialize_roundtrip(self, sample_nodes, sample_edges):
        graph = CodeGraph(
            schema_version="1.0.0",
            repo=RepoInfo(
                repo_id="local:demo",
                name="demo",
                root_path="/demo",
                file_count=1,
                symbol_count=len(sample_nodes),
            ),
            nodes=sample_nodes,
            edges=sample_edges,
        )
        json_str = graph.model_dump_json(exclude_none=True)
        restored = CodeGraph.model_validate_json(json_str)
        assert len(restored.nodes) == len(sample_nodes)
        assert len(restored.edges) == len(sample_edges)
        assert restored.repo.name == "demo"
