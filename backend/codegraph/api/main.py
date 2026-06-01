"""FastAPI application entry point.

Serves the CodeGraph Explorer local API.
Loads the graph from ``.codegraph/graph.json`` on startup if available.
"""
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from codegraph.api.deps import init_store
from codegraph.api.routes_context import router as context_router
from codegraph.api.routes_graph import router as graph_router
from codegraph.api.routes_repo import router as repo_router
from codegraph.api.routes_symbols import router as symbols_router
from codegraph.graph.models import CodeGraph
from codegraph.graph.store import GraphStore
from codegraph.storage.file_store import FileStore


def _resolve_project_root() -> Path:
    """Resolve the project root from env var or cwd."""
    env_root = os.environ.get("CODEGRAPH_PROJECT_ROOT", "")
    if env_root:
        return Path(env_root).resolve()
    return Path.cwd()


def _load_graph_from_disk(codegraph_dir: Path, store: GraphStore) -> None:
    """Try to load a previously saved graph into the store."""
    graph_path = codegraph_dir / "graph.json"
    if not graph_path.exists():
        return
    try:
        graph = CodeGraph.model_validate_json(
            graph_path.read_text(encoding="utf-8")
        )
        store.load_from_graph(graph)
    except Exception:
        pass  # silently continue — user can re-index


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared state on startup, clean up on shutdown."""
    project_root = _resolve_project_root()
    codegraph_dir = project_root / ".codegraph"
    codegraph_dir.mkdir(exist_ok=True)

    store = GraphStore()
    _load_graph_from_disk(codegraph_dir, store)
    init_store(store, codegraph_dir)

    file_store = FileStore(codegraph_dir)

    app.state.store = store
    app.state.file_store = file_store

    # Print startup info (only when not under uvicorn reloader)
    if os.environ.get("WERKZEUG_RUN_MAIN", "true") != "false":
        if not (codegraph_dir / "graph.json").exists():
            print(
                "\n  Warning: No CodeGraph index found.\n"
                f"  Run: codegraph init {project_root}\n",
                file=sys.stderr,
            )
        else:
            node_count = len(store.all_nodes())
            edge_count = len(store.all_edges())
            print(
                f"\n  CodeGraph API ready — {node_count} symbols, {edge_count} edges\n"
                f"  Project: {project_root}",
                file=sys.stderr,
            )

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
