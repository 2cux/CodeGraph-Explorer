"""Graph exploration API routes.

PRD §16.1 — GET /api/graph/subgraph, GET /api/graph/stats
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from codegraph.api.deps import get_store
from codegraph.graph.store import GraphStore
from codegraph.graph import query as graph_query

router = APIRouter(prefix="/api/graph", tags=["graph"])


class GraphNodeItem(BaseModel):
    id: str
    label: str
    type: str
    file_path: str | None = None


class GraphEdgeItem(BaseModel):
    source: str
    target: str
    type: str
    confidence: float | None = None


class LayoutHints(BaseModel):
    group_by: str = "file"
    max_nodes: int = 100
    suggested_view: str = "local_call_graph"


class SubgraphResponse(BaseModel):
    center_node_id: str
    depth: int
    nodes: list[GraphNodeItem] = []
    edges: list[GraphEdgeItem] = []
    layout_hints: LayoutHints = LayoutHints()


class GraphStatsResponse(BaseModel):
    symbol_count: int = 0
    file_count: int = 0
    edge_count: int = 0
    function_count: int = 0
    method_count: int = 0
    class_count: int = 0
    module_count: int = 0
    test_count: int = 0
    import_count: int = 0
    low_confidence_edges: int = 0
    low_confidence_ratio: float = 0.0


def _node_to_item(node) -> GraphNodeItem:
    return GraphNodeItem(
        id=node.id,
        label=node.name,
        type=node.type.value if hasattr(node.type, "value") else str(node.type),
        file_path=node.file_path,
    )


def _edge_to_item(edge) -> GraphEdgeItem:
    return GraphEdgeItem(
        source=edge.source,
        target=edge.target,
        type=edge.type.value if hasattr(edge.type, "value") else str(edge.type),
        confidence=edge.confidence,
    )


@router.get("/subgraph", response_model=SubgraphResponse)
async def get_subgraph(
    symbol_id: str = Query(..., description="Center node ID"),
    depth: int = Query(1, ge=1, le=3, description="Neighbor depth"),
    store: GraphStore = Depends(get_store),
):
    """Return a local subgraph centered on a symbol at the given depth."""
    normalized = symbol_id.rstrip("/")
    center = store.get_node(normalized)
    if not center:
        raise HTTPException(status_code=404, detail=f"Symbol not found: {normalized}")

    result = graph_query.get_subgraph(store, normalized, depth=depth)
    return SubgraphResponse(
        center_node_id=normalized,
        depth=depth,
        nodes=[_node_to_item(n) for n in result["nodes"]],
        edges=[_edge_to_item(e) for e in result["edges"]],
        layout_hints=LayoutHints(
            group_by="file",
            max_nodes=100,
            suggested_view="local_call_graph",
        ),
    )


@router.get("/stats", response_model=GraphStatsResponse)
async def get_graph_stats(
    store: GraphStore = Depends(get_store),
):
    """Return aggregate statistics for the entire code graph."""
    stats = graph_query.get_graph_stats(store)
    return GraphStatsResponse(**stats)
