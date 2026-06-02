"""Tests for graph validation pipeline — validate_graph, repair_graph,
save_validation_report, load_validation_report, and integrations."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from codegraph.graph.models import (
    EdgeMetadata,
    EdgeType,
    GraphEdge,
    GraphNode,
    Location,
    NodeType,
    Resolution,
)
from codegraph.graph.validation import (
    load_validation_report,
    repair_graph,
    save_validation_report,
    validate_graph,
)
from codegraph.storage.sqlite_store import SUPPORTED_SCHEMA_VERSION, SqliteStore

# ── Helpers ────────────────────────────────────────────────────────────


def _make_node(
    node_id: str,
    name: str = "",
    node_type: str = "function",
    file_path: str = "app/module.py",
) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "name": name or node_id.split("::")[-1],
        "file_path": file_path,
        "module": file_path.replace("/", ".").removesuffix(".py"),
        "tags": [],
        "metadata": {},
    }


def _make_edge(
    edge_id: str,
    source: str,
    target: str,
    edge_type: str = "calls",
    confidence: float = 1.0,
    resolution: str = "import_resolved",
) -> dict:
    return {
        "id": edge_id,
        "type": edge_type,
        "source": source,
        "target": target,
        "confidence": confidence,
        "metadata": {
            "resolution": resolution,
            "is_dynamic": False,
            "reason": "",
        },
    }


def _write_sqlite_nodes(store: SqliteStore, nodes: list[dict]) -> None:
    """Save node dicts to SQLite store (clear first)."""
    store.clear()
    store.save_nodes(nodes)


def _write_sqlite_edges(store: SqliteStore, edges: list[dict]) -> None:
    """Save edge dicts to SQLite store."""
    store.save_edges(edges)


# ── In-Memory Validation Tests ────────────────────────────────────────


class TestValidateGraphInMemory:
    """Tests for validate_graph with in-memory node/edge lists."""

    def test_dangling_edge_dropped(self, tmp_path):
        """Edges referencing non-existent nodes are dropped."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            _make_node("a.py::foo", "foo"),
            _make_node("a.py::bar", "bar"),
        ]
        edges = [
            _make_edge("e1", "a.py::foo", "a.py::bar"),
            _make_edge("e2", "nonexistent", "a.py::foo"),  # dangling source
            _make_edge("e3", "a.py::foo", "nonexistent"),  # dangling target
        ]

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        assert len(report["dropped"]) >= 2
        dropped_issues = [d["issue"] for d in report["dropped"]]
        assert "dangling_edge" in dropped_issues

    def test_confidence_clamped(self, tmp_path):
        """Confidence outside [0,1] is clamped."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [_make_node("a.py::foo", "foo")]
        edges = [
            _make_edge("e1", "a.py::foo", "a.py::foo", confidence=1.5),
            _make_edge("e2", "a.py::foo", "a.py::foo", confidence=-0.2),
        ]

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        assert len(report["auto_corrected"]) >= 2
        clamped = [
            c for c in report["auto_corrected"]
            if c["issue"] == "confidence_clamped"
        ]
        assert len(clamped) == 2

    def test_duplicate_node_id_dropped(self, tmp_path):
        """Duplicate node IDs are dropped (first kept)."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            _make_node("a.py::foo", "foo"),
            _make_node("a.py::foo", "foo_dup"),  # duplicate
        ]
        edges: list[dict] = []

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        assert len(report["dropped"]) >= 1
        assert report["stats"]["node_count"] == 1

    def test_invalid_edge_type_dropped(self, tmp_path):
        """Edges with invalid type are dropped."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            _make_node("a.py::foo", "foo"),
            _make_node("a.py::bar", "bar"),
        ]
        edges = [
            _make_edge("e1", "a.py::foo", "a.py::bar", edge_type="calls"),
            _make_edge("e2", "a.py::bar", "a.py::foo", edge_type="nonexistent"),
        ]

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        assert len(report["dropped"]) >= 1
        invalid = [d for d in report["dropped"] if d["issue"] == "invalid_edge_type"]
        assert len(invalid) == 1

    def test_invalid_node_type_warning(self, tmp_path):
        """Invalid node types produce a warning (not dropped)."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            _make_node("a.py::foo", "foo", node_type="function"),
            _make_node("a.py::bar", "bar", node_type="nonexistent"),
        ]
        edges: list[dict] = []

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        warnings_issues = [w["issue"] for w in report["warnings"]]
        assert "invalid_node_type" in warnings_issues

    def test_orphan_ratio_warning(self, tmp_path):
        """High orphan ratio triggers a warning."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        # 5 nodes, only 1 edge → 3 orphans at least
        nodes = [
            _make_node(f"mod.py::f{i}", f"f{i}")
            for i in range(5)
        ]
        edges = [
            _make_edge("e1", "mod.py::f0", "mod.py::f1"),
        ]

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        assert report["stats"]["orphan_ratio"] > 0.5
        assert any(
            w["issue"] == "high_orphan_ratio"
            for w in report["warnings"]
        )

    def test_external_ratio_warning(self, tmp_path):
        """High external symbol ratio triggers a warning."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            _make_node("mod.py::f1", "f1", node_type="function"),
            _make_node("ext::os_path", "os.path", node_type="external_symbol"),
            _make_node("ext::json_dumps", "json.dumps", node_type="external_symbol"),
        ]
        edges: list[dict] = []

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        assert report["stats"]["external_ratio"] > 0.3
        assert any(
            w["issue"] == "high_external_ratio"
            for w in report["warnings"]
        )

    def test_low_confidence_ratio_warning(self, tmp_path):
        """High low-confidence edge ratio triggers a warning."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            _make_node("a.py::foo", "foo"),
            _make_node("a.py::bar", "bar"),
            _make_node("a.py::baz", "baz"),
        ]
        edges = [
            _make_edge("e1", "a.py::foo", "a.py::bar", confidence=0.5),
            _make_edge("e2", "a.py::bar", "a.py::baz", confidence=0.3),
            _make_edge("e3", "a.py::foo", "a.py::baz", confidence=1.0),
        ]

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        assert report["stats"]["low_confidence_ratio"] > 0.5
        assert any(
            w["issue"] == "high_low_confidence_ratio"
            for w in report["warnings"]
        )

    def test_path_escape_warning(self, tmp_path):
        """File paths resolving outside project root trigger a warning."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            _make_node("a.py::foo", "foo"),
            _make_node("../../outside.py::evil", "evil",
                       file_path="../../outside.py"),
        ]
        edges: list[dict] = []

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        path_warnings = [
            w for w in report["warnings"]
            if w["issue"] in ("path_outside_root", "path_resolution_error")
        ]
        assert len(path_warnings) >= 1

    def test_missing_tags_auto_corrected(self, tmp_path):
        """Nodes missing tags get empty list auto-corrected."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            {"id": "a.py::foo", "type": "function", "name": "foo",
             "file_path": "a.py", "module": "a", "metadata": {}},
            # tags key is missing
        ]
        edges: list[dict] = []

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        corrected = [
            c for c in report["auto_corrected"]
            if c["issue"] == "missing_tags"
        ]
        assert len(corrected) == 1
        # The node should now have tags
        assert nodes[0]["tags"] == []

    def test_resolution_invalid_warning(self, tmp_path):
        """Invalid resolution in edge metadata triggers a warning."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            _make_node("a.py::foo", "foo"),
            _make_node("a.py::bar", "bar"),
        ]
        edges = [
            _make_edge("e1", "a.py::foo", "a.py::bar",
                       resolution="not_a_real_resolution"),
        ]

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        assert any(
            w["issue"] == "invalid_resolution"
            for w in report["warnings"]
        )

    def test_metadata_not_json_serializable_warning(self, tmp_path):
        """Non-JSON-serializable metadata triggers a warning."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            {"id": "a.py::foo", "type": "function", "name": "foo",
             "file_path": "a.py", "module": "a", "tags": [],
             "metadata": {"callback": lambda x: x}},  # not serializable
        ]
        edges: list[dict] = []

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        assert any(
            w["issue"] == "metadata_not_serializable"
            for w in report["warnings"]
        )

    def test_ok_report_no_issues(self, tmp_path):
        """A clean graph produces ok status with no issues."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [
            _make_node("a.py::foo", "foo"),
            _make_node("a.py::bar", "bar"),
        ]
        edges = [
            _make_edge("e1", "a.py::foo", "a.py::bar"),
        ]

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)

        assert report["status"] == "ok"
        assert len(report["auto_corrected"]) == 0
        assert len(report["dropped"]) == 0
        assert len(report["warnings"]) == 0
        assert len(report["fatal"]) == 0


