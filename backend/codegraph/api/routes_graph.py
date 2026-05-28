"""Graph exploration API routes.

PRD §16.1 — GET /api/graph/subgraph, GET /api/graph/stats, GET /api/graph/overview
"""
import os
from collections import Counter

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


# ── Overview file-level graph models ───────────────────────────────────


class OverviewNodeItem(BaseModel):
    id: str
    path: str
    label: str
    module: str
    symbol_count: int
    function_count: int
    class_count: int
    test_count: int


class OverviewEdgeItem(BaseModel):
    source: str
    target: str
    edge_count: int
    types: list[str]


class OverviewResponse(BaseModel):
    nodes: list[OverviewNodeItem] = []
    edges: list[OverviewEdgeItem] = []


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


@router.get("/overview", response_model=OverviewResponse)
async def get_graph_overview(
    store: GraphStore = Depends(get_store),
):
    """Return a file-level overview of the entire code graph.

    Groups symbols by file, computes cross-file dependency edges,
    and returns a graph suitable for the project overview visualization.
    """
    nodes = store.all_nodes()
    edges = store.all_edges()

    # ── Group nodes by file_path ────────────────────────────────────────
    file_map: dict[str, dict] = {}
    # Infer project root: the common prefix of all file paths
    all_paths = [n.file_path for n in nodes if n.file_path]
    common_parts = None
    for fp in all_paths:
        parts = fp.replace("\\", "/").split("/")
        if common_parts is None:
            common_parts = parts[:-1]  # exclude filename
        else:
            i = 0
            while i < len(common_parts) and i < len(parts) and common_parts[i] == parts[i]:
                i += 1
            common_parts = common_parts[:i]
    skip_count = len(common_parts) if common_parts else 0

    for node in nodes:
        fp = node.file_path or "unknown"
        if fp not in file_map:
            parts = fp.replace("\\", "/").split("/")
            # Module = first meaningful directory after common prefix
            module_dir = parts[skip_count] if skip_count < len(parts) else "other"
            file_map[fp] = {
                "id": fp,
                "path": fp,
                "label": os.path.basename(fp),
                "module": module_dir,
                "symbol_count": 0,
                "function_count": 0,
                "class_count": 0,
                "test_count": 0,
            }
        file_map[fp]["symbol_count"] += 1
        if node.type.value in ("function", "method"):
            file_map[fp]["function_count"] += 1
        elif node.type.value == "class":
            file_map[fp]["class_count"] += 1
        elif node.type.value == "test":
            file_map[fp]["test_count"] += 1

    # ── Compute cross-file edge aggregates ──────────────────────────────
    cross_edges: dict[tuple[str, str], Counter] = Counter()
    for edge in edges:
        src_node = store.get_node(edge.source)
        tgt_node = store.get_node(edge.target)
        if not src_node or not tgt_node:
            continue
        src_file = src_node.file_path or "unknown"
        tgt_file = tgt_node.file_path or "unknown"
        if src_file == tgt_file:
            continue
        key = (src_file, tgt_file)
        cross_edges[key] += 1

    return OverviewResponse(
        nodes=[OverviewNodeItem(**v) for v in file_map.values()],
        edges=[
            OverviewEdgeItem(
                source=src,
                target=tgt,
                edge_count=count,
                types=["depends_on"],
            )
            for (src, tgt), count in cross_edges.items()
        ],
    )
