"""CLI entry point for codegraph commands."""

from pathlib import Path
from datetime import datetime, timezone

import typer
from pydantic import TypeAdapter

from codegraph.graph.models import GraphNode, GraphEdge, CodeGraph, RepoInfo, NodeType
from codegraph.graph.store import GraphStore
from codegraph.graph import query as graph_query
from codegraph.graph import impact as graph_impact
from codegraph.indexer.graph_builder import build_index
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


@app.command()
def index(
    root: str = typer.Argument(
        ..., help="Root path of the codebase to index",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Re-index even if index already exists",
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

    if not force and (output_dir / "nodes.json").exists():
        typer.echo("Index already exists. Use --force to re-index.")
        return

    typer.echo(f"Scanning {root_path} ...")
    nodes, edges = build_index(root_path)

    typer.echo(f"Found {len(nodes)} symbols and {len(edges)} relationships.")

    # Build the top-level graph container
    repo_name = root_path.name
    graph = CodeGraph(
        schema_version="1.0.0",
        repo=RepoInfo(
            repo_id=f"local:{repo_name}",
            name=repo_name,
            root_path=str(root_path),
            languages=["python"],
            indexed_at=datetime.now(timezone.utc).isoformat(),
            file_count=len({n.file_path for n in nodes}),
            symbol_count=len(nodes),
        ),
        nodes=nodes,
        edges=edges,
    )

    # JSON file output
    store = FileStore(output_dir)
    node_adapter = TypeAdapter(list[GraphNode])
    edge_adapter = TypeAdapter(list[GraphEdge])
    store.save_nodes(node_adapter.dump_python(nodes))
    store.save_edges(edge_adapter.dump_python(edges))

    # Full graph output
    graph_path = output_dir / "graph.json"
    graph_path.write_text(
        graph.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )

    typer.echo(f"Index written to {output_dir / 'graph.json'}")
    typer.echo(f"  Files indexed: {graph.repo.file_count}")
    typer.echo(f"  Symbols:       {graph.repo.symbol_count}")
    typer.echo(f"  Edges:         {len(edges)}")

    # SQLite output
    if not no_sqlite:
        try:
            sqlite_path = output_dir / "index.sqlite"
            sql_store = SqliteStore(sqlite_path)
            sql_store.initialize()
            sql_store.save_nodes(node_adapter.dump_python(nodes))
            sql_store.save_edges(edge_adapter.dump_python(edges))
            sql_store.close()
            typer.echo(f"  SQLite:        {sqlite_path}")
        except Exception as e:
            typer.echo(f"  SQLite warning: {e}", err=True)


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
    results = graph_query.search_symbols(store, query)

    if not results:
        typer.echo("No results found.")
        return

    if json_output:
        import json
        typer.echo(json.dumps(results, indent=2, ensure_ascii=False))
        return

    typer.echo(f"Found {len(results)} result(s) for '{query}':\n")
    for r in results[:30]:
        score_display = f"{r['score']:.1f}" if r["score"] else "?"
        sources = ", ".join(r.get("match_sources", []))
        typer.echo(f"  [{score_display}] {r['symbol_id']}")
        typer.echo(f"       type: {r['type']}  file: {r['file_path']}")
        if sources:
            typer.echo(f"       match: {sources}")
        typer.echo()

    if len(results) > 30:
        typer.echo(f"  ... and {len(results) - 30} more.")


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


# ── context command ───────────────────────────────────────────────────


@app.command()
def context():
    """Generate a Context Pack for a natural language task."""
    typer.echo("Not yet implemented (Phase 3).")


# ── dashboard command ─────────────────────────────────────────────────


@app.command()
def dashboard():
    """Start the local Dashboard (FastAPI backend + React frontend)."""
    typer.echo("Not yet implemented (Phase 5).")


if __name__ == "__main__":
    app()
