"""Framework resolver tests for TS/JS projects."""

from pathlib import Path

import pytest

from codegraph.graph.models import EdgeType, NodeType, Resolution
from codegraph.graph.store import GraphStore
from codegraph.graph import query as graph_query
from codegraph.indexer.graph_builder import build_index_v2
from codegraph.language_support.registry import reset_registry


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset():
    reset_registry()


def _index(name: str):
    return build_index_v2(FIXTURES / name)


def _store(nodes, edges) -> GraphStore:
    store = GraphStore()
    store.load_from_lists(nodes, edges)
    return store


def _edges(edges, edge_type: EdgeType):
    return [e for e in edges if e.type == edge_type]


def test_express_routes_to_same_file_and_imported_handlers():
    nodes, edges = _index("express_project")
    routes = [n for n in nodes if n.type == NodeType.route and n.framework_id == "express"]
    assert any(n.metadata.get("route_path") == "/users" and n.metadata.get("http_method") == "GET" for n in routes)
    assert any(n.metadata.get("route_path") == "/api/users" and n.metadata.get("http_method") == "POST" for n in routes)

    route_edges = _edges(edges, EdgeType.routes_to)
    targets = {e.target for e in route_edges if e.confidence >= 0.8}
    assert "src/handlers.ts::listUsers" in targets
    assert "src/handlers.ts::createUser" in targets
    assert all(e.metadata.provenance == "framework_resolver" for e in route_edges if e.confidence >= 0.8)


def test_express_uncertain_handlers_do_not_resolve_to_confirmed_symbols():
    nodes, edges = _index("express_project")
    route_edges = _edges(edges, EdgeType.routes_to)

    assert not any(e.target == "src/handlers.ts::ghostHandler" and e.confidence >= 0.8 for e in route_edges)
    object_edges = [
        e for e in route_edges
        if e.metadata and (e.metadata.evidence or {}).get("handler") == "userController.list"
    ]
    assert object_edges
    assert all(e.metadata.resolution == Resolution.object_method_unknown for e in object_edges)
    assert all(e.confidence < 0.6 for e in object_edges)

    inline_edges = [
        e for e in route_edges
        if e.metadata and e.metadata.resolution == Resolution.inline_handler
    ]
    assert inline_edges
    assert all(e.confidence < 0.6 for e in inline_edges)


def test_nextjs_file_routes_resolve_handlers():
    nodes, edges = _index("nextjs_project")
    route_nodes = [n for n in nodes if n.type == NodeType.route and n.framework_id == "nextjs"]
    route_keys = {(n.metadata.get("http_method"), n.metadata.get("route_path")) for n in route_nodes}
    assert ("ALL", "/api/users") in route_keys
    assert ("ALL", "/api/users/:id") in route_keys
    assert ("GET", "/api/users") in route_keys
    assert ("POST", "/api/users") in route_keys
    assert ("GET", "/api/users/:id") in route_keys

    confirmed = [e for e in _edges(edges, EdgeType.routes_to) if e.confidence >= 0.8]
    assert any(e.target == "app/api/users/route.ts::GET" for e in confirmed)
    assert any(e.target == "app/api/users/route.ts::POST" for e in confirmed)


def test_nestjs_controller_routes_and_service_dependency():
    nodes, edges = _index("nestjs_project")
    controllers = [n for n in nodes if n.type == NodeType.controller]
    services = [n for n in nodes if n.type == NodeType.service]
    assert any(n.name == "UsersController" for n in controllers)
    assert any(n.name == "UsersService" for n in services)

    confirmed_routes = [e for e in _edges(edges, EdgeType.routes_to) if e.confidence >= 0.8]
    assert any(e.target == "src/users.controller.ts::UsersController.listUsers" for e in confirmed_routes)
    assert any((e.metadata.evidence or {}).get("route_path") == "/users/:id" for e in confirmed_routes)

    deps = [e for e in _edges(edges, EdgeType.depends_on) if e.confidence >= 0.8]
    assert any(e.source == "src/users.controller.ts::UsersController" and e.target == "src/users.service.ts::UsersService" for e in deps)
    assert not any(e.target.endswith("dynamicProvider") and e.confidence >= 0.8 for e in deps)


def test_react_components_and_jsx_references():
    nodes, edges = _index("react_project")
    components = [n for n in nodes if n.type == NodeType.component]
    assert {n.name for n in components} >= {"UserCard", "UserList", "EmptyState", "GhostList"}

    confirmed_refs = [e for e in _edges(edges, EdgeType.references) if e.confidence >= 0.8]
    assert any(e.source == "src/UserList.tsx::UserList" and e.target == "src/UserCard.tsx::UserCard" for e in confirmed_refs)
    assert not any(e.source == "src/GhostList.tsx::GhostList" and e.target == "src/UserCard.tsx::UserCard" for e in confirmed_refs)


def test_search_route_top1_and_neighbors_are_usable():
    nodes, edges = _index("express_project")
    store = _store(nodes, edges)
    result = graph_query.search_symbols(store, query="/api/users", types=["route"], limit=5)
    assert result["results"]
    assert result["results"][0]["type"] == "route"

    route_id = result["results"][0]["symbol_id"]
    outgoing = store.get_outgoing_edges(route_id)
    assert any(e.type == EdgeType.routes_to and e.confidence >= 0.8 for e in outgoing)


def test_mcp_compact_edge_includes_framework_summary():
    from codegraph.mcp_server import _serialize_edge

    nodes, edges = _index("nextjs_project")
    edge = next(
        e for e in edges
        if e.type == EdgeType.routes_to
        and e.confidence >= 0.8
        and (e.metadata.evidence or {}).get("http_method") == "GET"
    )
    compact = _serialize_edge(edge, response_mode="compact")
    assert compact["framework_id"] == "nextjs"
    assert compact["route_path"] in {"/api/users", "/api/users/:id"}
    assert compact["handler"] == "GET"
    assert compact["provenance"] == "framework_resolver"
