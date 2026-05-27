"""CLI entry point for codegraph commands."""

from pathlib import Path
from datetime import datetime, timezone

import typer
from pydantic import TypeAdapter

from codegraph.graph.models import GraphNode, GraphEdge, CodeGraph, RepoInfo
from codegraph.indexer.graph_builder import build_index
from codegraph.storage.file_store import FileStore

app = typer.Typer(
    name="codegraph",
    help="CodeGraph Explorer - AI Agent-first code context tool",
)


@app.command()
def index(
    root: str = typer.Argument(
        ..., help="Root path of the codebase to index",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Re-index even if index already exists",
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

    store = FileStore(output_dir)
    node_adapter = TypeAdapter(list[GraphNode])
    edge_adapter = TypeAdapter(list[GraphEdge])
    store.save_nodes(node_adapter.dump_python(nodes))
    store.save_edges(edge_adapter.dump_python(edges))

    # Save full graph
    graph_path = output_dir / "graph.json"
    graph_path.write_text(
        graph.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )

    typer.echo(f"Index written to {output_dir / 'graph.json'}")
    typer.echo(f"  Files indexed: {graph.repo.file_count}")
    typer.echo(f"  Symbols:       {graph.repo.symbol_count}")
    typer.echo(f"  Edges:         {len(edges)}")


@app.command()
def context():
    """Generate a Context Pack for a natural language task."""
    typer.echo("Not yet implemented (Phase 3).")


@app.command()
def search():
    """Search for code symbols across the indexed codebase."""
    typer.echo("Not yet implemented (Phase 2).")


@app.command()
def explain():
    """Explain a symbol's call relationships."""
    typer.echo("Not yet implemented (Phase 2).")


@app.command()
def impact():
    """Analyze the impact surface of modifying a symbol."""
    typer.echo("Not yet implemented (Phase 2).")


@app.command()
def dashboard():
    """Start the local Dashboard (FastAPI backend + React frontend)."""
    typer.echo("Not yet implemented (Phase 5).")
