"""FastAPI application entry point.

Serves the CodeGraph Explorer local API on http://localhost:8765.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from codegraph.api.deps import init_store
from codegraph.api.routes_context import router as context_router
from codegraph.api.routes_dashboard import router as dashboard_router
from codegraph.api.routes_graph import router as graph_router
from codegraph.api.routes_repo import router as repo_router
from codegraph.api.routes_symbols import router as symbols_router
from codegraph.graph.store import GraphStore
from codegraph.storage.file_store import FileStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared state on startup, clean up on shutdown."""
    codegraph_dir = Path.cwd() / ".codegraph"
    codegraph_dir.mkdir(exist_ok=True)

    store = GraphStore()
    init_store(store)

    file_store = FileStore(codegraph_dir)

    app.state.store = store
    app.state.file_store = file_store
    yield


app = FastAPI(
    title="CodeGraph Explorer API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(repo_router)
app.include_router(symbols_router)
app.include_router(graph_router)
app.include_router(context_router)
app.include_router(dashboard_router)
