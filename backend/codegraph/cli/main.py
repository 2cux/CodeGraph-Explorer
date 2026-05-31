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
            "Error: No .codegraph directory found. Run 'codegraph init' first.",
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
def init(
    root: str = typer.Argument(
        ".", help="Root path of the codebase to index (defaults to current directory)",
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
    """Initialize local code graph index. One-time setup, then MCP Server and Dashboard work directly.

    This scans the codebase, parses AST, and builds the code graph index.
    Once initialized, MCP Server and Dashboard can consume the index immediately.
    """
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


@app.command(name="index", hidden=True)
def index_cmd(
    root: str = typer.Argument(
        ".", help="Root path of the codebase to index (defaults to current directory)",
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
    """Backward-compatible alias for 'init'. Use 'codegraph init' instead."""
    init(root=root, force=force, incremental=incremental, no_sqlite=no_sqlite)


@app.command()
def update() -> None:
    """Update CodeGraph Explorer to the latest version.

    Re-installs the 'codegraph' package from the current source directory,
    preserving existing MCP configurations and index files.
    """
    import subprocess
    import sys

    # Find the package root (where pyproject.toml lives)
    try:
        import codegraph
        pkg_dir = Path(__import__('codegraph').__file__).parent.parent.resolve()
    except Exception:
        typer.echo("Error: Could not locate codegraph package directory.", err=True)
        raise typer.Exit(1)

    if not (pkg_dir / "pyproject.toml").exists():
        typer.echo(
            "Error: codegraph does not appear to be installed in editable mode.\n"
            "To update, re-clone and re-install:\n"
            "  git clone <repo-url>\n"
            "  cd CodeGraph-Explorer\n"
            "  pip install -e \"backend[mcp,watch]\"",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(f"Updating codegraph from {pkg_dir} ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", f"{pkg_dir}[mcp,watch]"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        typer.echo("CodeGraph Explorer updated successfully.")
        typer.echo("MCP configurations and index files are preserved.")
    else:
        typer.echo(f"Update failed:\n{result.stderr}", err=True)
        raise typer.Exit(1)


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
        typer.echo(f"  codegraph init")
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
        typer.echo(f"  codegraph init")
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
def api(
    root: str = typer.Option(
        ..., "--root", "-r",
        help="Project root path (required)",
    ),
    host: str = typer.Option(
        "127.0.0.1", "--host",
        help="Bind address",
    ),
    port: int = typer.Option(
        8000, "--port", "-p",
        help="API server port",
    ),
) -> None:
    """Start the CodeGraph API server (backend only, no frontend).

    Reads the .codegraph index from the specified project root.
    Use 'codegraph dashboard' to start both API + frontend together.

    Examples:
        codegraph api --root .
        codegraph api --root /path/to/project --port 8000
    """
    import subprocess
    import sys

    root_path = Path(root).resolve()
    if not root_path.is_dir():
        typer.echo(f"Error: {root} is not a valid directory", err=True)
        raise typer.Exit(1)

    cg_dir = root_path / ".codegraph"
    if not (cg_dir / "graph.json").exists():
        typer.echo("No CodeGraph index found. Run: codegraph init")

    typer.echo(f"CodeGraph API starting at http://{host}:{port}")
    typer.echo(f"Project: {root_path}")
    typer.echo(f"API docs: http://{host}:{port}/docs")
    typer.echo("Press Ctrl+C to stop.\n")

    env = {
        **os.environ,
        "CODEGRAPH_PROJECT_ROOT": str(root_path),
    }

    args = [
        sys.executable, "-m", "uvicorn", "codegraph.api.main:app",
        "--host", host, "--port", str(port),
        "--log-level", "warning",
    ]

    try:
        subprocess.run(args, env=env)
    except KeyboardInterrupt:
        typer.echo("\nShutting down...")


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
            "Run 'codegraph init <project>' first to enable full functionality.",
            err=True,
        )

    # ── Start server in a subprocess ─────────────────────────────────
    typer.echo(f"Starting CodeGraph Dashboard at http://{host}:{port} ...")

    env: dict[str, str] = {
        "_DEV_MODE": "1" if dev else "0",
    }
    if root:
        env["CODEGRAPH_PROJECT_ROOT"] = str(Path(root).resolve())

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
            f"  codegraph init {root_path}",
            err=True,
        )

    run_watch_loop(root_path, debounce_ms=debounce_ms, poll_interval=poll_interval)


# ── mcp command (debug) ──────────────────────────────────────────────────


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
    """[Debug] Start the MCP server directly over stdio.

    Prefer ``codegraph serve --mcp`` for normal use — it includes startup
    validation and clear error messages. This command is a debug shortcut
    that launches the MCP server without validation.
    """
    from codegraph.mcp_server import main as mcp_main

    if root:
        os.environ["CODEGRAPH_PROJECT_ROOT"] = root
    if watch:
        os.environ["CODEGRAPH_WATCH"] = "1"

    mcp_main()


# ── serve command ──────────────────────────────────────────────────────


def _validate_serve_env(root_path: str | None) -> Path:
    """Validate the environment for ``serve --mcp`` startup.

    Checks CODEGRAPH_PROJECT_ROOT, directory existence, .codegraph presence,
    and index file completeness. Returns the resolved project root Path.

    Exits with a clear message on any failure (no traceback).
    """
    # Resolve project root
    env_root = os.environ.get("CODEGRAPH_PROJECT_ROOT", "")
    cli_root = root_path

    if cli_root:
        resolved = Path(cli_root).resolve()
    elif env_root:
        resolved = Path(env_root).resolve()
    else:
        # Walk up from CWD to find .codegraph
        cg_dir = _find_codegraph_dir(None)
        if cg_dir is not None:
            resolved = cg_dir.parent.resolve()
        else:
            resolved = Path.cwd().resolve()

    # Check 1: path exists
    if not resolved.exists():
        typer.echo(
            f"ERROR: Project root does not exist.\n"
            f"  Path: {resolved}\n"
            f"  Run:  mkdir -p {resolved}",
            err=True,
        )
        raise typer.Exit(1)

    # Check 2: path is a directory
    if not resolved.is_dir():
        typer.echo(
            f"ERROR: Project root is not a directory.\n"
            f"  Path: {resolved}",
            err=True,
        )
        raise typer.Exit(1)

    cg_dir = resolved / ".codegraph"

    # Check 3: .codegraph directory exists
    if not cg_dir.exists():
        typer.echo(
            f"No CodeGraph index found.\n"
            f"Project root: {resolved}\n"
            f"Run:\n"
            f"  cd {resolved}\n"
            f"  codegraph init",
            err=True,
        )
        raise typer.Exit(1)

    # Check 4: index files are complete
    missing_files: list[str] = []
    for fname in ("graph.json", "nodes.json", "edges.json", "metadata.json"):
        if not (cg_dir / fname).exists():
            missing_files.append(fname)

    if missing_files:
        typer.echo(
            f"CodeGraph index is incomplete — missing files: {', '.join(missing_files)}\n"
            f"Project root: {resolved}\n"
            f"Run:\n"
            f"  cd {resolved}\n"
            f"  codegraph init --force",
            err=True,
        )
        raise typer.Exit(1)

    return resolved


@app.command()
def serve(
    mcp_flag: bool = typer.Option(
        False, "--mcp",
        help="Start as MCP server over stdio (for AI agent integration)",
    ),
    check: bool = typer.Option(
        False, "--check",
        help="Only validate environment, do not start the server",
    ),
    watch: bool = typer.Option(
        False, "--watch", "-w",
        help="Enable watch mode for automatic incremental index sync",
    ),
) -> None:
    """Start the CodeGraph server.

    With --mcp: start MCP server over stdio for AI agent integration.
    This is the command written into MCP config by ``codegraph configure``.

    With --mcp --check: validate the environment and exit without starting.
    Use this to diagnose MCP startup issues.

    Examples:
        codegraph serve --mcp
        codegraph serve --mcp --check
    """
    if not mcp_flag:
        typer.echo("Usage: codegraph serve --mcp", err=True)
        typer.echo("")
        typer.echo("  --mcp    Start MCP server over stdio (for AI agent integration)")
        typer.echo("  --check  Validate environment only, do not start the server")
        typer.echo("  --watch  Enable watch mode for automatic incremental index sync")
        typer.echo("")
        typer.echo("This command is normally invoked by MCP clients (Claude Code, Cursor)")
        typer.echo("via the config written by ``codegraph configure``.")
        raise typer.Exit(1)

    root_path: str | None = None
    if os.environ.get("CODEGRAPH_PROJECT_ROOT"):
        root_path = os.environ["CODEGRAPH_PROJECT_ROOT"]

    project_root = _validate_serve_env(root_path)

    if check:
        # Check mode: validate and exit
        typer.echo("CodeGraph MCP check passed.")
        typer.echo(f"  Project root:  {project_root}")
        typer.echo(f"  Index path:    {project_root / '.codegraph'}")
        metadata_path = project_root / ".codegraph" / "metadata.json"
        if metadata_path.exists():
            from codegraph.graph.models import IndexMetadata
            try:
                meta = IndexMetadata.model_validate_json(metadata_path.read_text("utf-8"))
                typer.echo(f"  Indexed at:    {meta.indexed_at}")
                typer.echo(f"  Symbols:       {meta.symbol_count}")
                typer.echo(f"  Edges:         {meta.edge_count}")
                typer.echo(f"  Files:         {meta.file_count}")
            except Exception:
                pass
        return

    # Set env for the MCP server subprocess
    os.environ["CODEGRAPH_PROJECT_ROOT"] = str(project_root)
    if watch:
        os.environ["CODEGRAPH_WATCH"] = "1"

    from codegraph.mcp_server import main as mcp_main
    mcp_main()


# ── doctor command ──────────────────────────────────────────────────────


@app.command()
def doctor(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root to check (defaults to CODEGRAPH_PROJECT_ROOT or CWD)",
    ),
) -> None:
    """Diagnose CodeGraph setup and report any issues.

    Checks: CLI availability, Python version, package path, project root,
    .codegraph presence, index status, MCP config paths, and serve --mcp
    readiness.
    """
    import sys
    import platform
    import importlib.util

    def ok(msg: str) -> None:
        typer.echo(f"  [OK]    {msg}")

    def warn(msg: str) -> None:
        typer.echo(f"  [WARN]  {msg}")

    def fail(msg: str) -> None:
        typer.echo(f"  [FAIL]  {msg}")

    typer.echo("CodeGraph Doctor")
    typer.echo("=" * 50)
    typer.echo()

    # 1. CLI availability
    typer.echo("1. CLI availability")
    try:
        import codegraph
        ok(f"codegraph package importable (version: {getattr(codegraph, '__version__', 'unknown')})")
    except ImportError:
        fail("codegraph package not importable — reinstall with: pip install -e \"backend[mcp,watch]\"")
    typer.echo()

    # 2. Python version
    typer.echo("2. Python version")
    py_version = sys.version_info
    if py_version >= (3, 10):
        ok(f"Python {platform.python_version()} ({sys.executable})")
    else:
        fail(f"Python {platform.python_version()} — need 3.10+")
    typer.echo()

    # 3. Package path
    typer.echo("3. Package path")
    spec = importlib.util.find_spec("codegraph")
    if spec and spec.origin:
        pkg_path = Path(spec.origin).parent.parent
        ok(str(pkg_path))
    else:
        warn("Could not determine package path")
    typer.echo()

    # 4. Project root
    typer.echo("4. Project root")
    if root:
        project_root = Path(root).resolve()
    elif os.environ.get("CODEGRAPH_PROJECT_ROOT"):
        project_root = Path(os.environ["CODEGRAPH_PROJECT_ROOT"]).resolve()
    else:
        # Try auto-detect
        cg_dir = _find_codegraph_dir(None)
        project_root = cg_dir.parent.resolve() if cg_dir else Path.cwd().resolve()

    if project_root.exists() and project_root.is_dir():
        ok(str(project_root))
    else:
        fail(f"{project_root} — path does not exist or is not a directory")
    typer.echo()

    # 5. .codegraph presence & index status
    typer.echo("5. Index status")
    cg_dir = project_root / ".codegraph"
    if not cg_dir.exists():
        fail(f" No .codegraph directory in {project_root}")
        typer.echo(f"     Run: cd {project_root} && codegraph init")
        typer.echo()
    else:
        ok(f".codegraph found in {project_root}")
        # Check each index file
        index_files = {
            "graph.json": (cg_dir / "graph.json").exists(),
            "nodes.json": (cg_dir / "nodes.json").exists(),
            "edges.json": (cg_dir / "edges.json").exists(),
            "metadata.json": (cg_dir / "metadata.json").exists(),
            "index.sqlite": (cg_dir / "index.sqlite").exists(),
        }
        all_present = all(index_files.values())
        missing = [k for k, v in index_files.items() if not v]
        if all_present:
            ok("All index files present")
        else:
            fail(f"Missing index files: {', '.join(missing)}")
            typer.echo(f"     Run: cd {project_root} && codegraph init --force")

        # Print stats from metadata if available
        if index_files["metadata.json"]:
            from codegraph.graph.models import IndexMetadata
            try:
                meta = IndexMetadata.model_validate_json(
                    (cg_dir / "metadata.json").read_text("utf-8")
                )
                typer.echo(f"     Indexed:  {meta.indexed_at}")
                typer.echo(f"     Symbols:  {meta.symbol_count}")
                typer.echo(f"     Edges:    {meta.edge_count}")
                typer.echo(f"     Files:    {meta.file_count}")
            except Exception:
                pass

        # Freshness check
        if index_files["metadata.json"] and index_files["graph.json"]:
            store = FileStore(cg_dir)
            metadata = store.load_metadata()
            if metadata:
                result = detect_status(project_root, metadata)
                if result.status == "fresh":
                    ok("Index is fresh")
                elif result.status == "stale":
                    warn(f"Index is stale — {result.total_changes} file(s) changed")
                    typer.echo(f"     Run: codegraph init --incremental")
        typer.echo()

    # 6. MCP config paths
    typer.echo("6. MCP configuration")
    from codegraph.configure import (
        CLAUDE_USER_CONFIG, CURSOR_USER_CONFIG,
        read_config, MCP_SERVER_NAME,
    )

    config_paths = [
        ("Claude Code (user)", CLAUDE_USER_CONFIG),
        ("Cursor (user)", CURSOR_USER_CONFIG),
    ]
    configured_any = False
    for label, cfg_path in config_paths:
        data = read_config(cfg_path)
        server_cfg = data.get("mcpServers", {}).get(MCP_SERVER_NAME)
        if server_cfg:
            configured_any = True
            cmd = server_cfg.get("command", "?")
            args = server_cfg.get("args", [])
            has_env = "env" in server_cfg and "CODEGRAPH_PROJECT_ROOT" in server_cfg.get("env", {})
            root_str = server_cfg.get("env", {}).get("CODEGRAPH_PROJECT_ROOT", "auto-detect")
            ok(f"{label}: configured ({' '.join([cmd] + args)}, root={root_str})")
        else:
            warn(f"{label}: not configured ({cfg_path})")
    if not configured_any:
        typer.echo("     Run: codegraph configure all")
    typer.echo()

    # 7. serve --mcp readiness
    typer.echo("7. serve --mcp readiness")
    try:
        _validate_serve_env(str(project_root))
        ok("serve --mcp can start")
    except typer.Exit:
        fail("serve --mcp would fail — see errors above")


# ── configure command group ──────────────────────────────────────────────

configure_app = typer.Typer(
    name="configure",
    help="Configure MCP server integration for AI coding agents (Claude Code, Cursor)",
)
app.add_typer(configure_app)


def _print_configure_result(result: dict) -> None:
    """Print a single configure_target / remove_target result."""
    status = result["status"]
    target = result["target"]
    filepath = result["filepath"]
    if status == "configured":
        typer.echo(f"  [CONFIGURED] {target} -> {filepath}")
    elif status == "overwritten":
        typer.echo(f"  [UPDATED]    {target} -> {filepath}")
    elif status == "removed":
        typer.echo(f"  [REMOVED]    {target} from {filepath}")
    elif status == "not_configured":
        typer.echo(f"  [SKIP]       {target}: not configured in {filepath}")
    else:
        typer.echo(f"  [SKIP]       {target}: already configured")
        typer.echo(f"               Use --force to update CODEGRAPH_PROJECT_ROOT.")


@configure_app.command(name="all")
def configure_all(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Set CODEGRAPH_PROJECT_ROOT env var in config (omit for CWD auto-detection)",
    ),
    python_command: str = typer.Option(
        None, "--command", "-c",
        help="Python interpreter path (default: current interpreter)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Overwrite existing configuration",
    ),
    project: bool = typer.Option(
        False, "--project", "-p",
        help="Write to project-level config (./.mcp.json, ./.cursor/mcp.json) instead of user-level",
    ),
) -> None:
    """Configure both Claude Code and Cursor MCP servers (user-level by default).

    This is the recommended one-time setup command. It writes MCP server
    configuration so that Claude Code and Cursor can automatically discover
    and use CodeGraph Explorer on every project.

    Examples:
        codegraph configure all
        codegraph configure all --force
        codegraph configure all --root /path/to/project
        codegraph configure all --project
    """
    from codegraph.configure import configure_target, ConfigTarget

    results = []
    for target in (ConfigTarget.CLAUDE, ConfigTarget.CURSOR):
        result = configure_target(
            target,
            root=root,
            python_command=python_command,
            project=project,
            force=force,
        )
        results.append(result)

    typer.echo("\nCodeGraph MCP configuration:\n")
    all_already = all(r["status"] == "already_configured" for r in results)
    for r in results:
        _print_configure_result(r)

    typer.echo()

    if all_already and not force:
        typer.echo("Existing CodeGraph MCP config found.")
        typer.echo("Use --force to update CODEGRAPH_PROJECT_ROOT.\n")
    else:
        typer.echo("Configured CodeGraph MCP.\n")
        typer.echo("Next:")
        typer.echo("  cd your-project")
        typer.echo("  codegraph init")
        typer.echo("  codegraph doctor")
        typer.echo("  Restart Claude Code / Cursor.")
        typer.echo()


@configure_app.command(name="claude")
def configure_claude(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Set CODEGRAPH_PROJECT_ROOT env var in config",
    ),
    python_command: str = typer.Option(
        None, "--command", "-c",
        help="Python interpreter path (default: current interpreter)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Overwrite existing configuration",
    ),
    project: bool = typer.Option(
        False, "--project", "-p",
        help="Write to project-level config (./.mcp.json) instead of user-level",
    ),
) -> None:
    """Configure Claude Code MCP server only (user-level by default).

    Examples:
        codegraph configure claude
        codegraph configure claude --project
        codegraph configure claude --root /path/to/project
    """
    from codegraph.configure import configure_target, ConfigTarget

    result = configure_target(
        ConfigTarget.CLAUDE,
        root=root,
        python_command=python_command,
        project=project,
        force=force,
    )
    _print_configure_result(result)


@configure_app.command(name="cursor")
def configure_cursor(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Set CODEGRAPH_PROJECT_ROOT env var in config",
    ),
    python_command: str = typer.Option(
        None, "--command", "-c",
        help="Python interpreter path (default: current interpreter)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Overwrite existing configuration",
    ),
    project: bool = typer.Option(
        False, "--project", "-p",
        help="Write to project-level config (./.cursor/mcp.json) instead of user-level",
    ),
) -> None:
    """Configure Cursor MCP server only (user-level by default).

    Examples:
        codegraph configure cursor
        codegraph configure cursor --project
        codegraph configure cursor --root /path/to/project
    """
    from codegraph.configure import configure_target, ConfigTarget

    result = configure_target(
        ConfigTarget.CURSOR,
        root=root,
        python_command=python_command,
        project=project,
        force=force,
    )
    _print_configure_result(result)


