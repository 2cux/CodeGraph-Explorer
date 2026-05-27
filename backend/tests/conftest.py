"""Shared test fixtures for CodeGraph tests."""

import pytest
from codegraph.graph.models import (
    GraphNode, GraphEdge, CodeGraph, RepoInfo,
    NodeType, EdgeType, Location, EdgeLocation, EdgeMetadata, Resolution,
)
from codegraph.graph.store import GraphStore


@pytest.fixture
def sample_nodes() -> list[GraphNode]:
    return [
        GraphNode(
            id="app/api/auth.py",
            type=NodeType.file,
            name="auth.py",
            file_path="app/api/auth.py",
            module="app.api.auth",
        ),
        GraphNode(
            id="app/api/auth.py::login",
            type=NodeType.function,
            name="login",
            file_path="app/api/auth.py",
            module="app.api.auth",
            qualified_name="app.api.auth.login",
            location=Location(line_start=6, line_end=9),
            signature="(username: str, password: str) -> str",
            docstring="Authenticate a user and return a session token.",
            code_preview="def login(username: str, password: str) -> str:\n    ...",
        ),
        GraphNode(
            id="app/api/auth.py::logout",
            type=NodeType.function,
            name="logout",
            file_path="app/api/auth.py",
            module="app.api.auth",
            qualified_name="app.api.auth.logout",
            location=Location(line_start=12, line_end=14),
            signature="(token: str) -> None",
        ),
        GraphNode(
            id="app/store/token_store.py::save_token",
            type=NodeType.function,
            name="save_token",
            file_path="app/store/token_store.py",
            module="app.store.token_store",
            signature="(token: str) -> None",
        ),
        GraphNode(
            id="app/store/token_store.py::revoke_token",
            type=NodeType.function,
            name="revoke_token",
            file_path="app/store/token_store.py",
            module="app.store.token_store",
            signature="(token: str) -> None",
        ),
        GraphNode(
            id="main.py",
            type=NodeType.file,
            name="main.py",
            file_path="main.py",
            module="main",
        ),
        GraphNode(
            id="main.py::main",
            type=NodeType.function,
            name="main",
            file_path="main.py",
            module="main",
            qualified_name="main.main",
            signature="() -> None",
        ),
        GraphNode(
            id="app/models/user.py::User",
            type=NodeType.class_,
            name="User",
            file_path="app/models/user.py",
            module="app.models.user",
            qualified_name="app.models.user.User",
            signature="User",
            tags=["dataclass"],
        ),
    ]


@pytest.fixture
def sample_edges() -> list[GraphEdge]:
    return [
        GraphEdge(
            id="edge_0001",
            type=EdgeType.calls,
            source="main.py::main",
            target="app/api/auth.py::login",
            confidence=0.95,
            source_location=EdgeLocation(file_path="main.py", line_start=10, line_end=10),
            metadata=EdgeMetadata(
                call_expr="login",
                resolution=Resolution.import_resolved,
            ),
        ),
        GraphEdge(
            id="edge_0002",
            type=EdgeType.calls,
            source="main.py::main",
            target="app/api/auth.py::logout",
            confidence=0.95,
            source_location=EdgeLocation(file_path="main.py", line_start=11, line_end=11),
            metadata=EdgeMetadata(
                call_expr="logout",
                resolution=Resolution.import_resolved,
            ),
        ),
        GraphEdge(
            id="edge_0003",
            type=EdgeType.calls,
            source="app/api/auth.py::login",
            target="app/store/token_store.py::save_token",
            confidence=0.9,
            source_location=EdgeLocation(file_path="app/api/auth.py", line_start=8, line_end=8),
            metadata=EdgeMetadata(
                call_expr="save_token",
                resolution=Resolution.import_resolved,
            ),
        ),
        GraphEdge(
            id="edge_0004",
            type=EdgeType.calls,
            source="app/api/auth.py::logout",
            target="app/store/token_store.py::revoke_token",
            confidence=0.9,
            source_location=EdgeLocation(file_path="app/api/auth.py", line_start=13, line_end=13),
            metadata=EdgeMetadata(
                call_expr="revoke_token",
                resolution=Resolution.import_resolved,
            ),
        ),
    ]


@pytest.fixture
def populated_store(sample_nodes, sample_edges) -> GraphStore:
    store = GraphStore()
    store.add_nodes(sample_nodes)
    store.add_edges(sample_edges)
    return store


@pytest.fixture
def empty_store() -> GraphStore:
    return GraphStore()
