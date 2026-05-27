"""Tests for the indexer — scanner, parser, symbol extractor, call extractor, graph builder."""

import ast
from pathlib import Path

import pytest
from codegraph.indexer.scanner import scan_python_files, EXCLUDE_DIRS
from codegraph.indexer.parser_python import parse_file, extract_classes, extract_functions, extract_imports, is_test_function
from codegraph.indexer.symbol_extractor import (
    build_node_id, extract_symbols, _module_name, _visibility, _build_function_signature,
)
from codegraph.indexer.call_extractor import extract_calls, resolve_call_name, _FileContext
from codegraph.indexer.graph_builder import build_index, build_index_from_paths
from codegraph.graph.models import NodeType, EdgeType


# ══════════════════════════════════════════════════════════════════════════
# Scanner tests
# ══════════════════════════════════════════════════════════════════════════


class TestScanPythonFiles:
    def test_exclude_dirs(self):
        assert ".git" in EXCLUDE_DIRS
        assert "__pycache__" in EXCLUDE_DIRS
        assert "node_modules" in EXCLUDE_DIRS
        assert ".venv" in EXCLUDE_DIRS

    def test_scan_demo_project(self):
        """Integration test — scan the demo project."""
        demo_root = Path("examples/demo_python_project")
        if not demo_root.exists():
            pytest.skip("Demo project not found")
        files = scan_python_files(demo_root)
        assert len(files) >= 5  # main.py + app dir files
        assert any(f.name == "main.py" for f in files)
        assert any(f.name == "auth.py" for f in files)

    def test_scan_excludes_codegraph(self):
        """Ensure .codegraph dir is excluded even if present."""
        demo_root = Path("examples/demo_python_project")
        if not demo_root.exists():
            pytest.skip("Demo project not found")
        files = scan_python_files(demo_root)
        paths = {str(f.relative_to(demo_root)) for f in files}
        assert not any(p.startswith(".codegraph") for p in paths)


# ══════════════════════════════════════════════════════════════════════════
# Parser tests
# ══════════════════════════════════════════════════════════════════════════


SIMPLE_CODE = """
def greet(name: str) -> str:
    return f"Hello {name}"

class MyClass:
    def method(self) -> None:
        pass
"""


class TestParseFile:
    def test_parse_string(self):
        tree = ast.parse(SIMPLE_CODE)
        assert isinstance(tree, ast.Module)

    def test_extract_functions(self):
        tree = ast.parse(SIMPLE_CODE)
        funcs = extract_functions(tree)
        assert len(funcs) == 1
        assert funcs[0].name == "greet"

    def test_extract_classes(self):
        tree = ast.parse(SIMPLE_CODE)
        classes = extract_classes(tree)
        assert len(classes) == 1
        assert classes[0].name == "MyClass"

    def test_is_test_function(self):
        tree = ast.parse("def test_something(): pass")
        func = tree.body[0]
        assert is_test_function(func)

    def test_not_test_function(self):
        tree = ast.parse("def normal(): pass")
        func = tree.body[0]
        assert not is_test_function(func)

    def test_extract_imports(self):
        tree = ast.parse("import os\nfrom pathlib import Path\nx = 1")
        imports = extract_imports(tree)
        assert len(imports) == 2


# ══════════════════════════════════════════════════════════════════════════
# Symbol Extractor tests
# ══════════════════════════════════════════════════════════════════════════


class TestBuildNodeId:
    def test_file_node(self):
        assert build_node_id("app/api/auth.py") == "app/api/auth.py"

    def test_function_node(self):
        assert build_node_id("app/api/auth.py", "login") == "app/api/auth.py::login"

    def test_module_node(self):
        assert build_node_id("x.py", "module:app") == "module:app"

    def test_external_node(self):
        assert build_node_id("x.py", "external:fastapi.APIRouter") == "external:fastapi.APIRouter"


class TestModuleName:
    def test_simple(self):
        assert _module_name("app/api/auth.py") == "app.api.auth"

    def test_init(self):
        assert _module_name("app/__init__.py") == "app"

    def test_top_level(self):
        assert _module_name("main.py") == "main"

    def test_windows_path(self):
        assert _module_name("app\\api\\auth.py") == "app.api.auth"


class TestVisibility:
    def test_public(self):
        assert _visibility("login") == "public"

    def test_protected(self):
        assert _visibility("_helper") == "protected"

    def test_private(self):
        assert _visibility("__internal") == "private"


class TestBuildFunctionSignature:
    def test_simple(self):
        tree = ast.parse("def hello(name: str) -> None: pass")
        sig = _build_function_signature(tree.body[0])
        assert "hello" in sig
        assert "name: str" in sig
        assert "None" in sig

    def test_no_args(self):
        tree = ast.parse("def hello() -> int: pass")
        sig = _build_function_signature(tree.body[0])
        assert "hello()" in sig


