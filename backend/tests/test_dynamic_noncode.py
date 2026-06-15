from pathlib import Path

from codegraph.graph.impact import analyze_impact
from codegraph.graph.explain import explain_file
from codegraph.graph.models import EdgeType, Resolution
from codegraph.graph.store import GraphStore
from codegraph.indexer.graph_builder import build_index
from codegraph.language_support.registry import reset_registry
from codegraph.mcp_server import _serialize_edge


FIXTURE = Path(__file__).parent / "fixtures" / "dynamic_noncode_project"


def _load():
    reset_registry()
    return build_index(FIXTURE)


def _store(nodes, edges):
    store = GraphStore()
    store.load_from_lists(nodes, edges)
    return store


def test_dynamic_heuristic_edges_keep_provenance_and_metadata():
    nodes, edges = _load()
    dynamic_edges = [
        edge for edge in edges
        if edge.metadata
        and edge.metadata.provenance == "heuristic"
        and edge.metadata.evidence
        and edge.metadata.evidence.get("synthesized_by") in {
            "event-emitter",
            "callback-registration",
            "react-event-handler",
            "middleware-chain",
        }
    ]
    assert dynamic_edges

    event_edge = next(edge for edge in dynamic_edges if edge.metadata.resolution == Resolution.event_emitter_heuristic)
    evidence = event_edge.metadata.evidence
    assert evidence["registered_at"] == "src/app.ts:9"
    assert evidence["triggered_at"] == "src/app.ts:13"
    assert evidence["confidence"] == event_edge.confidence

    compact = _serialize_edge(event_edge, response_mode="compact")
    assert compact["evidence_summary"] == 'dynamic: event-emitter via "user.created" @src/app.ts:9'


def test_dynamic_edges_connect_callbacks_routes_and_react_handlers():
    nodes, edges = _load()
    calls = [edge for edge in edges if edge.type == EdgeType.calls]
    depends = [edge for edge in edges if edge.type == EdgeType.depends_on]

    assert any(
        edge.source == "src/app.ts::triggerUserCreated"
        and edge.target == "src/handlers.ts::createUser"
        and edge.metadata.resolution == Resolution.event_emitter_heuristic
        for edge in calls
    )
    assert any(
        edge.source == "src/app.ts::scheduleRefresh"
        and edge.target == "src/handlers.ts::listUsers"
        and edge.metadata.resolution == Resolution.callback_invocation_heuristic
        for edge in calls
    )
    assert any(
        edge.source == "src/ActionPanel.tsx::ActionPanel"
        and edge.target == "src/handlers.ts::listUsers"
        and edge.metadata.resolution == Resolution.react_event_handler_heuristic
        for edge in calls
    )
    assert any(
        edge.target == "src/handlers.ts::authMiddleware"
        and edge.metadata.resolution == Resolution.middleware_chain_heuristic
        for edge in depends
    )


def test_non_code_files_produce_architecture_edges_and_explainable_roles():
    nodes, edges = _load()
    edge_types = {edge.type for edge in edges}
    assert EdgeType.configures in edge_types
    assert EdgeType.deploys in edge_types
    assert EdgeType.documents in edge_types
    assert EdgeType.defines_schema in edge_types
    assert EdgeType.migrates in edge_types
    assert EdgeType.runs_script in edge_types

    assert any(edge.source == "package.json" and edge.type == EdgeType.configures for edge in edges)
    assert any(edge.source == "Dockerfile" and edge.type == EdgeType.deploys and edge.target == "src/app.ts" for edge in edges)
    assert any(edge.source == ".env.example" and edge.type == EdgeType.configures and edge.target == "src/app.ts" for edge in edges)
    assert any(edge.source == "schema.graphql" and edge.type == EdgeType.defines_schema and edge.target == "src/resolvers.ts" for edge in edges)
    assert any(edge.source == "migrations/001_create_users.sql" and edge.type == EdgeType.migrates and edge.target == "src/userStore.ts" for edge in edges)

    store = _store(nodes, edges)
    docker_explanation = explain_file(store, "Dockerfile")
    workflow_explanation = explain_file(store, ".github/workflows/ci.yml")
    assert docker_explanation["likely_role"] == "Container / deployment configuration"
    assert workflow_explanation["likely_role"] == "CI / automation workflow"

    package_impact = analyze_impact(store, "package.json")
    assert any(entry["file_path"] == "src/app.ts" for entry in package_impact["confirmed_impact"]["files"])
