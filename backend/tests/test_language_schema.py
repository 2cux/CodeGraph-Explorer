"""Tests for schema extensions (language_id, framework_id, provenance)."""

import json
import pytest
import tempfile
from pathlib import Path

from codegraph.graph.models import (
    GraphNode,
    GraphEdge,
    EdgeType,
    EdgeMetadata,
    NodeType,
    Resolution,
)
from codegraph.language_support.resolver import Provenance
from codegraph.storage.sqlite_store import SqliteStore


# ── Pydantic-only tests (no SQLite) ─────────────────────────────────────

class TestGraphNodeSchema:
    def test_node_has_language_id(self):
        node = GraphNode(id="test.py", type=NodeType.file, name="test")
        assert node.language_id == "python"
        assert node.language == "python"

    def test_node_language_id_can_be_set(self):
        node = GraphNode(
            id="test.ts", type=NodeType.file, name="test",
            language_id="typescript", language="typescript",
        )
        assert node.language_id == "typescript"

    def test_node_has_framework_id(self):
        node = GraphNode(id="test.py", type=NodeType.file, name="test")
        assert node.framework_id is None

    def test_node_framework_id_can_be_set(self):
        node = GraphNode(
            id="test.py", type=NodeType.file, name="test",
            framework_id="fastapi",
        )
        assert node.framework_id == "fastapi"

    def test_node_defaults_are_backward_compatible(self):
        """Existing code that only sets language should still work."""
        node = GraphNode(id="test.py", type=NodeType.file, name="test")
        assert node.language == "python"
        assert node.language_id == "python"


class TestEdgeMetadataSchema:
    def test_metadata_has_provenance(self):
        meta = EdgeMetadata(
            resolution=Resolution.exact_ast_match,
            provenance="ast",
        )
        assert meta.provenance == "ast"

    def test_metadata_provenance_defaults_none(self):
        meta = EdgeMetadata(resolution=Resolution.exact_ast_match)
        assert meta.provenance is None

    def test_metadata_provenance_with_enum_value(self):
        meta = EdgeMetadata(
            resolution=Resolution.imported_function_exact,
            provenance=Provenance.IMPORT_RESOLVER.value,
        )
        assert meta.provenance == "import_resolver"

    def test_full_confirmed_edge_has_all_fields(self):
        """Every confirmed edge must have resolution, provenance, confidence, evidence."""
        meta = EdgeMetadata(
            resolution=Resolution.imported_function_exact,
            provenance=Provenance.IMPORT_RESOLVER.value,
            evidence={"import_path": "other.helper"},
        )
        edge = GraphEdge(
            id="e1",
            type=EdgeType.calls,
            source="a.py::f",
            target="b.py::g",
            confidence=0.90,
            metadata=meta,
        )
        assert edge.metadata.resolution == Resolution.imported_function_exact
        assert edge.metadata.provenance == "import_resolver"
        assert edge.confidence == 0.90
        assert edge.metadata.evidence == {"import_path": "other.helper"}


# ── SQLite persistence tests ────────────────────────────────────────────

class TestSQLiteSchemaMigration:
    """Tests for SQLite storage of new schema fields.

    Each test explicitly closes the store before letting the tempdir
    context manager clean up, to avoid Windows file-lock issues.
    """

    def test_language_id_stored_and_retrieved(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            store = SqliteStore(db_path)
            try:
                store.initialize()
                node = GraphNode(
                    id="test.py",
                    type=NodeType.file,
                    name="test",
                    language_id="python",
                    framework_id="fastapi",
                )
                store.save_nodes([node.model_dump()])
                retrieved = store.get_node("test.py")
                assert retrieved is not None
                assert retrieved.get("language_id") == "python"
                assert retrieved.get("framework_id") == "fastapi"
            finally:
                store.close()

    def test_legacy_language_column_still_works(self):
        """Nodes saved with only 'language' should have language_id populated."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            store = SqliteStore(db_path)
            try:
                store.initialize()
                node_data = {
                    "id": "test.py",
                    "type": "file",
                    "name": "test",
                    "language": "python",
                }
                store.save_nodes([node_data])
                retrieved = store.get_node("test.py")
                assert retrieved is not None
                assert retrieved.get("language_id") == "python"
            finally:
                store.close()

    def test_provenance_in_edge_metadata(self):
        """Provenance stored in edge_metadata JSON must be retrievable."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            store = SqliteStore(db_path)
            try:
                store.initialize()
                edge = GraphEdge(
                    id="e1",
                    type=EdgeType.calls,
                    source="a.py::f",
                    target="b.py::g",
                    confidence=0.90,
                    metadata=EdgeMetadata(
                        resolution=Resolution.imported_function_exact,
                        provenance="import_resolver",
                        evidence={"k": "v"},
                    ),
                )
                store.save_edges([edge.model_dump()])
                retrieved = store.query_edges({"source": "a.py::f"})
                assert len(retrieved) == 1
                r_meta = retrieved[0].get("metadata")
                assert r_meta is not None
                assert r_meta.get("provenance") == "import_resolver"
                assert r_meta.get("resolution") == "imported_function_exact"
            finally:
                store.close()

    def test_search_symbols_includes_language_id(self):
        """search_symbols results should include language_id."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            store = SqliteStore(db_path)
            try:
                store.initialize()
                node = GraphNode(
                    id="test.py",
                    type=NodeType.file,
                    name="test",
                    language_id="python",
                )
                store.save_nodes([node.model_dump()])
                result = store.search_symbols(query="test")
                assert len(result["results"]) >= 1
                assert "language_id" in result["results"][0]
                assert result["results"][0]["language_id"] == "python"
            finally:
                store.close()

    def test_search_symbols_language_id_filter(self):
        """search_symbols with language_id filter should return matching results."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            store = SqliteStore(db_path)
            try:
                store.initialize()
                py_node = GraphNode(
                    id="test.py",
                    type=NodeType.file,
                    name="py_test",
                    language_id="python",
                )
                ts_node = GraphNode(
                    id="test.ts",
                    type=NodeType.file,
                    name="ts_test",
                    language_id="typescript",
                )
                store.save_nodes([py_node.model_dump(), ts_node.model_dump()])

                all_results = store.search_symbols(query="test")
                assert len(all_results["results"]) == 2

                py_results = store.search_symbols(query="test", language_id="python")
                assert len(py_results["results"]) == 1
                assert py_results["results"][0]["symbol_id"] == "test.py"

                ts_results = store.search_symbols(query="test", language_id="typescript")
                assert len(ts_results["results"]) == 1
                assert ts_results["results"][0]["symbol_id"] == "test.ts"
            finally:
                store.close()
