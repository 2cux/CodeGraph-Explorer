"""Graph exploration API routes.

PRD §16.1 — GET /api/graph/subgraph
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from codegraph.api.deps import get_store
from codegraph.graph.store import GraphStore

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
    confidence: str | None = None


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
        raise HTTPException(
            status_code=404, detail=f"Symbol not found: {normalized}"
        )

    visited: set[str] = set()
    nodes: list[GraphNodeItem] = []
    edges: list[GraphEdgeItem] = []

    def walk(current_id: str, current_depth: int) -> None:
        if current_depth > depth or current_id in visited:
            return
        visited.add(current_id)

        current_node = store.get_node(current_id)
        if current_node:
            nodes.append(
                GraphNodeItem(
                    id=current_node.id,
                    label=current_node.name,
                    type=current_node.type.value
                    if hasattr(current_node.type, "value")
                    else str(current_node.type),
                    file_path=current_node.file_path,
                )
            )

        neighbors = store.get_neighbors(current_id)
        for neighbor, edge in neighbors:
            edges.append(
                GraphEdgeItem(
                    source=current_id,
                    target=neighbor.id,
                    type=edge.type.value
                    if hasattr(edge.type, "value")
                    else str(edge.type),
                    confidence=edge.confidence,
                )
            )
            walk(neighbor.id, current_depth + 1)

    walk(normalized, 0)

    max_nodes = 100
    if len(nodes) > max_nodes:
        nodes = nodes[:max_nodes]

    return SubgraphResponse(
        center_node_id=normalized,
        depth=depth,
        nodes=nodes,
        edges=edges,
        layout_hints=LayoutHints(
            group_by="file",
            max_nodes=max_nodes,
            suggested_view="local_call_graph",
        ),
    )
