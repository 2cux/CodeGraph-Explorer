"""Shared incremental index logic used by CLI and watch mode.

Performs diff-based indexing: detect changed/added/deleted files,
patch the existing node/edge sets, and save updated artifacts.
"""

from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter

from codegraph.graph.models import GraphEdge, GraphNode, IndexMetadata
from codegraph.indexer.graph_builder import build_index_from_paths
from codegraph.indexer.scanner import scan_python_files, compute_fingerprint
from codegraph.indexer.status import detect_status, StatusResult
from codegraph.storage.file_store import FileStore


class IncrementalResult:
    """Structured result from an incremental index run."""

    def __init__(
        self,
        status: str,  # "fresh" | "updated" | "missing" | "error"
        status_result: StatusResult | None = None,
        nodes_removed: int = 0,
        nodes_added: int = 0,
        edges_added: int = 0,
        total_symbols: int = 0,
        total_edges: int = 0,
        total_files: int = 0,
        error: str | None = None,
    ) -> None:
        self.status = status
        self.status_result = status_result
        self.nodes_removed = nodes_removed
        self.nodes_added = nodes_added
        self.edges_added = edges_added
        self.total_symbols = total_symbols
        self.total_edges = total_edges
        self.total_files = total_files
        self.error = error

    @property
    def changed_count(self) -> int:
        if self.status_result is None:
            return 0
        return len(self.status_result.changed_files)

    @property
    def added_count(self) -> int:
        if self.status_result is None:
            return 0
        return len(self.status_result.added_files)

    @property
    def deleted_count(self) -> int:
        if self.status_result is None:
            return 0
        return len(self.status_result.deleted_files)


def run_incremental_index(
    root_path: Path,
    output_dir: Path,
    store: FileStore,
    no_sqlite: bool = False,
) -> IncrementalResult:
    """Run incremental index update and return structured result.

    Does NOT hold the index lock — callers must acquire the lock before
    calling this function.
    """
    metadata = store.load_metadata()
    status_result = detect_status(root_path, metadata)

    if status_result.status == "missing":
        return IncrementalResult(
            status="missing",
            status_result=status_result,
        )

    if status_result.status == "fresh":
        return IncrementalResult(
            status="fresh",
            status_result=status_result,
            total_symbols=metadata.symbol_count if metadata else 0,
            total_edges=metadata.edge_count if metadata else 0,
            total_files=metadata.file_count if metadata else 0,
        )

    total_changes = status_result.total_changes
    if total_changes == 0:
        return IncrementalResult(
            status="fresh",
            status_result=status_result,
            total_symbols=metadata.symbol_count if metadata else 0,
            total_edges=metadata.edge_count if metadata else 0,
            total_files=metadata.file_count if metadata else 0,
        )

    # Load existing graph data
    existing_nodes_data = store.load_nodes()
    existing_edges_data = store.load_edges()
    node_adapter = TypeAdapter(list[GraphNode])
    edge_adapter = TypeAdapter(list[GraphEdge])

    current_nodes = node_adapter.validate_python(existing_nodes_data)
    current_edges = edge_adapter.validate_python(existing_edges_data)

    # 1. Remove nodes/edges for deleted and changed files
    files_to_remove = set(status_result.deleted_files) | set(status_result.changed_files)
    removed_node_ids: set[str] = set()
    if files_to_remove:
        for f in files_to_remove:
            removed_node_ids.update(
                n.id for n in current_nodes if n.file_path == f
            )
        current_nodes = [n for n in current_nodes if n.file_path not in files_to_remove]
        current_edges = [
            e for e in current_edges
            if e.source not in removed_node_ids and e.target not in removed_node_ids
        ]

    nodes_removed = len(removed_node_ids)

    # 2. Re-index changed and added files
    files_to_reindex: list[Path] = []
    for rel in status_result.changed_files + status_result.added_files:
        p = root_path / rel
        if p.exists():
            files_to_reindex.append(p)

    new_nodes: list[GraphNode] = []
    new_edges: list[GraphEdge] = []
    if files_to_reindex:
        new_nodes, new_edges = build_index_from_paths(root_path, files_to_reindex)
        current_nodes.extend(new_nodes)
        current_edges.extend(new_edges)

    # 3. Save updated artifacts
    _save_index_artifacts(output_dir, current_nodes, current_edges, root_path, no_sqlite)

    return IncrementalResult(
        status="updated",
        status_result=status_result,
        nodes_removed=nodes_removed,
        nodes_added=len(new_nodes),
        edges_added=len(new_edges),
        total_symbols=len(current_nodes),
        total_edges=len(current_edges),
        total_files=len({n.file_path for n in current_nodes}),
    )


def _save_index_artifacts(
    output_dir: Path,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    root_path: Path,
    no_sqlite: bool = False,
) -> None:
    """Save graph.json, nodes.json, edges.json, metadata.json, and optionally SQLite."""
    from codegraph.graph.models import FileEntry, RepoInfo, CodeGraph

    now_iso = datetime.now(timezone.utc).isoformat()
    node_adapter = TypeAdapter(list[GraphNode])
    edge_adapter = TypeAdapter(list[GraphEdge])

    metadata = IndexMetadata(
        schema_version="1.0.0",
        indexer_version="1.0.0",
        root_path=str(root_path),
        indexed_at=now_iso,
        file_count=len({n.file_path for n in nodes}),
        symbol_count=len(nodes),
        edge_count=len(edges),
        files=[],
    )
    all_files = scan_python_files(root_path)
    for f in all_files:
        rel = f.relative_to(root_path).as_posix()
        metadata.files.append(FileEntry(
            path=rel,
            fingerprint=compute_fingerprint(f),
            indexed_at=now_iso,
        ))

    store = FileStore(output_dir)
    store.save_nodes(node_adapter.dump_python(nodes))
    store.save_edges(edge_adapter.dump_python(edges))
    store.save_metadata(metadata)

    repo_name = root_path.name
    graph = CodeGraph(
        schema_version="1.0.0",
        repo=RepoInfo(
            repo_id=f"local:{repo_name}",
            name=repo_name,
            root_path=str(root_path),
            languages=["python"],
            indexed_at=now_iso,
            file_count=metadata.file_count,
            symbol_count=metadata.symbol_count,
        ),
        nodes=nodes,
        edges=edges,
    )
    graph_path = output_dir / "graph.json"
    graph_path.write_text(
        graph.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )

    if not no_sqlite:
        try:
            from codegraph.storage.sqlite_store import SqliteStore
            sqlite_path = output_dir / "index.sqlite"
            sql_store = SqliteStore(sqlite_path)
            sql_store.initialize()
            sql_store.clear()
            sql_store.save_nodes(node_adapter.dump_python(nodes))
            sql_store.save_edges(edge_adapter.dump_python(edges))
            sql_store.close()
        except Exception:
            pass
