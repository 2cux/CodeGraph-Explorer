"""CLI entry point for codegraph commands."""

import json
import os
import sys
import time as time_module
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
from codegraph.hooks.manager import HookManager
from codegraph.hooks.logger import get_hook_logger
from codegraph.indexer.graph_builder import build_index, build_index_from_paths
from codegraph.indexer.lock import IndexLock
from codegraph.indexer.scanner import scan_python_files, compute_fingerprint
from codegraph.indexer.status import detect_status, detect_status_with_classification, StatusResult, get_index_status
from codegraph.storage.file_store import FileStore
from codegraph.storage.sqlite_store import SqliteStore
from codegraph.storage.state_store import IndexStateStore
from codegraph.storage.writer import (
    write_full_index,
    write_incremental_update,
    repair_json_from_sqlite,
    SqliteWriteError,
)
from codegraph.storage.integrity import check_storage_integrity

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
    """Load the graph into a GraphStore, preferring SQLite over JSON.

    Returns (store, codegraph_dir).
    """
    cg_dir = _find_codegraph_dir(root)
    if cg_dir is None:
        typer.echo(
            "Error: No .codegraph directory found. Run 'codegraph init' first.",
            err=True,
        )
        raise typer.Exit(1)

    sqlite_path = cg_dir / "index.sqlite"
    store = GraphStore()
    if sqlite_path.exists():
        try:
            sql_store = SqliteStore(sqlite_path)
            sql_store.initialize()
            node_adapter = TypeAdapter(list[GraphNode])
            edge_adapter = TypeAdapter(list[GraphEdge])
            store.load_from_lists(
                node_adapter.validate_python(sql_store.load_all_nodes()),
                edge_adapter.validate_python(sql_store.load_all_edges()),
            )
            sql_store.close()
            return store, cg_dir
        except Exception:
            pass

    graph_path = cg_dir / "graph.json"
    try:
        graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
    except Exception as e:
        typer.echo(f"Error: Failed to load {graph_path}: {e}", err=True)
        raise typer.Exit(1)

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


def _maybe_install_hook(
    root_path: Path,
    no_hook: bool,
    state_store: IndexStateStore,
    force: bool = False,
) -> None:
    """Auto-install the git post-commit hook after a successful init.

    Checks whether the project is a git repo, whether auto-update is enabled,
    and whether the hook is already installed.
    """
    if no_hook:
        return

    # Check auto_update_on_commit config
    hook_config = state_store.get_hook_config()
    if not hook_config.get("auto_update_on_commit", True):
        return

    # Check if this is a git repo
    git_dir = HookManager._find_git_dir(root_path)
    if git_dir is None:
        return

    # Check if hook already installed
    hook_path = git_dir / "hooks" / "post-commit"
    if hook_path.exists():
        content = hook_path.read_text(encoding="utf-8")
        from codegraph.hooks.template import SENTINEL_START
        if SENTINEL_START in content and not force:
            return  # Already installed, nothing to do

    # Install the hook
    result = HookManager.install(root_path, force=force)
    if result["installed"]:
        typer.echo()
        typer.echo(
            f"> Post-commit hook {result['action']}. "
            f"Index will auto-update after each commit."
        )
        typer.echo(
            "> Disable with: codegraph config set auto_update_on_commit false"
        )


