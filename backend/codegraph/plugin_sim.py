"""Plugin command simulation for AI Agent integration testing.

Simulates how an AI coding agent plugin (e.g. Cursor, Claude Code, Copilot)
would invoke ``/codegraph`` commands programmatically.

Usage::

    from codegraph.plugin_sim import CodeGraphPlugin

    plugin = CodeGraphPlugin()
    plugin.index("./examples/demo_python_project")

    # All commands return structured dicts for agent consumption
    result = plugin.search("login")
    print(result["results"])

    ctx = plugin.context("add MFA to login flow")
    print(ctx["pack_id"])
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CodeGraphPlugin:
    """Programmatic simulation of ``/codegraph`` plugin commands.

    Each method maps to a ``/codegraph <command>`` invocation, returning
    structured data suitable for AI Agent consumption.
    """

    def __init__(self, codegraph_dir: str | None = None) -> None:
        self._codegraph_dir = Path(codegraph_dir).resolve() if codegraph_dir else None

    # ── helpers ─────────────────────────────────────────────────────────

    def _require_index(self) -> Path:
        """Ensure .codegraph exists and return its path."""
        cg = self._resolve_codegraph_dir()
        if not cg:
            raise RuntimeError(
                "No .codegraph directory found. Run index() first."
            )
        return cg

    def _resolve_codegraph_dir(self) -> Path | None:
        if self._codegraph_dir and self._codegraph_dir.exists():
            return self._codegraph_dir
        # walk up from cwd
        start = Path.cwd()
        for parent in [start] + list(start.parents):
            candidate = parent / ".codegraph"
            if (candidate / "graph.json").exists():
                return candidate
        return None

    def _load_graph(self) -> dict[str, Any]:
        """Load and return the graph.json as a dict."""
        from codegraph.graph.models import CodeGraph
        from codegraph.graph.store import GraphStore

        cg_dir = self._require_index()
        graph_path = cg_dir / "graph.json"
        graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))

        store = GraphStore()
        store.load_from_graph(graph)
        return {"store": store, "graph": graph, "cg_dir": cg_dir}

    # ── Plugin Commands ─────────────────────────────────────────────────

    def index(
        self,
        root: str,
        force: bool = False,
        no_sqlite: bool = False,
    ) -> dict[str, Any]:
        """``/codegraph index`` — scan and build code graph.

        Simulates ``codegraph index <root> [-f] [--no-sqlite]``.

        Returns summary dict with repo metadata and counts.
        """
        from codegraph.indexer.graph_builder import build_index
        from codegraph.graph.models import CodeGraph, RepoInfo, GraphNode, GraphEdge
        from pydantic import TypeAdapter
        from codegraph.storage.file_store import FileStore

        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise ValueError(f"Not a directory: {root}")

        output_dir = root_path / ".codegraph"
        output_dir.mkdir(parents=True, exist_ok=True)

        if not force and (output_dir / "nodes.json").exists():
            return {
                "status": "skipped",
                "message": "Index already exists. Use force=True to re-index.",
                "root": str(root_path),
            }

        nodes, edges = build_index(root_path)

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

        # JSON output
        store = FileStore(output_dir)
        node_adapter = TypeAdapter(list[GraphNode])
        edge_adapter = TypeAdapter(list[GraphEdge])
        store.save_nodes(node_adapter.dump_python(nodes))
        store.save_edges(edge_adapter.dump_python(edges))

        graph_path = output_dir / "graph.json"
        graph_path.write_text(
            graph.model_dump_json(indent=2, exclude_none=True), encoding="utf-8",
        )

        # SQLite output
        if not no_sqlite:
            try:
                from codegraph.storage.sqlite_store import SqliteStore

                sqlite_path = output_dir / "index.sqlite"
                sql_store = SqliteStore(sqlite_path)
                sql_store.initialize()
                sql_store.save_nodes(node_adapter.dump_python(nodes))
                sql_store.save_edges(edge_adapter.dump_python(edges))
                sql_store.close()
            except Exception:
                pass  # non-critical

        self._codegraph_dir = output_dir

        return {
            "status": "indexed",
            "repo_name": repo_name,
            "root_path": str(root_path),
            "file_count": graph.repo.file_count,
            "symbol_count": graph.repo.symbol_count,
            "edge_count": len(edges),
            "languages": graph.repo.languages,
            "index_path": ".codegraph/",
        }

    def search(
        self,
        query: str,
        limit: int = 30,
    ) -> dict[str, Any]:
        """``/codegraph search <query>`` — search code symbols.

        Returns dict with ``results`` list and ``total`` count.
        Each result: ``symbol_id``, ``name``, ``type``, ``file_path``,
        ``score``, ``match_sources``.
        """
        from codegraph.graph import query as graph_query

        data = self._load_graph()
        store = data["store"]
        result = graph_query.search_symbols(store, query=query, limit=limit)

        return {
            "command": "search",
            "query": query,
            "total": result["total"],
            "results": result["results"][:limit],
        }

    def explain(
        self,
        symbol: str,
        depth: int = 2,
    ) -> dict[str, Any]:
        """``/codegraph explain <symbol>`` — explain a symbol.

        Returns callers, callees, and symbol metadata.
        """
        from codegraph.graph import query as graph_query
        from codegraph.graph.models import GraphNode

        data = self._load_graph()
        store = data["store"]

        # Resolve symbol
        node = store.get_node(symbol)
        if not node:
            symbol_lower = symbol.lower()
            for n in store.all_nodes():
                if n.name.lower() == symbol_lower:
                    node = n
                    break
        if not node:
            for n in store.all_nodes():
                if symbol.lower() in n.id.lower():
                    node = n
                    break
        if not node:
            return {"command": "explain", "symbol": symbol, "error": "not_found"}

        callers = graph_query.get_callers(store, node.id)
        callees = graph_query.get_callees(store, node.id)

        return {
            "command": "explain",
            "symbol_id": node.id,
            "name": node.name,
            "type": node.type.value,
            "file_path": node.file_path,
            "signature": node.signature,
            "docstring": node.docstring.split("\n")[0] if node.docstring else None,
            "callers": [{"node_id": c[0], "edge_type": c[1]} for c in callers],
            "callees": [{"node_id": c[0], "edge_type": c[1]} for c in callees],
            "caller_count": len(callers),
            "callee_count": len(callees),
        }

    def impact(
        self,
        symbol: str,
        depth: int = 2,
    ) -> dict[str, Any]:
        """``/codegraph impact <symbol>`` — analyze change impact.

        Returns affected symbols, files, risk assessment, recommendations.
        """
        from codegraph.graph import impact as graph_impact

        data = self._load_graph()
        store = data["store"]

        node = store.get_node(symbol)
        if not node:
            for n in store.all_nodes():
                if symbol.lower() in n.id.lower():
                    node = n
                    break
        if not node:
            return {"command": "impact", "symbol": symbol, "error": "not_found"}

        result = graph_impact.analyze_impact(store, node.id, depth=depth)

        return {
            "command": "impact",
            "symbol": node.id,
            "affected_symbols": result.get("affected_symbols", []),
            "affected_files": result.get("affected_files", []),
            "risk": result.get("risk", {}),
            "recommendations": result.get("recommendations", []),
            "warnings": result.get("warnings", []),
        }

    def context(
        self,
        task: str,
        max_tokens: int = 6000,
        depth: int = 2,
        include_tests: bool = True,
    ) -> dict[str, Any]:
        """``/codegraph context <task>`` — generate a Context Pack.

        This is the **core command** of CodeGraph Explorer. Returns a full
        Context Pack with entry points, call graph, impact, reading plan,
        and agent instructions.
        """
        from codegraph.context.pack_builder import build_context_pack

        data = self._load_graph()
        store = data["store"]
        cg_dir = data["cg_dir"]

        output_dir = cg_dir / "context_packs"

        pack = build_context_pack(
            store=store,
            task_description=task,
            max_tokens=max_tokens,
            depth=depth,
            include_tests=include_tests,
            output_dir=str(output_dir),
        )

        return json.loads(pack.model_dump_json(exclude_none=True))

    def dashboard(
        self,
        port: int = 8765,
        dev: bool = False,
    ) -> dict[str, Any]:
        """``/codegraph dashboard`` — start the dashboard server.

        Returns connection info. The actual server runs in a subprocess.
        """
        import subprocess

        cg = self._resolve_codegraph_dir()
        url = f"http://127.0.0.1:{port}"

        env = dict(
            _ROOT_DIR=str(Path.cwd()),
            _DEV_MODE="1" if dev else "0",
        )

        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "codegraph.api.main:app",
             "--host", "127.0.0.1", "--port", str(port),
             "--log-level", "warning"],
            env={**os.environ, **env},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        time.sleep(1.5)

        return {
            "command": "dashboard",
            "url": url,
            "pid": proc.pid,
            "has_index": cg is not None,
            "note": "Server running in background. Call dashboard_stop(pid) to stop.",
        }

    @staticmethod
    def dashboard_stop(pid: int) -> None:
        """Stop a dashboard server started via ``dashboard()``."""
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

    def repo_summary(self) -> dict[str, Any]:
        """Return the repository summary (like API GET /api/repo/summary)."""
        data = self._load_graph()
        store = data["store"]

        nodes = store.all_nodes()
        edges = store.all_edges()

        function_count = sum(1 for n in nodes if n.type.value in ("function", "method"))
        class_count = sum(1 for n in nodes if n.type.value == "class")
        low_conf = sum(1 for e in edges if e.confidence < 0.6)
        low_conf_ratio = low_conf / len(edges) if edges else 0.0

        return {
            "name": Path.cwd().name,
            "file_count": len({n.file_path for n in nodes}),
            "symbol_count": len(nodes),
            "function_count": function_count,
            "class_count": class_count,
            "edge_count": len(edges),
            "low_confidence_ratio": round(low_conf_ratio, 4),
        }

    def verify_index(self, root: str) -> dict[str, Any]:
        """Check if a project is already indexed, return status."""
        root_path = Path(root).resolve()
        output_dir = root_path / ".codegraph"
        graph_path = output_dir / "graph.json"

        if not graph_path.exists():
            return {
                "indexed": False,
                "root": str(root_path),
                "message": "Not indexed yet. Run index() first.",
            }

        try:
            from codegraph.graph.models import CodeGraph
            graph = CodeGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
            return {
                "indexed": True,
                "root": str(root_path),
                "file_count": graph.repo.file_count,
                "symbol_count": graph.repo.symbol_count,
                "edge_count": len(graph.edges),
                "indexed_at": graph.repo.indexed_at,
            }
        except Exception as e:
            return {
                "indexed": False,
                "root": str(root_path),
                "error": str(e),
                "message": "Index is corrupt. Re-index with force=True.",
            }
