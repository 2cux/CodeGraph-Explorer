"""CLI entry point for codegraph commands."""

import os
from pathlib import Path
from datetime import datetime, timezone

import typer
from pydantic import TypeAdapter

from codegraph.graph.models import (
    GraphNode, GraphEdge, CodeGraph, RepoInfo, NodeType,
    FileEntry, IndexMetadata,
)
from codegraph.graph.store import GraphStore
from codegraph.graph import query as graph_query
from codegraph.graph import impact as graph_impact
from codegraph.indexer.graph_builder import build_index, build_index_from_paths
from codegraph.indexer.scanner import scan_python_files, compute_fingerprint
from codegraph.indexer.status import detect_status, StatusResult
from codegraph.storage.file_store import FileStore
from codegraph.storage.sqlite_store import SqliteStore

app = typer.Typer(
    name="codegraph",
    help="CodeGraph Explorer - AI Agent-first code context tool",
)


# ── Helpers ──────────────────────────────────────────────────────────


def _find_codegraph_dir(root: str | None = None) -> Path | None:
    """Walk up from cwd (or given root) to find .codegraph directory."""
    start = Path(root).resolve() if root else Path.cwd()
    for parent in [start] + list(start.parents):
        candidate = parent / ".codegraph"
        if (candidate / "graph.json").exists():
            return candidate
    return None


def _load_store(root: str | None = None) -> tuple[GraphStore, Path]:
    """Load the graph from .codegraph/graph.json into a GraphStore.

    Returns (store, codegraph_dir).
    """
    cg_dir = _find_codegraph_dir(root)
    if cg_dir is None:
        typer.echo(
            "Error: No .codegraph directory found. Run 'codegraph index' first.",
            err=True,
        )
        raise typer.Exit(1)

    graph_path = cg_dir / "graph.json"
    try:
        graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    except Exception as e:
        typer.echo(f"Error: Failed to load {graph_path}: {e}", err=True)
        raise typer.Exit(1)

    store = GraphStore()
    store.load_from_graph(graph)
    return store, cg_dir


def _find_node(store: GraphStore, symbol: str) -> GraphNode | None:
    """Resolve a symbol expression to a node.

    Symbol can be:
      - A full node ID (file.py::func)
      - A bare symbol name (partial match)
      - A file path
    """
    node = store.get_node(symbol)
    if node:
        return node

    symbol_lower = symbol.lower()
    for n in store.all_nodes():
        if n.name.lower() == symbol_lower:
            return n

    for n in store.all_nodes():
        if symbol_lower in n.id.lower():
            return n

    return None


def _format_location(node: GraphNode) -> str:
    if node.location:
        return f":{node.location.line_start}"
    return ""


def _type_label(node_type: NodeType) -> str:
    return {
        NodeType.function: "function",
        NodeType.method: "method",
        NodeType.class_: "class",
        NodeType.module: "module",
        NodeType.file: "file",
        NodeType.test: "test",
        NodeType.import_: "import",
        NodeType.external_symbol: "external",
    }.get(node_type, node_type.value)


# ── index command ────────────────────────────────────────────────────


def _save_index_artifacts(
    output_dir: Path,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    root_path: Path,
    no_sqlite: bool = False,
) -> None:
    """Save graph.json, nodes.json, edges.json, metadata.json, and optionally SQLite."""
    now_iso = datetime.now(timezone.utc).isoformat()
    node_adapter = TypeAdapter(list[GraphNode])
    edge_adapter = TypeAdapter(list[GraphEdge])

    # Build metadata
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
    # Compute fingerprints for all source files
    all_files = scan_python_files(root_path)
    for f in all_files:
        rel = f.relative_to(root_path).as_posix()
        metadata.files.append(FileEntry(
            path=rel,
            fingerprint=compute_fingerprint(f),
            indexed_at=now_iso,
        ))

    # JSON file output
    store = FileStore(output_dir)
    store.save_nodes(node_adapter.dump_python(nodes))
    store.save_edges(edge_adapter.dump_python(edges))
    store.save_metadata(metadata)

    # Full graph output
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

    # SQLite output
    if not no_sqlite:
        try:
            sqlite_path = output_dir / "index.sqlite"
            sql_store = SqliteStore(sqlite_path)
            sql_store.initialize()
            sql_store.clear()
            sql_store.save_nodes(node_adapter.dump_python(nodes))
            sql_store.save_edges(edge_adapter.dump_python(edges))
            sql_store.close()
        except Exception:
            pass  # SQLite is best-effort


