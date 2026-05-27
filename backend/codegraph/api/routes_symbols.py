"""Symbol search and detail API routes.

PRD §16.1 — search, detail, callers, callees, neighbors, impact.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from codegraph.api.deps import get_store
from codegraph.graph.models import GraphNode, NodeType
from codegraph.graph.store import GraphStore
from codegraph.graph import query as graph_query
from codegraph.graph import impact as graph_impact

router = APIRouter(prefix="/api/symbols", tags=["symbols"])


# ── Response models ──────────────────────────────────────────────


class PositionModel(BaseModel):
    line_start: int
    line_end: int
    column_start: int | None = None
    column_end: int | None = None


class SymbolDetailResponse(BaseModel):
    id: str
    name: str
    type: str
    file_path: str
    module: str | None = None
    qualified_name: str | None = None
    display_name: str | None = None
    position: PositionModel | None = None
    signature: str | None = None
    docstring: str | None = None
    code_preview: str | None = None
    visibility: str | None = None
    tags: list[str] = []


class SearchResultItem(BaseModel):
    symbol_id: str
    name: str
    type: str
    file_path: str
    score: float
    match_sources: list[str] = []


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    query: str


class NeighborItem(BaseModel):
    node_id: str
    name: str
    type: str
    file_path: str
    edge_type: str
    confidence: str = "unknown"


class NeighborsResponse(BaseModel):
    center_node_id: str
    neighbors: list[NeighborItem]
    total: int


class ImpactAffectedSymbol(BaseModel):
    symbol_id: str
    reason: str
    impact_type: str
    distance: int
    confidence: float = 0.0


class ImpactAffectedFile(BaseModel):
    file_path: str
    reason: str
    priority: str = "medium"


class ImpactRisk(BaseModel):
    level: str
    reasons: list[str]


class ImpactResponse(BaseModel):
    changed_symbol: str
    affected_symbols: list[ImpactAffectedSymbol] = []
    affected_files: list[ImpactAffectedFile] = []
    risk: ImpactRisk | None = None


# ── Helpers ──────────────────────────────────────────────────────


def _node_to_detail(node: GraphNode) -> SymbolDetailResponse:
    pos = None
    if node.location:
        pos = PositionModel(
            line_start=node.location.line_start,
            line_end=node.location.line_end,
            column_start=node.location.column_start,
            column_end=node.location.column_end,
        )
    return SymbolDetailResponse(
        id=node.id,
        name=node.name,
        type=node.type.value if isinstance(node.type, NodeType) else str(node.type),
        file_path=node.file_path,
        module=node.module,
        qualified_name=node.qualified_name,
        display_name=node.display_name,
        position=pos,
        signature=node.signature,
        docstring=node.docstring,
        code_preview=node.code_preview,
        visibility=node.visibility,
        tags=node.tags,
    )


def _node_to_search_item(
    node: GraphNode, score: float, sources: list[str] | None = None
) -> SearchResultItem:
    return SearchResultItem(
        symbol_id=node.id,
        name=node.name,
        type=node.type.value if isinstance(node.type, NodeType) else str(node.type),
        file_path=node.file_path,
        score=score,
        match_sources=sources or [],
    )


def _resolve_symbol_id(node_id: str) -> str:
    """Normalise node_id — strip trailing slashes."""
    return node_id.rstrip("/")


# ── Routes ───────────────────────────────────────────────────────


@router.get("/search", response_model=SearchResponse)
async def search_symbols(
    query: str = Query("", description="Search keyword"),
    type_filter: str | None = Query(None, alias="type", description="Filter by node type"),
    file_filter: str | None = Query(None, alias="file", description="Filter by file path"),
    store: GraphStore = Depends(get_store),
):
    """Search for symbols by name, file path, or docstring."""
    results = graph_query.search_symbols(store, query)
    items = [
        SearchResultItem(
            symbol_id=r.get("id", r.get("symbol_id", "")),
            name=r.get("name", ""),
            type=r.get("type", ""),
            file_path=r.get("file_path", ""),
            score=r.get("score", 0.0),
            match_sources=r.get("match_sources", []),
        )
        for r in results
    ]

    if type_filter:
        items = [i for i in items if i.type == type_filter]
    if file_filter:
        items = [i for i in items if file_filter in i.file_path]

    return SearchResponse(results=items, total=len(items), query=query)


@router.get("/{node_id:path}/impact", response_model=ImpactResponse)
async def get_impact(
    node_id: str,
    depth: int = Query(2, ge=1, le=5),
    store: GraphStore = Depends(get_store),
):
    """Analyse the impact surface of modifying a symbol."""
    normalized = _resolve_symbol_id(node_id)
    node = store.get_node(normalized)
    if not node:
        raise HTTPException(status_code=404, detail=f"Symbol not found: {normalized}")

    result = graph_impact.analyze_impact(store, normalized, depth=depth)
    return ImpactResponse(
        changed_symbol=normalized,
        affected_symbols=[
            ImpactAffectedSymbol(**s) if isinstance(s, dict) else s
            for s in result.get("affected_symbols", [])
        ],
        affected_files=[
            ImpactAffectedFile(**f) if isinstance(f, dict) else f
            for f in result.get("affected_files", [])
        ],
        risk=ImpactRisk(**result["risk"]) if result.get("risk") else None,
    )


@router.get("/{node_id:path}/neighbors", response_model=NeighborsResponse)
async def get_neighbors(
    node_id: str,
    depth: int = Query(1, ge=1, le=3),
    store: GraphStore = Depends(get_store),
):
    """Return the local subgraph centered on a symbol (1-hop by default)."""
    normalized = _resolve_symbol_id(node_id)
    node = store.get_node(normalized)
    if not node:
        raise HTTPException(status_code=404, detail=f"Symbol not found: {normalized}")

    neighbors = store.get_neighbors(normalized)
    items = []
    for neighbor, edge in neighbors:
        items.append(
            NeighborItem(
                node_id=neighbor.id,
                name=neighbor.name,
                type=neighbor.type.value
                if isinstance(neighbor.type, NodeType)
                else str(neighbor.type),
                file_path=neighbor.file_path,
                edge_type=edge.type.value
                if hasattr(edge.type, "value")
                else str(edge.type),
                confidence=edge.confidence,
            )
        )

    return NeighborsResponse(
        center_node_id=normalized, neighbors=items, total=len(items)
    )


@router.get("/{node_id:path}/callees")
async def get_callees(
    node_id: str,
    store: GraphStore = Depends(get_store),
):
    """Return all callees of a symbol (functions it calls)."""
    normalized = _resolve_symbol_id(node_id)
    node = store.get_node(normalized)
    if not node:
        raise HTTPException(status_code=404, detail=f"Symbol not found: {normalized}")

    callees = graph_query.get_callees(store, normalized)
    items = []
    for callee_id, edge_type in callees:
        callee_node = store.get_node(callee_id)
        items.append(
            {
                "node_id": callee_id,
                "name": callee_node.name if callee_node else callee_id,
                "type": callee_node.type.value if callee_node and isinstance(callee_node.type, NodeType) else (str(callee_node.type) if callee_node else "unknown"),
                "file_path": callee_node.file_path if callee_node else "",
                "edge_type": edge_type,
            }
        )

    return {"symbol_id": normalized, "callees": items, "total": len(items)}


@router.get("/{node_id:path}/callers")
async def get_callers(
    node_id: str,
    store: GraphStore = Depends(get_store),
):
    """Return all callers of a symbol (functions that call it)."""
    normalized = _resolve_symbol_id(node_id)
    node = store.get_node(normalized)
    if not node:
        raise HTTPException(status_code=404, detail=f"Symbol not found: {normalized}")

    callers = graph_query.get_callers(store, normalized)
    items = []
    for caller_id, edge_type in callers:
        caller_node = store.get_node(caller_id)
        items.append(
            {
                "node_id": caller_id,
                "name": caller_node.name if caller_node else caller_id,
                "type": caller_node.type.value if caller_node and isinstance(caller_node.type, NodeType) else (str(caller_node.type) if caller_node else "unknown"),
                "file_path": caller_node.file_path if caller_node else "",
                "edge_type": edge_type,
            }
        )

    return {"symbol_id": normalized, "callers": items, "total": len(items)}


@router.get("/{node_id:path}", response_model=SymbolDetailResponse)
async def get_symbol_detail(
    node_id: str,
    store: GraphStore = Depends(get_store),
):
    """Return details for a specific symbol by its node ID."""
    normalized = _resolve_symbol_id(node_id)
    node = store.get_node(normalized)
    if not node:
        raise HTTPException(status_code=404, detail=f"Symbol not found: {normalized}")

    return _node_to_detail(node)