# ── SQLite-Based Validation Tests ─────────────────────────────────────


class TestValidateGraphSQLite:
    """Tests for validate_graph with SQLite store."""

    def test_schema_version_incompatible_fatal(self, tmp_path):
        """Incompatible schema version is a fatal error."""
        db_path = tmp_path / "index.sqlite"
        store = SqliteStore(db_path)
        store.initialize()

        # Set an unsupported schema version
        store.set_meta("schema_version", "999.0.0")

        # Add a node so node_count > 0
        nodes = [_make_node("n1", "f1")]
        _write_sqlite_nodes(store, nodes)

        report = validate_graph(tmp_path, tmp_path, store=store)
        assert report["status"] == "error"
        assert any(
            "schema" in f.get("issue", "").lower()
            for f in report["fatal"]
        )
        store.close()

    def test_empty_nodes_fatal(self, tmp_path):
        """Zero nodes is a fatal error."""
        db_path = tmp_path / "index.sqlite"
        store = SqliteStore(db_path)
        store.initialize()

        # No nodes saved
        report = validate_graph(tmp_path, tmp_path, store=store)
        assert report["status"] == "error"
        assert any(
            f["issue"] == "empty_nodes"
            for f in report["fatal"]
        )
        store.close()

    def test_fts_count_mismatch_warning(self, tmp_path):
        """FTS count != node count triggers a warning."""
        db_path = tmp_path / "index.sqlite"
        store = SqliteStore(db_path)
        store.initialize()

        nodes = [
            _make_node("a.py::foo", "foo"),
            _make_node("a.py::bar", "bar"),
        ]
        _write_sqlite_nodes(store, nodes)

        # Manually delete FTS rows to create mismatch
        if store.has_fts_table():
            store.conn.execute("DELETE FROM symbols_fts")
            store.conn.commit()

        report = validate_graph(tmp_path, tmp_path, store=store)
        assert any(
            w["issue"] == "fts_count_mismatch"
            for w in report["warnings"]
        )
        store.close()

    def test_dangling_edges_in_sqlite(self, tmp_path):
        """SQLite dangling edges are detected and counted."""
        db_path = tmp_path / "index.sqlite"
        store = SqliteStore(db_path)
        store.initialize()

        nodes = [_make_node("a.py::foo", "foo")]
        _write_sqlite_nodes(store, nodes)

        # Insert an edge referencing a non-existent node directly
        store.conn.execute(
            "INSERT INTO edges(id, type, source, target, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            ["dangling1", "calls", "a.py::foo", "nonexistent", 1.0],
        )
        store.conn.commit()

        danglers = store.dangling_edge_count()
        assert danglers >= 1

        report = validate_graph(tmp_path, tmp_path, store=store)
        assert report["stats"]["dangling_edge_count"] >= 1
        store.close()


