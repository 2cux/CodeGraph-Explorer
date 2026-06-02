"""Tests for PythonExtractor — output parity with existing extraction."""

import pytest
import tempfile
from pathlib import Path

from codegraph.language_support.python.extractor import PythonExtractor
from codegraph.graph.models import NodeType, GraphNode, GraphEdge
from codegraph.indexer.symbol_extractor import extract_symbols
from codegraph.indexer.parser_python import parse_file
from codegraph.indexer.scanner import normalize_path


SIMPLE_PY = """\
import os
from pathlib import Path

def hello(name: str) -> str:
    \"\"\"Say hello.\"\"\"
    return f"Hello, {name}"

class Greeter:
    def greet(self, name: str) -> str:
        return hello(name)
"""


@pytest.fixture
def tmp_py_file():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        py_file = root / "hello.py"
        py_file.write_text(SIMPLE_PY, encoding="utf-8")
        yield py_file, root


class TestPythonExtractor:
    def test_extract_returns_result(self, tmp_py_file):
        py_file, root = tmp_py_file
        extractor = PythonExtractor()
        result = extractor.extract(
            file_path=str(py_file),
            project_root=str(root),
        )
        assert result.language_id == "python"
        assert result.file_path == "hello.py"
        assert len(result.symbols) > 0

    def test_extract_symbols_match_existing(self, tmp_py_file):
        """PythonExtractor symbols must match existing extract_symbols output."""
        py_file, root = tmp_py_file
        rel = normalize_path(py_file.relative_to(root))
        tree = parse_file(py_file)

        # Existing extraction
        existing_nodes = extract_symbols(rel, tree)

        # New extractor
        extractor = PythonExtractor()
        result = extractor.extract(
            file_path=str(py_file),
            project_root=str(root),
        )
        new_nodes = result.symbols

        # Same count
        assert len(new_nodes) == len(existing_nodes), (
            f"Node count mismatch: new={len(new_nodes)}, existing={len(existing_nodes)}"
        )

        # Same IDs
        existing_ids = {n.id for n in existing_nodes}
        new_ids = {n.id for n in new_nodes}
        assert new_ids == existing_ids, f"ID mismatch: {new_ids ^ existing_ids}"

    def test_extract_sets_language_id(self, tmp_py_file):
        py_file, root = tmp_py_file
        extractor = PythonExtractor()
        result = extractor.extract(
            file_path=str(py_file),
            project_root=str(root),
        )
        for node in result.symbols:
            assert node.language_id == "python"
            assert node.language == "python"

    def test_extract_produces_function_node(self, tmp_py_file):
        py_file, root = tmp_py_file
        extractor = PythonExtractor()
        result = extractor.extract(
            file_path=str(py_file),
            project_root=str(root),
        )
        funcs = [n for n in result.symbols if n.type == NodeType.function]
        assert len(funcs) == 1
        assert funcs[0].name == "hello"

    def test_extract_produces_class_node(self, tmp_py_file):
        py_file, root = tmp_py_file
        extractor = PythonExtractor()
        result = extractor.extract(
            file_path=str(py_file),
            project_root=str(root),
        )
        classes = [n for n in result.symbols if n.type == NodeType.class_]
        assert len(classes) == 1
        assert classes[0].name == "Greeter"

    def test_extract_produces_method_node(self, tmp_py_file):
        py_file, root = tmp_py_file
        extractor = PythonExtractor()
        result = extractor.extract(
            file_path=str(py_file),
            project_root=str(root),
        )
        methods = [n for n in result.symbols if n.type == NodeType.method]
        assert len(methods) == 1
        assert methods[0].name == "greet"

    def test_extract_produces_import_nodes(self, tmp_py_file):
        py_file, root = tmp_py_file
        extractor = PythonExtractor()
        result = extractor.extract(
            file_path=str(py_file),
            project_root=str(root),
        )
        imports = [n for n in result.symbols
                   if n.type in (NodeType.import_, NodeType.external_symbol)]
        assert len(imports) >= 1

    def test_extract_has_raw_edges(self, tmp_py_file):
        py_file, root = tmp_py_file
        extractor = PythonExtractor()
        result = extractor.extract(
            file_path=str(py_file),
            project_root=str(root),
        )
        assert hasattr(result, '_raw_edges')
        assert len(result._raw_edges) > 0

    def test_extract_populates_imports(self, tmp_py_file):
        py_file, root = tmp_py_file
        extractor = PythonExtractor()
        result = extractor.extract(
            file_path=str(py_file),
            project_root=str(root),
        )
        assert len(result.imports) >= 1

    def test_extract_populates_exports(self, tmp_py_file):
        py_file, root = tmp_py_file
        extractor = PythonExtractor()
        result = extractor.extract(
            file_path=str(py_file),
            project_root=str(root),
        )
        export_names = {e.name for e in result.exports}
        assert "hello" in export_names
        assert "Greeter" in export_names

    def test_extract_with_content_param(self):
        extractor = PythonExtractor()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            py_file = root / "test.py"
            py_file.write_text(SIMPLE_PY, encoding="utf-8")
            result = extractor.extract(
                file_path=str(py_file),
                content=SIMPLE_PY,
                project_root=str(root),
            )
            assert result.language_id == "python"
            assert len(result.symbols) > 0
