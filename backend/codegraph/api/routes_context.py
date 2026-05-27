"""Context Pack API routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/context", tags=["context"])


@router.post("/generate")
async def generate_context_pack(task_description: str):
    """Generate a Context Pack for a natural language task."""
    ...
