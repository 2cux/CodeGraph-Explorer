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


class EntryPointItem(BaseModel):
    symbol_id: str
    name: str
    type: str
    file_path: str
    edge_count: int  # combined callers + callees


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
    entry_points: list[EntryPointItem] = []


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


def _compute_entry_points(store: GraphStore, max_count: int = 6) -> list[EntryPointItem]:
    """Find top connected non-test, non-init symbols as likely entry points."""
    from collections import Counter

    # Count incoming + outgoing edges per symbol
    edge_counts: Counter[str] = Counter()
    for edge in store.all_edges():
        edge_counts[edge.source] += 1
        edge_counts[edge.target] += 1

    def _is_test_path(file_path: str) -> bool:
        """True if the file is under a test directory or named test_*."""
        parts = file_path.replace("\\", "/").split("/")
        return any(p in ("tests", "test", "__tests__") for p in parts)

    def _type_priority(t: str) -> int:
        return {"function": 3, "method": 3, "class": 2, "module": 1, "file": 1}.get(t, 0)

    candidates: list[EntryPointItem] = []
    for node in store.all_nodes():
        if node.type.value == "test":
            continue
        if node.name == "__init__":
            continue
        if _is_test_path(node.file_path):
            continue
        ec = edge_counts.get(node.id, 0)
        if ec == 0:
            continue
        candidates.append(EntryPointItem(
            symbol_id=node.id,
            name=node.name,
            type=node.type.value,
            file_path=node.file_path,
            edge_count=ec,
        ))

    # Sort: edge_count desc, then type priority desc, then prefer shorter names
    candidates.sort(key=lambda c: (
        c.edge_count,
        _type_priority(c.type),
        -len(c.file_path),  # prefer files closer to root
    ), reverse=True)

    return candidates[:max_count]


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

    entry_points = _compute_entry_points(store)

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
        entry_points=entry_points,
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
    from codegraph.storage.writer import write_full_index, write_incremental_update
    from codegraph.storage.state_store import IndexStateStore

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

        state_store = IndexStateStore(cg_dir)
        files_to_remove = set(status_result.deleted_files) | set(status_result.changed_files)
        try:
            counts = write_incremental_update(
                cg_dir, current_nodes, current_edges, root_path,
                removed_files=files_to_remove, state_store=state_store,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Index write failed: {e}")

        return IndexResponse(
            status="ok",
            message=f"Incrementally updated index — {status_result.total_changes} file(s) affected.",
            file_count=len({n.file_path for n in current_nodes}),
            symbol_count=counts["nodes"],
            edge_count=counts["edges"],
        )

    # mode == "force" — full rebuild
    nodes, edges = build_index(root_path)
    state_store = IndexStateStore(cg_dir)
    try:
        counts = write_full_index(
            cg_dir, nodes, edges, root_path, state_store=state_store,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Index write failed: {e}")

    return IndexResponse(
        status="ok",
        message="Full index rebuilt successfully.",
        file_count=len({n.file_path for n in nodes}),
        symbol_count=counts["nodes"],
        edge_count=counts["edges"],
    )