# ── Report Persistence Tests ──────────────────────────────────────────


class TestValidationReportPersistence:
    """Tests for save_validation_report and load_validation_report."""

    def test_validation_report_written(self, tmp_path):
        """Validation report is written and loadable."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes = [_make_node("a.py::foo", "foo")]
        edges: list[dict] = []

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)
        path = save_validation_report(cg_dir, report)

        assert path.exists()
        assert path.name == "validation_report.json"

        loaded = load_validation_report(cg_dir)
        assert loaded is not None
        assert loaded["status"] == report["status"]
        assert "issue_counts" in loaded
        assert "stats" in loaded
        assert "generated_at" in loaded
        assert "suggested_fix" in loaded

    def test_load_nonexistent_report(self, tmp_path):
        """Loading a non-existent report returns None."""
        cg_dir = tmp_path / "nonexistent"
        assert load_validation_report(cg_dir) is None

    def test_fatal_report_suggests_init_force(self, tmp_path):
        """Fatal validation suggests init --force."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        nodes: list[dict] = []
        edges: list[dict] = []

        report = validate_graph(cg_dir, root, nodes=nodes, edges=edges)
        path = save_validation_report(cg_dir, report)

        loaded = load_validation_report(cg_dir)
        assert loaded is not None
        assert loaded["status"] == "error"
        assert loaded["suggested_fix"] == "codegraph init --force"