@app.command()
def index(
    root: str = typer.Argument(
        ..., help="Root path of the codebase to index",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Re-index even if index already exists",
    ),
    incremental: bool = typer.Option(
        False, "--incremental", "-i",
        help="Incrementally update only changed/new/deleted files",
    ),
    no_sqlite: bool = typer.Option(
        False, "--no-sqlite",
        help="Skip SQLite output",
    ),
) -> None:
    """Scan the codebase, parse AST, and build code graph index."""
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        typer.echo(f"Error: {root} is not a valid directory", err=True)
        raise typer.Exit(1)

    output_dir = root_path / ".codegraph"
    output_dir.mkdir(parents=True, exist_ok=True)

    store = FileStore(output_dir)

    if incremental:
        _run_incremental_index(root_path, output_dir, store, no_sqlite)
        return

    if not force and (output_dir / "nodes.json").exists():
        typer.echo("Index already exists. Use --force to re-index.")
        return

    typer.echo(f"Scanning {root_path} ...")
    nodes, edges = build_index(root_path)

    typer.echo(f"Found {len(nodes)} symbols and {len(edges)} relationships.")

    _save_index_artifacts(output_dir, nodes, edges, root_path, no_sqlite)

    typer.echo(f"Index written to {output_dir / 'graph.json'}")
    typer.echo(f"  Files indexed: {len({n.file_path for n in nodes})}")
    typer.echo(f"  Symbols:       {len(nodes)}")
    typer.echo(f"  Edges:         {len(edges)}")


def _run_incremental_index(
    root_path: Path,
    output_dir: Path,
    store: FileStore,
    no_sqlite: bool,
) -> None:
    """Incrementally update the index for changed / added / deleted files."""
    metadata = store.load_metadata()
    status_result = detect_status(root_path, metadata)

    if status_result.status == "missing":
        typer.echo("No existing index found. Run full index first:")
        typer.echo(f"  codegraph index {root_path}")
        return

    if status_result.status == "fresh":
        typer.echo("Index status: fresh")
        typer.echo("No changes detected. Nothing to update.")
        return

    typer.echo(f"Index status: stale")
    total_changes = status_result.total_changes

    if status_result.changed_files:
        typer.echo(f"  Changed files: {len(status_result.changed_files)}")
        for f in status_result.changed_files[:10]:
            typer.echo(f"    - {f}")
        if len(status_result.changed_files) > 10:
            typer.echo(f"    ... and {len(status_result.changed_files) - 10} more")
    if status_result.added_files:
        typer.echo(f"  Added files: {len(status_result.added_files)}")
        for f in status_result.added_files[:10]:
            typer.echo(f"    + {f}")
        if len(status_result.added_files) > 10:
            typer.echo(f"    ... and {len(status_result.added_files) - 10} more")
    if status_result.deleted_files:
        typer.echo(f"  Deleted files: {len(status_result.deleted_files)}")
        for f in status_result.deleted_files[:10]:
            typer.echo(f"    x {f}")
        if len(status_result.deleted_files) > 10:
            typer.echo(f"    ... and {len(status_result.deleted_files) - 10} more")

    if total_changes == 0:
        return

    # Load existing graph data
    existing_nodes = store.load_nodes()
    existing_edges = store.load_edges()
    node_adapter = TypeAdapter(list[GraphNode])
    edge_adapter = TypeAdapter(list[GraphEdge])

    current_nodes = node_adapter.validate_python(existing_nodes)
    current_edges = edge_adapter.validate_python(existing_edges)

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

    # 2. Re-index changed and added files
    files_to_reindex: list[Path] = []
    for rel in status_result.changed_files + status_result.added_files:
        p = root_path / rel
        if p.exists():
            files_to_reindex.append(p)

    if files_to_reindex:
        typer.echo(f"Re-indexing {len(files_to_reindex)} file(s)...")
        new_nodes, new_edges = build_index_from_paths(root_path, files_to_reindex)
        current_nodes.extend(new_nodes)
        current_edges.extend(new_edges)
        typer.echo(f"  Added {len(new_nodes)} symbols, {len(new_edges)} relationships.")

    # 3. Save updated artifacts
    _save_index_artifacts(output_dir, current_nodes, current_edges, root_path, no_sqlite)

    typer.echo(f"Updated index written to {output_dir / 'graph.json'}")
    typer.echo(f"  Total files:   {len({n.file_path for n in current_nodes})}")
    typer.echo(f"  Total symbols:  {len(current_nodes)}")
    typer.echo(f"  Total edges:    {len(current_edges)}")


