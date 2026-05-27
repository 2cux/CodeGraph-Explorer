"""Symbol search and detail API routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/symbols", tags=["symbols"])


@router.get("/search")
async def search_symbols(query: str):
    """Search for symbols matching the given query."""
    ...


@router.get("/{node_id:path}")
async def get_symbol_detail(node_id: str):
    """Return details for a specific symbol."""
    ...