# ── index command ────────────────────────────────────────────────────


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
        help="Skip SQLite output (JSON-only fallback)",
    ),
    no_hook: bool = typer.Option(
        False, "--no-hook",
        help="Skip installing the git post-commit auto-update hook",
    ),
) -> None:
    """Initialize local code graph index. One-time setup, then MCP Server works directly.

    This scans the codebase, parses AST, and builds the code graph index.
    Once initialized, MCP Server can consume the index immediately.

    By default, a git post-commit hook is also installed to keep the index
    updated automatically after every commit. Use --no-hook to opt out.
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        typer.echo(f"Error: {root} is not a valid directory", err=True)
        raise typer.Exit(1)

    output_dir = root_path / ".codegraph"
    output_dir.mkdir(parents=True, exist_ok=True)

    state_store = IndexStateStore(output_dir)

    if incremental:
        _run_incremental_index(root_path, output_dir, no_sqlite, state_store)
        _maybe_install_hook(root_path, no_hook, state_store)
        return

    if not force and (output_dir / "nodes.json").exists():
        typer.echo("Index already exists. Use --force to re-index.")
        _maybe_install_hook(root_path, no_hook, state_store)
        return

    typer.echo(f"Scanning {root_path} ...")
    nodes, edges = build_index(root_path)

    typer.echo(f"Found {len(nodes)} symbols and {len(edges)} relationships.")

    try:
        counts = write_full_index(
            output_dir, nodes, edges, root_path,
            no_sqlite=no_sqlite, state_store=state_store,
        )
    except SqliteWriteError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Index written to {output_dir / 'graph.json'}")
    typer.echo(f"  Files indexed: {len({n.file_path for n in nodes})}")
    typer.echo(f"  Symbols:       {counts['nodes']}")
    typer.echo(f"  Edges:         {counts['edges']}")
    if not no_sqlite and counts.get("fts_symbols", 0) > 0:
        typer.echo(f"  FTS symbols:   {counts['fts_symbols']}")

    # ── Agent adoption hint ──────────────────────────────────────────────
    if counts.get("nodes", 0) > 0:
        typer.echo("")
        typer.echo("CodeGraph index ready.")
        typer.echo("")
        typer.echo(
            "To help your coding agent remember to use CodeGraph, "
            "add the CodeGraph Usage Reminder to your target project rules:"
        )
        typer.echo("")
        typer.echo("  - Claude Code: CLAUDE.md")
        typer.echo("  - Cursor:      .cursor/rules/codegraph.mdc")
        typer.echo("  - Other agents: AGENTS.md or equivalent")
        typer.echo("")
        typer.echo("See README: Agent 使用建议")
    else:
        typer.echo("")
        typer.echo(
            "Warning: 0 symbols indexed. The index may be empty or invalid. "
            "Run 'codegraph doctor' to diagnose."
        )

    _maybe_install_hook(root_path, no_hook, state_store, force=force)


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
    no_hook: bool = typer.Option(
        False, "--no-hook",
        help="Skip installing the git post-commit hook",
    ),
) -> None:
    """Backward-compatible alias for 'init'. Use 'codegraph init' instead."""
    init(root=root, force=force, incremental=incremental, no_sqlite=no_sqlite, no_hook=no_hook)


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
    no_sqlite: bool,
    state_store,  # IndexStateStore
) -> None:
    """Incrementally update the index for changed / added / deleted files.

    Uses true incremental SQLite patch — only affected nodes/edges are
    deleted and re-inserted. Cross-file dependents are re-resolved.
    """
    from codegraph.indexer.incremental import (
        run_incremental_index,
        _find_direct_dependents,
    )
    from codegraph.indexer.fingerprint import FingerprintStore

    store = FileStore(output_dir)
    metadata = store.load_metadata()

    # Try classification-based detection
    fp_store = FingerprintStore(output_dir)
    stored_fps = fp_store.load()

    if stored_fps:
        status_result = detect_status_with_classification(
            root_path, metadata, fp_store,
        )
    else:
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

    # Show change summary with classification
    change_summary = status_result.change_summary
    typer.echo(f"Change summary:")
    typer.echo(f"  unchanged:  {change_summary['none']}")
    typer.echo(f"  cosmetic:   {change_summary['cosmetic']}")
    typer.echo(f"  structural: {change_summary['structural']}")
    typer.echo(f"  added:      {change_summary['added']}")
    typer.echo(f"  deleted:    {change_summary['deleted']}")
    typer.echo()

    # Check for full rebuild recommendation
    structural_count = len(status_result.structural_files)
    total_idx = metadata.file_count if metadata else 1
    if structural_count > 30 or structural_count > 0.3 * max(total_idx, 1):
        typer.echo(
            f"Note: {structural_count} structural files changed "
            f"({total_idx} indexed). Consider running:"
        )
        typer.echo(f"  codegraph init --force")
        typer.echo()

    if status_result.structural_files:
        typer.echo(f"  Structural files: {len(status_result.structural_files)}")
        for f in status_result.structural_files[:10]:
            typer.echo(f"    ~ {f}")
        if len(status_result.structural_files) > 10:
            typer.echo(f"    ... and {len(status_result.structural_files) - 10} more")
    if status_result.cosmetic_files:
        typer.echo(f"  Cosmetic files: {len(status_result.cosmetic_files)} (skipped)")
        for f in status_result.cosmetic_files[:5]:
            typer.echo(f"    - {f}")
        if len(status_result.cosmetic_files) > 5:
            typer.echo(f"    ... and {len(status_result.cosmetic_files) - 5} more")
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

    # Only structural + added + deleted need action
    actionable = structural_count + len(status_result.added_files) + len(status_result.deleted_files)
    if actionable == 0:
        typer.echo("No structural changes to index. Only cosmetic changes detected — skipped.")
        return

    # Find direct dependents for cross-file edge resolution
    dependent_files: list[str] = []
    sqlite_path = output_dir / "index.sqlite"
    if structural_count > 0 and not no_sqlite and sqlite_path.exists():
        dependent_files = _find_direct_dependents(
            status_result.structural_files, sqlite_path,
        )
        if dependent_files:
            typer.echo(f"  Dependent files: {len(dependent_files)} (re-resolving cross-file edges)")
            for f in dependent_files[:5]:
                typer.echo(f"    ↳ {f}")
            if len(dependent_files) > 5:
                typer.echo(f"    ... and {len(dependent_files) - 5} more")
        typer.echo()

    # Use the shared incremental index logic (true incremental SQLite patch)
    result = run_incremental_index(
        root_path, output_dir, store,
        no_sqlite=no_sqlite, state_store=state_store,
    )

    if result.status == "error":
        typer.echo(f"Error: {result.error}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Incremental index updated {actionable} files.")
    typer.echo(f"Updated index written to {output_dir / 'graph.json'}")
    typer.echo(f"  Total symbols:  {result.total_symbols}")
    typer.echo(f"  Total edges:    {result.total_edges}")
    typer.echo(f"  Nodes removed:  {result.deleted_nodes_count}")
    typer.echo(f"  Nodes inserted: {result.inserted_nodes_count}")
    typer.echo(f"  Edges removed:  {result.deleted_edges_count}")
    typer.echo(f"  Edges inserted: {result.inserted_edges_count}")
    if result.reparsed_files > 0:
        typer.echo(f"  Files re-parsed:{result.reparsed_files}")
    if result.dependent_files > 0:
        typer.echo(f"  Dependents:     {result.dependent_files}")
    typer.echo(f"  Duration:       {result.duration_ms:.0f}ms")
    if not no_sqlite:
        typer.echo(f"  Write mode:     incremental patch (not full replace)")


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
    store, cg_dir = _load_store(root)
    sqlite_path = cg_dir / "index.sqlite"
    if sqlite_path.exists():
        sql_store = SqliteStore(sqlite_path)
        try:
            sql_store.initialize()
            result_dict = graph_query.search_symbols(sql_store, query)
        finally:
            sql_store.close()
    else:
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
            "callers": [{"node_id": c["symbol_id"]} for c in callers],
            "callees": [{"node_id": c["symbol_id"]} for c in callees],
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
        for entry in callers:
            caller_id = entry["symbol_id"]
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
        for entry in callees:
            callee_id = entry["symbol_id"]
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


# ── api command ───────────────────────────────────────────────────────


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
    """Start the CodeGraph API server.

    Reads the .codegraph index from the specified project root.

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
    """Resolve and validate the environment for ``serve --mcp`` startup.

    Checks CODEGRAPH_PROJECT_ROOT, directory existence, and .codegraph
    presence. Returns the resolved project root Path.

    **Graceful startup**: Does NOT exit when the .codegraph directory is
    missing or incomplete.  The MCP server must stay alive so that tools
    like ``codegraph_repo_status`` can return structured diagnostics and
    guide the user to run ``codegraph init``.  Only truly fatal conditions
    (project root path does not exist or is not a directory) cause an exit.
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

    # Check 1: path exists (fatal — nowhere to serve from)
    if not resolved.exists():
        typer.echo(
            f"ERROR: Project root does not exist.\n"
            f"  Path: {resolved}\n"
            f"  Run:  mkdir -p {resolved}",
            err=True,
        )
        raise typer.Exit(1)

    # Check 2: path is a directory (fatal)
    if not resolved.is_dir():
        typer.echo(
            f"ERROR: Project root is not a directory.\n"
            f"  Path: {resolved}",
            err=True,
        )
        raise typer.Exit(1)

    cg_dir = resolved / ".codegraph"

    # Check 3: .codegraph directory — warn but do not exit.
    # The MCP server starts without an index and tools return structured
    # errors asking the user to run "codegraph init".
    if not cg_dir.exists():
        typer.echo(
            f"Warning: No CodeGraph index found at {cg_dir}\n"
            f"Run 'codegraph init' in the target project.\n"
            f"  cd {resolved}\n"
            f"  codegraph init",
            err=True,
        )
    else:
        # Check 4: index completeness — warn but do not exit
        missing_files: list[str] = []
        for fname in ("graph.json", "nodes.json", "edges.json", "metadata.json"):
            if not (cg_dir / fname).exists():
                missing_files.append(fname)
        if missing_files:
            typer.echo(
                f"Warning: CodeGraph index is incomplete — missing files: {', '.join(missing_files)}\n"
                f"Run 'codegraph init --force' in the target project.\n"
                f"  cd {resolved}\n"
                f"  codegraph init --force",
                err=True,
            )

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
        typer.echo(f"  Python:         {sys.executable}")
        typer.echo(f"  Package:        codegraph (importable)")
        typer.echo(f"  Project root:   {project_root}")
        typer.echo(f"  Index dir:      {project_root / '.codegraph'}")

        index_found = (project_root / ".codegraph").exists()
        if index_found:
            metadata_path = project_root / ".codegraph" / "metadata.json"
            if metadata_path.exists():
                from codegraph.graph.models import IndexMetadata
                try:
                    meta = IndexMetadata.model_validate_json(metadata_path.read_text("utf-8"))
                    typer.echo(f"  Index:          found ({meta.symbol_count} symbols, {meta.edge_count} edges)")
                    typer.echo(f"  Indexed at:     {meta.indexed_at}")
                except Exception:
                    typer.echo(f"  Index:          found (metadata unreadable)")
            else:
                typer.echo(f"  Index:          found (no metadata)")
        else:
            typer.echo(f"  Index:          NOT FOUND")
            typer.echo(f"  Warning: No .codegraph directory found. Tools will return errors")
            typer.echo(f"           until the user runs: codegraph init")

        # MCP protocol compliance: verify tools return dicts, not double-encoded strings
        from codegraph.mcp_server import _respond_ok, _respond_error, ZERO_TELEMETRY_STATEMENT
        test_ok = _respond_ok({"test": True}, tool="check")
        test_err = _respond_error("TEST", "check", tool="check")
        if isinstance(test_ok, dict) and isinstance(test_err, dict):
            typer.echo("  [OK] MCP tools return structured dicts (protocol-compliant)")
        else:
            typer.echo("  [FAIL] MCP tools return strings (double-encoded JSON)", err=True)
        typer.echo(f"  [OK] Zero telemetry: {ZERO_TELEMETRY_STATEMENT[:80]}...")

        if not index_found:
            typer.echo("")
            typer.echo("Next steps:")
            typer.echo(f"  1. cd {project_root}")
            typer.echo(f"  2. codegraph init")
            typer.echo(f"  3. codegraph serve --mcp --check   # re-validate")
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
    repair: bool = typer.Option(
        False, "--repair",
        help="Repair JSON inconsistencies from SQLite (SQLite is source of truth)",
    ),
) -> None:
    """Diagnose CodeGraph setup and report any issues.

    Checks: CLI availability, Python version, package path, project root,
    .codegraph presence, index status, MCP config paths, MCP project root
    validation, serve --mcp readiness, MCP command existence, MCP
    server launch check, and MCP protocol compliance.
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

    # 4b. Enabled languages
    typer.echo("4b. Enabled languages")
    try:
        from codegraph.language_support.registry import get_registry
        registry = get_registry()
        enabled_langs = registry.list_enabled()
        if enabled_langs:
            for reg in enabled_langs:
                sl = reg.support_level.value
                sl_icon = "[PROD]" if sl == "production" else "[BETA]" if sl == "beta" else "[EXP]"
                ok(f"{sl_icon} {reg.language_id}: {', '.join(reg.extensions)}")
        else:
            warn("No languages registered")
    except Exception as e:
        warn(f"Could not load language registry: {e}")
    typer.echo()

    # 4c. Unsupported file count
    typer.echo("4c. Unsupported files")
    try:
        supported_exts: set[str] = set()
        for reg in enabled_langs:
            supported_exts.update(reg.extensions)
        unsupported_count = 0
        unsupported_exts: dict[str, int] = {}
        skip_dirs = {'.git', '.codegraph', '__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build', '.next'}
        for dirpath, dirnames, filenames in os.walk(str(project_root)):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith('.')]
            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                if ext and ext not in supported_exts:
                    unsupported_exts[ext] = unsupported_exts.get(ext, 0) + 1
                    unsupported_count += 1
        if unsupported_count > 0:
            top_exts = sorted(unsupported_exts.items(), key=lambda x: -x[1])[:5]
            top_str = ", ".join(f"{ext}({n})" for ext, n in top_exts)
            warn(f"{unsupported_count} file(s) with unsupported extensions (top: {top_str})")
        else:
            ok("All files match supported extensions")
    except Exception as e:
        warn(f"Could not check unsupported files: {e}")
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
        required_present = all(v for k, v in index_files.items() if k != "index.sqlite")
        missing = [k for k, v in index_files.items() if not v and k != "index.sqlite"]
        if required_present and index_files["index.sqlite"]:
            ok("All index files present")
        elif required_present:
            warn("index.sqlite missing; JSON fallback will be used")
            typer.echo(f"     Run: cd {project_root} && codegraph init --force")
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

        # Freshness check (lite — no file scanning)
        if index_files["metadata.json"] and index_files["graph.json"]:
            lite = get_index_status(project_root)
            status = lite["status"]
            if status == "fresh":
                ok("Index is fresh")
            elif status == "stale":
                cs = lite.get("last_change_summary") or {}
                total = sum(cs.values())
                warn(f"Index is stale — {total} file(s) changed")
                typer.echo(f"     Run: {lite.get('suggested_fix', 'codegraph init --incremental')}")
            elif status == "indexing":
                typer.echo("     Index update is in progress...")
            elif status == "error":
                fail(f"Index error: {lite.get('last_error', 'Unknown')}")
                typer.echo(f"     Run: {lite.get('suggested_fix', 'codegraph doctor')}")
        typer.echo()

    # 5b. Storage integrity
    typer.echo("5b. Storage integrity")
    if cg_dir.exists():
        try:
            integrity = check_storage_integrity(cg_dir)
            for check in integrity["checks"]:
                status = check["status"]
                message = check["message"]
                if status == "ok":
                    ok(message)
                elif status == "warning":
                    warn(message)
                else:
                    fail(message)

            # Show counts summary
            counts = integrity.get("counts", {})
            typer.echo("")
            typer.echo(f"     Counts summary:")
            typer.echo(f"       SQLite nodes:  {counts.get('sqlite_nodes', 'N/A')}")
            typer.echo(f"       SQLite edges:  {counts.get('sqlite_edges', 'N/A')}")
            typer.echo(f"       JSON nodes:    {counts.get('json_nodes', 'N/A')}")
            typer.echo(f"       JSON edges:    {counts.get('json_edges', 'N/A')}")
            typer.echo(f"       FTS symbols:   {counts.get('fts_symbols', 'N/A')}")
            typer.echo(f"       Metadata sym:  {counts.get('metadata_symbols', 'N/A')}")
            typer.echo(f"       Metadata edges:{counts.get('metadata_edges', 'N/A')}")

            # Consistency verdict
            consistency = integrity.get("consistency", "unknown")
            if consistency == "ok":
                ok(f"Consistency: {consistency}")
            elif consistency == "warning":
                warn(f"Consistency: {consistency}")
            else:
                fail(f"Consistency: {consistency}")

            suggestion = integrity.get("suggestion")
            if suggestion:
                typer.echo(f"     Suggestion: {suggestion}")

            # --repair logic
            if repair:
                typer.echo("")
                typer.echo("--- Repair ---")
                if consistency == "ok":
                    typer.echo("Storage is already consistent. No repair needed.")
                else:
                    try:
                        repair_counts = repair_json_from_sqlite(cg_dir, project_root)
                        typer.echo(f"Repair complete. JSON files rebuilt from SQLite.")
                        typer.echo(f"  Nodes: {repair_counts['nodes']}")
                        typer.echo(f"  Edges: {repair_counts['edges']}")
                        # Re-run integrity check
                        integrity2 = check_storage_integrity(cg_dir)
                        consistency2 = integrity2.get("consistency", "unknown")
                        if consistency2 == "ok":
                            ok(f"Post-repair consistency: {consistency2}")
                        else:
                            warn(f"Post-repair consistency: {consistency2}")
                    except SqliteWriteError as e:
                        fail(str(e))
        except Exception as e:
            fail(f"Storage integrity check failed: {e}")
    else:
        warn("Skipped because .codegraph is missing")
    typer.echo()

    # 5c. Fingerprint health
    typer.echo("5c. Fingerprint health")
    if cg_dir.exists():
        fp_path = cg_dir / "fingerprints.json"
        if not fp_path.exists():
            warn("fingerprints.json missing")
            typer.echo(f"     Run: cd {project_root} && codegraph init --force")
        else:
            try:
                from codegraph.indexer.fingerprint import FingerprintStore
                fp_store = FingerprintStore(cg_dir)
                fps = fp_store.load()
                ok(f"fingerprints.json present ({len(fps)} entries)")

                # Check for stale fingerprints
                stale = [p for p in fps if not (project_root / p).exists()]
                if stale:
                    warn(f"{len(stale)} stale fingerprint(s) for deleted files")
                else:
                    ok("No stale fingerprints")

                # Check coverage
                if index_files.get("metadata.json"):
                    from codegraph.indexer.scanner import scan_supported_files, normalize_path
                    current = {normalize_path(f.relative_to(project_root))
                               for f in scan_supported_files(project_root)}
                    missing = current - set(fps.keys())
                    if missing:
                        warn(f"{len(missing)} file(s) have no fingerprint")
                        typer.echo(f"     Run: codegraph init --force")
                    else:
                        ok("All indexed files have fingerprints")
            except Exception as e:
                fail(f"Fingerprint check failed: {e}")
    else:
        warn("Skipped because .codegraph is missing")
    typer.echo()

    # 5d. Incremental performance stats
    typer.echo("5d. Incremental performance")
    if cg_dir.exists():
        state_store = IndexStateStore(cg_dir)
        state = state_store.load()
        inc_stats = state.get("last_incremental_stats")
        if inc_stats and inc_stats.get("duration_ms", 0) > 0:
            full_replace = inc_stats.get("full_replace", True)
            mode = "full replace" if full_replace else "incremental patch"
            ok(f"Last run: {inc_stats.get('changed_files', 0)} changed, "
               f"{inc_stats.get('reparsed_files', 0)} re-parsed, "
               f"{inc_stats.get('dependent_files', 0)} dependents")
            typer.echo(f"     Nodes: {inc_stats.get('deleted_nodes', 0)} deleted, "
                       f"{inc_stats.get('inserted_nodes', 0)} inserted")
            typer.echo(f"     Edges: {inc_stats.get('deleted_edges', 0)} deleted, "
                       f"{inc_stats.get('inserted_edges', 0)} inserted")
            typer.echo(f"     Duration: {inc_stats.get('duration_ms', 0):.0f}ms")
            typer.echo(f"     Write mode: {mode}")
        else:
            ok("No incremental stats recorded yet")
    else:
        warn("Skipped because .codegraph is missing")
    typer.echo()

    # 5e. Graph health (validation)
    typer.echo("5e. Graph health")
    if cg_dir.exists():
        try:
            from codegraph.graph.validation import (
                validate_graph, load_validation_report,
                save_validation_report,
            )

            report = load_validation_report(cg_dir)
            if report is None:
                # Run fresh validation if no cached report
                sqlite_path = cg_dir / "index.sqlite"
                if sqlite_path.exists():
                    sql_store = SqliteStore(sqlite_path)
                    sql_store.initialize()
                    report = validate_graph(
                        cg_dir=cg_dir, project_root=project_root,
                        store=sql_store,
                    )
                    save_validation_report(cg_dir, report)
                    sql_store.close()
                else:
                    warn("No SQLite index to validate")

            if report:
                status = report.get("status", "unknown")
                if status == "ok":
                    ok(f"Graph validation: {status}")
                elif status == "warning":
                    warn(f"Graph validation: {status}")
                else:
                    fail(f"Graph validation: {status}")

                edge_health = report.get("edge_health", {})
                typer.echo(
                    f"     Total edges (incl. dropped): "
                    f"{edge_health.get('total_edges', 0)}"
                )
                typer.echo(
                    f"     Auto-corrected: "
                    f"{edge_health.get('total_auto_corrected', 0)}"
                )
                typer.echo(
                    f"     Dropped:        "
                    f"{edge_health.get('total_dropped', 0)}"
                )
                typer.echo(
                    f"     Dropped ratio:  "
                    f"{edge_health.get('dropped_ratio', 0):.1%}"
                )

                # Show dropped by reason (top 5)
                dropped_br = edge_health.get("dropped_by_reason", [])
                if dropped_br:
                    typer.echo("     Dropped by reason:")
                    for br in dropped_br[:5]:
                        reason = br.get("reason", "?")
                        count = br.get("count", 0)
                        examples = br.get("top_examples", [])
                        first_ex = (
                            examples[0].get("message", "")[:100]
                            if examples else ""
                        )
                        typer.echo(f"       {reason}: {count}")
                        if first_ex:
                            typer.echo(f"         e.g. {first_ex}")

                # Show auto-corrected by reason (top 5)
                ac_br = edge_health.get("auto_corrected_by_reason", [])
                if ac_br:
                    typer.echo("     Auto-corrected by reason:")
                    for br in ac_br[:5]:
                        reason = br.get("reason", "?")
                        count = br.get("count", 0)
                        examples = br.get("top_examples", [])
                        first_ex = (
                            examples[0].get("message", "")[:100]
                            if examples else ""
                        )
                        typer.echo(f"       {reason}: {count}")
                        if first_ex:
                            typer.echo(f"         e.g. {first_ex}")

                # Show impact assessment
                impact = edge_health.get("impact_assessment", "")
                if impact:
                    typer.echo(f"     Impact: {impact}")

                # Show suggested actions
                actions = edge_health.get("suggested_actions", [])
                for action in actions:
                    typer.echo(f"     Action: {action}")

                # Legacy stats
                stats = report.get("stats", {})
                typer.echo(
                    f"     Orphan ratio:       "
                    f"{stats.get('orphan_ratio', 0):.1%}"
                )
                typer.echo(
                    f"     Low-conf edge ratio:"
                    f"{stats.get('low_confidence_ratio', 0):.1%}"
                )

                suggested = report.get("suggested_fix")
                if suggested:
                    typer.echo(f"     Fix: {suggested}")
                else:
                    typer.echo(
                        f"     Report: {cg_dir / 'validation_report.json'}"
                    )
        except Exception as e:
            warn(f"Could not run graph validation: {e}")
    else:
        warn("Skipped because .codegraph is missing")
    typer.echo()

    # 5f. Parser diagnostics by language
    typer.echo("5f. Parser diagnostics")
    if cg_dir.exists() and (cg_dir / "graph.json").exists():
        try:
            graph_json = json.loads((cg_dir / "graph.json").read_text("utf-8"))
            nodes_list = graph_json.get("nodes", [])
            parser_errors: dict[str, int] = {}
            for node in nodes_list:
                meta = node.get("metadata", {})
                if meta.get("parse_error") or meta.get("parser_unavailable"):
                    lid = node.get("language_id", node.get("language", "unknown"))
                    parser_errors[lid] = parser_errors.get(lid, 0) + 1
            if parser_errors:
                for lid, count in sorted(parser_errors.items()):
                    warn(f"{lid}: {count} symbols with parse errors or parser unavailable")
            else:
                ok("No parser errors detected")
        except Exception as e:
            warn(f"Could not check parser diagnostics: {e}")
    else:
        typer.echo("     Skipped — no graph.json found")
    typer.echo()

    # 5g. Extractor errors by language
    typer.echo("5g. Extractor errors")
    if cg_dir.exists() and (cg_dir / "graph.json").exists():
        try:
            graph_json = json.loads((cg_dir / "graph.json").read_text("utf-8"))
            nodes_list = graph_json.get("nodes", [])
            extractor_errors: dict[str, int] = {}
            for node in nodes_list:
                meta = node.get("metadata", {})
                if meta.get("extractor_error") or meta.get("extraction_failed"):
                    lid = node.get("language_id", node.get("language", "unknown"))
                    extractor_errors[lid] = extractor_errors.get(lid, 0) + 1
            if extractor_errors:
                for lid, count in sorted(extractor_errors.items()):
                    warn(f"{lid}: {count} extraction errors")
            else:
                ok("No extractor errors detected")
        except Exception as e:
            warn(f"Could not check extractor errors: {e}")
    else:
        typer.echo("     Skipped — no graph.json found")
    typer.echo()

    # 5h. Resolver warnings by language
    typer.echo("5h. Resolver warnings")
    if cg_dir.exists() and (cg_dir / "graph.json").exists():
        try:
            graph_json = json.loads((cg_dir / "graph.json").read_text("utf-8"))
            nodes_list = graph_json.get("nodes", [])
            edges_list = graph_json.get("edges", [])
            node_map: dict[str, dict] = {n["id"]: n for n in nodes_list}
            resolver_warnings: dict[str, dict[str, int]] = {}
            for edge in edges_list:
                if edge.get("type") != "calls":
                    continue
                source_node = node_map.get(edge.get("source", ""))
                if not source_node:
                    continue
                resolution = edge.get("resolution") or (edge.get("metadata", {}) or {}).get("resolution", "")
                if resolution in ("unresolved", "name_match_candidate", "external_symbol"):
                    lid = source_node.get("language_id", source_node.get("language", "unknown"))
                    resolver_warnings.setdefault(lid, {"unresolved": 0, "possible": 0})
                    resolver_warnings[lid]["unresolved"] += 1
                elif resolution in ("possible_match", "heuristic_match", "partial_match", "overloaded_method_candidate", "interface_method_candidate"):
                    lid = source_node.get("language_id", source_node.get("language", "unknown"))
                    resolver_warnings.setdefault(lid, {"unresolved": 0, "possible": 0})
                    resolver_warnings[lid]["possible"] += 1
            if resolver_warnings:
                for lid, counts in sorted(resolver_warnings.items()):
                    total_warn = counts["unresolved"] + counts["possible"]
                    typer.echo(f"     {lid}: {counts['possible']} possible, {counts['unresolved']} unresolved edges")
            else:
                ok("No resolver warnings")
        except Exception as e:
            warn(f"Could not check resolver warnings: {e}")
    else:
        typer.echo("     Skipped — no graph.json found")
    typer.echo()

    # 5i. Benchmark fixture status
    typer.echo("5i. Benchmark fixture status")
    try:
        bench_dir = Path(__file__).resolve().parents[3] / "tests" / "agent_benchmark"
        if bench_dir.exists():
            cases_dir = bench_dir / "cases"
            if cases_dir.exists():
                case_files = list(cases_dir.glob("*.json"))
                langs_in_bench: set[str] = set()
                for cf in case_files:
                    case_data = json.loads(cf.read_text("utf-8"))
                    langs_in_bench.add(case_data.get("language", "python"))
                ok(f"Benchmark cases: {len(case_files)} ({', '.join(sorted(langs_in_bench))})")
                missing_langs = set(registry.language_ids()) - langs_in_bench
                if missing_langs:
                    warn(f"Languages without benchmark cases: {', '.join(sorted(missing_langs))}")
            else:
                warn("No benchmark cases directory found")
        else:
            typer.echo("     Benchmark directory not found (expected in repo)")
    except Exception as e:
        warn(f"Could not check benchmark fixture status: {e}")
    typer.echo()

    # 5j. Schema compatibility
    typer.echo("5j. Schema compatibility")
    if cg_dir.exists() and (cg_dir / "graph.json").exists():
        try:
            graph_json = json.loads((cg_dir / "graph.json").read_text("utf-8"))
            nodes_list = graph_json.get("nodes", [])
            schema_ver = graph_json.get("schema_version", "unknown")
            typer.echo(f"     Schema version: {schema_ver}")
            # Check language_id presence
            missing_lang = sum(1 for n in nodes_list if not n.get("language_id") and not n.get("language"))
            if missing_lang:
                warn(f"{missing_lang} node(s) missing language_id")
            else:
                ok("All nodes have language_id")
            # Check support_level presence
            missing_support = sum(1 for n in nodes_list if not n.get("support_level"))
            if missing_support:
                typer.echo(f"     {missing_support} node(s) missing support_level (defaulting to production)")
            else:
                ok("All nodes have support_level")
        except Exception as e:
            warn(f"Schema validation failed: {e}")
    else:
        typer.echo("     Skipped — no graph.json found")
    typer.echo()

    # 5k. Hook health
    typer.echo("5k. Hook health")
    if cg_dir.exists():
        state_store_5f = IndexStateStore(cg_dir)
        hook_cfg = state_store_5f.get_hook_config()

        auto_update = hook_cfg.get("auto_update_on_commit", True)
        installed = hook_cfg.get("installed", False)
        hook_path_str = hook_cfg.get("hook_path")
        last_run = hook_cfg.get("last_run_at")
        last_exit = hook_cfg.get("last_run_exit_code")
        last_dur = hook_cfg.get("last_run_duration_ms")
        total_runs = hook_cfg.get("total_runs", 0)
        total_fails = hook_cfg.get("total_failures", 0)

        # Check if this is a git repo
        git_dir_hook = HookManager._find_git_dir(project_root)
        is_git_repo = git_dir_hook is not None

        if not is_git_repo:
            warn("Not a git repository — post-commit hook not applicable")
        else:
            # Check hook file presence
            hook_file = git_dir_hook / "hooks" / "post-commit"
            hook_exists = hook_file.exists()

            if auto_update:
                ok("Auto-update on commit: enabled")
            else:
                warn("Auto-update on commit: disabled")
                typer.echo(f"       Enable with: codegraph config set auto_update_on_commit true")

            if hook_exists:
                content = hook_file.read_text(encoding="utf-8")
                from codegraph.hooks.template import SENTINEL_START
                has_managed = SENTINEL_START in content

                if has_managed:
                    ok(f"Post-commit hook installed: {hook_file}")

                    # Check Python path validity
                    python_path = HookManager._extract_field(
                        content, "CODEGRAPH_PYTHON",
                    )
                    if python_path:
                        if Path(python_path).exists():
                            ok(f"Python path valid: {python_path}")
                        else:
                            fail(f"Python path in hook does not exist: {python_path}")
                            typer.echo(f"       Run: codegraph hooks install --force")

                    # Check project root validity
                    hook_root = HookManager._extract_field(
                        content, "CODEGRAPH_PROJECT_ROOT",
                    )
                    if hook_root:
                        if Path(hook_root).exists():
                            ok(f"Project root valid: {hook_root}")
                        else:
                            fail(f"CODEGRAPH_PROJECT_ROOT invalid: {hook_root}")
                            typer.echo(f"       Run: codegraph hooks install --force")

                    # Last run info
                    if last_run:
                        status_label = "success" if last_exit == 0 else "error"
                        dur_str = f"{last_dur:.0f}ms" if last_dur else "N/A"
                        ok(f"Last run: {last_run} (exit {last_exit}, {dur_str})")
                    else:
                        typer.echo(f"  [INFO]  Last run: never")

                    if total_runs > 0:
                        typer.echo(
                            f"  [INFO]  Total runs: {total_runs}, "
                            f"failures: {total_fails}"
                        )
                else:
                    warn("Hook file exists but missing CodeGraph managed block")
                    typer.echo(f"       Run: codegraph hooks install")
            else:
                if auto_update:
                    warn("Post-commit hook not installed")
                    typer.echo(f"       Run: codegraph hooks install")
                else:
                    typer.echo("  [INFO]  Post-commit hook not installed (auto-update disabled)")
    else:
        warn("Skipped because .codegraph is missing")
    typer.echo()

    # 5l. Test coverage signal
    typer.echo("5l. Test coverage signal")
    if cg_dir.exists() and (cg_dir / "graph.json").exists():
        try:
            from codegraph.graph.test_coverage import compute_test_coverage_signal
            from codegraph.graph.models import GraphNode, GraphEdge

            # Load nodes and edges from graph.json (consistent with other doctor sections)
            graph_json = json.loads((cg_dir / "graph.json").read_text("utf-8"))
            raw_nodes = graph_json.get("nodes", [])
            raw_edges = graph_json.get("edges", [])

            nodes = [GraphNode.model_validate(n) for n in raw_nodes]
            edges = [GraphEdge.model_validate(e) for e in raw_edges]

            signal = compute_test_coverage_signal(nodes, edges, str(project_root))

            status = signal.get("status", "unknown")
            test_files_count = signal.get("test_files_detected", 0)
            tested_by_count = signal.get("tested_by_edges", 0)
            high_conf = signal.get("tested_symbols_high_confidence", 0)
            low_conf = signal.get("tested_symbols_low_confidence", 0)
            unknown_conf = signal.get("tested_symbols_unknown_confidence", 0)
            message = signal.get("message", "")
            warnings_list = signal.get("warnings", [])

            typer.echo(f"     test files detected: {test_files_count}")
            typer.echo(f"     tested_by edges:     {tested_by_count}")
            typer.echo(f"       high confidence:   {high_conf}")
            typer.echo(f"       low confidence:    {low_conf}")
            typer.echo(f"       unknown confidence:{unknown_conf}")

            if status == "ok":
                ok(f"Status: {status}")
            elif status in ("incomplete", "low_confidence"):
                warn(f"Status: {status}")
            elif status == "unknown":
                typer.echo(f"  [INFO]  Status: {status}")
            else:
                typer.echo(f"     Status: {status}")

            typer.echo(f"     Message: {message}")

            for w in warnings_list:
                warn(f"Warning: {w}")

        except Exception as e:
            warn(f"Could not compute test coverage signal: {e}")
    else:
        typer.echo("     Skipped — no graph.json found")
    typer.echo()

    # 5m. Coverage gaps
    typer.echo("5m. Coverage gaps")
    if cg_dir.exists() and (cg_dir / "graph.json").exists():
        try:
            from codegraph.graph.coverage_gaps import compute_coverage_gaps
            from codegraph.graph.store import GraphStore

            # Build an in-memory store from graph.json
            gap_store = GraphStore()
            gap_store.load_from_lists(nodes, edges)

            gaps = compute_coverage_gaps(
                gap_store,
                project_root=str(project_root),
                include_low_confidence=True,
                limit=50,
            )
            summary = gaps.get("summary", {})
            prod_checked = summary.get("production_symbols_checked", 0)
            without_test = summary.get("symbols_without_test_signal", 0)
            low_conf_links = len(gaps.get("low_confidence_links", []))
            confidence = summary.get("confidence", "unknown")

            typer.echo(f"     production symbols checked: {prod_checked}")
            typer.echo(f"     symbols without confident test signal: {without_test}")
            typer.echo(f"     low-confidence links: {low_conf_links}")
            typer.echo(f"     status: {confidence}")

            # Never fail on coverage gaps — INFO only
            if confidence in ("low", "unknown") and without_test > 0:
                typer.echo(f"  [INFO]  Coverage signal is {confidence}. Run codegraph_coverage_gaps via MCP for details.")
            elif without_test > 0:
                typer.echo(f"  [INFO]  {without_test} symbols lack test coverage signal. Run codegraph_coverage_gaps via MCP for details.")
            else:
                ok("All production symbols have confident test coverage signal")

        except Exception as e:
            warn(f"Could not compute coverage gaps: {e}")
    else:
        typer.echo("     Skipped — no graph.json found")
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

    # 7. MCP project binding
    typer.echo("7. MCP project binding")
    cwd_path = Path.cwd().resolve()

    # Show current project context
    typer.echo(f"     Current CWD:")
    typer.echo(f"       {cwd_path}")
    if (cwd_path / ".codegraph" / "graph.json").exists():
        ok(f"     .codegraph found in CWD")
    else:
        cg_found = _find_codegraph_dir(str(cwd_path))
        if cg_found:
            typer.echo(f"     .codegraph found at: {cg_found.parent}")
        else:
            warn(f"     No .codegraph in or above CWD — run: codegraph init")
    typer.echo()

    has_fixed_root = False
    for label, cfg_path in config_paths:
        data = read_config(cfg_path)
        server_cfg = data.get("mcpServers", {}).get(MCP_SERVER_NAME)
        if not server_cfg:
            continue
        env_root = server_cfg.get("env", {}).get("CODEGRAPH_PROJECT_ROOT")
        if not env_root:
            # Auto-detect mode — this is the recommended global config
            ok(f"{label}: Global MCP config uses auto-detect project root.")
            continue
        has_fixed_root = True
        root_path = Path(env_root)
        if not root_path.exists():
            fail(f"{label}: CODEGRAPH_PROJECT_ROOT path does not exist: {env_root}")
            typer.echo(f"       Run: codegraph configure {'cursor' if 'Cursor' in label else 'claude'} --force")
            continue
        if not root_path.is_dir():
            fail(f"{label}: CODEGRAPH_PROJECT_ROOT is not a directory: {env_root}")
            continue
        cg_subdir = root_path / ".codegraph"
        if not cg_subdir.exists():
            fail(f"{label}: no .codegraph at CODEGRAPH_PROJECT_ROOT ({env_root})")
            typer.echo(f"       Run: cd {env_root} && codegraph init")
            continue
        if not (cg_subdir / "graph.json").exists():
            fail(f"{label}: .codegraph is incomplete at {env_root} (missing graph.json)")
            typer.echo(f"       Run: cd {env_root} && codegraph init --force")
            continue
        ok(f"{label}: .codegraph found at {env_root}")
        # Check if CODEGRAPH_PROJECT_ROOT matches current project
        if root_path.resolve() != cwd_path:
            typer.echo()
            warn(f"{label}: Global MCP config is bound to a fixed project:")
            typer.echo(f"       {root_path.resolve()}")
            typer.echo()
            typer.echo(f"     Current project (CWD):")
            typer.echo(f"       {cwd_path}")
            typer.echo()
            typer.echo(f"     This may cause CodeGraph MCP to query the wrong index.")
            typer.echo()
            typer.echo(f"     Suggested fix:")
            typer.echo(f"       codegraph configure all --force")
            typer.echo(f"     or use project-scoped config:")
            typer.echo(f"       codegraph configure all --project")

    if not has_fixed_root and configured_any:
        typer.echo()
        ok("Global MCP config uses auto-detect project root.")
    typer.echo()

    # 8. serve --mcp readiness
    typer.echo("8. serve --mcp readiness")
    try:
        _validate_serve_env(str(project_root))
        ok("serve --mcp can start")
    except typer.Exit:
        fail("serve --mcp would fail — see errors above")
    typer.echo()

    # 9. MCP command existence
    typer.echo("9. MCP command existence")
    import shutil
    for label, cfg_path in config_paths:
        data = read_config(cfg_path)
        server_cfg = data.get("mcpServers", {}).get(MCP_SERVER_NAME)
        if not server_cfg:
            continue
        cmd = server_cfg.get("command", "")
        if not cmd:
            fail(f"{label}: empty command in config")
            continue
        # Determine if it's a bare command name or a path
        cmd_path = Path(cmd)
        if cmd_path.is_absolute() or "/" in cmd or "\\" in cmd:
            # Absolute or relative path — check file existence
            if cmd_path.exists():
                ok(f"{label}: {cmd}")
            elif shutil.which(cmd):
                ok(f"{label}: {cmd} (found on PATH)")
            else:
                fail(f"{label}: {cmd} — file not found")
        else:
            # Bare command name — check PATH
            found = shutil.which(cmd)
            if found:
                ok(f"{label}: {cmd} -> {found}")
            else:
                fail(f"{label}: {cmd} — not found on PATH")
    typer.echo()

    # 10. MCP server launch check
    typer.echo("10. MCP server launch check")
    import subprocess
    for label, cfg_path in config_paths:
        data = read_config(cfg_path)
        server_cfg = data.get("mcpServers", {}).get(MCP_SERVER_NAME)
        if not server_cfg:
            continue
        cmd = server_cfg.get("command", "")
        args = server_cfg.get("args", [])
        env_vars = server_cfg.get("env", {})
        if not cmd:
            continue

        # Build check command based on config style
        if args == ["serve", "--mcp"]:
            # legacy codegraph CLI mode
            check_args = [cmd, "serve", "--mcp", "--check"]
        else:
            # python -m codegraph.mcp_server mode
            check_args = [cmd] + args + ["--check"]

        # Pass project root via env if configured
        check_env = os.environ.copy()
        if "CODEGRAPH_PROJECT_ROOT" in env_vars:
            check_env["CODEGRAPH_PROJECT_ROOT"] = env_vars["CODEGRAPH_PROJECT_ROOT"]

        try:
            proc = subprocess.run(
                check_args,
                capture_output=True,
                text=True,
                timeout=30,
                env=check_env,
            )
            if proc.returncode == 0:
                ok(f"{label}: {' '.join(check_args)} — success")
            else:
                err_msg = proc.stderr.strip() or proc.stdout.strip()
                fail(f"{label}: {' '.join(check_args)} — exit code {proc.returncode}")
                if err_msg:
                    typer.echo(f"       {err_msg[:200]}")
        except FileNotFoundError:
            fail(f"{label}: {cmd} — command not found")
        except subprocess.TimeoutExpired:
            warn(f"{label}: {cmd} — check timed out (may be OK, server may just need more time)")
        except Exception as e:
            warn(f"{label}: {cmd} — could not check: {e}")
    typer.echo()

    # 11. MCP protocol compliance
    typer.echo("11. MCP protocol compliance")
    try:
        from codegraph.mcp_server import _respond_ok, _respond_error, ZERO_TELEMETRY_STATEMENT

        # Check 1: Response helpers return dicts (not double-encoded JSON strings)
        test_ok = _respond_ok({"test": True}, tool="doctor_probe")
        test_err = _respond_error("TEST", "doctor probe", tool="doctor_probe")

        if isinstance(test_ok, dict) and isinstance(test_err, dict):
            ok("Tool responses are structured dicts (proper MCP protocol)")
        else:
            fail("Tool responses are JSON strings (double-encoded — MCP clients may not parse correctly)")

        # Check 2: Envelope structure validation
        required_keys = {"ok", "tool", "warnings", "index_status", "index_health", "meta"}
        if required_keys <= set(test_ok.keys()):
            ok(f"Response envelope has all required keys: {sorted(required_keys)}")
        else:
            missing = required_keys - set(test_ok.keys())
            fail(f"Response envelope missing keys: {sorted(missing)}")

        if required_keys <= set(test_err.keys()) and "error" in test_err:
            ok("Error envelope has all required keys including error details")
        else:
            fail("Error envelope structure invalid")

        # Check 3: Zero telemetry confirmation
        ok(f"Zero telemetry: {ZERO_TELEMETRY_STATEMENT}")

        # Check 4: Verify diagnostic logging targets stderr
        import inspect
        from codegraph.mcp_server import _log
        log_source = inspect.getsource(_log)
        if "file=sys.stderr" in log_source or "sys.stderr" in log_source:
            ok("Diagnostic logging uses stderr (stdout clean for MCP protocol)")
        else:
            warn("Diagnostic logging may write to stdout — could corrupt MCP protocol")

    except ImportError as e:
        fail(f"Cannot import MCP server module: {e}")
    except Exception as e:
        fail(f"Protocol check failed: {e}")
    typer.echo()

    # ── 12. Summary ──────────────────────────────────────────────────────
    typer.echo("12. Summary")
    typer.echo("-" * 30)

    # Collect index health signals from lite function
    if cg_dir.exists():
        lite = get_index_status(project_root)
    else:
        lite = get_index_status(project_root)

    index_status = lite["status"]
    idx_health = lite.get("index_health") or {}
    health_status = idx_health.get("status", "ok") if idx_health else "ok"

    if index_status == "fresh":
        ok(f"Index status:  {index_status}")
    elif index_status == "stale":
        warn(f"Index status:  {index_status}")
    elif index_status == "missing":
        fail(f"Index status:  {index_status}")
    elif index_status == "error":
        fail(f"Index status:  {index_status}")
    else:
        typer.echo(f"  [INFO]  Index status:  {index_status}")

    if health_status == "ok":
        ok(f"Index health:  {health_status}")
    elif health_status == "warning":
        warn(f"Index health:  {health_status}")
    else:
        fail(f"Index health:  {health_status}")

    # Validation status
    issue_counts = idx_health.get("issue_counts", {})
    if idx_health:
        typer.echo(f"  [INFO]  Validation:     {health_status} "
                   f"({issue_counts.get('warnings', 0)} warnings, "
                   f"{issue_counts.get('fatal', 0)} fatal)")
    else:
        typer.echo(f"  [INFO]  Validation:     no report")

    # Fingerprints
    fp = lite.get("fingerprint_health")
    if fp and fp.get("present"):
        ok(f"Fingerprints:  present ({fp.get('count', 0)} entries)")
    elif fp:
        warn("Fingerprints:  missing or corrupt")
    else:
        typer.echo("  [INFO]  Fingerprints:  not available")

    # Storage consistency (captured from step 5b)
    storage_msg = "unknown"
    if cg_dir.exists():
        try:
            integrity = check_storage_integrity(cg_dir)
            storage_msg = integrity.get("consistency", "unknown")
        except Exception:
            storage_msg = "error"
    if storage_msg == "ok":
        ok(f"Storage:       {storage_msg}")
    elif storage_msg == "warning":
        warn(f"Storage:       {storage_msg}")
    else:
        fail(f"Storage:       {storage_msg}")

    # Hook status
    hook_info = lite.get("hook", {})
    if hook_info.get("installed"):
        ok(f"Hook:          installed (auto-update: {hook_info.get('auto_update_on_commit', True)})")
    elif hook_info.get("auto_update_on_commit", True):
        warn("Hook:          not installed (auto-update enabled but hook missing)")
        typer.echo("       Run: codegraph hooks install")
    else:
        typer.echo("  [INFO]  Hook:          not installed (auto-update disabled)")

    # Suggested fix
    suggested = lite.get("suggested_fix")
    if suggested:
        typer.echo(f"  [INFO]  Suggested fix: {suggested}")
    else:
        ok("Suggested fix: No action needed")

    typer.echo()


