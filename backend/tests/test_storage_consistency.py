"""Tests for storage consistency: SQLite-primary writes, JSON export, integrity."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from codegraph.graph.models import GraphNode, GraphEdge, NodeType, EdgeType, Resolution
from codegraph.graph.store import GraphStore
from codegraph.indexer.graph_builder import build_index
from codegraph.storage.file_store import FileStore
from codegraph.storage.sqlite_store import SqliteStore
from codegraph.storage.state_store import IndexStateStore
from codegraph.storage.writer import (
    write_full_index,
    write_incremental_update,
    export_json_from_sqlite,
    repair_json_from_sqlite,
    SqliteWriteError,
)
from codegraph.storage.integrity import check_storage_integrity


# ── Helpers ──────────────────────────────────────────────────────────


def _make_sample_project(root: Path) -> tuple[Path, Path]:
    """Create a minimal Python project with a few source files.
    Returns (root, app_dir).
    """
    app_dir = root / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "__init__.py").write_text("")
    (app_dir / "auth.py").write_text(
        "def login(user: str, password: str) -> bool:\n    return True\n\n"
        "def logout() -> None:\n    pass\n"
    )
    (app_dir / "models.py").write_text(
        "class User:\n    def __init__(self, name: str) -> None:\n        self.name = name\n"
    )
    return root, app_dir


def _index_and_write(root: Path) -> dict:
    """Build index and write to .codegraph, return counts."""
    cg_dir = root / ".codegraph"
    cg_dir.mkdir(exist_ok=True)
    nodes, edges = build_index(root)
    state_store = IndexStateStore(cg_dir)
    return write_full_index(cg_dir, nodes, edges, root, state_store=state_store)


# ── Full Init Consistency ────────────────────────────────────────────


class TestFullInitConsistency:
    """Full init produces consistent SQLite/JSON/metadata counts."""

    def test_full_init_counts_match(self, tmp_path):
        """After full init, SQLite nodes/edges == JSON nodes/edges."""
        root, _ = _make_sample_project(tmp_path)
        counts = _index_and_write(root)
        cg_dir = root / ".codegraph"

        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        sql_nodes = sql_store.node_count()
        sql_edges = sql_store.edge_count()
        sql_store.close()

        json_nodes = len(json.loads((cg_dir / "nodes.json").read_text()))
        json_edges = len(json.loads((cg_dir / "edges.json").read_text()))

        assert counts["nodes"] == sql_nodes == json_nodes
        assert counts["edges"] == sql_edges == json_edges

    def test_full_init_fts_count_matches(self, tmp_path):
        """After full init, FTS symbols count == SQLite node count."""
        root, _ = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        assert sql_store.fts_count() == sql_store.node_count()
        sql_store.close()

    def test_full_init_state_updated(self, tmp_path):
        """After full init, state.json has 'fresh' status and stats."""
        root, _ = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        state_store = IndexStateStore(cg_dir)
        state = state_store.load()
        assert state["status"] == "fresh"
        assert state["last_indexed_at"] is not None
        assert "stats" in state
        assert state["stats"]["symbols"] > 0
        assert state["stats"]["edges"] >= 0


# ── Incremental Consistency ──────────────────────────────────────────


class TestIncrementalConsistency:
    """Incremental init produces consistent counts."""

    def test_incremental_after_change_counts_match(self, tmp_path):
        """After modifying a file and running incremental, all counts match."""
        root, app_dir = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        # Modify a file
        (app_dir / "auth.py").write_text(
            "def login(user: str, password: str) -> bool:\n    return True\n\n"
            "def logout() -> None:\n    pass\n\n"
            "def verify_token(token: str) -> bool:\n    return True\n"
        )

        # Rebuild and write incremental
        nodes, edges = build_index(root)
        state_store = IndexStateStore(cg_dir)
        counts = write_incremental_update(
            cg_dir, nodes, edges, root,
            removed_files=set(), state_store=state_store,
        )

        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        assert counts["nodes"] == sql_store.node_count()
        assert counts["edges"] == sql_store.edge_count()
        sql_store.close()

        json_nodes = len(json.loads((cg_dir / "nodes.json").read_text()))
        json_edges = len(json.loads((cg_dir / "edges.json").read_text()))
        assert counts["nodes"] == json_nodes
        assert counts["edges"] == json_edges

    def test_incremental_no_removed_files_stays_consistent(self, tmp_path):
        """When no files removed, write_incremental_update works fine."""
        root, _ = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        nodes, edges = build_index(root)
        counts = write_incremental_update(
            cg_dir, nodes, edges, root,
            removed_files=set(),
        )

        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        assert counts["nodes"] == sql_store.node_count()
        sql_store.close()


# ── Deleted File Cleanup ─────────────────────────────────────────────


class TestDeletedFileCleanup:
    """Deleted files are properly cleaned from all stores."""

    def test_deleted_file_no_nodes_in_sqlite(self, tmp_path):
        """After deleting a file and incrementally updating, SQLite has no nodes for it."""
        root, app_dir = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        # Delete models.py
        models_path = app_dir / "models.py"
        models_path.unlink()

        # Rebuild and write incremental
        nodes, edges = build_index(root)
        state_store = IndexStateStore(cg_dir)
        write_incremental_update(
            cg_dir, nodes, edges, root,
            removed_files={"app/models.py"}, state_store=state_store,
        )

        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        all_nodes = sql_store.load_all_nodes()
        models_nodes = [n for n in all_nodes if "models.py" in n.get("file_path", "")]
        assert len(models_nodes) == 0, f"Found {len(models_nodes)} leftover nodes for models.py"
        sql_store.close()

    def test_deleted_file_no_fts_entries(self, tmp_path):
        """FTS has no entries for deleted file's symbols."""
        root, app_dir = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        models_path = app_dir / "models.py"
        models_path.unlink()

        nodes, edges = build_index(root)
        state_store = IndexStateStore(cg_dir)
        write_incremental_update(
            cg_dir, nodes, edges, root,
            removed_files={"app/models.py"}, state_store=state_store,
        )

        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        assert sql_store.fts_count() == sql_store.node_count()
        sql_store.close()

    def test_deleted_file_in_state_tracking(self, tmp_path):
        """state.deleted_files tracks the deleted file."""
        root, app_dir = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        models_path = app_dir / "models.py"
        models_path.unlink()

        nodes, edges = build_index(root)
        state_store = IndexStateStore(cg_dir)
        write_incremental_update(
            cg_dir, nodes, edges, root,
            removed_files={"app/models.py"}, state_store=state_store,
        )

        state = state_store.load()
        assert "app/models.py" in state.get("deleted_files", [])


