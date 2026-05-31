"""Repository API routes.

PRD §16.1 — GET /api/repo/summary, GET /api/repo/status, POST /api/repo/index
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from codegraph.api.deps import get_store, get_commit_hash, get_codegraph_dir, get_project_root
from codegraph.graph.store import GraphStore
from codegraph.indexer.graph_builder import build_index, build_index_from_paths
from codegraph.indexer.scanner import scan_python_files, compute_fingerprint
from codegraph.indexer.status import detect_status
from codegraph.storage.file_store import FileStore
from codegraph.graph.models import FileEntry, IndexMetadata, GraphNode, GraphEdge
from pydantic import TypeAdapter

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


class StatusResponse(BaseModel):
    status: str  # "fresh" | "stale" | "missing"
    indexed_at: str | None = None
    changed_files: list[str] = []
    added_files: list[str] = []
    deleted_files: list[str] = []
    recommendation: str = ""


class IndexRequest(BaseModel):
    mode: str = "force"  # "force" | "incremental"


class IndexResponse(BaseModel):
    status: str
    message: str
    file_count: int = 0
    symbol_count: int = 0
    edge_count: int = 0


@router.get("/summary", response_model=RepoSummaryResponse)
async def get_repo_summary(store: GraphStore = Depends(get_store)):
    """Return metadata about the indexed repository."""
    nodes = store.all_nodes()
    edges = store.all_edges()

    function_count = sum(
        1 for n in nodes if n.type.value in ("function", "method")
    )
    class_count = sum(1 for n in nodes if n.type.value == "class")

    low_conf = sum(1 for e in edges if e.confidence < 0.6)
    low_conf_ratio = low_conf / len(edges) if edges else 0.0

    project_root = get_project_root()
    return RepoSummaryResponse(
        name=project_root.name,
        root_path=str(project_root),
        file_count=len({n.file_path for n in nodes}),
        symbol_count=len(nodes),
        function_count=function_count,
        class_count=class_count,
        edge_count=len(edges),
        indexed_at=datetime.now(timezone.utc).isoformat(),
        commit_hash=get_commit_hash(),
        low_confidence_ratio=round(low_conf_ratio, 4),
    )


@router.get("/status", response_model=StatusResponse)
async def get_repo_status():
    """Check index freshness — fresh, stale, or missing."""
    cg_dir = get_codegraph_dir()
    metadata_path = cg_dir / "metadata.json"
    if not metadata_path.exists():
        project_root = get_project_root()
        return StatusResponse(
            status="missing",
            recommendation=f"Run: codegraph init {project_root}",
        )

    store = FileStore(cg_dir)
    metadata = store.load_metadata()
    root_path = Path(metadata.root_path) if metadata and metadata.root_path else cg_dir.parent
    result = detect_status(root_path, metadata)

    return StatusResponse(
        status=result.status,
        indexed_at=result.indexed_at,
        changed_files=result.changed_files,
        added_files=result.added_files,
        deleted_files=result.deleted_files,
        recommendation=result.recommendation,
    )


@router.post("/index", response_model=IndexResponse)
async def trigger_indexing(body: IndexRequest | None = None):
    """Trigger a full or incremental index build.

    Body: {"mode": "force"} or {"mode": "incremental"}
    """
    from codegraph.cli.main import _save_index_artifacts

    mode = body.mode if body else "force"
    cg_dir = get_codegraph_dir()
    root_path = get_project_root()
    store = FileStore(cg_dir)

    if mode == "incremental":
        metadata = store.load_metadata()
        status_result = detect_status(root_path, metadata)

        if status_result.status == "missing":
            raise HTTPException(
                status_code=400,
                detail="No existing index found. Use mode=force for initial indexing.",
            )
        if status_result.status == "fresh":
            return IndexResponse(
                status="ok",
                message="Index is fresh. No changes detected.",
            )

        # Load existing and apply incremental update
        node_adapter = TypeAdapter(list[GraphNode])
        edge_adapter = TypeAdapter(list[GraphEdge])

        existing_nodes_data = store.load_nodes()
        existing_edges_data = store.load_edges()
        current_nodes = node_adapter.validate_python(existing_nodes_data)
        current_edges = edge_adapter.validate_python(existing_edges_data)

        files_to_remove = set(status_result.deleted_files) | set(status_result.changed_files)
        removed_node_ids: set[str] = set()
        if files_to_remove:
            for f in files_to_remove:
                removed_node_ids.update(n.id for n in current_nodes if n.file_path == f)
            current_nodes = [n for n in current_nodes if n.file_path not in files_to_remove]
            current_edges = [
                e for e in current_edges
                if e.source not in removed_node_ids and e.target not in removed_node_ids
            ]

        files_to_reindex = [
            root_path / rel
            for rel in status_result.changed_files + status_result.added_files
        ]
        files_to_reindex = [p for p in files_to_reindex if p.exists()]

        if files_to_reindex:
            new_nodes, new_edges = build_index_from_paths(root_path, files_to_reindex)
            current_nodes.extend(new_nodes)
            current_edges.extend(new_edges)

        _save_index_artifacts(cg_dir, current_nodes, current_edges, root_path)

        return IndexResponse(
            status="ok",
            message=f"Incrementally updated index — {status_result.total_changes} file(s) affected.",
            file_count=len({n.file_path for n in current_nodes}),
            symbol_count=len(current_nodes),
            edge_count=len(current_edges),
        )

    # mode == "force" — full rebuild
    nodes, edges = build_index(root_path)
    _save_index_artifacts(cg_dir, nodes, edges, root_path)

    return IndexResponse(
        status="ok",
        message="Full index rebuilt successfully.",
        file_count=len({n.file_path for n in nodes}),
        symbol_count=len(nodes),
        edge_count=len(edges),
    )