# ── sync command (internal, for hook invocation) ───────────────────────────

@app.command(name="sync", hidden=True)
def sync_cmd(
    incremental: bool = typer.Option(
        False, "--incremental", "-i",
        help="Use incremental update (only changed files)",
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q",
        help="Suppress stdout output (for hook usage)",
    ),
    trigger: str = typer.Option(
        "manual",
        "--trigger",
        help="What triggered this sync (e.g. 'post-commit', 'manual')",
    ),
) -> None:
    """Internal: trigger an incremental index sync.

    Called by the git post-commit hook.  Always exits with code 0
    so that a failing sync never blocks a git commit.
    """
    start_time = time_module.monotonic()
    logger = None
    exit_code = 0

    # --- Resolve project root ---
    project_root = _resolve_project_root()
    if project_root is None:
        if not quiet:
            typer.echo(
                "No .codegraph directory found. Run 'codegraph init' first.",
                err=True,
            )
        sys.exit(0)

    cg_dir = project_root / ".codegraph"

    # --- Set up logger ---
    log_dir = cg_dir / "logs"
    try:
        logger = get_hook_logger(log_dir)
    except Exception:
        pass

    def _log(msg: str, level: str = "info") -> None:
        if logger:
            getattr(logger, level)(msg)
        if not quiet and level != "debug":
            typer.echo(f"[codegraph sync] {msg}", err=True)

    # --- Check auto_update_on_commit config ---
    try:
        state_store = IndexStateStore(cg_dir)
        hook_config = state_store.get_hook_config()
        if not hook_config.get("auto_update_on_commit", True):
            _log("auto_update_on_commit is disabled, skipping sync")
            sys.exit(0)
    except Exception:
        pass

    # --- Acquire index lock ---
    lock = IndexLock(cg_dir)
    if not lock.acquire(timeout=10.0):
        _log("Could not acquire index lock — another sync may be in progress. Skipping.")
        sys.exit(0)

    try:
        _log(f"Sync started (trigger={trigger})")
        state_store = IndexStateStore(cg_dir)
        state_store.mark_indexing()

        from codegraph.indexer.incremental import run_incremental_index

        result = run_incremental_index(
            project_root, cg_dir, FileStore(cg_dir), state_store=state_store,
        )
        if result.status == "missing":
            raise RuntimeError("No index metadata found. Run 'codegraph init' first.")
        if result.status == "error":
            raise RuntimeError(result.error or "Incremental sync failed")

        duration_ms = (time_module.monotonic() - start_time) * 1000
        _log(
            f"Sync complete: {result.reparsed_files} files "
            f"re-parsed, {result.inserted_nodes_count} nodes, "
            f"{result.inserted_edges_count} edges "
            f"({duration_ms:.0f}ms)",
        )

        state_store.record_hook_run(exit_code=0, duration_ms=duration_ms)
        state_store.update_status("fresh")
    except Exception as exc:
        exit_code = 1
        duration_ms = (time_module.monotonic() - start_time) * 1000
        _log(f"Sync failed: {exc}", level="error")

        try:
            state_store = IndexStateStore(cg_dir)
            state_store.record_hook_run(exit_code=1, duration_ms=duration_ms)
            state_store.update_status("error", last_error=str(exc))
        except Exception:
            pass
    finally:
        lock.release()

    # Always exit 0 — never block a git commit
    sys.exit(0)