# ── Doctor Detection ─────────────────────────────────────────────────


class TestDoctorDetection:
    """Doctor detects inconsistencies."""

    def test_doctor_consistency_ok_for_fresh_index(self, tmp_path):
        """Fresh index gets consistency=ok from integrity check."""
        root, _ = _make_sample_project(tmp_path)
        _index_and_write(root)

        integrity = check_storage_integrity(root / ".codegraph")
        assert integrity["consistency"] == "ok"
        assert integrity["suggestion"] is None

    def test_doctor_detects_json_missing(self, tmp_path):
        """If JSON files are missing, doctor reports error."""
        root, _ = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        # Corrupt: delete nodes.json
        (cg_dir / "nodes.json").unlink()

        integrity = check_storage_integrity(cg_dir)
        assert integrity["consistency"] in ("error", "warning")
        # Should have a specific check about nodes.json
        node_checks = [c for c in integrity["checks"] if "nodes.json" in c["name"]]
        assert any(c["status"] == "error" for c in node_checks)

    def test_doctor_detects_sqlite_json_mismatch(self, tmp_path):
        """If SQLite and JSON diverge, doctor reports issue."""
        root, _ = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        # Corrupt: modify nodes.json to have wrong count
        (cg_dir / "nodes.json").write_text("[]")

        integrity = check_storage_integrity(cg_dir)
        # Should detect mismatch
        mismatch_checks = [c for c in integrity["checks"] if "nodes_vs_json" in c["name"]]
        if mismatch_checks:
            assert mismatch_checks[0]["status"] == "error"
        assert integrity["consistency"] != "ok"

    def test_counts_block_present(self, tmp_path):
        """Integrity result includes counts dict."""
        root, _ = _make_sample_project(tmp_path)
        _index_and_write(root)

        integrity = check_storage_integrity(root / ".codegraph")
        counts = integrity["counts"]
        assert "sqlite_nodes" in counts
        assert "sqlite_edges" in counts
        assert "json_nodes" in counts
        assert "json_edges" in counts
        assert "fts_symbols" in counts


# ── Repair ───────────────────────────────────────────────────────────


