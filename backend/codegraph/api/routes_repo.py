"""Repository API routes.

PRD §16.1 — GET /api/repo/summary, POST /api/repo/index
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from codegraph.api.deps import get_store
from codegraph.graph.store import GraphStore

router = APIRouter(prefix="/api/repo", tags=["repo"])


class RepoSummaryResponse(BaseModel):
    name: str
    root_path: str
    file_count: int
    symbol_count: int
    function_count: int
    class_count: int
    edge_count: int
    indexed_at: str | None = None
    commit_hash: str | None = None
    failed_files: int = 0
    low_confidence_ratio: float = 0.0


class IndexResponse(BaseModel):
    status: str
    message: str
    file_count: int = 0
    symbol_count: int = 0
    edge_count: int = 0


@router.get("/summary", response_model=RepoSummaryResponse)
async def get_repo_summary(store: GraphStore = Depends(get_store)):
    """Return metadata about the indexed repository."""
    nodes = store.search_nodes("")
    edges = []

    function_count = sum(
        1 for n in nodes if n.type.value in ("function", "method")
    )
    class_count = sum(1 for n in nodes if n.type.value == "class")

    return RepoSummaryResponse(
        name=Path.cwd().name,
        root_path=str(Path.cwd()),
        file_count=len({n.file_path for n in nodes}),
        symbol_count=len(nodes),
        function_count=function_count,
        class_count=class_count,
        edge_count=len(edges),
        indexed_at=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/index", response_model=IndexResponse)
async def trigger_indexing():
    """Trigger a full codebase index.

    The actual indexing logic lives in codegraph/indexer/.
    This endpoint delegates to the CLI index command.
    """
    raise HTTPException(
        status_code=501,
        detail="Indexing is not available via API. "
        "Run 'codegraph index' from the CLI.",
    )
