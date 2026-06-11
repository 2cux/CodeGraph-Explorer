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

        # MCP protocol compliance: verify tools return dicts, not double-encoded strings
        from codegraph.mcp_server import _respond_ok, _respond_error, ZERO_TELEMETRY_STATEMENT
        test_ok = _respond_ok({"test": True}, tool="check")
        test_err = _respond_error("TEST", "check", tool="check")
        if isinstance(test_ok, dict) and isinstance(test_err, dict):
            typer.echo("  [OK] MCP tools return structured dicts (protocol-compliant)")
        else:
            typer.echo("  [FAIL] MCP tools return strings (double-encoded JSON)", err=True)
        typer.echo(f"  [OK] Zero telemetry: {ZERO_TELEMETRY_STATEMENT[:80]}...")
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

                issue_counts = report.get("issue_counts", {})
                typer.echo(
                    f"     Auto-corrected: {issue_counts.get('auto_corrected', 0)}"
                )
                typer.echo(
                    f"     Dropped:        {issue_counts.get('dropped', 0)}"
                )
                typer.echo(
                    f"     Warnings:       {issue_counts.get('warnings', 0)}"
                )
                typer.echo(
                    f"     Fatal:          {issue_counts.get('fatal', 0)}"
                )

                stats = report.get("stats", {})
                typer.echo(
                    f"     Orphan ratio:       {stats.get('orphan_ratio', 0):.1%}"
                )
                typer.echo(
                    f"     External ratio:     {stats.get('external_ratio', 0):.1%}"
                )
                typer.echo(
                    f"     Low-conf edge ratio:{stats.get('low_confidence_ratio', 0):.1%}"
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

    # 7. MCP project root validation
    typer.echo("7. MCP project root validation")
    for label, cfg_path in config_paths:
        data = read_config(cfg_path)
        server_cfg = data.get("mcpServers", {}).get(MCP_SERVER_NAME)
        if not server_cfg:
            continue
        env_root = server_cfg.get("env", {}).get("CODEGRAPH_PROJECT_ROOT")
        if not env_root:
            fail(f"{label}: CODEGRAPH_PROJECT_ROOT is not set in config")
            typer.echo(f"       Run: codegraph configure {'cursor' if 'Cursor' in label else 'claude'} --force")
            continue
        root_path = Path(env_root)
        if not root_path.exists():
            fail(f"{label}: {env_root} — path does not exist")
            typer.echo(f"       Run: codegraph configure {'cursor' if 'Cursor' in label else 'claude'} --force")
            continue
        if not root_path.is_dir():
            fail(f"{label}: {env_root} — is not a directory")
            continue
        cg_subdir = root_path / ".codegraph"
        if not cg_subdir.exists():
            fail(f"{label}: {env_root} — no .codegraph directory")
            typer.echo(f"       Run: cd {env_root} && codegraph init")
            continue
        if not (cg_subdir / "graph.json").exists():
            fail(f"{label}: {env_root} — .codegraph is incomplete (missing graph.json)")
            typer.echo(f"       Run: cd {env_root} && codegraph init --force")
            continue
        ok(f"{label}: {env_root} — .codegraph found")
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


def _show_configure_success(root: str) -> None:
    """Show project root and index status after a successful configure."""
    from pathlib import Path as _Path

    root_path = _Path(root).resolve()
    cg_dir = root_path / ".codegraph"

    typer.echo(f"Project root:")
    typer.echo(f"  {root_path}")
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

    results = []
    for target in (ConfigTarget.CLAUDE, ConfigTarget.CURSOR):
        result = configure_target(
            target,
            root=root,
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
        typer.echo("Use --force to update CODEGRAPH_PROJECT_ROOT.\n")
    else:
        # Show the actual command that was written
        server_cfg = build_server_config(root=root, command_override=command_override)
        cmd_str = " ".join([server_cfg["command"]] + server_cfg["args"])
        typer.echo("Configured CodeGraph MCP.")
        typer.echo(f"Command:")
        typer.echo(f"  {cmd_str}")
        typer.echo()
        _show_configure_success(server_cfg["env"]["CODEGRAPH_PROJECT_ROOT"])
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

    result = configure_target(
        ConfigTarget.CLAUDE,
        root=root,
        command_override=command_override,
        project=project,
        force=force,
    )
    _print_configure_result(result)
    if result["status"] in ("configured", "overwritten"):
        server_cfg = build_server_config(root=root, command_override=command_override)
        _show_configure_success(server_cfg["env"]["CODEGRAPH_PROJECT_ROOT"])


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

    result = configure_target(
        ConfigTarget.CURSOR,
        root=root,
        command_override=command_override,
        project=project,
        force=force,
    )
    _print_configure_result(result)
    if result["status"] in ("configured", "overwritten"):
        server_cfg = build_server_config(root=root, command_override=command_override)
        _show_configure_success(server_cfg["env"]["CODEGRAPH_PROJECT_ROOT"])


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