class TestRepairCommand:
    """Repair re-exports JSON from SQLite."""

    def test_repair_from_healthy_sqlite(self, tmp_path):
        """Repair rebuilds JSON matching SQLite when SQLite is healthy."""
        root, _ = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        # Corrupt JSON
        (cg_dir / "nodes.json").write_text("[]")
        (cg_dir / "edges.json").write_text("[]")

        # Repair
        repair_counts = repair_json_from_sqlite(cg_dir, root)
        assert repair_counts["nodes"] > 0

        # Verify counts match again
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        json_nodes = len(json.loads((cg_dir / "nodes.json").read_text()))
        assert json_nodes == sql_store.node_count()
        assert json_nodes == repair_counts["nodes"]
        sql_store.close()

    def test_repair_with_missing_sqlite_raises(self, tmp_path):
        """When SQLite is missing, repair raises SqliteWriteError."""
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        # No index.sqlite

        with pytest.raises(SqliteWriteError, match="missing"):
            repair_json_from_sqlite(cg_dir, tmp_path)

    def test_repair_with_corrupt_sqlite_raises(self, tmp_path):
        """When SQLite is corrupt, repair raises SqliteWriteError."""
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "index.sqlite").write_text("not a sqlite database")

        with pytest.raises(SqliteWriteError, match="corrupted"):
            repair_json_from_sqlite(cg_dir, tmp_path)


# ── Benchmark Report ─────────────────────────────────────────────────


class TestBenchmarkReport:
    """Benchmark report handles missing results."""

    def test_report_missing_results_returns_sentinel(self, tmp_path, monkeypatch):
        """When result files are missing, generate_report returns MISSING_RESULTS."""
        pytest.importorskip("tests.agent_benchmark.report",
                            reason="tests not on PYTHONPATH (run from project root)")
        import tests.agent_benchmark.report as report_mod
        monkeypatch.setattr(report_mod, "_RESULTS_DIR", tmp_path)
        monkeypatch.setattr(report_mod, "_REPORTS_DIR", tmp_path)

        result = report_mod.generate_report()
        assert result == "MISSING_RESULTS"

    def test_makefile_has_benchmark_target(self):
        """Makefile has correct benchmark target."""
        makefile_path = Path(__file__).resolve().parents[3] / "Makefile"
        if not makefile_path.exists():
            makefile_path = Path(__file__).resolve().parents[2] / "Makefile"
        content = makefile_path.read_text()
        assert "benchmark:" in content
        assert "runner --mode baseline" in content
        assert "runner --mode codegraph" in content
        assert "report" in content


# ── SqliteWriteError ─────────────────────────────────────────────────


class TestSqliteWriteError:
    """SqliteWriteError is raised when SQLite write fails."""

    def test_write_full_index_raises_on_bad_path(self, tmp_path):
        """write_full_index raises SqliteWriteError on unwritable path."""
        root, _ = _make_sample_project(tmp_path)
        nodes, edges = build_index(root)
        # Use a path that would be a file, not a directory — creates invalid SQLite path
        bad_dir = tmp_path / "not_a_dir.txt"
        bad_dir.write_text("block")

        with pytest.raises((SqliteWriteError, OSError)):
            write_full_index(bad_dir, nodes, edges, root)

    def test_no_sqlite_fallback_works(self, tmp_path):
        """With no_sqlite=True, write works without SQLite."""
        root, _ = _make_sample_project(tmp_path)
        cg_dir = root / ".codegraph"
        cg_dir.mkdir(exist_ok=True)
        nodes, edges = build_index(root)

        counts = write_full_index(cg_dir, nodes, edges, root, no_sqlite=True)
        assert counts["nodes"] > 0
        assert counts["fts_symbols"] == 0  # No FTS without SQLite
        assert (cg_dir / "nodes.json").exists()
        assert (cg_dir / "graph.json").exists()
        assert not (cg_dir / "index.sqlite").exists()


# ── JSON Export Roundtrip ────────────────────────────────────────────


class TestJsonExportRoundtrip:
    """export_json_from_sqlite preserves data."""

    def test_export_roundtrip(self, tmp_path):
        """Data exported from SQLite matches what was written."""
        root, _ = _make_sample_project(tmp_path)
        _index_and_write(root)
        cg_dir = root / ".codegraph"

        json_nodes, json_edges = export_json_from_sqlite(cg_dir)
        assert len(json_nodes) > 0
        assert len(json_edges) >= 0

        # Verify JSON files were written
        file_nodes = json.loads((cg_dir / "nodes.json").read_text())
        file_edges = json.loads((cg_dir / "edges.json").read_text())
        assert len(file_nodes) == len(json_nodes)
        assert len(file_edges) == len(json_edges)