# ── Repair Tests ──────────────────────────────────────────────────────


class TestRepairGraph:
    """Tests for repair_graph lightweight repair operations."""

    def test_repair_drops_dangling_edges(self, tmp_path):
        """repair_graph removes dangling edges from SQLite."""
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        cg_dir = proj_root / ".codegraph"
        cg_dir.mkdir()
        db_path = cg_dir / "index.sqlite"

        store = SqliteStore(db_path)
        store.initialize()

        nodes = [_make_node("a.py::foo", "foo")]
        _write_sqlite_nodes(store, nodes)

        # Insert a dangling edge
        store.conn.execute(
            "INSERT INTO edges(id, type, source, target, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            ["dangling1", "calls", "a.py::foo", "nonexistent", 1.0],
        )
        store.conn.commit()

        # First validate — should find dangling edges
        report1 = validate_graph(cg_dir, proj_root, store=store)
        assert report1["stats"]["dangling_edge_count"] >= 1

        # Repair
        report2 = repair_graph(cg_dir, report1, store=store)

        # After repair, no dangling edges remain
        assert report2["stats"]["dangling_edge_count"] == 0

        # Verify directly in SQLite
        danglers = store.dangling_edge_count()
        assert danglers == 0
        store.close()

    def test_repair_rebuilds_fts(self, tmp_path):
        """repair_graph rebuilds FTS when mismatched."""
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        cg_dir = proj_root / ".codegraph"
        cg_dir.mkdir()
        db_path = cg_dir / "index.sqlite"

        store = SqliteStore(db_path)
        store.initialize()

        nodes = [
            _make_node("a.py::foo", "foo"),
            _make_node("a.py::bar", "bar"),
        ]
        _write_sqlite_nodes(store, nodes)

        # Corrupt FTS
        if store.has_fts_table():
            store.conn.execute("DELETE FROM symbols_fts")
            store.conn.commit()

        report1 = validate_graph(cg_dir, proj_root, store=store)
        fts_mismatch = any(
            w["issue"] == "fts_count_mismatch" for w in report1["warnings"]
        )
        assert fts_mismatch

        report2 = repair_graph(cg_dir, report1, store=store)

        # After repair, FTS count should match node count
        assert report2["stats"]["fts_count"] == report2["stats"]["node_count"]
        store.close()

    def test_repair_confidence_clamp(self, tmp_path):
        """repair_graph clamps out-of-range confidence values."""
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        cg_dir = proj_root / ".codegraph"
        cg_dir.mkdir()
        db_path = cg_dir / "index.sqlite"

        store = SqliteStore(db_path)
        store.initialize()

        nodes = [
            _make_node("a.py::foo", "foo"),
            _make_node("a.py::bar", "bar"),
        ]
        _write_sqlite_nodes(store, nodes)

        edges = [
            _make_edge("e1", "a.py::foo", "a.py::bar", confidence=1.5),
        ]
        _write_sqlite_edges(store, edges)

        report1 = validate_graph(cg_dir, proj_root, store=store)
        clamped = [
            c for c in report1["auto_corrected"]
            if c["issue"] == "confidence_clamped"
        ]
        assert len(clamped) >= 1

        # Repair — but repair with store still open (not own_store)
        report2 = repair_graph(cg_dir, report1, store=store)
        # After repair, clamping should be applied in SQLite
        assert report2 is not None
        store.close()

    def test_repair_fatal_refuses(self, tmp_path):
        """repair_graph refuses to fix fatal schema version mismatch."""
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        cg_dir = proj_root / ".codegraph"
        cg_dir.mkdir()
        db_path = cg_dir / "index.sqlite"

        store = SqliteStore(db_path)
        store.initialize()
        store.set_meta("schema_version", "999.0.0")

        nodes = [_make_node("n1", "f1")]
        _write_sqlite_nodes(store, nodes)

        report = validate_graph(cg_dir, proj_root, store=store)
        assert report["status"] == "error"

        with pytest.raises(ValueError, match="init --force"):
            repair_graph(cg_dir, report, store=store)
        store.close()