# ── status command ────────────────────────────────────────────────────


@app.command()
def status(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (auto-detected from cwd if omitted)",
    ),
) -> None:
    """Check the freshness of the code graph index."""
    root_path = Path(root).resolve() if root else Path.cwd()
    output_dir = root_path / ".codegraph"

    if not (output_dir / "metadata.json").exists():
        typer.echo("Index status: missing")
        typer.echo("")
        typer.echo("No .codegraph index found. Run:")
        typer.echo(f"  codegraph index {root_path}")
        return

    store = FileStore(output_dir)
    metadata = store.load_metadata()
    result = detect_status(root_path, metadata)

    typer.echo(f"Index status: {result.status}")
    if result.indexed_at:
        typer.echo(f"  Indexed at: {result.indexed_at}")

    if result.status == "fresh":
        typer.echo("  No changes detected.")
        return

    if result.status == "stale":
        if result.changed_files:
            typer.echo(f"Changed files:")
            for f in result.changed_files:
                typer.echo(f"  - {f}")
        if result.added_files:
            typer.echo(f"Added files:")
            for f in result.added_files:
                typer.echo(f"  + {f}")
        if result.deleted_files:
            typer.echo(f"Deleted files:")
            for f in result.deleted_files:
                typer.echo(f"  x {f}")
        typer.echo("")
        typer.echo(result.recommendation)


# ── search command ────────────────────────────────────────────────────