class TestExtractSymbols:
    def test_extract_from_code(self):
        tree = ast.parse("""
def hello(name: str) -> None:
    '''Say hello.'''
    pass

class User:
    def greet(self) -> None:
        pass
""")
        nodes = extract_symbols("test.py", tree)
        ids = {n.id for n in nodes}
        assert "test.py::hello" in ids
        assert "test.py::User" in ids
        assert "test.py::User.greet" in ids

    def test_extract_file_node(self):
        tree = ast.parse("x = 1")
        nodes = extract_symbols("test.py", tree)
        file_nodes = [n for n in nodes if n.type == NodeType.file]
        assert len(file_nodes) == 1
        assert file_nodes[0].id == "test.py"

    def test_extract_module_node(self):
        tree = ast.parse("x = 1")
        nodes = extract_symbols("test.py", tree)
        module_nodes = [n for n in nodes if n.type == NodeType.module]
        assert len(module_nodes) == 1
        assert module_nodes[0].id == "module:test"

    def test_extract_imports(self):
        tree = ast.parse("import os\nfrom pathlib import Path")
        nodes = extract_symbols("test.py", tree)
        import_nodes = [n for n in nodes if n.type in (NodeType.import_, NodeType.external_symbol)]
        assert len(import_nodes) >= 2

    def test_signature_and_docstring(self):
        tree = ast.parse("""
def hello(name: str) -> None:
    '''Say hello.'''
    print(name)
""")
        nodes = extract_symbols("test.py", tree)
        func_node = next(n for n in nodes if n.name == "hello")
        assert func_node.signature is not None
        assert func_node.docstring == "Say hello."
        assert func_node.code_preview is not None


# ══════════════════════════════════════════════════════════════════════════
# Call Extractor tests
# ══════════════════════════════════════════════════════════════════════════


class TestResolveCallName:
    def test_simple_name(self):
        tree = ast.parse("foo()")
        call = tree.body[0].value
        assert resolve_call_name(call) == "foo"

    def test_attribute_call(self):
        tree = ast.parse("obj.method()")
        call = tree.body[0].value
        assert resolve_call_name(call) == "obj.method"

    def test_chained_attribute(self):
        tree = ast.parse("a.b.c()")
        call = tree.body[0].value
        assert resolve_call_name(call) == "a.b.c"


class TestExtractCalls:
    def test_same_file_call(self):
        code = """
def foo():
    bar()

def bar():
    pass
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("test.py"), rel_path="test.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        assert any(e.source == "test.py::foo" and e.target == "test.py::bar" for e in call_edges)

    def test_call_within_class(self):
        code = """
class MyClass:
    def run(self):
        self.helper()

    def helper(self):
        pass
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("test.py"), rel_path="test.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        assert any(e.source == "test.py::MyClass.run" and e.target == "test.py::MyClass.helper"
                   for e in call_edges)

    def test_confidence_levels(self):
        code = """
def foo():
    bar()

def bar():
    pass
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("test.py"), rel_path="test.py")
        for e in edges:
            assert 0.0 <= e.confidence <= 1.0
            assert e.metadata is not None
            assert e.metadata.resolution is not None

    def test_no_calls(self):
        code = """
x = 1
y = 2
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("test.py"), rel_path="test.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        assert call_edges == []

    def test_inherits(self):
        code = """
class Base:
    pass

class Child(Base):
    pass
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("test.py"), rel_path="test.py")
        inherits_edges = [e for e in edges if e.type == EdgeType.inherits]
        assert len(inherits_edges) >= 1
        assert inherits_edges[0].source == "test.py::Child"
        assert "Base" in inherits_edges[0].target


# ══════════════════════════════════════════════════════════════════════════
# Graph Builder tests (integration)
# ══════════════════════════════════════════════════════════════════════════


class TestBuildIndex:
    def test_build_from_paths(self):
        """Build index from source code strings."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "test.py").write_text("""
def hello():
    pass
""", encoding="utf-8")
        paths = [tmp / "test.py"]
        nodes, edges = build_index_from_paths(tmp, paths)
        assert len(nodes) >= 2  # file node + module node + function node
        assert any(n.id == "test.py::hello" for n in nodes)

    def test_build_demo_project(self):
        """Full integration test with demo project."""
        demo_root = Path("examples/demo_python_project")
        if not demo_root.exists():
            pytest.skip("Demo project not found")
        nodes, edges = build_index(demo_root)
        assert len(nodes) > 10
        assert len(edges) > 10
        # Check we find key symbols
        ids = {n.id for n in nodes}
        assert "app/api/auth.py::login" in ids
        assert "app/api/auth.py::logout" in ids
        assert "app/store/token_store.py::save_token" in ids
        assert "main.py::main" in ids
        # Check call edges
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        assert len(call_edges) > 0