# ── hooks command group ────────────────────────────────────────────────────

hooks_app = typer.Typer(
    name="hooks",
    help="Manage git post-commit hook for automatic index updates",
)
app.add_typer(hooks_app)


@hooks_app.command(name="install")
def hooks_install(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (defaults to auto-detect from CWD)",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Re-install even if already installed",
    ),
) -> None:
    """Install the git post-commit hook for automatic index updates.

    The hook runs 'codegraph sync --incremental --quiet' after each commit,
    keeping the MCP index fresh without manual intervention.

    Examples:
        codegraph hooks install
        codegraph hooks install --root /path/to/project
        codegraph hooks install --force
    """
    project_root = _resolve_hook_project_root(root)
    if project_root is None:
        typer.echo("Error: Could not determine project root.", err=True)
        typer.echo(
            "Use --root to specify the project directory, or run from within "
            "a project that already has a .codegraph directory.",
            err=True,
        )
        raise typer.Exit(1)

    result = HookManager.install(project_root, force=force)
    if result["installed"]:
        if result["action"] == "skip":
            typer.echo(result["message"])
            typer.echo("Use --force to re-install.")
        else:
            typer.echo(f"Post-commit hook {result['action']}.")
            typer.echo(f"  Path: {result['hook_path']}")
            typer.echo(f"  Python: {sys.executable}")
            typer.echo(f"  Project root: {project_root.resolve()}")
    else:
        typer.echo(f"Error: {result['message']}", err=True)
        raise typer.Exit(1)


@hooks_app.command(name="uninstall")
def hooks_uninstall(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (defaults to auto-detect from CWD)",
    ),
) -> None:
    """Remove the CodeGraph managed post-commit hook.

    Only the CodeGraph managed block is removed — any user-written
    hook content is preserved.

    Examples:
        codegraph hooks uninstall
        codegraph hooks uninstall --root /path/to/project
    """
    project_root = _resolve_hook_project_root(root)
    if project_root is None:
        typer.echo("Error: Could not determine project root.", err=True)
        raise typer.Exit(1)

    result = HookManager.uninstall(project_root)
    typer.echo(result["message"])
    if not result["uninstalled"]:
        raise typer.Exit(1)


@hooks_app.command(name="status")
def hooks_status(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (defaults to auto-detect from CWD)",
    ),
    json_output: bool = typer.Option(
        False, "--json",
        help="Output status as JSON",
    ),
) -> None:
    """Show the current state of the post-commit hook.

    Examples:
        codegraph hooks status
        codegraph hooks status --json
    """
    import json

    project_root = _resolve_hook_project_root(root)
    if project_root is None:
        typer.echo("Error: Could not determine project root.", err=True)
        raise typer.Exit(1)

    status = HookManager.status(project_root)

    if json_output:
        typer.echo(json.dumps(status, indent=2, ensure_ascii=False))
        return

    typer.echo("Hook status:")
    typer.echo(f"  State:                  {status['state']}")
    typer.echo(f"  Installed:              {status['installed']}")
    typer.echo(f"  Auto-update on commit:  {status['auto_update_on_commit']}")
    typer.echo(f"  Hook path:              {status['hook_path'] or 'N/A'}")
    typer.echo(f"  Last run:               {status['last_run_at'] or 'never'}")
    typer.echo(f"  Total runs:             {status['total_runs']}")
    typer.echo(f"  Total failures:         {status['total_failures']}")
    typer.echo(f"  Valid:                  {status['valid']}")
    if status["issues"]:
        typer.echo("  Issues:")
        for issue in status["issues"]:
            typer.echo(f"    - {issue}")


# ── config command group ───────────────────────────────────────────────────

config_app = typer.Typer(
    name="config",
    help="Get or set CodeGraph configuration values",
)
app.add_typer(config_app)


_VALID_CONFIG_KEYS = {"auto_update_on_commit"}


@config_app.command(name="set")
def config_set(
    key: str = typer.Argument(..., help="Config key to set"),
    value: str = typer.Argument(..., help="New value"),
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (defaults to auto-detect from CWD)",
    ),
) -> None:
    """Set a configuration value.

    Supported keys:
        auto_update_on_commit  (true/false)

    Examples:
        codegraph config set auto_update_on_commit false
        codegraph config set auto_update_on_commit true
    """
    if key not in _VALID_CONFIG_KEYS:
        typer.echo(
            f"Error: Unknown config key '{key}'. "
            f"Valid keys: {', '.join(sorted(_VALID_CONFIG_KEYS))}",
            err=True,
        )
        raise typer.Exit(1)

    project_root = _resolve_hook_project_root(root)
    if project_root is None:
        typer.echo("Error: Could not determine project root.", err=True)
        raise typer.Exit(1)

    cg_dir = project_root / ".codegraph"
    if not cg_dir.exists():
        typer.echo("Error: No .codegraph directory found. Run 'codegraph init' first.", err=True)
        raise typer.Exit(1)

    # Parse value
    if key == "auto_update_on_commit":
        raw = value.strip().lower()
        if raw in ("true", "1", "yes", "on"):
            parsed: object = True
        elif raw in ("false", "0", "no", "off"):
            parsed = False
        else:
            typer.echo(
                f"Error: '{value}' is not a valid boolean. Use true or false.",
                err=True,
            )
            raise typer.Exit(1)
    else:
        parsed = value

    state_store = IndexStateStore(cg_dir)
    state_store.update_hook_config(**{key: parsed})
    typer.echo(f"Set {key} = {parsed}")


@config_app.command(name="get")
def config_get(
    key: str = typer.Argument(..., help="Config key to get"),
    root: str = typer.Option(
        None, "--root", "-r",
        help="Project root (defaults to auto-detect from CWD)",
    ),
) -> None:
    """Get a configuration value.

    Examples:
        codegraph config get auto_update_on_commit
    """
    project_root = _resolve_hook_project_root(root)
    if project_root is None:
        typer.echo("Error: Could not determine project root.", err=True)
        raise typer.Exit(1)

    cg_dir = project_root / ".codegraph"
    if not cg_dir.exists():
        typer.echo("Error: No .codegraph directory found. Run 'codegraph init' first.", err=True)
        raise typer.Exit(1)

    state_store = IndexStateStore(cg_dir)
    hook_config = state_store.get_hook_config()

    if key in hook_config:
        typer.echo(str(hook_config[key]))
    else:
        typer.echo(f"Error: Unknown config key '{key}'.", err=True)
        raise typer.Exit(1)


def _resolve_project_root() -> Path | None:
    """Walk up from CWD to find a .codegraph directory.

    Returns the project root (parent of .codegraph), or None.
    """
    env_root = os.environ.get("CODEGRAPH_PROJECT_ROOT")
    if env_root:
        env_path = Path(env_root).resolve()
        if env_path.is_dir():
            return env_path

    start = Path.cwd()
    for parent in [start] + list(start.parents):
        if (parent / ".codegraph").is_dir():
            return parent
    return None


def _resolve_hook_project_root(root_arg: str | None) -> Path | None:
    """Resolve the project root for hook commands.

    Priority: --root arg > CODEGRAPH_PROJECT_ROOT env > auto-detect.
    """
    if root_arg:
        return Path(root_arg).resolve()

    env_root = os.environ.get("CODEGRAPH_PROJECT_ROOT")
    if env_root:
        env_path = Path(env_root).resolve()
        if env_path.is_dir():
            return env_path

    return _resolve_project_root()


# ── configure command group ──────────────────────────────────────────────

configure_app = typer.Typer(
    name="configure",
    help="Configure MCP server integration for AI coding agents (Claude Code, Cursor)",
)
app.add_typer(configure_app)

enrich_app = typer.Typer(
    name="enrich",
    help="LLM-assisted semantic enrichment via agent-side analysis",
)
app.add_typer(enrich_app)


