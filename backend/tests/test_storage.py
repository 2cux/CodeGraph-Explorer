"""Tests for storage layer — FileStore and SqliteStore."""

import json
from pathlib import Path

import pytest
from codegraph.storage.file_store import FileStore
from codegraph.storage.sqlite_store import SqliteStore


# ══════════════════════════════════════════════════════════════════════════
# FileStore tests
# ══════════════════════════════════════════════════════════════════════════


class TestFileStore:
    def test_save_and_load_nodes(self, tmp_path):
        store = FileStore(tmp_path)
        nodes = [
            {"id": "test.py", "type": "file", "name": "test.py"},
            {"id": "test.py::foo", "type": "function", "name": "foo"},
        ]
        store.save_nodes(nodes)
        loaded = store.load_nodes()
        assert len(loaded) == 2
        assert loaded[0]["id"] == "test.py"

    def test_save_and_load_edges(self, tmp_path):
        store = FileStore(tmp_path)
        edges = [
            {"id": "e1", "type": "calls", "source": "a", "target": "b"},
        ]
        store.save_edges(edges)
        loaded = store.load_edges()
        assert len(loaded) == 1
        assert loaded[0]["source"] == "a"

    def test_load_nodes_empty(self, tmp_path):
        store = FileStore(tmp_path / "subdir")
        assert store.load_nodes() == []

    def test_load_edges_empty(self, tmp_path):
        store = FileStore(tmp_path / "subdir")
        assert store.load_edges() == []

    def test_creates_directory(self, tmp_path):
        deep_dir = tmp_path / "a" / "b" / "c"
        store = FileStore(deep_dir)
        store.save_nodes([{"id": "x", "type": "file", "name": "x"}])
        assert deep_dir.exists()

    def test_load_stores_actual_json(self, tmp_path):
        store = FileStore(tmp_path)
        store.save_nodes([{"id": "n1", "type": "file", "name": "n1"}])
        data = json.loads((tmp_path / "nodes.json").read_text(encoding="utf-8"))
        assert data[0]["id"] == "n1"


# ══════════════════════════════════════════════════════════════════════════
# SqliteStore tests
# ══════════════════════════════════════════════════════════════════════════


class TestSqliteStore:
    def test_initialize_creates_tables(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        # Verify tables exist
        cursor = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [r[0] for r in cursor.fetchall()]
        assert "nodes" in tables
        assert "edges" in tables

    def test_save_and_query_nodes(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        nodes = [
            {"id": "n1", "type": "function", "name": "foo",
             "qualified_name": "mod.foo", "display_name": "foo",
             "file_path": "mod.py", "module": "mod",
             "language": "python", "location": None,
             "signature": None, "docstring": None,
             "code_preview": None, "visibility": "public",
             "tags": "[]", "metadata": "{}"},
        ]
        store.save_nodes(nodes)
        assert store.node_count() == 1
        loaded = store.get_node("n1")
        assert loaded is not None
        assert loaded["name"] == "foo"

    def test_save_and_query_edges(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        edges = [
            {"id": "e1", "type": "calls", "source": "a", "target": "b",
             "confidence": 0.9, "source_location": None, "edge_metadata": None},
        ]
        store.save_edges(edges)
        assert store.edge_count() == 1

    def test_query_nodes_with_filters(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        nodes = [
            {"id": "n1", "type": "function", "name": "foo", "qualified_name": "mod.foo",
             "display_name": "foo", "file_path": "mod.py", "module": "mod",
             "language": "python", "location": None, "signature": None,
             "docstring": None, "code_preview": None, "visibility": "public",
             "tags": "[]", "metadata": "{}"},
            {"id": "n2", "type": "class", "name": "Bar", "qualified_name": "mod.Bar",
             "display_name": "Bar", "file_path": "mod.py", "module": "mod",
             "language": "python", "location": None, "signature": None,
             "docstring": None, "code_preview": None, "visibility": "public",
             "tags": "[]", "metadata": "{}"},
        ]
        store.save_nodes(nodes)
        filtered = store.query_nodes({"type": "function"})
        assert len(filtered) == 1
        assert filtered[0]["name"] == "foo"

    def test_node_not_found(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        assert store.get_node("nonexistent") is None

    def test_clear(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        nodes = [
            {"id": "n1", "type": "function", "name": "foo", "qualified_name": "",
             "display_name": "", "file_path": "", "module": "",
             "language": "python", "location": None, "signature": None,
             "docstring": None, "code_preview": None, "visibility": "public",
             "tags": "[]", "metadata": "{}"},
        ]
        store.save_nodes(nodes)
        assert store.node_count() == 1
        store.clear()
        assert store.node_count() == 0

    def test_load_all(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        nodes = [
            {"id": "n1", "type": "function", "name": "foo", "qualified_name": "",
             "display_name": "", "file_path": "", "module": "",
             "language": "python", "location": None, "signature": None,
             "docstring": None, "code_preview": None, "visibility": "public",
             "tags": "[]", "metadata": "{}"},
        ]
        edges = [
            {"id": "e1", "type": "calls", "source": "n1", "target": "n2",
             "confidence": 0.9, "source_location": None, "edge_metadata": None},
        ]
        store.save_nodes(nodes)
        store.save_edges(edges)
        assert len(store.load_all_nodes()) == 1
        assert len(store.load_all_edges()) == 1

    def test_close_and_reopen(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        store.close()
        # Re-opening should work
        store2 = SqliteStore(db_path)
        store2.initialize()
        assert store2.node_count() == 0