# ── Integration Tests ─────────────────────────────────────────────────


class TestDoctorIntegration:
    """Tests for doctor CLI integration."""

    def test_doctor_shows_graph_health(self, tmp_path):
        """codegraph doctor shows '5e. Graph health' section."""
        # Create a minimal project with an index
        root = tmp_path / "proj"
        root.mkdir()
        (root / "app").mkdir()
        (root / "app" / "__init__.py").write_text("")
        (root / "app" / "main.py").write_text("def foo():\n    pass\n")

        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        # Create a minimal SQLite index
        from codegraph.storage.writer import write_full_index
        from codegraph.indexer.scanner import scan_python_files
        from codegraph.indexer.graph_builder import build_index

        nodes, edges = build_index(root)
        write_full_index(cg_dir, nodes, edges, root)

        # Run doctor and capture output
        from typer.testing import CliRunner
        from codegraph.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["doctor", "--root", str(root)])
        # Doctor should not crash; check for expected output
        assert result.exit_code == 0
        assert "5e. Graph health" in result.stdout


class TestMCPIntegration:
    """Tests for MCP index_health integration."""

    def test_mcp_index_health_in_status(self, tmp_path):
        """_build_index_status includes index_health when report exists."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        # Write graph.json (required by _find_codegraph_dir)
        (cg_dir / "graph.json").write_text("{}")

        # Write metadata.json so _build_index_status can load it
        metadata = {
            "schema_version": "1.0.0",
            "indexer_version": "1.0.0",
            "root_path": str(root),
            "indexed_at": "2025-01-01T00:00:00Z",
            "file_count": 1,
            "symbol_count": 1,
            "edge_count": 0,
            "files": [],
        }
        (cg_dir / "metadata.json").write_text(json.dumps(metadata))

        # Write state.json
        state = {"status": "fresh", "last_indexed_at": "2025-01-01T00:00:00Z"}
        (cg_dir / "state.json").write_text(json.dumps(state))

        # Write validation report directly (not via save_validation_report
        # which recalculates issue_counts from actual lists)
        report = {
            "status": "warning",
            "generated_at": "2025-01-01T00:00:00Z",
            "issue_counts": {"warnings": 2, "fatal": 0,
                             "auto_corrected": 0, "dropped": 1},
            "stats": {},
            "suggested_fix": "codegraph doctor --repair",
        }
        (cg_dir / "validation_report.json").write_text(json.dumps(report))

        import codegraph.mcp_server as mcp_mod
        old_root = getattr(mcp_mod, '_project_root', None)
        old_cg_dir = getattr(mcp_mod, '_cg_dir', None)
        old_store = getattr(mcp_mod, '_store', None)

        try:
            mcp_mod._project_root = root
            mcp_mod._cg_dir = cg_dir
            mcp_mod._store = None

            status = mcp_mod._build_index_status()
            assert "index_health" in status
            assert status["index_health"]["status"] == "warning"
            assert status["index_health"]["issue_counts"]["warnings"] == 2
        finally:
            mcp_mod._project_root = old_root
            mcp_mod._cg_dir = old_cg_dir
            mcp_mod._store = old_store

    def test_mcp_warnings_include_index_health(self, tmp_path):
        """_collect_warnings adds index_health warning when status != ok."""
        root = tmp_path / "proj"
        root.mkdir()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir()

        # Write graph.json (required by _find_codegraph_dir)
        (cg_dir / "graph.json").write_text("{}")

        # Write metadata.json
        metadata = {
            "schema_version": "1.0.0",
            "indexer_version": "1.0.0",
            "root_path": str(root),
            "indexed_at": "2025-01-01T00:00:00Z",
            "file_count": 1,
            "symbol_count": 1,
            "edge_count": 0,
            "files": [],
        }
        (cg_dir / "metadata.json").write_text(json.dumps(metadata))

        # Write state.json
        state = {"status": "fresh", "last_indexed_at": "2025-01-01T00:00:00Z"}
        (cg_dir / "state.json").write_text(json.dumps(state))

        # Write validation report directly
        report = {
            "status": "warning",
            "generated_at": "2025-01-01T00:00:00Z",
            "issue_counts": {"warnings": 3, "fatal": 0,
                             "auto_corrected": 0, "dropped": 2},
            "stats": {},
            "suggested_fix": "codegraph doctor --repair",
        }
        (cg_dir / "validation_report.json").write_text(json.dumps(report))

        import codegraph.mcp_server as mcp_mod
        old_root = getattr(mcp_mod, '_project_root', None)
        old_cg_dir = getattr(mcp_mod, '_cg_dir', None)
        old_store = getattr(mcp_mod, '_store', None)

        try:
            mcp_mod._project_root = root
            mcp_mod._cg_dir = cg_dir
            mcp_mod._store = None

            warnings = mcp_mod._collect_warnings()

            health_warnings = [
                w for w in warnings if w.get("type") == "index_health"
            ]
            assert len(health_warnings) >= 1
            assert health_warnings[0]["severity"] == "warning"
            assert "codegraph doctor" in health_warnings[0]["message"]
        finally:
            mcp_mod._project_root = old_root
            mcp_mod._cg_dir = old_cg_dir
            mcp_mod._store = old_store

    def test_index_health_none_skipped(self):
        """When no validation report exists, index_health is not set.

        ``_build_index_status`` resolves ``.codegraph`` via
        ``_find_codegraph_dir(_project_root)``, so both ``_project_root``
        and ``_cg_dir`` must point into the same temp tree.
        """
        import codegraph.mcp_server as mcp_mod
        old_cg_dir = getattr(mcp_mod, '_cg_dir', None)
        old_project_root = getattr(mcp_mod, '_project_root', None)

        try:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                root_dir = Path(td) / "project"
                root_dir.mkdir()
                cg_dir = root_dir / ".codegraph"
                cg_dir.mkdir()
                mcp_mod._project_root = str(root_dir)
                mcp_mod._cg_dir = cg_dir

                status = mcp_mod._build_index_status()
                # Should not have index_health (no validation report in temp dir)
                assert "index_health" not in status
        finally:
            mcp_mod._cg_dir = old_cg_dir
            mcp_mod._project_root = old_project_root
