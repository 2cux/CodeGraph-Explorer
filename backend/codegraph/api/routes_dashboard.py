"""Dashboard stats API routes.

PRD §16.1 — GET /api/dashboard/stats
PRD §17.2 — Project Overview data requirements
"""
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from codegraph.api.deps import get_store
from codegraph.graph.store import GraphStore

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class DashboardStatsResponse(BaseModel):
    project_name: str
    root_path: str
    commit_hash: str | None = None
    file_count: int = 0
    symbol_count: int = 0
    function_count: int = 0
    class_count: int = 0
    edge_count: int = 0
    last_indexed_at: str | None = None
    failed_files: int = 0
    low_confidence_ratio: float = 0.0


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(store: GraphStore = Depends(get_store)):
    """Return aggregate statistics for the Dashboard Project Overview page."""
    nodes = store.all_nodes()
    edges = store.all_edges()

    function_count = sum(
        1 for n in nodes if n.type.value in ("function", "method")
    )
    class_count = sum(1 for n in nodes if n.type.value == "class")

    low_conf = sum(1 for e in edges if e.confidence < 0.6)
    low_conf_ratio = low_conf / len(edges) if edges else 0.0

    return DashboardStatsResponse(
        project_name=Path.cwd().name,
        root_path=str(Path.cwd()),
        file_count=len({n.file_path for n in nodes}),
        symbol_count=len(nodes),
        function_count=function_count,
        class_count=class_count,
        edge_count=len(edges),
        low_confidence_ratio=round(low_conf_ratio, 4),
    )
