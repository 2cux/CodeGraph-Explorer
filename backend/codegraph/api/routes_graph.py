"""Graph exploration API routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/neighbors/{node_id:path}")
async def get_neighbors(node_id: str, depth: int = 1):
    """Return the local subgraph centered on a node."""
    ...


@router.get("/callers/{node_id:path}")
async def get_callers(node_id: str):
    """Return all callers of a symbol."""
    ...


@router.get("/callees/{node_id:path}")
async def get_callees(node_id: str):
    """Return all callees of a symbol."""
    ...
