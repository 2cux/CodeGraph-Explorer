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
from codegraph.graph.models import EdgeType

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


# ── Edge detail models ────────────────────────────────────────────────


class EdgeSourceLocation(BaseModel):
    file_path: str
    line_start: int
    line_end: int


class EdgeDetail(BaseModel):
    source: str
    target: str
    type: str
    confidence: float
    confidence_level: str
    resolution: str
    reason_codes: list[str] = []
    reason: str = ""
    evidence: dict = {}
    source_location: EdgeSourceLocation | None = None


class EdgeDetailOk(BaseModel):
    ok: bool = True
    edge: EdgeDetail
    warnings: list[str] = []


class EdgeErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = {}


class EdgeDetailError(BaseModel):
    ok: bool = False
    error: EdgeErrorDetail
    warnings: list[str] = []


def _confidence_level(c: float) -> str:
    if c >= 0.80:
        return "high"
    if c >= 0.60:
        return "medium"
    if c >= 0.40:
        return "low"
    return "unknown"


@router.get("/edge", response_model=EdgeDetailOk | EdgeDetailError)
async def get_edge_detail(
    source: str = Query(..., description="Source node ID"),
    target: str = Query(..., description="Target node ID"),
    type: str | None = Query(default=None, description="Edge type for disambiguation"),
    store: GraphStore = Depends(get_store),
):
    """Return full detail for a single edge identified by source and target.

    If multiple edges exist between the same source-target pair, the optional
    *type* parameter disambiguates. If multiple edges still match, returns
    AMBIGUOUS_EDGE with candidate list.
    """
    edges = store.get_edges_between(source, target, type)

    if not edges:
        return EdgeDetailError(
            ok=False,
            error=EdgeErrorDetail(
                code="EDGE_NOT_FOUND",
                message="Edge not found",
                details={"source": source, "target": target, "type": type or "*"},
            ),
            warnings=[],
        )

    if len(edges) > 1:
        candidates = []
        for e in edges:
            etype = e.type.value if hasattr(e.type, "value") else str(e.type)
            candidates.append({"source": e.source, "target": e.target, "type": etype})
        return EdgeDetailError(
            ok=False,
            error=EdgeErrorDetail(
                code="AMBIGUOUS_EDGE",
                message=f"Multiple edges found between {source} and {target}. Provide the 'type' parameter to disambiguate.",
                details={"candidates": candidates},
            ),
            warnings=[],
        )

    edge = edges[0]
    etype = edge.type.value if hasattr(edge.type, "value") else str(edge.type)
    resolution = ""
    reason = ""
    evidence: dict = {}
    reason_codes: list[str] = []
    source_location = None

    if edge.metadata:
        resolution = edge.metadata.resolution.value if hasattr(edge.metadata.resolution, "value") else str(edge.metadata.resolution)
        reason = edge.metadata.reason or ""
        evidence = edge.metadata.evidence or {}
        if edge.metadata.resolution:
            reason_codes.append(resolution)

    if edge.source_location:
        source_location = EdgeSourceLocation(
            file_path=edge.source_location.file_path,
            line_start=edge.source_location.line_start,
            line_end=edge.source_location.line_end,
        )

    return EdgeDetailOk(
        ok=True,
        edge=EdgeDetail(
            source=edge.source,
            target=edge.target,
            type=etype,
            confidence=edge.confidence,
            confidence_level=_confidence_level(edge.confidence),
            resolution=resolution,
            reason_codes=reason_codes,
            reason=reason,
            evidence=evidence,
            source_location=source_location,
        ),
        warnings=[],
    )
