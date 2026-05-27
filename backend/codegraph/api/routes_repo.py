"""Repository API routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/repo", tags=["repo"])


@router.get("/info")
async def get_repo_info():
    """Return metadata about the indexed repository."""
    ...