@app.command()
def search(
    query: str = typer.Argument(
        ..., help="Search keyword for symbols",
    ),
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (auto-detected from cwd if omitted)",
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """Search for code symbols across the indexed codebase."""
    store, _ = _load_store(root)
    result_dict = graph_query.search_symbols(store, query)
    items = result_dict.get("results", []) if isinstance(result_dict, dict) else result_dict
    total = result_dict.get("total", len(items)) if isinstance(result_dict, dict) else len(items)

    if not items:
        typer.echo("No results found.")
        return

    if json_output:
        import json
        typer.echo(json.dumps(result_dict, indent=2, ensure_ascii=False))
        return

    typer.echo(f"Found {total} result(s) for '{query}':\n")
    for r in items[:30]:
        score_display = f"{r['score']:.1f}" if r.get("score") else "?"
        sources = ", ".join(r.get("match_sources", []))
        typer.echo(f"  [{score_display}] {r['symbol_id']}")
        typer.echo(f"       type: {r['type']}  file: {r['file_path']}")
        if sources:
            typer.echo(f"       match: {sources}")
        typer.echo()

    if total > 30:
        typer.echo(f"  ... and {total - 30} more.")


# ── explain command ───────────────────────────────────────────────────


@app.command()
def explain(
    symbol: str = typer.Argument(
        ..., help="Symbol ID (file.py::func) or name to explain",
    ),
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (auto-detected from cwd if omitted)",
    ),
    depth: int = typer.Option(
        2, "--depth", "-d",
        help="Call chain depth",
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """Explain a symbol's call relationships."""
    store, _ = _load_store(root)
    node = _find_node(store, symbol)

    if not node:
        typer.echo(f"Error: Symbol '{symbol}' not found in index.", err=True)
        raise typer.Exit(1)

    callers = graph_query.get_callers(store, node.id)
    callees = graph_query.get_callees(store, node.id)

    if json_output:
        import json
        typer.echo(json.dumps({
            "symbol_id": node.id,
            "name": node.name,
            "type": node.type.value,
            "file_path": node.file_path,
            "signature": node.signature,
            "callers": [{"node_id": c[0]} for c in callers],
            "callees": [{"node_id": c[0]} for c in callees],
        }, indent=2, ensure_ascii=False))
        return

    location = _format_location(node)
    typer.echo(f"Symbol: {node.name} ({_type_label(node.type)})")
    typer.echo(f"  ID:     {node.id}")
    typer.echo(f"  File:   {node.file_path}{location}")
    if node.signature:
        typer.echo(f"  Sig:    {node.signature}")
    if node.docstring:
        doc_first_line = node.docstring.split("\n")[0]
        typer.echo(f"  Doc:    {doc_first_line}")
    typer.echo()

    if callers:
        typer.echo(f"Callers ({len(callers)}):")
        for caller_id, _ in callers:
            caller_node = store.get_node(caller_id)
            if caller_node:
                caller_loc = _format_location(caller_node)
                typer.echo(f"  <- {caller_id}{caller_loc}")
            else:
                typer.echo(f"  <- {caller_id}")
    else:
        typer.echo("Callers: (none)")
    typer.echo()

    if callees:
        typer.echo(f"Callees ({len(callees)}):")
        for callee_id, _ in callees:
            callee_node = store.get_node(callee_id)
            if callee_node:
                callee_loc = _format_location(callee_node)
                typer.echo(f"  -> {callee_id}{callee_loc}")
            else:
                typer.echo(f"  -> {callee_id}")
    else:
        typer.echo("Callees: (none)")


# ── impact command ────────────────────────────────────────────────────


@app.command()
def impact(
    symbol: str = typer.Argument(
        ..., help="Symbol ID (file.py::func) or name to analyze",
    ),
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (auto-detected from cwd if omitted)",
    ),
    depth: int = typer.Option(
        2, "--depth", "-d",
        help="Transitive traversal depth",
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """Analyze the impact surface of modifying a symbol."""
    store, _ = _load_store(root)
    node = _find_node(store, symbol)

    if not node:
        typer.echo(f"Error: Symbol '{symbol}' not found in index.", err=True)
        raise typer.Exit(1)

    result = graph_impact.analyze_impact(store, node.id, depth=depth)

    if json_output:
        import json
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return

    risk = result.get("risk", {})
    level = risk.get("level", "unknown")
    typer.echo(f"Impact Analysis: {node.name}")
    typer.echo(f"  Symbol: {node.id}")
    typer.echo(f"  Risk:   {level.upper()}")
    for reason in risk.get("reasons", []):
        typer.echo(f"    - {reason}")
    typer.echo()

    affected = result.get("affected_symbols", [])
    if affected:
        typer.echo(f"Affected Symbols ({len(affected)}):")
        for s in affected:
            dist = s.get("distance", 0)
            marker = "  [DEF]" if dist == 0 else f"  [D{dist}]"
            imp_type = s.get("impact_type", "?")
            typer.echo(f"  {marker} {s['symbol_id']} ({imp_type})")
    else:
        typer.echo("Affected Symbols: (none)")
    typer.echo()

    files = result.get("affected_files", [])
    if files:
        typer.echo(f"Affected Files ({len(files)}):")
        for f in files:
            priority = f.get("priority", "medium")
            marker = "!!" if priority == "high" else " -"
            typer.echo(f"  {marker} {f['file_path']} [{priority}]")
            typer.echo(f"       {f['reason']}")

    # ── Recommendations ──────────────────────────────────────────
    recommendations = result.get("recommendations", [])
    if recommendations:
        typer.echo()
        typer.echo("Recommendations:")
        for i, rec in enumerate(recommendations, 1):
            typer.echo(f"  {i}. {rec}")

    # ── Warnings ─────────────────────────────────────────────────
    warnings = result.get("warnings", [])
    if warnings:
        typer.echo()
        typer.echo("Warnings:")
        for w in warnings:
            typer.echo(f"  ! {w}")


# ── context command ───────────────────────────────────────────────────


@app.command()
def context(
    task: str = typer.Argument(
        ..., help="Natural language task description",
    ),
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (auto-detected from cwd if omitted)",
    ),
    max_tokens: int = typer.Option(
        6000, "--max-tokens", "-t",
        help="Maximum token budget for context",
    ),
    depth: int = typer.Option(
        2, "--depth", "-d",
        help="Call chain traversal depth",
    ),
    no_tests: bool = typer.Option(
        False, "--no-tests",
        help="Skip test discovery",
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j",
        help="Output pack JSON to stdout",
    ),
) -> None:
    """Generate an Evidence Pack for a natural language task.

    This is the core command of CodeGraph Explorer. It analyzes the
    indexed code graph and produces a task-aware context package
    with entry points, call graph, impact analysis, reading plan,
    and agent instructions.
    """
    from codegraph.context.pack_builder import build_context_pack

    store, cg_dir = _load_store(root)
    output_dir = cg_dir / "context_packs"

    pack = build_context_pack(
        store=store,
        task_description=task,
        max_tokens=max_tokens,
        depth=depth,
        include_tests=not no_tests,
        output_dir=str(output_dir),
    )

    if json_output:
        import json
        typer.echo(json.dumps(json.loads(pack.model_dump_json(exclude_none=True)), indent=2))
        return

    typer.echo(f"Evidence Pack: {pack.pack_id}")
    typer.echo(f"  Task:         {pack.task.raw_request[:60]}{'...' if len(pack.task.raw_request) > 60 else ''}")
    typer.echo(f"  Intent:       {pack.task.intent.value}")
    typer.echo(f"  Entry Points: {len(pack.entry_points)}")
    typer.echo(f"  Related:      {len(pack.related_symbols)}")
    typer.echo(f"  Call Graph:   {len(pack.call_graph.nodes)} nodes, {len(pack.call_graph.edges)} edges")
    typer.echo(f"  Selected Ctx: {len(pack.selected_context)} items")
    tb = pack.token_budget
    typer.echo(f"  Token Budget: {tb.get('used_tokens', 0)}/{tb.get('max_tokens', 0)} used")
    if pack.impact.changed_symbol:
        risk_level = pack.impact.risk.level.value if hasattr(pack.impact.risk.level, 'value') else pack.impact.risk.level
        typer.echo(f"  Risk Level:   {risk_level}")
    if pack.exports.markdown_path:
        typer.echo(f"  Markdown:     {pack.exports.markdown_path}")
    if pack.exports.json_path:
        typer.echo(f"  JSON:         {pack.exports.json_path}")
    typer.echo()

    if pack.entry_points:
        typer.echo("Entry Points:")
        for ep in pack.entry_points[:5]:
            typer.echo(f"  [{ep.score:.2f}] {ep.symbol_id}")
            typer.echo(f"         {ep.reason}")
        typer.echo()

    if pack.selected_context:
        typer.echo("Selected Context:")
        for sc in pack.selected_context[:6]:
            typer.echo(f"  [{sc.priority}] {sc.symbol_id or sc.context_id} ({sc.relation})")
        typer.echo()

    if pack.warnings:
        typer.echo("Warnings:")
        for w in pack.warnings:
            typer.echo(f"  ! {w}")


# ── dashboard command ─────────────────────────────────────────────────


@app.command()
def dashboard(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (optional, auto-detected from cwd)",
    ),
    port: int = typer.Option(
        8765, "--port", "-p",
        help="Dashboard server port",
    ),
    host: str = typer.Option(
        "127.0.0.1", "--host",
        help="Bind address",
    ),
    open_browser: bool = typer.Option(
        True, "--open/--no-open",
        help="Auto-open browser on startup",
    ),
    dev: bool = typer.Option(
        False, "--dev",
        help="Start in dev mode (no frontend build required, uses Vite proxy)",
    ),
) -> None:
    """Start the local Dashboard (FastAPI backend + React frontend).

    Launches the FastAPI server with the built frontend or in dev mode.
    Default address: http://localhost:8765
    """
    import subprocess
    import sys
    import time
    import webbrowser

    # Check whether .codegraph exists
    cg_dir = _find_codegraph_dir(root)
    if cg_dir is None:
        typer.echo(
            "Warning: No .codegraph directory found. "
            "Run 'codegraph index <project>' first to enable full functionality.",
            err=True,
        )

    # ── Start server in a subprocess ─────────────────────────────────
    typer.echo(f"Starting CodeGraph Dashboard at http://{host}:{port} ...")

    env = dict(
        _ROOT_DIR=str(Path.cwd()),
        _DEV_MODE="1" if dev else "0",
    )
    if root:
        env["_PROJECT_ROOT"] = str(Path(root).resolve())

    merged_env = {**os.environ, **env}

    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "codegraph.api.main:app",
         "--host", host, "--port", str(port),
         "--log-level", "info"],
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # Give the server a moment to start
    time.sleep(1.5)

    url = f"http://{host}:{port}"

    if open_browser:
        webbrowser.open(url)

    typer.echo(f"\n  Dashboard: {url}")
    typer.echo(f"  API:       {url}/api/repo/summary")
    typer.echo("  Press Ctrl+C to stop.\n")

    # Stream server output until interrupted
    try:
        for line in server_process.stdout or []:
            print(line.decode("utf-8", errors="replace"), end="")
    except KeyboardInterrupt:
        typer.echo("\nShutting down...")
    finally:
        server_process.terminate()
        server_process.wait()


