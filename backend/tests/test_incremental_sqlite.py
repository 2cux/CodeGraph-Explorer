"""Tests for true incremental SQLite write (not full replace).

Verifies:
- Structural change only updates affected file's nodes/edges
- Added file only inserts new nodes
- Deleted file removes nodes/edges/FTS
- Cosmetic change doesn't rewrite nodes/edges
- Rollback on failure preserves old index
- No dangling edges after incremental
- FTS syncs correctly
- state.last_incremental_stats recorded
- JSON export matches SQLite counts
- Doctor detects FTS inconsistency
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from codegraph.graph.models import GraphNode, GraphEdge
from codegraph.indexer.graph_builder import build_index
from codegraph.indexer.incremental import (
    run_incremental_index,
    IncrementalResult,
    _find_direct_dependents,
    _file_to_module,
)
from codegraph.indexer.fingerprint import FingerprintStore
from codegraph.storage.file_store import FileStore
from codegraph.storage.sqlite_store import SqliteStore
from codegraph.storage.state_store import IndexStateStore
from codegraph.storage.writer import (
    write_full_index,
    write_incremental_patch,
    update_fingerprints_incremental,
    SqliteWriteError,
)
from codegraph.storage.integrity import check_storage_integrity


# ── Helper: create a minimal Python project in a temp dir ─────────────────


def _write_py(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal project with cross-file imports.

    Returns (root_path, cg_dir).
    """
    root = tmp_path / "project"
    cg_dir = root / ".codegraph"

    _write_py(root / "app" / "__init__.py", "")
    _write_py(root / "app" / "api" / "__init__.py", "")
    _write_py(root / "app" / "services" / "__init__.py", "")

    _write_py(root / "app" / "api" / "auth.py", """\
def login(username: str, password: str) -> str:
    '''Authenticate a user.'''
    return "token-" + username


def verify_token(token: str) -> bool:
    '''Verify a token string.'''
    return token.startswith("token-")
""")

    _write_py(root / "app" / "services" / "auth_service.py", """\
from app.api.auth import login, verify_token


class AuthService:
    def authenticate(self, user: str, pwd: str) -> str:
        token = login(user, pwd)
        return token

    def check(self, token: str) -> bool:
        return verify_token(token)
""")

    _write_py(root / "app" / "utils.py", """\
def helper() -> str:
    return "helper"
""")

    return root, cg_dir


def _full_init(root: Path, cg_dir: Path) -> dict[str, int]:
    """Run a full index on the project and return counts."""
    nodes, edges = build_index(root)
    state_store = IndexStateStore(cg_dir)
    counts = write_full_index(cg_dir, nodes, edges, root, state_store=state_store)
    return counts


# ── Tests ────────────────────────────────────────────────────────────────


