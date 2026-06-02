"""Tests for storage layer — FileStore and SqliteStore."""

import json
from unittest import mock
from pathlib import Path

import pytest
from codegraph.graph.models import GraphEdge, IndexMetadata, Resolution
from codegraph.storage.file_store import FileStore
from codegraph.storage.integrity import check_storage_integrity
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

    def test_save_nodes_atomic_success(self, tmp_path):
        store = FileStore(tmp_path)
        store.save_nodes([{"id": "n1", "type": "file", "name": "n1"}])
        assert not (tmp_path / ".nodes.json.tmp").exists()
        assert store.load_nodes()[0]["id"] == "n1"

    def test_save_nodes_failure_keeps_old_json_readable(self, tmp_path):
        store = FileStore(tmp_path)
        original = [{"id": "old", "type": "file", "name": "old"}]
        store.save_nodes(original)
        with mock.patch("os.replace", side_effect=OSError("replace failed")):
            with pytest.raises(OSError):
                store.save_nodes([{"id": "new", "type": "file", "name": "new"}])
        assert store.load_nodes() == original

    def test_save_metadata_atomic_success(self, tmp_path):
        store = FileStore(tmp_path)
        metadata = IndexMetadata(schema_version="1.0.0", symbol_count=1, edge_count=0)
        store.save_metadata(metadata)
        assert store.load_metadata().schema_version == "1.0.0"


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

    def test_initialize_enables_wal(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        assert store.get_journal_mode() == "wal"

    def test_initialize_creates_fts_when_available(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        if store.supports_fts5():
            assert store.has_fts_table()

    def test_initialize_warns_when_fts_unavailable(self, tmp_path, monkeypatch):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        monkeypatch.setattr(store, "supports_fts5", lambda: False)
        store.initialize()
        assert store.fts_warning is not None

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

    def test_edge_metadata_maps_to_pydantic_metadata(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        store.save_edges([{
            "id": "e1",
            "type": "calls",
            "source": "a",
            "target": "b",
            "confidence": 0.9,
            "source_location": None,
            "metadata": {
                "resolution": "same_file_exact",
                "reason": "unit test",
            },
        }])
        loaded = store.load_all_edges()[0]
        assert "edge_metadata" not in loaded
        assert loaded["metadata"]["resolution"] == "same_file_exact"
        parsed = GraphEdge(**loaded)
        assert parsed.metadata is not None
        assert parsed.metadata.resolution == Resolution.same_file_exact

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

    def test_search_symbols_returns_score_and_match_sources(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        store.save_nodes([{
            "id": "n1", "type": "function", "name": "login_user",
            "qualified_name": "auth.login_user", "display_name": "login_user",
            "file_path": "app/auth.py", "module": "auth", "language": "python",
            "location": {"line_start": 3, "line_end": 5},
            "signature": "def login_user():", "docstring": "Authenticate account",
            "code_preview": None, "visibility": "public", "tags": ["auth"], "metadata": {},
        }])
        result = store.search_symbols("Authenticate", limit=10)
        assert result["results"]
        assert "score" in result["results"][0]
        assert "match_sources" in result["results"][0]

    def test_search_symbols_falls_back_to_like_when_fts_disabled(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        store.save_nodes([{
            "id": "n1", "type": "function", "name": "reset_password",
            "qualified_name": "auth.reset_password", "display_name": "reset_password",
            "file_path": "app/auth.py", "module": "auth", "language": "python",
            "location": None, "signature": None, "docstring": None,
            "code_preview": None, "visibility": "public", "tags": [], "metadata": {},
        }])
        result = store.search_symbols("password", limit=10, use_fts=False)
        assert "like_name" in result["results"][0]["match_sources"]

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


class TestStorageIntegrity:
    def test_detects_json_sqlite_metadata_count_mismatch(self, tmp_path):
        store = FileStore(tmp_path)
        store.save_nodes([{"id": "n1", "type": "function", "name": "f"}])
        store.save_edges([])
        store.save_metadata(IndexMetadata(schema_version="1.0.0", symbol_count=2, edge_count=0))
        sql = SqliteStore(tmp_path / "index.sqlite")
        sql.initialize()
        sql.save_nodes([{
            "id": "n1", "type": "function", "name": "f", "qualified_name": "",
            "display_name": "", "file_path": "a.py", "module": "",
            "language": "python", "location": None, "signature": None,
            "docstring": None, "code_preview": None, "visibility": "public",
            "tags": [], "metadata": {},
        }])
        sql.save_nodes([{
            "id": "n2", "type": "function", "name": "g", "qualified_name": "",
            "display_name": "", "file_path": "b.py", "module": "",
            "language": "python", "location": None, "signature": None,
            "docstring": None, "code_preview": None, "visibility": "public",
            "tags": [], "metadata": {},
        }])
        sql.close()
        result = check_storage_integrity(tmp_path)
        assert result["status"] == "error"
        assert any(c["name"] == "sqlite.nodes_vs_json" for c in result["checks"])

    def test_detects_fts_count_mismatch(self, tmp_path):
        sql = SqliteStore(tmp_path / "index.sqlite")
        sql.initialize()
        sql.save_nodes([{
            "id": "n1", "type": "function", "name": "f", "qualified_name": "",
            "display_name": "", "file_path": "a.py", "module": "",
            "language": "python", "location": None, "signature": None,
            "docstring": None, "code_preview": None, "visibility": "public",
            "tags": [], "metadata": {},
        }])
        if not sql.has_fts_table():
            pytest.skip("SQLite FTS5 unavailable")
        sql.conn.execute("DELETE FROM symbols_fts")
        sql.conn.commit()
        sql.close()
        FileStore(tmp_path).save_nodes([{"id": "n1", "type": "function", "name": "f"}])
        FileStore(tmp_path).save_edges([])
        FileStore(tmp_path).save_metadata(IndexMetadata(schema_version="1.0.0", symbol_count=1, edge_count=0))
        result = check_storage_integrity(tmp_path)
        assert any(c["status"] == "warning" and c["name"] == "sqlite.fts_count" for c in result["checks"])

    def test_detects_missing_schema_version(self, tmp_path):
        FileStore(tmp_path).save_nodes([])
        FileStore(tmp_path).save_edges([])
        (tmp_path / "metadata.json").write_text(json.dumps({
            "indexer_version": "1.0.0",
            "symbol_count": 0,
            "edge_count": 0,
        }), encoding="utf-8")
        result = check_storage_integrity(tmp_path)
        assert any(c["status"] == "warning" and c["name"] == "metadata.schema_version" for c in result["checks"])

    def test_detects_incompatible_schema_version(self, tmp_path):
        FileStore(tmp_path).save_nodes([])
        FileStore(tmp_path).save_edges([])
        (tmp_path / "metadata.json").write_text(json.dumps({
            "schema_version": "9.9.9",
            "indexer_version": "1.0.0",
            "symbol_count": 0,
            "edge_count": 0,
        }), encoding="utf-8")
        result = check_storage_integrity(tmp_path)
        assert any(c["status"] == "error" and c["name"] == "metadata.schema_version" for c in result["checks"])