def _show_configure_success(root: str | None = None) -> None:
    """Show project root and index status after a successful configure.

    When ``root`` is None, the config is global auto-detect mode (no fixed
    CODEGRAPH_PROJECT_ROOT). The MCP server will auto-detect the current
    project by walking up from CWD.
    """
    from pathlib import Path as _Path

    if root is None:
        typer.echo("Mode: global auto-detect")
        typer.echo("  The MCP server will auto-detect the current project from CWD.")
        typer.echo("  It walks up from the working directory to find .codegraph/.")
        typer.echo()
        # Check if CWD has a .codegraph index
        cg_dir = _Path.cwd() / ".codegraph"
        if cg_dir.exists() and (cg_dir / "graph.json").exists():
            typer.echo(f"Current directory has index:")
            typer.echo(f"  {_Path.cwd()}")
        else:
            typer.echo("Current directory:")
            typer.echo(f"  {_Path.cwd()}")
            typer.echo("  No .codegraph found in CWD. Run: codegraph init")
        typer.echo()
        typer.echo("To fix project root later:")
        typer.echo("  codegraph configure all --force")
        typer.echo()
        return

    root_path = _Path(root).resolve()
    cg_dir = root_path / ".codegraph"

    typer.echo(f"Mode: project-bound")
    typer.echo(f"  This MCP config is bound to:")
    typer.echo(f"  {root_path}")
    typer.echo(f"  The MCP server will always query this project.")
    typer.echo(f"  Use global auto-detect config if you want CodeGraph to follow")
    typer.echo(f"  the current project:  codegraph configure all --force")
    typer.echo()

    if cg_dir.exists() and (cg_dir / "graph.json").exists():
        # Check freshness
        try:
            from codegraph.indexer.status import detect_status
            from codegraph.storage.file_store import FileStore
            store = FileStore(cg_dir)
            metadata = store.load_metadata()
            if metadata:
                result = detect_status(root_path, metadata)
                typer.echo(f"Index:")
                typer.echo(f"  {result.status}")
            else:
                typer.echo(f"Index:")
                typer.echo(f"  present")
        except Exception:
            typer.echo(f"Index:")
            typer.echo(f"  present")
    else:
        typer.echo(f"Index:")
        typer.echo(f"  not found — run: codegraph init")
    typer.echo()
    typer.echo("If you move projects, run:")
    typer.echo("  codegraph configure all --force")
    typer.echo()


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
    command_override: str = typer.Option(
        None, "--command", "-c",
        help="MCP server command (default: current Python interpreter). Use 'codegraph' for the CLI entry point.",
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
        codegraph configure all --command codegraph
    """
    from codegraph.configure import configure_target, ConfigTarget, build_server_config

    # When --project is used without explicit --root, pin to CWD
    effective_root = root
    if project and effective_root is None:
        effective_root = str(Path.cwd().resolve())

    results = []
    for target in (ConfigTarget.CLAUDE, ConfigTarget.CURSOR):
        result = configure_target(
            target,
            root=effective_root,
            command_override=command_override,
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
        typer.echo("Use --force to update.\n")
    else:
        # Show the actual command that was written
        server_cfg = build_server_config(root=effective_root, command_override=command_override)
        cmd_str = " ".join([server_cfg["command"]] + server_cfg["args"])
        typer.echo("Configured CodeGraph MCP.")
        typer.echo(f"Command:")
        typer.echo(f"  {cmd_str}")
        typer.echo()
        # Show root info (may be None for global auto-detect)
        cfg_root = server_cfg.get("env", {}).get("CODEGRAPH_PROJECT_ROOT")
        _show_configure_success(cfg_root)
        typer.echo("Next:")
        typer.echo("  codegraph doctor")
        typer.echo("  Restart Claude Code / Cursor.")
        typer.echo()


@configure_app.command(name="claude")
def configure_claude(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Set CODEGRAPH_PROJECT_ROOT env var in config",
    ),
    command_override: str = typer.Option(
        None, "--command", "-c",
        help="MCP server command (default: current Python interpreter). Use 'codegraph' for the CLI entry point.",
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
    from codegraph.configure import configure_target, ConfigTarget, build_server_config

    effective_root = root
    if project and effective_root is None:
        effective_root = str(Path.cwd().resolve())

    result = configure_target(
        ConfigTarget.CLAUDE,
        root=effective_root,
        command_override=command_override,
        project=project,
        force=force,
    )
    _print_configure_result(result)
    if result["status"] in ("configured", "overwritten"):
        server_cfg = build_server_config(root=effective_root, command_override=command_override)
        cfg_root = server_cfg.get("env", {}).get("CODEGRAPH_PROJECT_ROOT")
        _show_configure_success(cfg_root)


@configure_app.command(name="cursor")
def configure_cursor(
    root: str = typer.Option(
        None, "--root", "-r",
        help="Set CODEGRAPH_PROJECT_ROOT env var in config",
    ),
    command_override: str = typer.Option(
        None, "--command", "-c",
        help="MCP server command (default: current Python interpreter). Use 'codegraph' for the CLI entry point.",
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
    from codegraph.configure import configure_target, ConfigTarget, build_server_config

    effective_root = root
    if project and effective_root is None:
        effective_root = str(Path.cwd().resolve())

    result = configure_target(
        ConfigTarget.CURSOR,
        root=effective_root,
        command_override=command_override,
        project=project,
        force=force,
    )
    _print_configure_result(result)
    if result["status"] in ("configured", "overwritten"):
        server_cfg = build_server_config(root=effective_root, command_override=command_override)
        cfg_root = server_cfg.get("env", {}).get("CODEGRAPH_PROJECT_ROOT")
        _show_configure_success(cfg_root)


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


@configure_app.command(name="workflows")
def configure_workflows(
    agent: str = typer.Option(
        ..., "--agent", "-a",
        help="Target agent to install workflow commands for (e.g. 'claude')",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Overwrite existing workflow command files",
    ),
) -> None:
    """Install CodeGraph workflow commands for the target agent.

    Copies workflow command templates into the target project so that
    the agent can follow CodeGraph-first workflows via explicit slash
    commands like /codegraph-impact, /codegraph-test-audit, etc.

    Currently only ``--agent claude`` is supported, which writes
    markdown command files into ``.claude/commands/``.

    Examples:
        codegraph configure workflows --agent claude
        codegraph configure workflows --agent claude --force
    """
    if agent not in ("claude",):
        typer.echo(
            f"Error: Unsupported agent '{agent}'. "
            f"Currently only 'claude' is supported.",
            err=True,
        )
        raise typer.Exit(1)

    # Locate the template directory
    try:
        import codegraph
        pkg_dir = Path(codegraph.__file__).parent
    except Exception:
        typer.echo("Error: Could not locate codegraph package directory.", err=True)
        raise typer.Exit(1)

    templates_dir = pkg_dir / "templates" / "claude_commands"
    if not templates_dir.is_dir():
        typer.echo(
            f"Error: Template directory not found: {templates_dir}",
            err=True,
        )
        raise typer.Exit(1)

    # Target directory in CWD
    target_dir = Path.cwd() / ".claude" / "commands"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Command file list
    command_files = [
        "codegraph-impact.md",
        "codegraph-test-audit.md",
        "codegraph-explain.md",
        "codegraph-find.md",
        "codegraph-enrich.md",
    ]

    # Agent file list
    agent_files = [
        "codegraph-file-enricher.md",
        "codegraph-symbol-enricher.md",
        "codegraph-enrich-reviewer.md",
    ]

    installed: list[str] = []
    skipped: list[str] = []
    overwritten: list[str] = []
    errors: list[str] = []

    for filename in command_files:
        src = templates_dir / filename
        dst = target_dir / filename

        if not src.exists():
            errors.append(f"{filename}: template not found at {src}")
            continue

        if dst.exists() and not force:
            skipped.append(filename)
            continue

        action = "overwritten" if dst.exists() else "installed"
        try:
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            if action == "overwritten":
                overwritten.append(filename)
            else:
                installed.append(filename)
        except OSError as e:
            errors.append(f"{filename}: {e}")

    # ── Output ──────────────────────────────────────────────────────────
    if errors:
        typer.echo()
        for err in errors:
            typer.echo(f"  [ERROR] {err}", err=True)

    if installed:
        typer.echo()
        typer.echo("Installed Claude Code workflow commands:")
        typer.echo()
        for f in installed:
            typer.echo(f"  - .claude/commands/{f}")

    if overwritten:
        typer.echo()
        typer.echo("Overwritten (--force):")
        typer.echo()
        for f in overwritten:
            typer.echo(f"  - .claude/commands/{f}")

    if skipped:
        typer.echo()
        for f in skipped:
            typer.echo(
                f"  [SKIP] .claude/commands/{f} already exists. "
                f"Use --force to overwrite."
            )

    if installed or overwritten:
        typer.echo()
        typer.echo("Use them in Claude Code:")
        typer.echo()
        typer.echo("  - /codegraph-impact")
        typer.echo("  - /codegraph-test-audit")
        typer.echo("  - /codegraph-explain")
        typer.echo("  - /codegraph-find")
        typer.echo("  - /codegraph-enrich")
        typer.echo()

    if skipped and not installed and not overwritten:
        typer.echo()
        typer.echo(
            "All workflow commands already exist. Use --force to overwrite."
        )
        typer.echo()

    # ── Agent templates ──────────────────────────────────────────────────

    agents_dir = pkg_dir / "templates" / "agents"
    if agents_dir.is_dir():
        target_agents_dir = Path.cwd() / ".claude" / "agents"
        target_agents_dir.mkdir(parents=True, exist_ok=True)

        ag_installed: list[str] = []
        ag_skipped: list[str] = []
        ag_errors: list[str] = []

        for filename in agent_files:
            src = agents_dir / filename
            dst = target_agents_dir / filename

            if not src.exists():
                ag_errors.append(f"{filename}: template not found at {src}")
                continue

            if dst.exists() and not force:
                ag_skipped.append(filename)
                continue

            try:
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                ag_installed.append(filename)
            except OSError as e:
                ag_errors.append(f"{filename}: {e}")

        if ag_errors:
            for err in ag_errors:
                typer.echo(f"  [ERROR] {err}", err=True)

        if ag_installed:
            typer.echo()
            typer.echo("Installed enrichment agent definitions:")
            typer.echo()
            for f in ag_installed:
                typer.echo(f"  - .claude/agents/{f}")

        if ag_skipped:
            for f in ag_skipped:
                typer.echo(
                    f"  [SKIP] .claude/agents/{f} already exists. "
                    f"Use --force to overwrite."
                )

    # ── Enrich usage hint ────────────────────────────────────────────────

    if "codegraph-enrich.md" in installed or "codegraph-enrich.md" in overwritten:
        typer.echo()
        typer.echo("Enrichment workflow available:")
        typer.echo()
        typer.echo("  - /codegraph-enrich")
        typer.echo()
        typer.echo("This runs agent-side LLM enrichment with zero API config:")
        typer.echo("  prepare -> analyze -> validate -> import")
        typer.echo()


# ── configure git-hook command ────────────────────────────────────────────


@configure_app.command(name="git-hook")
def configure_git_hook(
    pre_commit_impact: bool = typer.Option(
        False, "--pre-commit-impact",
        help="Install optional pre-commit impact check hook",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Overwrite existing pre-commit hook (backs up old hook)",
    ),
) -> None:
    """Install optional Git hooks for CodeGraph workflows.

    Currently supports --pre-commit-impact which installs a hook that
    runs ``codegraph workflow impact`` on staged changed files before
    each commit.  The hook is advisory only — it never blocks commits.

    Examples:
        codegraph configure git-hook --pre-commit-impact
        codegraph configure git-hook --pre-commit-impact --force
    """
    import stat
    from datetime import datetime

    if not pre_commit_impact:
        typer.echo(
            "Usage: codegraph configure git-hook --pre-commit-impact\n"
            "\n"
            "Install optional Git pre-commit impact hook.\n"
            "\n"
            "Options:\n"
            "  --pre-commit-impact  Install pre-commit impact check hook\n"
            "  --force              Overwrite existing hook (backs up old hook)",
        )
        return

    cwd = Path.cwd().resolve()

    # 1. Check if current directory is a Git repo
    git_dir = cwd / ".git"
    if git_dir.is_file():
        # Worktree support — .git is a file containing "gitdir: <real-path>"
        try:
            content = git_dir.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir: "):
                real = content[len("gitdir: "):]
                real_path = Path(real)
                if not real_path.is_absolute():
                    real_path = (cwd / real_path).resolve()
                if real_path.is_dir():
                    git_dir = real_path
        except (OSError, UnicodeDecodeError):
            pass

    if not git_dir.is_dir():
        typer.echo(
            "Error: Not a Git repository.\n"
            f"  Current directory: {cwd}\n"
            "  Run this command from within a Git repository.",
            err=True,
        )
        raise typer.Exit(1)

    # 2. Ensure hooks directory exists
    hooks_dir = git_dir / "hooks"
    if not hooks_dir.exists():
        typer.echo(
            f"Error: .git/hooks/ directory not found at {hooks_dir}",
            err=True,
        )
        raise typer.Exit(1)

    hook_path = hooks_dir / "pre-commit"

    # 3. Build the hook script
    from codegraph.hooks.template import build_pre_commit_impact_hook_script

    hook_script = build_pre_commit_impact_hook_script()

    # 4. Handle existing hook
    if hook_path.exists():
        if not force:
            typer.echo(
                "Existing pre-commit hook found. Not overwritten.\n"
                "\n"
                "To install manually, add the CodeGraph hook block from:\n"
                "  docs/git-hooks.md\n"
                "\n"
                "Or rerun with:\n"
                "  codegraph configure git-hook --pre-commit-impact --force"
            )
            return

        # --force: backup existing hook before overwriting
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup_path = hooks_dir / "pre-commit.codegraph.bak"

        if backup_path.exists():
            # Add timestamp to avoid overwriting old backup
            backup_path = hooks_dir / f"pre-commit.codegraph.bak.{timestamp}"

        existing_content = hook_path.read_bytes()
        backup_path.write_bytes(existing_content)
        typer.echo(f"Backed up existing hook to: {backup_path.name}")

    # 5. Write the hook
    hook_path.write_text(hook_script, encoding="utf-8", newline="\n")

    # 6. Make executable on Unix
    if sys.platform != "win32":
        st = hook_path.stat()
        hook_path.chmod(st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # 7. Output success
    typer.echo()
    typer.echo("Installed CodeGraph pre-commit impact hook:")
    typer.echo()
    typer.echo(f"  {hook_path}")
    typer.echo()
    typer.echo("This hook runs:")
    typer.echo("  codegraph workflow impact --files <staged files> --change-type unknown --format markdown")
    typer.echo()
    typer.echo("Default behavior: warning only. It does not block commits.")


# ── enrich command group ──────────────────────────────────────────────────


@enrich_app.command(name="prepare")
def enrich_prepare(
    max_files: int = typer.Option(
        100, "--max-files", "-n",
        help="Maximum number of files to include in the prepare output",
    ),
    max_symbols_per_file: int = typer.Option(
        20, "--max-symbols-per-file", "-s",
        help="Maximum symbols per file",
    ),
    output: str = typer.Option(
        None, "--output", "-o",
        help="Output path (default: .codegraph/intermediate/enrich_input.json)",
    ),
    root: str | None = typer.Option(
        None, "--root", "-r",
        help="Project root directory (auto-detected if omitted)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Overwrite existing output file",
    ),
) -> None:
    """Generate bounded input JSON for enrichment agents.

    Reads the code graph index and produces per-file metadata
    (symbols, imports, exports, callers, callees, snippets) within
    configured limits. The output is written to
    .codegraph/intermediate/enrich_input.json by default.
    """
    from codegraph.enrich.prepare import generate_prepare_output, write_prepare_output
    from codegraph.storage.intermediate_store import IntermediateStore

    store, cg_dir = _load_store(root)

    # Default: use intermediate store for batch tracking
    intermediate = IntermediateStore(cg_dir)
    default_path = intermediate.dir / "enrich_input.json"
    output_path = Path(output) if output else default_path

    if output_path.exists() and not force:
        typer.echo(f"Error: {output_path} already exists. Use --force to overwrite.", err=True)
        raise typer.Exit(1)

    prepare_output = generate_prepare_output(
        store=store,
        cg_dir=cg_dir,
        max_files=max_files,
        max_symbols_per_file=max_symbols_per_file,
    )
    written_path = write_prepare_output(prepare_output, cg_dir)
    # Also write a timestamped batch copy for audit trail
    intermediate.write_batch("prepare", prepare_output.model_dump())
    typer.echo(f"Prepare output written to: {written_path}")
    typer.echo(f"  Files: {len(prepare_output.files)}")
    typer.echo(f"  Total symbols: {sum(len(f.symbols) for f in prepare_output.files)}")
    typer.echo(f"  Constraints: max_summary={prepare_output.constraints.max_summary_chars} chars")


@enrich_app.command(name="validate")
def enrich_validate(
    input_path: str = typer.Argument(
        None,
        help="Path to agent output JSON (default: .codegraph/intermediate/enrich_output.json)",
    ),
    root: str | None = typer.Option(
        None, "--root", "-r",
        help="Project root directory (auto-detected if omitted)",
    ),
    strict: bool = typer.Option(
        False, "--strict",
        help="Treat warnings as errors",
    ),
) -> None:
    """Validate agent-produced enrichment output.

    Checks JSON schema, path/symbol existence, evidence validity,
    and constraint compliance. Use after the enrichment agent has
    produced its output.
    """
    from codegraph.enrich.validate import validate_agent_output
    from codegraph.storage.intermediate_store import IntermediateStore

    store, cg_dir = _load_store(root)
    output_path = Path(input_path) if input_path else cg_dir / "intermediate" / "enrich_output.json"

    if not output_path.exists():
        typer.echo(f"Error: File not found: {output_path}", err=True)
        raise typer.Exit(1)

    result = validate_agent_output(output_path, store)

    # Write validation report to intermediate directory for audit trail
    intermediate = IntermediateStore(cg_dir)
    intermediate.write_validation_report(result)

    typer.echo()
    typer.echo(f"Validation {'PASSED' if result.valid else 'FAILED'}")
    typer.echo(f"  Files checked: {result.stats.get('files_checked', 0)}")
    typer.echo(f"  Symbols checked: {result.stats.get('symbols_checked', 0)}")
    typer.echo(f"  Errors: {result.stats.get('total_errors', 0)}")
    typer.echo(f"  Warnings: {result.stats.get('total_warnings', 0)}")

    if result.errors:
        typer.echo()
        typer.echo("Errors:")
        for e in result.errors:
            typer.echo(f"  [{e.severity.upper()}] {e.path}: {e.message}")
    if result.warnings:
        typer.echo()
        typer.echo("Warnings:")
        for w in result.warnings:
            typer.echo(f"  [{w.severity.upper()}] {w.path}: {w.message}")

    exit_code = 1 if result.errors or (strict and result.warnings) else 0
    if exit_code:
        raise typer.Exit(exit_code)


@enrich_app.command(name="import")
def enrich_import(
    input_path: str = typer.Argument(
        None,
        help="Path to validated agent output JSON (default: .codegraph/intermediate/enrich_output.json)",
    ),
    root: str | None = typer.Option(
        None, "--root", "-r",
        help="Project root directory (auto-detected if omitted)",
    ),
    skip_validation: bool = typer.Option(
        False, "--skip-validation",
        help="Skip validation (dangerous: may import invalid data)",
    ),
) -> None:
    """Import validated enrichment data into the SQLite index.

    Reads validated agent output and writes enrichment fields
    (summary, role, responsibilities, edge_cases, test_relevance,
    confidence, evidence) to the nodes table. Tags are merged.
    """
    from codegraph.enrich.validate import validate_agent_output
    from codegraph.enrich.import_enrich import import_enrichment
    from codegraph.storage.intermediate_store import IntermediateStore

    store, cg_dir = _load_store(root)

    # Resolve input path: explicit arg > latest batch > default name
    if input_path:
        output_path = Path(input_path)
    else:
        intermediate = IntermediateStore(cg_dir)
        latest = intermediate.latest_batch()
        if latest:
            output_path = latest
        else:
            output_path = cg_dir / "intermediate" / "enrich_output.json"

    if not output_path.exists():
        typer.echo(f"Error: File not found: {output_path}", err=True)
        raise typer.Exit(1)

    if not skip_validation:
        result = validate_agent_output(output_path, store)
        if not result.valid:
            typer.echo("Error: Validation failed. Fix errors or use --skip-validation.", err=True)
            raise typer.Exit(1)
        if result.warnings:
            typer.echo(f"Warnings ({len(result.warnings)}):")
            for w in result.warnings[:5]:
                typer.echo(f"  - {w.path}: {w.message}")
            typer.echo()

    sqlite_path = cg_dir / "index.sqlite"
    if not sqlite_path.exists():
        typer.echo("Error: No SQLite index found. Run 'codegraph init' first.", err=True)
        raise typer.Exit(1)

    sqlite_store = SqliteStore(sqlite_path)
    sqlite_store.initialize()
    stats = import_enrichment(output_path, store, sqlite_store)
    sqlite_store.close()

    typer.echo("Import complete:")
    typer.echo(f"  Files enriched: {stats['file_count']}")
    typer.echo(f"  Symbols enriched: {stats['symbol_count']}")
    typer.echo(f"  Enriched at: {stats['enriched_at']}")


@enrich_app.command(name="status")
def enrich_status(
    root: str | None = typer.Option(
        None, "--root", "-r",
        help="Project root directory (auto-detected if omitted)",
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j",
        help="Output as JSON",
    ),
) -> None:
    """Show enrichment statistics.

    Displays how many nodes and files have been enriched,
    confidence breakdown, and last import time.
    """
    from codegraph.enrich.status import get_enrichment_status
    from codegraph.storage.intermediate_store import IntermediateStore

    cg_dir = _find_codegraph_dir(root)
    if cg_dir is None:
        typer.echo("Error: No .codegraph directory found. Run 'codegraph init' first.", err=True)
        raise typer.Exit(1)

    sqlite_path = cg_dir / "index.sqlite"
    if not sqlite_path.exists():
        typer.echo("Error: No SQLite index found. Run 'codegraph init' first.", err=True)
        raise typer.Exit(1)

    sqlite_store = SqliteStore(sqlite_path)
    sqlite_store.initialize()
    status = get_enrichment_status(sqlite_store)
    sqlite_store.close()

    # Load audit trail from intermediate store
    intermediate = IntermediateStore(cg_dir)
    trail = intermediate.audit_trail()

    if json_output:
        output = status.model_dump()
        output["audit_trail"] = trail
        typer.echo(json.dumps(output, indent=2))
    else:
        pct = (status.enriched_nodes / status.total_nodes * 100) if status.total_nodes > 0 else 0
        typer.echo()
        typer.echo("Enrichment Status")
        typer.echo("==================")
        typer.echo(f"  Total nodes:     {status.total_nodes}")
        typer.echo(f"  Enriched:        {status.enriched_nodes} ({pct:.1f}%)")
        typer.echo(f"  Pending:         {status.pending_nodes}")
        typer.echo(f"  Skipped:         {status.skipped_nodes}")
        typer.echo(f"  Errors:          {status.error_nodes}")
        typer.echo(f"  Enriched files:  {status.enriched_files} / {status.total_files}")
        typer.echo()
        typer.echo("Confidence breakdown (analyzed nodes):")
        for level, count in status.confidence_breakdown.items():
            typer.echo(f"  {level}: {count}")
        if status.last_enriched_at:
            typer.echo()
            typer.echo(f"  Last enriched:   {status.last_enriched_at}")

        # Audit trail
        if trail:
            typer.echo()
            typer.echo("Audit Trail (batch files):")
            for entry in trail:
                typer.echo(
                    f"  {entry['batch_file']} — "
                    f"{entry['file_count']} files, "
                    f"{entry['symbol_count']} symbols"
                )
        else:
            typer.echo()
            typer.echo("Audit Trail: no batch files found.")


@enrich_app.command(name="clear")
def enrich_clear(
    root: str | None = typer.Option(
        None, "--root", "-r",
        help="Project root directory (auto-detected if omitted)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Remove all enrichment data from the index.

    Resets enrichment columns to defaults on all nodes.
    The structural index (symbols, edges) is not affected.
    """
    from codegraph.enrich.clear import clear_enrichment

    if not force:
        typer.echo("This will remove all enrichment data from the index.")
        typer.echo("Structural index (symbols, edges) will NOT be affected.")
        answer = typer.prompt("Continue? [y/N]")
        if answer.lower() not in ("y", "yes"):
            typer.echo("Aborted.")
            raise typer.Exit(0)

    cg_dir = _find_codegraph_dir(root)
    if cg_dir is None:
        typer.echo("Error: No .codegraph directory found. Run 'codegraph init' first.", err=True)
        raise typer.Exit(1)

    sqlite_path = cg_dir / "index.sqlite"
    if not sqlite_path.exists():
        typer.echo("Error: No SQLite index found. Run 'codegraph init' first.", err=True)
        raise typer.Exit(1)

    sqlite_store = SqliteStore(sqlite_path)
    sqlite_store.initialize()
    count = clear_enrichment(sqlite_store)
    sqlite_store.close()

    typer.echo(f"Enrichment cleared from {count} nodes.")


@enrich_app.command(name="batches")
def enrich_batches(
    prune: bool = typer.Option(
        False, "--prune",
        help="Remove old batch files, keeping the most recent",
    ),
    keep: int = typer.Option(
        10, "--keep", "-k",
        help="Number of most recent batch files to keep when pruning",
    ),
    clear: bool = typer.Option(
        False, "--clear",
        help="Remove ALL intermediate files (batch + validation reports)",
    ),
    root: str | None = typer.Option(
        None, "--root", "-r",
        help="Project root directory (auto-detected if omitted)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Skip confirmation prompt for --clear",
    ),
) -> None:
    """List, prune, or clear intermediate enrichment batch files.

    Shows audit trail of batch enrichment files in
    .codegraph/intermediate/. Use --prune to remove old batches
    (keeps the most recent N). Use --clear to remove everything.
    """
    from codegraph.storage.intermediate_store import IntermediateStore

    cg_dir = _find_codegraph_dir(root)
    if cg_dir is None:
        typer.echo("Error: No .codegraph directory found. Run 'codegraph init' first.", err=True)
        raise typer.Exit(1)

    intermediate = IntermediateStore(cg_dir)

    if clear:
        if not force:
            typer.echo("This will remove ALL intermediate files:")
            typer.echo(f"  {intermediate.dir}")
            answer = typer.prompt("Continue? [y/N]")
            if answer.lower() not in ("y", "yes"):
                typer.echo("Aborted.")
                raise typer.Exit(0)
        count = intermediate.clear_all()
        typer.echo(f"Removed {count} intermediate file(s).")
        return

    if prune:
        removed = intermediate.prune_batches(keep=keep)
        typer.echo(f"Removed {removed} batch file(s); kept {keep} most recent.")
        return

    # Default: list batches
    batches = intermediate.list_batches()
    if not batches:
        typer.echo("No batch files found in .codegraph/intermediate/")
        return

    trail = intermediate.audit_trail()
    typer.echo()
    typer.echo(f"Batch files ({len(batches)}):")
    typer.echo("=" * 60)
    for entry in trail:
        typer.echo(
            f"  {entry['batch_file']}"
        )
        typer.echo(
            f"    Files: {entry['file_count']}, "
            f"Symbols: {entry['symbol_count']}"
        )
        if entry.get("enriched_at"):
            typer.echo(f"    Enriched at: {entry['enriched_at']}")
        typer.echo()


# ── workflow command group ──────────────────────────────────────────────────

workflow_app = typer.Typer(
    name="workflow",
    help="Deterministic workflow commands for CI, hooks, and fallback",
)
app.add_typer(workflow_app)


@workflow_app.command(name="impact")
def workflow_impact(
    files: str | None = typer.Option(
        None, "--files",
        help="Comma-separated file paths you plan to edit",
    ),
    symbols: str | None = typer.Option(
        None, "--symbols",
        help="Comma-separated symbol names you plan to modify",
    ),
    change_type: str = typer.Option(
        "unknown", "--change-type", "-t",
        help="Change type: refactor | bugfix | feature | test | cleanup | unknown",
    ),
    description: str | None = typer.Option(
        None, "--description",
        help="Optional short description (used in report summary only)",
    ),
    include_tests: bool = typer.Option(
        True, "--include-tests/--no-include-tests",
        help="Include affected tests in the report",
    ),
    limit: int = typer.Option(
        50, "--limit", "-l",
        help="Maximum results per category",
    ),
    fmt: str = typer.Option(
        "markdown", "--format",
        help="Output format: markdown | json",
    ),
    output: str | None = typer.Option(
        None, "--output", "-o",
        help="Write report to file instead of stdout",
    ),
    force_output: bool = typer.Option(
        False, "--force-output",
        help="Overwrite existing output file",
    ),
    root: str | None = typer.Option(
        None, "--root", "-r",
        help="Project root (auto-detected from cwd if omitted)",
    ),
) -> None:
    """Run a deterministic impact analysis workflow.

    This is the CLI fallback for ``codegraph_pre_edit_check``. It produces
    a Markdown (default) or JSON impact report based on the local CodeGraph
    index. Prefer MCP ``codegraph_pre_edit_check`` when available; use this
    CLI command when MCP is unavailable, in CI, in hooks, or when you need
    a deterministic written report.

    Examples:

        codegraph workflow impact --files src/server.ts --change-type refactor

        codegraph workflow impact --symbols startServer,applyMiddleware --change-type cleanup --format json

        codegraph workflow impact --files app/api/auth.py --output .codegraph/reports/impact.md
    """
    VALID_CHANGE_TYPES = {"refactor", "bugfix", "feature", "test", "cleanup", "unknown"}
    VALID_FORMATS = {"markdown", "json"}

    # ── Validate arguments ──────────────────────────────────────────────
    def _exit_error(msg: str) -> None:
        """Exit with error, using JSON format if requested."""
        if fmt == "json":
            typer.echo(json.dumps({
                "ok": False,
                "error": msg,
                "workflow": "impact",
            }, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"Error: {msg}", err=True)
        raise typer.Exit(1)

    if change_type not in VALID_CHANGE_TYPES:
        _exit_error(
            f"Invalid change_type '{change_type}'. "
            f"Valid: {', '.join(sorted(VALID_CHANGE_TYPES))}"
        )

    if fmt not in VALID_FORMATS:
        _exit_error(
            f"Invalid format '{fmt}'. Valid: {', '.join(sorted(VALID_FORMATS))}"
        )

    # Parse comma-separated inputs
    planned_file_list: list[str] = []
    if files:
        planned_file_list = [f.strip() for f in files.split(",") if f.strip()]

    planned_symbol_names: list[str] = []
    if symbols:
        planned_symbol_names = [s.strip() for s in symbols.split(",") if s.strip()]

    if not planned_file_list and not planned_symbol_names:
        _exit_error("At least one of --files or --symbols must be provided.")

    # ── Load store ──────────────────────────────────────────────────────
    try:
        store, cg_dir = _load_store(root)
    except typer.Exit:
        raise
    except Exception as e:
        if fmt == "json":
            typer.echo(json.dumps({
                "ok": False,
                "error": str(e),
                "workflow": "impact",
            }, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    # ── Build index status ──────────────────────────────────────────────
    from codegraph.indexer.status import get_index_status

    project_root = str(cg_dir.parent)
    idx_status = get_index_status(project_root)
    fresh = idx_status.get("status", "unknown")

    # ── Run pre-edit check ──────────────────────────────────────────────
    from codegraph.workflow import run_pre_edit_check

    try:
        result = run_pre_edit_check(
            store=store,
            files=planned_file_list,
            symbols=planned_symbol_names,
            change_type=change_type,
            description=description,
            include_tests=include_tests,
            limit=limit,
        )
    except Exception as e:
        if fmt == "json":
            typer.echo(json.dumps({
                "ok": False,
                "error": f"Workflow failed: {e}",
                "workflow": "impact",
            }, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"Error: Workflow failed: {e}", err=True)
        raise typer.Exit(1)

    # ── Format output ───────────────────────────────────────────────────
    if fmt == "json":
        output_text = _format_workflow_json(
            result=result,
            files=planned_file_list,
            symbols=planned_symbol_names,
            change_type=change_type,
            idx_status=idx_status,
        )
    else:
        output_text = _format_workflow_markdown(
            result=result,
            files=planned_file_list,
            symbols=planned_symbol_names,
            change_type=change_type,
            fresh=fresh,
            project_root=project_root,
            idx_status=idx_status,
        )

    # ── Write output ────────────────────────────────────────────────────
    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists() and not force_output:
            typer.echo(
                f"Error: Output file '{output}' already exists. "
                f"Use --force-output to overwrite.",
                err=True,
            )
            raise typer.Exit(1)
        out_path.write_text(output_text, encoding="utf-8")
        typer.echo(f"Report written to: {out_path.resolve()}")
    else:
        typer.echo(output_text)


def _format_workflow_json(
    result: dict,
    files: list[str],
    symbols: list[str],
    change_type: str,
    idx_status: dict,
) -> str:
    """Format workflow result as JSON."""
    stats = idx_status.get("stats", {})
    warnings_list = result.get("warnings", [])
    # Convert index warnings for JSON output
    idx_warnings_list: list[dict] = []
    raw_idx_warnings = idx_status.get("warnings", [])
    if isinstance(raw_idx_warnings, list):
        for w in raw_idx_warnings:
            if isinstance(w, dict):
                idx_warnings_list.append(w)
            else:
                idx_warnings_list.append({"message": str(w)})

    output_data = {
        "ok": True,
        "workflow": "impact",
        "input": {
            "files": files,
            "symbols": symbols,
            "change_type": change_type,
        },
        "index_status": {
            "freshness": idx_status.get("status", "unknown"),
            "project_root": idx_status.get("project_root", ""),
            "index_path": str(idx_status.get("index_path") or ""),
            "indexed_at": idx_status.get("indexed_at"),
            "stats": {
                "files": stats.get("files", 0),
                "symbols": stats.get("symbols", 0),
                "edges": stats.get("edges", 0),
            } if stats else {},
        },
        "planned_symbols": result.get("planned_symbols", []),
        "impact_summary": result.get("impact_summary", {}),
        "affected_callers": result.get("affected_callers", []),
        "affected_files": result.get("affected_files", []),
        "affected_tests": result.get("affected_tests", []),
        "recommended_checks": result.get("recommended_checks", []),
        "warnings": warnings_list + idx_warnings_list,
    }
    return json.dumps(output_data, indent=2, ensure_ascii=False)


def _format_workflow_markdown(
    result: dict,
    files: list[str],
    symbols: list[str],
    change_type: str,
    fresh: str,
    project_root: str,
    idx_status: dict,
) -> str:
    """Format workflow result as Markdown."""
    impact_summary = result.get("impact_summary", {})
    planned_symbols = result.get("planned_symbols", [])
    affected_callers = result.get("affected_callers", [])
    affected_files = result.get("affected_files", [])
    affected_tests = result.get("affected_tests", [])
    recommended_checks = result.get("recommended_checks", [])
    warnings_list = result.get("warnings", [])
    change_desc = result.get("description", "")

    lines: list[str] = []

    # Header
    lines.append("# CodeGraph Impact Workflow Report")
    lines.append("")

    # Input section
    lines.append("## Input")
    lines.append(f"- Change type: {change_type}")
    if change_desc:
        lines.append(f"- Description: {change_desc}")
    if files:
        lines.append("- Files:")
        for f in files:
            lines.append(f"  - `{f}`")
    if symbols:
        lines.append("- Symbols:")
        for s in symbols:
            lines.append(f"  - `{s}`")
    lines.append("")

    # Index Status
    lines.append("## Index Status")
    lines.append(f"- Freshness: {fresh}")
    lines.append(f"- Project root: `{project_root}`")
    idx_warnings = idx_status.get("warnings", [])
    if isinstance(idx_warnings, list) and idx_warnings:
        for w in idx_warnings:
            if isinstance(w, dict):
                lines.append(f"- Warning: {w.get('message', str(w))}")
            else:
                lines.append(f"- Warning: {w}")

    # Stale index warning
    if fresh == "stale":
        lines.append("")
        lines.append(
            "> **⚠ Warning: Index is stale.** "
            "Results may not reflect recent file changes."
        )
        cs = idx_status.get("last_change_summary", {})
        total = sum(cs.values()) if cs else 0
        if total > 0:
            lines.append(f"> {total} file(s) changed since last index.")
        suggested = idx_status.get("suggested_fix", "Run: codegraph init --incremental")
        lines.append(f"> {suggested}")
    elif fresh == "missing":
        lines.append("")
        lines.append(
            "> **⚠ Warning: Index is missing.** Run `codegraph init` first."
        )
    elif fresh == "indexing":
        lines.append("")
        lines.append(
            "> **ℹ Index update is in progress.** "
            "Results may reflect the previous index."
        )
    elif fresh == "error":
        lines.append("")
        lines.append(
            f"> **⚠ Index error:** "
            f"{idx_status.get('last_error', 'Unknown error')}"
        )

    lines.append("")

    # Planned Symbols
    lines.append("## Planned Symbols")
    if planned_symbols:
        lines.append("| Symbol | Type | File | Lines |")
        lines.append("|---|---|---|---|")
        for ps in planned_symbols[:20]:
            sym_name = ps.get("symbol", "?")
            sym_type = ps.get("type", "?")
            sym_file = ps.get("file", "?")
            line_start = ps.get("line_start")
            line_end = ps.get("line_end")
            lines_str = f"L{line_start}" if line_start else ""
            if line_end and line_end != line_start:
                lines_str += f"-{line_end}"
            lines.append(
                f"| `{sym_name}` | {sym_type} | `{sym_file}` | {lines_str} |"
            )
    else:
        lines.append("*(none)*")
    lines.append("")

    # Impact Summary
    lines.append("## Impact Summary")
    risk_level = impact_summary.get("risk_level", "unknown")
    confidence = impact_summary.get("confidence", "unknown")
    summary = impact_summary.get("summary", "")
    lines.append(f"- Risk level: **{risk_level}**")
    lines.append(f"- Confidence: {confidence}")
    lines.append(f"- Summary: {summary}")
    lines.append("")

    # Affected Callers
    lines.append("## Affected Callers")
    if affected_callers:
        lines.append("| Symbol | File | Distance | Confidence |")
        lines.append("|---|---|---|---|")
        for c in affected_callers[:30]:
            cid = c.get("symbol_id", "?")
            cname = c.get("name", cid)
            cfile = c.get("file_path", "?")
            cdist = c.get("distance", 0)
            cconf = c.get("confidence", 1.0)
            lines.append(
                f"| `{cname}` | `{cfile}` | {cdist} | {cconf:.0%} |"
            )
    else:
        lines.append("*(none)*")
    lines.append("")

    # Affected Files
    lines.append("## Affected Files")
    if affected_files:
        lines.append("| File | Priority | Layer |")
        lines.append("|---|---|---|")
        for af in affected_files[:20]:
            af_path = af.get("file_path", "?")
            af_priority = af.get("priority", "medium")
            af_layer = af.get("layer", "unknown")
            lines.append(f"| `{af_path}` | {af_priority} | {af_layer} |")
    else:
        lines.append("*(none)*")
    lines.append("")

    # Affected Tests
    lines.append("## Affected Tests")
    if affected_tests:
        lines.append("| Test | File | Confidence |")
        lines.append("|---|---|---|")
        for t in affected_tests[:20]:
            tname = t.get("name", t.get("symbol_id", "?"))
            tfile = t.get("file_path", "?")
            tconf = t.get("confidence", 1.0)
            lines.append(f"| `{tname}` | `{tfile}` | {tconf:.0%} |")
    else:
        lines.append("*(none)*")
    lines.append("")

    # Recommended Checks
    lines.append("## Recommended Checks")
    if recommended_checks:
        for i, rc in enumerate(recommended_checks, 1):
            rc_type = rc.get("type", "?")
            rc_target = rc.get("target", "?")
            rc_reason = rc.get("reason", "")
            lines.append(f"{i}. **[{rc_type}]** `{rc_target}`: {rc_reason}")
    else:
        lines.append("*(none)*")
    lines.append("")

    # Warnings
    if warnings_list:
        lines.append("## Warnings")
        for w in warnings_list:
            w_msg = w.get("message", str(w))
            lines.append(f"- [!] {w_msg}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(
        "*This is a CodeGraph heuristic impact workflow report. "
        "It does not execute tests or modify files.*"
    )
    lines.append("")

    return "\n".join(lines)


# ── workflow test-audit ──────────────────────────────────────────────────


@workflow_app.command(name="test-audit")
def workflow_test_audit(
    paths: str | None = typer.Option(
        None, "--paths",
        help="Comma-separated path glob patterns to restrict scope (e.g. 'src/**,backend/**')",
    ),
    types: str | None = typer.Option(
        None, "--types",
        help="Comma-separated node types (e.g. 'function,method,class'). Default: production types.",
    ),
    limit: int = typer.Option(
        50, "--limit", "-l",
        help="Maximum results per category",
    ),
    include_low_confidence: bool = typer.Option(
        True, "--include-low-confidence/--no-low-confidence",
        help="Include low-confidence test links",
    ),
    fmt: str = typer.Option(
        "markdown", "--format",
        help="Output format: markdown | json",
    ),
    output: str | None = typer.Option(
        None, "--output", "-o",
        help="Write report to file instead of stdout",
    ),
    force_output: bool = typer.Option(
        False, "--force-output",
        help="Overwrite existing output file",
    ),
    root: str | None = typer.Option(
        None, "--root", "-r",
        help="Project root (auto-detected from cwd if omitted)",
    ),
) -> None:
    """Run a deterministic test coverage audit workflow.

    Lists production symbols and files without confident ``tested_by``
    coverage signals. This is a heuristic graph signal, NOT runtime line
    coverage.

    Examples:

        codegraph workflow test-audit

        codegraph workflow test-audit --paths src/** --types function,method

        codegraph workflow test-audit --format json --output .codegraph/reports/test-audit.json
    """
    VALID_FORMATS = {"markdown", "json"}

    if fmt not in VALID_FORMATS:
        typer.echo(
            f"Error: Invalid format '{fmt}'. Valid: {', '.join(sorted(VALID_FORMATS))}",
            err=True,
        )
        raise typer.Exit(1)

    # Parse comma-separated inputs
    path_list: list[str] | None = None
    if paths:
        path_list = [p.strip() for p in paths.split(",") if p.strip()]

    type_list: list[str] | None = None
    if types:
        type_list = [t.strip() for t in types.split(",") if t.strip()]

    # Load store
    try:
        store, cg_dir = _load_store(root)
    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    project_root = str(cg_dir.parent)

    # Run test audit
    from codegraph.workflow import run_test_audit

    try:
        result = run_test_audit(
            store=store,
            paths=path_list,
            types=type_list,
            include_low_confidence=include_low_confidence,
            limit=limit,
            project_root=project_root,
        )
    except Exception as e:
        if fmt == "json":
            typer.echo(json.dumps({
                "ok": False,
                "error": f"Workflow failed: {e}",
                "workflow": "test-audit",
            }, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"Error: Workflow failed: {e}", err=True)
        raise typer.Exit(1)

    # Format output
    if fmt == "json":
        output_text = _format_test_audit_json(result, path_list, type_list)
    else:
        output_text = _format_test_audit_markdown(result, path_list, type_list, project_root)

    # Write output
    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists() and not force_output:
            typer.echo(
                f"Error: Output file '{output}' already exists. "
                f"Use --force-output to overwrite.",
                err=True,
            )
            raise typer.Exit(1)
        out_path.write_text(output_text, encoding="utf-8")
        typer.echo(f"Report written to: {out_path.resolve()}")
    else:
        typer.echo(output_text)


def _format_test_audit_json(
    result: dict,
    paths: list[str] | None,
    types: list[str] | None,
) -> str:
    """Format test audit result as JSON."""
    summary = result.get("summary", {})
    output_data = {
        "ok": True,
        "workflow": "test-audit",
        "input": {
            "paths": paths,
            "types": types,
        },
        "summary": summary,
        "symbols_without_tests": result.get("symbols_without_tests", []),
        "files_without_tests": result.get("files_without_tests", []),
        "low_confidence_links": result.get("low_confidence_links", []),
        "warnings": result.get("warnings", []),
    }
    return json.dumps(output_data, indent=2, ensure_ascii=False)


def _format_test_audit_markdown(
    result: dict,
    paths: list[str] | None,
    types: list[str] | None,
    project_root: str,
) -> str:
    """Format test audit result as Markdown."""
    summary = result.get("summary", {})
    symbols_without = result.get("symbols_without_tests", [])
    files_without = result.get("files_without_tests", [])
    low_conf_links = result.get("low_confidence_links", [])
    warnings_list = result.get("warnings", [])

    lines: list[str] = []
    lines.append("# CodeGraph Test Audit Report")
    lines.append("")

    # Input
    lines.append("## Input")
    if paths:
        lines.append(f"- Paths: {', '.join(paths)}")
    if types:
        lines.append(f"- Types: {', '.join(types)}")
    if not paths and not types:
        lines.append("- Scope: all production symbols")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append(f"- Production symbols checked: {summary.get('production_symbols_checked', 0)}")
    lines.append(f"- Symbols without test signal: {summary.get('symbols_without_test_signal', 0)}")
    lines.append(f"- Confidence: {summary.get('confidence', 'unknown')}")
    msg = summary.get("message", "")
    if msg:
        lines.append(f"- Message: {msg}")
    lines.append("")
    lines.append(
        "> **Note:** This is a heuristic graph signal — not runtime line coverage. "
        "Symbols listed here lack ``tested_by`` edges in the code graph."
    )
    lines.append("")

    # Symbols Without Tests
    lines.append("## Symbols Without Confident Test Coverage")
    if symbols_without:
        lines.append("| Symbol | File | Type | Suggested Test File |")
        lines.append("|---|---|---|---|")
        for s in symbols_without[:30]:
            s_name = s.get("symbol", s.get("symbol_id", "?"))
            s_file = s.get("file", "?")
            s_type = s.get("type", "?")
            s_test = s.get("suggested_test_file", "")
            lines.append(f"| `{s_name}` | `{s_file}` | {s_type} | `{s_test}` |")
    else:
        lines.append("*(none found — all production symbols have test coverage signals)*")
    lines.append("")

    # Files Without Tests
    lines.append("## Files Without Test Coverage")
    if files_without:
        lines.append("| File | Symbols Without Test |")
        lines.append("|---|---|")
        for f in files_without[:20]:
            f_path = f.get("file", "?")
            f_count = f.get("symbols_without_test_signal", 0)
            lines.append(f"| `{f_path}` | {f_count} |")
    else:
        lines.append("*(none)*")
    lines.append("")

    # Low Confidence Links
    if low_conf_links:
        lines.append("## Low Confidence Test Links")
        lines.append("| Symbol | Test | Confidence |")
        lines.append("|---|---|---|")
        for link in low_conf_links[:15]:
            l_sym = link.get("production_symbol", link.get("production_symbol_id", "?"))
            l_test = link.get("test_symbol", link.get("test_symbol_id", "?"))
            l_conf = link.get("confidence", "?")
            lines.append(f"| `{l_sym}` | `{l_test}` | {l_conf} |")
        lines.append("")

    # Warnings
    if warnings_list:
        lines.append("## Warnings")
        for w in warnings_list:
            w_msg = w.get("message", str(w)) if isinstance(w, dict) else str(w)
            lines.append(f"- [!] {w_msg}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*Generated by CodeGraph workflow test-audit. "
        "This is a heuristic graph signal, not runtime line coverage.*"
    )
    lines.append("")

    return "\n".join(lines)


# ── workflow explain ─────────────────────────────────────────────────────


@workflow_app.command(name="explain")
def workflow_explain(
    symbol: str | None = typer.Option(
        None, "--symbol", "-s",
        help="Symbol name or ID to explain (e.g. 'MemoryService' or 'src/server.py::login')",
    ),
    file: str | None = typer.Option(
        None, "--file", "-f",
        help="File path relative to project root to explain",
    ),
    include_snippet: bool = typer.Option(
        True, "--include-snippet/--no-snippet",
        help="Include source code snippet in explanation",
    ),
    include_tests: bool = typer.Option(
        True, "--include-tests/--no-tests",
        help="Include test coverage signal",
    ),
    include_relationships: bool = typer.Option(
        True, "--include-relationships/--no-relationships",
        help="Include top callers/callees",
    ),
    max_snippet_lines: int = typer.Option(
        40, "--max-snippet-lines",
        help="Maximum snippet lines",
    ),
    fmt: str = typer.Option(
        "markdown", "--format",
        help="Output format: markdown | json",
    ),
    output: str | None = typer.Option(
        None, "--output", "-o",
        help="Write report to file instead of stdout",
    ),
    force_output: bool = typer.Option(
        False, "--force-output",
        help="Overwrite existing output file",
    ),
    root: str | None = typer.Option(
        None, "--root", "-r",
        help="Project root (auto-detected from cwd if omitted)",
    ),
) -> None:
    """Run a deterministic symbol or file explanation workflow.

    Produces a structured, evidence-backed explanation of a symbol or file
    using indexed metadata and heuristics — no LLM, no embeddings.

    Examples:

        codegraph workflow explain --symbol MemoryService

        codegraph workflow explain --file src/server.ts

        codegraph workflow explain --symbol "src/server.py::login" --format json
    """
    VALID_FORMATS = {"markdown", "json"}

    if fmt not in VALID_FORMATS:
        typer.echo(
            f"Error: Invalid format '{fmt}'. Valid: {', '.join(sorted(VALID_FORMATS))}",
            err=True,
        )
        raise typer.Exit(1)

    if not symbol and not file:
        typer.echo("Error: Provide either --symbol or --file.", err=True)
        raise typer.Exit(1)

    if symbol and file:
        typer.echo("Error: Provide exactly one of --symbol or --file, not both.", err=True)
        raise typer.Exit(1)

    # Load store
    try:
        store, cg_dir = _load_store(root)
    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    project_root = str(cg_dir.parent)

    # Run explain
    from codegraph.workflow import run_explain

    try:
        result = run_explain(
            store=store,
            symbol=symbol,
            file=file,
            include_snippet=include_snippet,
            include_tests=include_tests,
            include_relationships=include_relationships,
            max_snippet_lines=max_snippet_lines,
            project_root=project_root,
        )
    except Exception as e:
        if fmt == "json":
            typer.echo(json.dumps({
                "ok": False,
                "error": f"Workflow failed: {e}",
                "workflow": "explain",
            }, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"Error: Workflow failed: {e}", err=True)
        raise typer.Exit(1)

    if not result.get("ok"):
        if fmt == "json":
            typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"Error: {result.get('error', 'Unknown error')}", err=True)
        raise typer.Exit(1)

    # Format output
    if fmt == "json":
        output_text = json.dumps(result, indent=2, ensure_ascii=False)
    else:
        output_text = _format_explain_markdown(result, project_root)

    # Write output
    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists() and not force_output:
            typer.echo(
                f"Error: Output file '{output}' already exists. "
                f"Use --force-output to overwrite.",
                err=True,
            )
            raise typer.Exit(1)
        out_path.write_text(output_text, encoding="utf-8")
        typer.echo(f"Report written to: {out_path.resolve()}")
    else:
        typer.echo(output_text)


def _format_explain_markdown(result: dict, project_root: str) -> str:
    """Format explain result as Markdown."""
    lines: list[str] = []
    lines.append("# CodeGraph Explain Report")
    lines.append("")

    target_kind = result.get("target_kind", "unknown")
    target = result.get("target", {})

    if target_kind == "symbol":
        # Symbol explanation
        symbol_name = target.get("symbol", target.get("name", "?"))
        symbol_id = target.get("symbol_id", "?")
        symbol_type = target.get("type", "?")
        file_path = target.get("file", "?")
        line_start = target.get("line_start")
        line_end = target.get("line_end")

        lines.append("## Symbol")
        lines.append(f"- Name: **{symbol_name}**")
        lines.append(f"- ID: `{symbol_id}`")
        lines.append(f"- Type: {symbol_type}")
        lines.append(f"- File: `{file_path}`")
        if line_start:
            loc_str = f"L{line_start}"
            if line_end and line_end != line_start:
                loc_str += f"-{line_end}"
            lines.append(f"- Location: {loc_str}")
        lines.append("")

        # Explanation
        explanation = result.get("explanation", {})
        summary = explanation.get("summary", "")
        confidence = explanation.get("confidence", "unknown")
        basis = explanation.get("basis", [])

        if summary:
            lines.append("## Summary")
            lines.append(f"{summary} (confidence: {confidence})")
            if basis:
                lines.append(f"Basis: {', '.join(basis)}")
            lines.append("")

        # Implementation signals
        impl_signals = result.get("implementation_signals", {})
        if impl_signals:
            active_signals = {k: v for k, v in impl_signals.items() if v}
            if active_signals:
                lines.append("## Implementation Signals")
                for key, val in active_signals.items():
                    if isinstance(val, bool):
                        lines.append(f"- {key}: {'yes' if val else 'no'}")
                    else:
                        lines.append(f"- {key}: {val}")
                lines.append("")

        # Relationships
        relationships = result.get("relationships", {})
        callers = relationships.get("top_callers", [])
        callers_count = relationships.get("callers_count", len(callers))
        callees = relationships.get("top_callees", [])
        callees_count = relationships.get("callees_count", len(callees))

        if callers:
            lines.append(f"## Top Callers ({callers_count})")
            lines.append("| Caller | File | Confidence |")
            lines.append("|---|---|---|")
            for c in callers[:10]:
                c_name = c.get("name", c.get("symbol_id", "?"))
                c_file = c.get("file_path", "?")
                c_conf = c.get("confidence", "?")
                c_conf_str = f"{c_conf:.0%}" if isinstance(c_conf, (int, float)) else str(c_conf)
                lines.append(f"| `{c_name}` | `{c_file}` | {c_conf_str} |")
            lines.append("")

        if callees:
            lines.append(f"## Top Callees ({callees_count})")
            lines.append("| Callee | File | Confidence |")
            lines.append("|---|---|---|")
            for c in callees[:10]:
                c_name = c.get("name", c.get("symbol_id", "?"))
                c_file = c.get("file_path", "?")
                c_conf = c.get("confidence", "?")
                c_conf_str = f"{c_conf:.0%}" if isinstance(c_conf, (int, float)) else str(c_conf)
                lines.append(f"| `{c_name}` | `{c_file}` | {c_conf_str} |")
            lines.append("")

        # Source snippet
        snippet = result.get("source_snippet", {})
        if snippet and snippet.get("snippet"):
            lines.append("## Source Snippet")
            lines.append("```python")
            lines.append(snippet["snippet"].strip())
            lines.append("```")
            lines.append("")

        # Test coverage
        test_signal = result.get("test_signal", {})
        if test_signal:
            lines.append("## Test Coverage Signal")
            tc_status = test_signal.get("status", "unknown")
            tc_count = test_signal.get("tested_by_count", 0)
            lines.append(f"- Status: {tc_status}")
            lines.append(f"- Test count: {tc_count}")
            related_tests = test_signal.get("related_tests", [])
            if related_tests:
                for t in related_tests[:5]:
                    t_name = t.get("name", t.get("symbol_id", "?"))
                    t_file = t.get("file_path", "?")
                    lines.append(f"  - `{t_name}` (`{t_file}`)")
            lines.append("")

    elif target_kind == "file":
        # File explanation
        target_file = target.get("file", "?")

        primary_symbols = result.get("primary_symbols", [])
        symbol_count = result.get("symbol_count", 0)
        likely_role = result.get("likely_role", "unknown")
        role_confidence = result.get("likely_role_confidence", "unknown")
        impl_signals = result.get("implementation_signals", {})

        lines.append("## File")
        lines.append(f"- Path: `{target_file}`")
        lines.append(f"- Symbols: {symbol_count}")
        lines.append(f"- Likely Role: **{likely_role}** (confidence: {role_confidence})")
        lines.append("")

        if impl_signals:
            active_signals = {k: v for k, v in impl_signals.items() if v}
            if active_signals:
                lines.append("## Implementation Signals")
                for key, val in active_signals.items():
                    if isinstance(val, list):
                        val_str = ", ".join(str(v) for v in val[:10])
                        lines.append(f"- {key}: {val_str}")
                    elif isinstance(val, bool):
                        lines.append(f"- {key}: {'yes' if val else 'no'}")
                    else:
                        lines.append(f"- {key}: {val}")
                lines.append("")

        if primary_symbols:
            lines.append("## Primary Symbols")
            lines.append("| Symbol | Type | Lines |")
            lines.append("|---|---|---|")
            for ps in primary_symbols[:15]:
                ps_name = ps.get("name", ps.get("symbol_id", "?"))
                ps_type = ps.get("type", "?")
                ps_loc = ps.get("location", {})
                ps_lines = ""
                if ps_loc:
                    start = ps_loc.get("line_start", "")
                    end = ps_loc.get("line_end", "")
                    ps_lines = f"L{start}" if start else ""
                    if end and end != start:
                        ps_lines += f"-{end}"
                lines.append(f"| `{ps_name}` | {ps_type} | {ps_lines} |")
            lines.append("")

        # Test signal
        test_signal = result.get("test_signal", {})
        if test_signal:
            lines.append("## Test Coverage Signal")
            tc_status = test_signal.get("status", "unknown")
            tc_count = test_signal.get("tested_by_count", 0)
            lines.append(f"- Status: {tc_status}")
            lines.append(f"- Test count: {tc_count}")
            lines.append("")

    # Warnings
    warnings_list = result.get("warnings", [])
    if warnings_list:
        lines.append("## Warnings")
        for w in warnings_list:
            w_msg = w.get("message", str(w)) if isinstance(w, dict) else str(w)
            lines.append(f"- [!] {w_msg}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*Generated by CodeGraph workflow explain. "
        "Evidence-backed explanation using indexed graph metadata.*"
    )
    lines.append("")

    return "\n".join(lines)


# ── workflow find ─────────────────────────────────────────────────────────


@workflow_app.command(name="find")
def workflow_find(
    query: str = typer.Argument(
        ..., help="Search keyword — symbol name, file path fragment, or docstring keyword",
    ),
    types: str | None = typer.Option(
        None, "--types", "-t",
        help="Comma-separated node types (e.g. 'function,method,class')",
    ),
    paths: str | None = typer.Option(
        None, "--paths", "-p",
        help="Comma-separated path glob patterns (e.g. 'src/**,app/api/**')",
    ),
    limit: int = typer.Option(
        20, "--limit", "-l",
        help="Maximum results to return (max 100)",
    ),
    include_tests: bool = typer.Option(
        True, "--include-tests/--no-tests",
        help="Include test symbols in results",
    ),
    fmt: str = typer.Option(
        "markdown", "--format",
        help="Output format: markdown | json",
    ),
    output: str | None = typer.Option(
        None, "--output", "-o",
        help="Write report to file instead of stdout",
    ),
    force_output: bool = typer.Option(
        False, "--force-output",
        help="Overwrite existing output file",
    ),
    root: str | None = typer.Option(
        None, "--root", "-r",
        help="Project root (auto-detected from cwd if omitted)",
    ),
) -> None:
    """Run a deterministic symbol search workflow.

    Search for functions, classes, methods, routes, services, or
    framework entry points by name, file path, or docstring keyword.

    Examples:

        codegraph workflow find login

        codegraph workflow find MemoryService --types class

        codegraph workflow find auth --paths src/api/** --format json
    """
    VALID_FORMATS = {"markdown", "json"}

    if fmt not in VALID_FORMATS:
        typer.echo(
            f"Error: Invalid format '{fmt}'. Valid: {', '.join(sorted(VALID_FORMATS))}",
            err=True,
        )
        raise typer.Exit(1)

    # Parse comma-separated inputs
    type_list: list[str] | None = None
    if types:
        type_list = [t.strip() for t in types.split(",") if t.strip()]

    path_list: list[str] | None = None
    if paths:
        path_list = [p.strip() for p in paths.split(",") if p.strip()]

    # Load store
    try:
        store, cg_dir = _load_store(root)
    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    # Run find
    from codegraph.workflow import run_find

    try:
        result = run_find(
            store=store,
            query=query,
            types=type_list,
            paths=path_list,
            limit=limit,
            include_tests=include_tests,
        )
    except Exception as e:
        if fmt == "json":
            typer.echo(json.dumps({
                "ok": False,
                "error": f"Workflow failed: {e}",
                "workflow": "find",
            }, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"Error: Workflow failed: {e}", err=True)
        raise typer.Exit(1)

    # Format output
    if fmt == "json":
        output_text = json.dumps({
            "ok": True,
            "workflow": "find",
            "input": {
                "query": query,
                "types": type_list,
                "paths": path_list,
            },
            **result,
        }, indent=2, ensure_ascii=False)
    else:
        output_text = _format_find_markdown(result, type_list, path_list)

    # Write output
    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists() and not force_output:
            typer.echo(
                f"Error: Output file '{output}' already exists. "
                f"Use --force-output to overwrite.",
                err=True,
            )
            raise typer.Exit(1)
        out_path.write_text(output_text, encoding="utf-8")
        typer.echo(f"Report written to: {out_path.resolve()}")
    else:
        typer.echo(output_text)


def _format_find_markdown(
    result: dict,
    types: list[str] | None,
    paths: list[str] | None,
) -> str:
    """Format find result as Markdown."""
    query = result.get("query", "")
    total = result.get("total", 0)
    results = result.get("results", [])

    lines: list[str] = []
    lines.append("# CodeGraph Find Results")
    lines.append("")

    lines.append("## Query")
    lines.append(f"- Search: **{query}**")
    if types:
        lines.append(f"- Types: {', '.join(types)}")
    if paths:
        lines.append(f"- Paths: {', '.join(paths)}")
    lines.append(f"- Results: {total}")
    lines.append("")

    if results:
        lines.append("## Results")
        lines.append("| # | Symbol | Type | File | Score | Match |")
        lines.append("|---|---|---|---|---|---|")
        for i, r in enumerate(results, 1):
            r_name = r.get("name", r.get("symbol_id", "?"))
            r_type = r.get("type", "?")
            r_file = r.get("file_path", "?")
            r_score = r.get("score", "?")
            r_match = ", ".join(r.get("match_sources", []))
            lines.append(f"| {i} | `{r_name}` | {r_type} | `{r_file}` | {r_score:.1f} | {r_match} |")
    else:
        lines.append("## Results")
        lines.append("*(no results found)*")
        lines.append("")
        lines.append("> Try broadening the query, removing type/path filters, or checking")
        lines.append("> `codegraph_repo_status` to confirm the index covers the right project.")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by CodeGraph workflow find.*")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    app()