@configure_app.command(name="show")
def configure_show(
    project: bool = typer.Option(
        False, "--project", "-p",
        help="Show project-level config status instead of user-level",
    ),
) -> None:
    """Display current MCP configuration status for all targets."""
    from codegraph.configure import show_status

    status = show_status(project=project)
    for target_name in ("claude", "cursor"):
        info = status[target_name]
        if info["configured"]:
            cfg = info["config"] or {}
            has_root = "env" in cfg and "CODEGRAPH_PROJECT_ROOT" in cfg.get("env", {})
            typer.echo(f"[CONFIGURED] {target_name}")
            typer.echo(f"  File:    {info['filepath']}")
            typer.echo(f"  Command: {cfg.get('command', '?')}")
            if has_root:
                typer.echo(f"  Root:    {cfg['env']['CODEGRAPH_PROJECT_ROOT']}")
            else:
                typer.echo("  Root:    auto-detect (CWD)")
        else:
            typer.echo(f"[NOT CONFIGURED] {target_name}")
            typer.echo(f"  File:    {info['filepath']}")
        typer.echo()


@configure_app.command(name="remove")
def configure_remove(
    target: str = typer.Argument(..., help="Target to remove: all, claude, or cursor"),
    project: bool = typer.Option(
        False, "--project", "-p",
        help="Remove from project-level config instead of user-level",
    ),
) -> None:
    """Remove MCP server configuration.

    Examples:
        codegraph configure remove all
        codegraph configure remove claude
        codegraph configure remove cursor --project
    """
    from codegraph.configure import remove_target, ConfigTarget

    if target not in ("all", "claude", "cursor"):
        typer.echo(f"Error: Invalid target '{target}'. Use: all, claude, cursor.", err=True)
        raise typer.Exit(1)

    targets: list[ConfigTarget]
    if target == "all":
        targets = [ConfigTarget.CLAUDE, ConfigTarget.CURSOR]
    else:
        targets = [ConfigTarget(target)]

    for t in targets:
        result = remove_target(t, project=project)
        _print_configure_result(result)


if __name__ == "__main__":
    app()