# ── watch command ────────────────────────────────────────────────────────


@app.command()
def watch(
    root: str = typer.Argument(
        ..., help="Root path of the project to watch",
    ),
    debounce_ms: int = typer.Option(
        500, "--debounce-ms", "-d",
        help="Debounce delay in milliseconds for batching file changes",
    ),
    poll_interval: float = typer.Option(
        2.0, "--poll-interval", "-p",
        help="Polling interval in seconds (only used when watchdog is unavailable)",
    ),
) -> None:
    """Watch the project for file changes and auto-update the index.

    Monitors Python files and config files for changes, additions, and
    deletions. When changes are detected, automatically runs an incremental
    index update after a debounce period.

    Requires the 'watch' extra for optimal performance:
        pip install -e "backend[watch]"

    Without watchdog, falls back to polling mode.
    """
    from codegraph.indexer.watch import run_watch_loop

    root_path = Path(root).resolve()
    if not root_path.is_dir():
        typer.echo(f"Error: {root} is not a valid directory", err=True)
        raise typer.Exit(1)

    # Check if .codegraph/index exists, warn if not
    cg_dir = root_path / ".codegraph"
    if not (cg_dir / "metadata.json").exists():
        typer.echo(
            "Warning: No existing index found. Watch will start but "
            "auto-sync requires a full index first:\n"
            f"  codegraph index {root_path}",
            err=True,
        )

    run_watch_loop(root_path, debounce_ms=debounce_ms, poll_interval=poll_interval)


# ── mcp command ──────────────────────────────────────────────────────────


@app.command()
def mcp(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (auto-detected from cwd if omitted, "
             "or set CODEGRAPH_PROJECT_ROOT env var)",
    ),
    watch: bool = typer.Option(
        False, "--watch", "-w",
        help="Enable watch mode for automatic incremental index sync",
    ),
) -> None:
    """Start the MCP server for AI agent integration.

    Runs a Model Context Protocol server over stdio, exposing tools
    for AI coding agents (Claude Code, Cursor) to query the code graph.

    Requires the 'mcp' extra: pip install codegraph[mcp]

    Configure in Claude Code:
      .claude/settings.local.json:
        {"mcpServers": {"codegraph": {
          "command": "python",
          "args": ["-m", "codegraph.mcp_server"],
          "env": {"CODEGRAPH_PROJECT_ROOT": "/path/to/project"}
        }}}
    """
    from codegraph.mcp_server import main as mcp_main

    if root:
        os.environ["CODEGRAPH_PROJECT_ROOT"] = root
    if watch:
        os.environ["CODEGRAPH_WATCH"] = "1"

    mcp_main()


if __name__ == "__main__":
    app()