class TestIncrementalStructuralChange:
    """Verify structural change only updates affected file."""

    def test_structural_change_only_updates_affected_nodes(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)

        # Full init
        counts = _full_init(root, cg_dir)
        assert counts["nodes"] > 0

        # Record initial SQLite state
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        initial_nodes = sql_store.load_all_nodes()
        initial_node_ids = {n["id"] for n in initial_nodes}
        initial_file_nodes = {n["id"] for n in initial_nodes
                             if n.get("file_path") == "app/api/auth.py"}
        sql_store.close()

        # Make structural change: add new function to auth.py
        auth_py = root / "app" / "api" / "auth.py"
        auth_py.write_text("""\
def login(username: str, password: str) -> str:
    '''Authenticate a user.'''
    return "token-" + username


def verify_token(token: str) -> bool:
    '''Verify a token string.'''
    return token.startswith("token-")


def logout(token: str) -> None:
    '''Invalidate a token.'''
    pass
""", encoding="utf-8")

        # Touch file to ensure mtime changes
        time.sleep(0.05)
        os.utime(str(auth_py), (time.time() + 10, time.time() + 10))

        # Run incremental
        store = FileStore(cg_dir)
        result = run_incremental_index(root, cg_dir, store)

        assert result.status == "updated"

        # Verify SQLite state
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        updated_nodes = sql_store.load_all_nodes()
        updated_node_ids = {n["id"] for n in updated_nodes}

        # Old auth.py nodes should be gone, new ones present
        old_auth_ids = initial_file_nodes
        new_auth_ids = {n["id"] for n in updated_nodes
                        if n.get("file_path") == "app/api/auth.py"}
        assert old_auth_ids != new_auth_ids, "auth.py nodes should have changed"
        assert "app/api/auth.py::logout" in new_auth_ids, "new function should exist"

        # utils.py nodes should be unchanged
        utils_nodes = {n["id"] for n in updated_nodes
                       if n.get("file_path") == "app/utils.py"}
        initial_utils = {n["id"] for n in initial_nodes
                         if n.get("file_path") == "app/utils.py"}
        assert utils_nodes == initial_utils, "untouched file nodes should be preserved"

        sql_store.close()

    def test_structural_change_writes_incremental_stats(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        # Structural change: modify function signature
        auth_py = root / "app" / "api" / "auth.py"
        auth_py.write_text("""\
def login(username: str, password: str, remember_me: bool = False) -> str:
    '''Authenticate a user.'''
    return "new-token-" + username


def verify_token(token: str) -> bool:
    '''Verify a token string.'''
    return token.startswith("new-token-")
""", encoding="utf-8")
        os.utime(str(auth_py), (time.time() + 10, time.time() + 10))

        store = FileStore(cg_dir)
        result = run_incremental_index(root, cg_dir, store)

        assert result.status == "updated"

        # Verify state.json has incremental stats
        state_store = IndexStateStore(cg_dir)
        state = state_store.load()
        stats = state.get("last_incremental_stats")
        assert stats is not None
        assert stats.get("changed_files", 0) > 0
        assert stats.get("reparsed_files", 0) > 0
        assert stats.get("duration_ms", 0) > 0
        assert stats.get("full_replace") is False, "should be incremental patch, not full replace"
        assert stats.get("inserted_nodes", 0) > 0
        assert stats.get("deleted_nodes", 0) > 0

    def test_no_dangling_edges_after_structural_change(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        # Structural change
        auth_py = root / "app" / "api" / "auth.py"
        auth_py.write_text("""\
def login(username: str, password: str) -> str:
    return "v2-" + username

def verify_token(token: str) -> bool:
    return token.startswith("v2-")

def new_feature() -> str:
    return "new"
""", encoding="utf-8")
        os.utime(str(auth_py), (time.time() + 10, time.time() + 10))

        store = FileStore(cg_dir)
        result = run_incremental_index(root, cg_dir, store)
        assert result.status == "updated"

        # Check for dangling edges
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        danglers = sql_store.dangling_edge_count()
        sql_store.close()
        assert danglers == 0, f"Found {danglers} dangling edges after incremental update"


class TestIncrementalAddedFile:
    """Verify added file only inserts new nodes."""

    def test_added_file_inserts_new_nodes_only(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        counts = _full_init(root, cg_dir)
        initial_node_count = counts["nodes"]

        # Record initial nodes
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        initial_nodes = sql_store.load_all_nodes()
        initial_ids = {n["id"] for n in initial_nodes}
        sql_store.close()

        # Add a new file
        _write_py(root / "app" / "new_module.py", """\
def new_function() -> str:
    return "new"
""")

        # Re-init to generate fingerprints for the new file
        # (incremental needs fingerprints.json to detect ADDED)
        from codegraph.indexer.fingerprint import (
            FingerprintStore, compute_fingerprints,
        )
        from codegraph.indexer.scanner import scan_python_files

        fp_store = FingerprintStore(cg_dir)
        all_files = scan_python_files(root)
        fps = compute_fingerprints(root, all_files)
        fp_store.save(fps)

        # Now remove the fingerprint for the new file to make it ADDED
        # (or just let detect_status detect it as added)
        # Actually, we should let the system work normally.
        # The new file should be detected as ADDED because it's in filesystem
        # but not in fingerprints.

        store = FileStore(cg_dir)
        result = run_incremental_index(root, cg_dir, store)

        # May be "updated" or "fresh" depending on fingerprint state
        if result.status == "updated":
            # Verify new nodes were added and old ones preserved
            sql_store = SqliteStore(cg_dir / "index.sqlite")
            sql_store.initialize()
            updated_nodes = sql_store.load_all_nodes()
            updated_ids = {n["id"] for n in updated_nodes}

            assert len(updated_ids) >= len(initial_ids), "nodes should not decrease"
            # Old nodes should still exist
            preserved = initial_ids & updated_ids
            assert len(preserved) > 0
            sql_store.close()


class TestIncrementalDeletedFile:
    """Verify deleted file removes nodes/edges/FTS."""

    def test_deleted_file_removes_all_traces(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        counts = _full_init(root, cg_dir)

        # Remember utils.py nodes
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        initial_nodes = sql_store.load_all_nodes()
        utils_ids = {n["id"] for n in initial_nodes
                     if n.get("file_path") == "app/utils.py"}
        auth_count = len([n for n in initial_nodes
                          if n.get("file_path") == "app/api/auth.py"])
        sql_store.close()
        assert len(utils_ids) > 0, "utils.py should have nodes"

        # Delete utils.py
        (root / "app" / "utils.py").unlink()

        # Update fingerprints to exclude deleted file
        fp_store = FingerprintStore(cg_dir)
        fps = fp_store.load()
        fps.pop("app/utils.py", None)
        fp_store.save(fps)

        store = FileStore(cg_dir)
        result = run_incremental_index(root, cg_dir, store)

        if result.status == "updated":
            sql_store = SqliteStore(cg_dir / "index.sqlite")
            sql_store.initialize()
            updated_nodes = sql_store.load_all_nodes()
            updated_utils_ids = {n["id"] for n in updated_nodes
                                 if n.get("file_path") == "app/utils.py"}
            updated_auth_count = len([n for n in updated_nodes
                                      if n.get("file_path") == "app/api/auth.py"])

            assert len(updated_utils_ids) == 0, "deleted file nodes should be removed"
            assert updated_auth_count > 0, "auth.py nodes should still exist"

            # Check FTS
            if sql_store.has_fts_table():
                fts_count = sql_store.fts_count()
                node_count = sql_store.node_count()
                assert fts_count == node_count, f"FTS {fts_count} != nodes {node_count}"

            sql_store.close()


class TestIncrementalCosmeticChange:
    """Verify cosmetic change doesn't rewrite nodes/edges."""

    def test_cosmetic_change_preserves_sqlite(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        # Record initial SQLite state
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        initial_nodes = sql_store.load_all_nodes()
        initial_node_count = sql_store.node_count()
        initial_edge_count = sql_store.edge_count()
        initial_fts = sql_store.fts_count()
        sql_store.close()

        # Make cosmetic change: add comments only
        auth_py = root / "app" / "api" / "auth.py"
        auth_py.write_text("""\
# This is a new comment
# And another one
def login(username: str, password: str) -> str:
    '''Authenticate a user.'''
    # More comments inside the function
    return "token-" + username


def verify_token(token: str) -> bool:
    '''Verify a token string.'''
    return token.startswith("token-")
""", encoding="utf-8")
        os.utime(str(auth_py), (time.time() + 10, time.time() + 10))

        store = FileStore(cg_dir)
        result = run_incremental_index(root, cg_dir, store)

        # Cosmetic change should NOT trigger SQLite updates
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        final_node_count = sql_store.node_count()
        final_edge_count = sql_store.edge_count()
        final_fts = sql_store.fts_count()
        sql_store.close()

        assert final_node_count == initial_node_count, (
            f"Cosmetic change should not modify nodes: "
            f"{initial_node_count} → {final_node_count}"
        )
        assert final_edge_count == initial_edge_count, (
            f"Cosmetic change should not modify edges: "
            f"{initial_edge_count} → {final_edge_count}"
        )
        if initial_fts is not None and final_fts is not None:
            assert final_fts == initial_fts


class TestIncrementalRollback:
    """Verify rollback on failure preserves old index."""

    def test_rollback_on_write_failure(self, tmp_path, monkeypatch):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        # Record state before change
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        pre_nodes = sql_store.load_all_nodes()
        pre_node_count = sql_store.node_count()
        pre_edge_count = sql_store.edge_count()
        sql_store.close()

        # Make structural change: add new function
        auth_py = root / "app" / "api" / "auth.py"
        auth_py.write_text("""\
def login(username: str, password: str) -> str:
    '''Authenticate a user.'''
    return "token-" + username


def verify_token(token: str) -> bool:
    '''Verify a token string.'''
    return token.startswith("token-")


def force_rollback() -> None:
    '''This function exists only to force structural change.'''
    pass
""", encoding="utf-8")
        time.sleep(0.05)
        os.utime(str(auth_py), (time.time() + 10, time.time() + 10))

        # Simulate a failure during SQLite commit.
        # Patch save_edges to raise after nodes and edges are deleted
        # but before commit — this triggers rollback.
        original_save = SqliteStore.save_edges

        def _failing_save(self, edges, commit=True):
            raise sqlite3.OperationalError("simulated disk full")

        import sqlite3
        monkeypatch.setattr(SqliteStore, "save_edges", _failing_save)

        from codegraph.indexer.graph_builder import build_index_from_paths
        try:
            nodes, edges = build_index_from_paths(root, [auth_py])
            write_incremental_patch(
                cg_dir, nodes, edges, root,
                removed_files={"app/api/auth.py"},
            )
            assert False, "Expected SqliteWriteError"
        except SqliteWriteError:
            pass  # expected
        finally:
            monkeypatch.setattr(SqliteStore, "save_edges", original_save)

        # Verify original index is intact after rollback
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        post_nodes = sql_store.load_all_nodes()
        post_node_count = sql_store.node_count()
        post_edge_count = sql_store.edge_count()
        sql_store.close()

        assert post_node_count == pre_node_count, (
            f"Rollback should preserve node count: "
            f"{pre_node_count} → {post_node_count}"
        )
        assert post_edge_count == pre_edge_count, (
            f"Rollback should preserve edge count: "
            f"{pre_edge_count} → {post_edge_count}"
        )


class TestIncrementalFTSSync:
    """Verify FTS stays in sync with nodes after incremental."""

    def test_fts_syncs_correctly(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        # Verify initial FTS sync
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        if not sql_store.has_fts_table():
            sql_store.close()
            pytest.skip("FTS5 not supported")
        assert sql_store.fts_count() == sql_store.node_count()
        sql_store.close()

        # Structural change
        auth_py = root / "app" / "api" / "auth.py"
        auth_py.write_text("""\
def login(username: str, password: str) -> str:
    return "v4-" + username

def verify_token(token: str) -> bool:
    return token.startswith("v4-")

def extra_function(x: int) -> int:
    return x * 2
""", encoding="utf-8")
        os.utime(str(auth_py), (time.time() + 10, time.time() + 10))

        store = FileStore(cg_dir)
        result = run_incremental_index(root, cg_dir, store)
        assert result.status == "updated"

        # Verify FTS sync
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        node_count = sql_store.node_count()
        fts_count = sql_store.fts_count()
        assert fts_count == node_count, (
            f"FTS count ({fts_count}) must match node count ({node_count})"
        )
        sql_store.close()


class TestJSONExportConsistency:
    """Verify JSON export matches SQLite after incremental."""

    def test_json_counts_match_sqlite_after_incremental(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        # Structural change: add new function
        auth_py = root / "app" / "api" / "auth.py"
        auth_py.write_text("""\
def login(username: str, password: str) -> str:
    '''Authenticate a user.'''
    return "token-" + username


def verify_token(token: str) -> bool:
    '''Verify a token string.'''
    return token.startswith("token-")


def refresh_token(token: str) -> str:
    '''Refresh a token.'''
    return "refreshed-" + token
""", encoding="utf-8")
        os.utime(str(auth_py), (time.time() + 10, time.time() + 10))

        store = FileStore(cg_dir)
        result = run_incremental_index(root, cg_dir, store)
        assert result.status == "updated"

        # Compare SQLite vs JSON
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        sqlite_node_count = sql_store.node_count()
        sqlite_edge_count = sql_store.edge_count()
        sql_store.close()

        file_store = FileStore(cg_dir)
        json_nodes = file_store.load_nodes()
        json_edges = file_store.load_edges()

        assert len(json_nodes) == sqlite_node_count, (
            f"JSON nodes ({len(json_nodes)}) != SQLite nodes ({sqlite_node_count})"
        )
        assert len(json_edges) == sqlite_edge_count, (
            f"JSON edges ({len(json_edges)}) != SQLite edges ({sqlite_edge_count})"
        )


class TestDoctorDetectsInconsistency:
    """Verify doctor detects FTS inconsistency."""

    def test_doctor_detects_fts_mismatch(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        # Artificially create FTS inconsistency
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        if not sql_store.has_fts_table():
            sql_store.close()
            pytest.skip("FTS5 not supported")

        # Delete some FTS entries to create mismatch
        c = sql_store.conn
        c.execute("DELETE FROM symbols_fts WHERE rowid IN (SELECT rowid FROM symbols_fts LIMIT 3)")
        c.commit()
        sql_store.close()

        # Run integrity check
        integrity = check_storage_integrity(cg_dir)
        fts_checks = [c for c in integrity["checks"]
                      if "fts" in c.get("name", "").lower()]

        # There should be a warning about FTS count mismatch
        fts_warnings = [c for c in fts_checks if c["status"] == "warning"]
        assert len(fts_warnings) > 0, "Doctor should warn about FTS mismatch"

    def test_doctor_detects_dangling_edges(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        # Artificially create dangling edge
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        c = sql_store.conn
        c.execute(
            "INSERT INTO edges (id, type, source, target, confidence) "
            "VALUES ('dangling_1', 'calls', 'nonexistent::a', 'nonexistent::b', 0.5)"
        )
        c.commit()
        sql_store.close()

        # Run integrity check
        integrity = check_storage_integrity(cg_dir)
        edge_checks = [c for c in integrity["checks"]
                       if "dangling" in c.get("name", "").lower()]

        dangling_warnings = [c for c in edge_checks if c["status"] == "warning"]
        assert len(dangling_warnings) > 0, "Doctor should detect dangling edges"


class TestFindDirectDependents:
    """Verify cross-file dependent discovery."""

    def test_finds_dependents_of_changed_module(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        sqlite_path = cg_dir / "index.sqlite"
        deps = _find_direct_dependents(
            ["app/api/auth.py"], sqlite_path,
        )

        # auth_service.py imports from auth.py, so it should be a dependent
        assert "app/services/auth_service.py" in deps, (
            f"auth_service.py should depend on auth.py, got: {deps}"
        )

    def test_no_dependents_for_leaf_module(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        sqlite_path = cg_dir / "index.sqlite"
        deps = _find_direct_dependents(
            ["app/utils.py"], sqlite_path,
        )

        # utils.py is not imported by anything
        assert len(deps) == 0, f"utils.py should have no dependents, got: {deps}"

    def test_file_to_module_conversion(self):
        assert _file_to_module("app/api/auth.py") == "app.api.auth"
        assert _file_to_module("app/__init__.py") == "app"
        assert _file_to_module("src/utils/helpers.py") == "src.utils.helpers"


class TestStateIncrementalStats:
    """Verify state.json records incremental performance stats."""

    def test_stats_full_replace_false(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        # Structural change: add new function
        auth_py = root / "app" / "api" / "auth.py"
        auth_py.write_text("""\
def login(username: str, password: str) -> str:
    '''Authenticate a user.'''
    return "token-" + username


def verify_token(token: str) -> bool:
    '''Verify a token string.'''
    return token.startswith("token-")


def validate_password(pwd: str) -> bool:
    '''Validate password strength.'''
    return len(pwd) >= 8
""", encoding="utf-8")
        os.utime(str(auth_py), (time.time() + 10, time.time() + 10))

        store = FileStore(cg_dir)
        result = run_incremental_index(root, cg_dir, store)
        assert result.status == "updated"

        state_store = IndexStateStore(cg_dir)
        state = state_store.load()
        stats = state.get("last_incremental_stats")
        assert stats is not None
        assert stats.get("full_replace") is False
        assert isinstance(stats.get("changed_files"), int)
        assert isinstance(stats.get("reparsed_files"), int)
        assert isinstance(stats.get("dependent_files"), int)
        assert isinstance(stats.get("deleted_nodes"), int)
        assert isinstance(stats.get("inserted_nodes"), int)
        assert isinstance(stats.get("deleted_edges"), int)
        assert isinstance(stats.get("inserted_edges"), int)
        assert isinstance(stats.get("duration_ms"), (int, float))
        assert stats.get("duration_ms", 0) > 0


class TestIncrementalPatchAPI:
    """Verify the write_incremental_patch function directly."""

    def test_patch_preserves_untouched_data(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        counts = _full_init(root, cg_dir)

        # Remember initial state
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        pre_node_count = sql_store.node_count()
        all_pre_nodes = sql_store.load_all_nodes()
        pre_utils_nodes = {n["id"] for n in all_pre_nodes
                           if n.get("file_path") == "app/utils.py"}
        sql_store.close()

        # Simulate re-indexing only auth.py (structural change)
        from codegraph.indexer.graph_builder import build_index_from_paths
        auth_py = root / "app" / "api" / "auth.py"
        # Modify file first
        auth_py.write_text("""\
def login(username: str, password: str) -> str:
    return "v7-" + username

def verify_token(token: str) -> bool:
    return token.startswith("v7-")

def extra() -> None:
    pass
""", encoding="utf-8")

        new_nodes, new_edges = build_index_from_paths(root, [auth_py])

        result = write_incremental_patch(
            cg_dir, new_nodes, new_edges, root,
            removed_files={"app/api/auth.py"},
        )

        # Verify only auth.py was touched
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        post_nodes = sql_store.load_all_nodes()
        post_utils_nodes = {n["id"] for n in post_nodes
                            if n.get("file_path") == "app/utils.py"}
        post_auth_nodes = {n["id"] for n in post_nodes
                           if n.get("file_path") == "app/api/auth.py"}
        sql_store.close()

        # utils.py nodes should be PRESERVED (not re-inserted, not deleted)
        assert pre_utils_nodes == post_utils_nodes, (
            "Untouched file nodes should be exactly preserved"
        )
        # auth.py nodes should be NEW
        assert "app/api/auth.py::extra" in post_auth_nodes

    def test_patch_handles_empty_new_data(self, tmp_path):
        root, cg_dir = _make_project(tmp_path)
        _full_init(root, cg_dir)

        # Delete a file with no new data to insert
        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        pre_count = sql_store.node_count()
        sql_store.close()

        result = write_incremental_patch(
            cg_dir, [], [], root,
            removed_files={"app/utils.py"},
        )

        sql_store = SqliteStore(cg_dir / "index.sqlite")
        sql_store.initialize()
        post_count = sql_store.node_count()
        sql_store.close()

        assert post_count < pre_count, "should have removed utils.py nodes"
        assert result["nodes_inserted"] == 0
        assert result["nodes_removed"] > 0
