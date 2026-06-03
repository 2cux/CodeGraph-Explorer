"""Framework benchmark checks for TS/JS framework resolver coverage."""

from pathlib import Path

from codegraph.graph import query as graph_query
from codegraph.graph.models import EdgeType, NodeType
from codegraph.graph.store import GraphStore
from codegraph.indexer.graph_builder import build_index_v2


FIXTURES = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures"


def _store_for(project: str) -> GraphStore:
    nodes, edges = build_index_v2(FIXTURES / project)
    store = GraphStore()
    store.load_from_lists(nodes, edges)
    return store


def _confirmed_edges(store: GraphStore, edge_type: EdgeType):
    return [
        e for e in store.all_edges()
        if e.type == edge_type and e.confidence >= 0.8 and not e.target.startswith("unresolved:")
    ]


def test_framework_route_to_handler_recall():
    expected = {
        "express_project": {
            ("GET", "/users", "src/handlers.ts::listUsers"),
            ("POST", "/api/users", "src/handlers.ts::createUser"),
        },
        "nextjs_project": {
            ("ALL", "/api/users", "pages/api/users.ts::handler"),
            ("ALL", "/api/users/:id", "pages/api/users/[id].ts::handler"),
            ("GET", "/api/users", "app/api/users/route.ts::GET"),
            ("POST", "/api/users", "app/api/users/route.ts::POST"),
            ("GET", "/api/users/:id", "app/api/users/[id]/route.ts::GET"),
        },
        "nestjs_project": {
            ("GET", "/users", "src/users.controller.ts::UsersController.listUsers"),
            ("POST", "/users/:id", "src/users.controller.ts::UsersController.createUser"),
        },
    }

    found = 0
    total = 0
    for project, expected_edges in expected.items():
        store = _store_for(project)
        total += len(expected_edges)
        route_meta = {
            n.id: (n.metadata.get("http_method"), n.metadata.get("route_path"))
            for n in store.all_nodes()
            if n.type == NodeType.route
        }
        actual = {
            (*route_meta.get(e.source, ("", "")), e.target)
            for e in _confirmed_edges(store, EdgeType.routes_to)
        }
        found += len(expected_edges & actual)

    recall = found / total
    assert recall >= 0.90


def test_framework_false_confirmed_edges_are_zero():
    express = _store_for("express_project")
    route_edges = _confirmed_edges(express, EdgeType.routes_to)
    false_route_edges = [
        e for e in route_edges
        if e.target == "src/handlers.ts::ghostHandler"
        or (e.metadata and (e.metadata.evidence or {}).get("handler") == "userController.list")
    ]
    assert false_route_edges == []

    react = _store_for("react_project")
    false_react_edges = [
        e for e in _confirmed_edges(react, EdgeType.references)
        if e.source == "src/GhostList.tsx::GhostList" and e.target == "src/UserCard.tsx::UserCard"
    ]
    assert false_react_edges == []


def test_framework_search_route_top1_accuracy_and_neighbors():
    store = _store_for("express_project")
    result = graph_query.search_symbols(store, query="/api/users", types=["route"], limit=1)
    assert result["results"]
    top = result["results"][0]
    assert top["type"] == "route"

    outgoing = store.get_outgoing_edges(top["symbol_id"])
    assert any(e.type == EdgeType.routes_to and e.confidence >= 0.8 for e in outgoing)
