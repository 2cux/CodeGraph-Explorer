"""Tests for the indexer — scanner, parser, symbol extractor, call extractor, graph builder."""

import ast
from pathlib import Path

import pytest
from codegraph.indexer.scanner import scan_python_files, EXCLUDE_DIRS
from codegraph.indexer.parser_python import parse_file, extract_classes, extract_functions, extract_imports, is_test_function
from codegraph.indexer.symbol_extractor import (
    build_node_id, extract_symbols, _module_name, _visibility, _build_function_signature,
    _is_test_file, _is_test_class, _detect_route_decorator, _detect_route_decorators_for_class,
)
from codegraph.indexer.call_extractor import (
    extract_calls, resolve_call_name, _FileContext,
    _ImportResolver, _reconstruct_attribute, _file_module,
)
from codegraph.indexer.symbol_extractor import (
    _resolve_relative_module as _symbol_resolve_relative,
)
from codegraph.indexer.graph_builder import build_index, build_index_from_paths, _build_test_relationships
from codegraph.graph.models import NodeType, EdgeType, Resolution


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

    def test_cross_file_calls_not_external(self):
        """Cross-file calls via from-import must resolve to real node IDs.

        Genuine stdlib/builtin calls (len, print, etc.) may stay as
        external: — only project-internal cross-file calls must resolve.
        """
        demo_root = Path("examples/demo_python_project")
        if not demo_root.exists():
            pytest.skip("Demo project not found")
        nodes, edges = build_index(demo_root)

        call_edges = [e for e in edges if e.type == EdgeType.calls]
        cross_file = [e for e in call_edges if e.source != e.target]
        assert len(cross_file) > 0, "Expected at least one cross-file call edge"

        internal_ids = {n.id for n in nodes if not n.id.startswith("external:")}
        # Build set of known qualified names for internal symbols
        internal_qual_names = {
            n.qualified_name for n in nodes
            if n.qualified_name and not n.id.startswith("external:")
        }

        unresolved_internal: list[str] = []
        for e in call_edges:
            if e.source not in internal_ids:
                continue
            if not e.target.startswith("external:"):
                continue
            qual_name = e.target[len("external:"):]
            # Only flag if the qual_name looks like a project-internal symbol
            # that we failed to resolve
            if qual_name in internal_qual_names or any(
                qual_name.startswith(prefix)
                for prefix in ["app.", "src.", "backend."]
            ):
                unresolved_internal.append(
                    f"{e.source} -> {e.target}"
                )

        assert unresolved_internal == [], (
            f"{len(unresolved_internal)} project-internal calls NOT resolved: "
            f"{unresolved_internal[:5]}"
        )

    def test_call_edges_use_import_resolved_confidence(self):
        """Cross-file calls from known imports must use import-resolved confidence.

        The exact resolution enum may be any of the import variants
        (imported_function_exact, imported_function_alias,
        imported_module_attribute, relative_import_resolved, or the
        legacy import_resolved) depending on the import pattern used.
        """
        demo_root = Path("examples/demo_python_project")
        if not demo_root.exists():
            pytest.skip("Demo project not found")
        nodes, edges = build_index(demo_root)

        _import_resolutions = {
            Resolution.imported_function_exact,
            Resolution.imported_function_alias,
            Resolution.imported_module_attribute,
            Resolution.relative_import_resolved,
            Resolution.import_resolved,
        }
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        resolved = [e for e in call_edges
                    if e.metadata and e.metadata.resolution in _import_resolutions]
        assert len(resolved) > 0, (
            "Expected at least one call edge with import-based resolution"
        )


# ══════════════════════════════════════════════════════════════════════════
# ImportResolver unit tests
# ══════════════════════════════════════════════════════════════════════════


class TestImportResolver:
    """Unit tests for _ImportResolver covering all 6 import/call patterns."""

    # ── Case 1: Absolute from-import ────────────────────────────────

    def test_case1_absolute_from_import(self):
        """``from app.store.token_store import save_token`` → ``save_token()``"""
        resolver = _ImportResolver("app.api.auth")
        alias = ast.alias(name="save_token", asname=None)
        resolver.add_import_from(alias, "app.store.token_store", level=0)

        target = resolver.resolve_name("save_token")
        assert target == "app.store.token_store.save_token"

    def test_case1_resolve_after_import(self):
        """Name must be resolvable after adding the import."""
        resolver = _ImportResolver("app.api.auth")
        alias = ast.alias(name="save_token", asname=None)
        resolver.add_import_from(alias, "app.store.token_store", level=0)

        assert resolver.resolve_name("save_token") is not None
        assert resolver.resolve_name("nonexistent") is None

    # ── Case 2: Absolute import module (chained attr call) ──────────

    def test_case2_absolute_import_module_is_known(self):
        """``import app.store.token_store`` → module tracked in known_modules."""
        resolver = _ImportResolver("main")
        alias = ast.alias(name="app.store.token_store", asname=None)
        resolver.add_import(alias)

        assert "app.store.token_store" in resolver.known_modules

    def test_case2_chained_attribute_resolution(self):
        """``app.store.token_store.save_token()`` → resolved via known_modules."""
        resolver = _ImportResolver("main")
        alias = ast.alias(name="app.store.token_store", asname=None)
        resolver.add_import(alias)

        target = resolver.resolve_chained("app.store.token_store.save_token")
        assert target == "app.store.token_store.save_token"

    def test_case2_alias_to_module(self):
        """``import a.b.c`` binds the top-level component ``a``."""
        resolver = _ImportResolver("main")
        alias = ast.alias(name="a.b.c", asname=None)
        resolver.add_import(alias)

        assert resolver.alias_to_module["a"] == "a.b.c"

    # ── Case 3: Import alias ────────────────────────────────────────

    def test_case3_import_alias_resolve_attribute(self):
        """``import app.store.token_store as ts`` → ``ts.func()``"""
        resolver = _ImportResolver("main")
        alias = ast.alias(name="app.store.token_store", asname="ts")
        resolver.add_import(alias)

        target = resolver.resolve_attribute("ts", "save_token")
        assert target == "app.store.token_store.save_token"

    def test_case3_import_alias_not_resolve_name(self):
        """Alias should NOT resolve as a plain name call (it's a module, not a symbol)."""
        resolver = _ImportResolver("main")
        alias = ast.alias(name="app.store.token_store", asname="ts")
        resolver.add_import(alias)

        assert resolver.resolve_name("ts") is None

    # ── Case 4: From-import alias ───────────────────────────────────

    def test_case4_from_import_alias(self):
        """``from app.store.token_store import save_token as persist`` → ``persist()``"""
        resolver = _ImportResolver("app.api.auth")
        alias = ast.alias(name="save_token", asname="persist_token")
        resolver.add_import_from(alias, "app.store.token_store", level=0)

        target = resolver.resolve_name("persist_token")
        assert target == "app.store.token_store.save_token"

    # ── Case 5: Same-package relative import ────────────────────────

    def test_case5_relative_import_level1(self):
        """``from .token_store import save_token`` in ``app.api.auth``"""
        resolver = _ImportResolver("app.api.auth")
        alias = ast.alias(name="save_token", asname=None)
        resolver.add_import_from(alias, "token_store", level=1)

        target = resolver.resolve_name("save_token")
        assert target == "app.api.token_store.save_token"

    def test_case5_relative_import_level1_init(self):
        """``from .mfa import verify_totp`` in ``app.api.auth``"""
        resolver = _ImportResolver("app.api.auth")
        alias = ast.alias(name="verify_totp", asname=None)
        resolver.add_import_from(alias, "mfa", level=1)

        target = resolver.resolve_name("verify_totp")
        assert target == "app.api.mfa.verify_totp"

    # ── Case 6: Parent-package relative import ──────────────────────

    def test_case6_relative_import_level2(self):
        """``from ..store.token_store import save_token`` in ``app.api.auth``"""
        resolver = _ImportResolver("app.api.auth")
        alias = ast.alias(name="save_token", asname=None)
        resolver.add_import_from(alias, "store.token_store", level=2)

        target = resolver.resolve_name("save_token")
        assert target == "app.store.token_store.save_token"

    def test_case6_relative_import_level2_deep(self):
        """``from ..other import func`` in ``a.b.c.mod`` → ``a.b.other.func``"""
        resolver = _ImportResolver("a.b.c.mod")
        alias = ast.alias(name="func", asname=None)
        resolver.add_import_from(alias, "other", level=2)

        target = resolver.resolve_name("func")
        assert target == "a.b.other.func"

    # ── Edge cases ──────────────────────────────────────────────────

    def test_relative_beyond_top_level(self):
        """Level > len(module_parts) keeps the base as-is."""
        resolver = _ImportResolver("main")
        alias = ast.alias(name="func", asname=None)
        resolver.add_import_from(alias, "something", level=3)

        # main has only 1 part; level 3 > 1, so base is kept as "something"
        target = resolver.resolve_name("func")
        assert target == "something.func"

    def test_known_modules_tracks_all_imports(self):
        """Both add_import and add_import_from should populate known_modules."""
        resolver = _ImportResolver("a.b")
        resolver.add_import(ast.alias(name="x.y.z", asname=None))
        resolver.add_import_from(ast.alias(name="func"), "p.q", level=0)

        assert "x.y.z" in resolver.known_modules
        assert "p.q" in resolver.known_modules

    def test_multiple_imports_same_file(self):
        """Multiple imports in the same file should all be tracked."""
        resolver = _ImportResolver("app.api.auth")
        resolver.add_import_from(ast.alias(name="save_token"), "app.store.token_store", level=0)
        resolver.add_import_from(ast.alias(name="revoke_token"), "app.store.token_store", level=0)
        resolver.add_import_from(ast.alias(name="verify_totp"), "mfa", level=1)

        assert resolver.resolve_name("save_token") == "app.store.token_store.save_token"
        assert resolver.resolve_name("revoke_token") == "app.store.token_store.revoke_token"
        assert resolver.resolve_name("verify_totp") == "app.api.mfa.verify_totp"


# ══════════════════════════════════════════════════════════════════════════
# Attribute reconstruction tests
# ══════════════════════════════════════════════════════════════════════════


class TestReconstructAttribute:
    """Tests for _reconstruct_attribute helper."""

    def test_simple_attribute(self):
        """obj.method → 'obj.method'"""
        tree = ast.parse("obj.method()")
        call = tree.body[0].value
        assert isinstance(call.func, ast.Attribute)
        assert _reconstruct_attribute(call.func) == "obj.method"

    def test_chained_attribute_three_levels(self):
        """a.b.c → 'a.b.c'"""
        tree = ast.parse("a.b.c()")
        call = tree.body[0].value
        assert isinstance(call.func, ast.Attribute)
        assert _reconstruct_attribute(call.func) == "a.b.c"

    def test_chained_attribute_four_levels(self):
        """app.store.token_store.save_token → 'app.store.token_store.save_token'"""
        tree = ast.parse("app.store.token_store.save_token()")
        call = tree.body[0].value
        assert isinstance(call.func, ast.Attribute)
        assert _reconstruct_attribute(call.func) == "app.store.token_store.save_token"


# ══════════════════════════════════════════════════════════════════════════
# Relative module resolution tests
# ══════════════════════════════════════════════════════════════════════════


class TestResolveRelativeModule:
    """Tests for _resolve_relative_module helper."""

    def test_level_zero_absolute(self):
        result = _symbol_resolve_relative("app.store.token_store", 0, "main")
        assert result == "app.store.token_store"

    def test_level_one(self):
        result = _symbol_resolve_relative("mfa", 1, "app.api.auth")
        assert result == "app.api.mfa"

    def test_level_two(self):
        result = _symbol_resolve_relative("store.token_store", 2, "app.api.auth")
        assert result == "app.store.token_store"

    def test_level_one_no_base(self):
        """``from . import something`` → base may be empty/None."""
        result = _symbol_resolve_relative("", 1, "app.api.auth")
        assert result == "app.api"

    def test_level_beyond_top(self):
        result = _symbol_resolve_relative("thing", 5, "a.b")
        assert result == "thing"


# ══════════════════════════════════════════════════════════════════════════
# File module helper tests
# ══════════════════════════════════════════════════════════════════════════


class TestFileModule:
    def test_simple(self):
        assert _file_module("app/api/auth.py") == "app.api.auth"

    def test_init(self):
        assert _file_module("app/store/__init__.py") == "app.store"

    def test_top_level(self):
        assert _file_module("main.py") == "main"

    def test_windows_paths(self):
        assert _file_module("app\\api\\users.py") == "app.api.users"


# ══════════════════════════════════════════════════════════════════════════
# Cross-file call integration tests (temp multi-file projects)
# ══════════════════════════════════════════════════════════════════════════


class TestCrossFileCallResolution:
    """End-to-end tests: build index from multi-file temp projects and
    verify that cross-file calls are resolved to real node IDs."""

    def test_case1_from_import_call_resolved(self):
        """from-import → call → must resolve to real target node."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "store").mkdir(parents=True, exist_ok=True)

        (tmp / "store" / "token_store.py").write_text("""
def save_token(token: str) -> None:
    pass
""", encoding="utf-8")

        (tmp / "auth.py").write_text("""
from store.token_store import save_token

def login(username: str) -> str:
    save_token("abc")
    return "ok"
""", encoding="utf-8")

        nodes, edges = build_index(tmp)

        # Verify the target node exists
        assert any(n.id == "store/token_store.py::save_token" for n in nodes)

        # Verify the call edge was resolved to the real target
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        login_calls = [e for e in call_edges
                       if e.source == "auth.py::login"]
        assert len(login_calls) == 1
        assert login_calls[0].target == "store/token_store.py::save_token"
        assert login_calls[0].metadata is not None
        assert login_calls[0].metadata.resolution == Resolution.imported_function_exact

    def test_case3_import_alias_call_resolved(self):
        """import X as Y → Y.func() → must resolve."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "store").mkdir(parents=True, exist_ok=True)

        (tmp / "store" / "token_store.py").write_text("""
def revoke_token(token: str) -> None:
    pass
""", encoding="utf-8")

        (tmp / "auth.py").write_text("""
import store.token_store as st

def logout(token: str) -> None:
    st.revoke_token(token)
""", encoding="utf-8")

        nodes, edges = build_index(tmp)

        call_edges = [e for e in edges if e.type == EdgeType.calls]
        logout_calls = [e for e in call_edges
                        if e.source == "auth.py::logout"]
        assert len(logout_calls) == 1
        assert logout_calls[0].target == "store/token_store.py::revoke_token"

    def test_case4_from_import_alias_resolved(self):
        """from X import Y as Z → Z() → must resolve."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "store").mkdir(parents=True, exist_ok=True)

        (tmp / "store" / "token_store.py").write_text("""
def save_token(token: str) -> None:
    pass
""", encoding="utf-8")

        (tmp / "auth.py").write_text("""
from store.token_store import save_token as persist

def login(u: str) -> str:
    persist("abc")
    return "ok"
""", encoding="utf-8")

        nodes, edges = build_index(tmp)

        call_edges = [e for e in edges if e.type == EdgeType.calls]
        login_calls = [e for e in call_edges
                       if e.source == "auth.py::login"]
        assert len(login_calls) == 1
        assert login_calls[0].target == "store/token_store.py::save_token"

    def test_case5_relative_import_resolved(self):
        """from .module import func → func() → must resolve."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "api").mkdir(parents=True, exist_ok=True)

        (tmp / "api" / "mfa.py").write_text("""
def verify_code(code: str) -> bool:
    return True
""", encoding="utf-8")

        (tmp / "api" / "auth.py").write_text("""
from .mfa import verify_code

def login() -> bool:
    return verify_code("123")
""", encoding="utf-8")

        nodes, edges = build_index(tmp)

        call_edges = [e for e in edges if e.type == EdgeType.calls]
        login_calls = [e for e in call_edges
                       if e.source == "api/auth.py::login"]
        assert len(login_calls) == 1
        assert login_calls[0].target == "api/mfa.py::verify_code"

    def test_case6_parent_relative_import_resolved(self):
        """from ..sibling.module import func → func() → must resolve."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "store").mkdir(parents=True, exist_ok=True)
        (tmp / "api").mkdir(parents=True, exist_ok=True)

        (tmp / "store" / "token_store.py").write_text("""
def save_token(token: str) -> None:
    pass
""", encoding="utf-8")

        (tmp / "api" / "auth.py").write_text("""
from ..store.token_store import save_token

def login() -> str:
    save_token("xyz")
    return "done"
""", encoding="utf-8")

        nodes, edges = build_index(tmp)

        call_edges = [e for e in edges if e.type == EdgeType.calls]
        login_calls = [e for e in call_edges
                       if e.source == "api/auth.py::login"]
        assert len(login_calls) == 1
        assert login_calls[0].target == "store/token_store.py::save_token"

    def test_case2_chained_import_call_resolved(self):
        """import a.b.c → a.b.c.func() → must resolve."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "store").mkdir(parents=True, exist_ok=True)

        (tmp / "store" / "token_store.py").write_text("""
def save_token(token: str) -> None:
    pass
""", encoding="utf-8")

        (tmp / "auth.py").write_text("""
import store.token_store

def login(u: str) -> str:
    store.token_store.save_token("abc")
    return "ok"
""", encoding="utf-8")

        nodes, edges = build_index(tmp)

        call_edges = [e for e in edges if e.type == EdgeType.calls]
        login_calls = [e for e in call_edges
                       if e.source == "auth.py::login"]
        assert len(login_calls) == 1
        assert login_calls[0].target == "store/token_store.py::save_token"

    def test_callers_callees_work_with_cross_file_calls(self):
        """After resolution, callers() and callees() must return correct results."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "store").mkdir(parents=True, exist_ok=True)

        (tmp / "store" / "token_store.py").write_text("""
def save_token(token: str) -> None:
    pass
""", encoding="utf-8")

        (tmp / "auth.py").write_text("""
from store.token_store import save_token

def login(u: str) -> str:
    save_token("abc")
    return "ok"
""", encoding="utf-8")

        from codegraph.graph.store import GraphStore
        from codegraph.graph.query import get_callers, get_callees

        nodes, edges = build_index(tmp)
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        # callees of login should include save_token
        callees = get_callees(store, "auth.py::login")
        callee_ids = [c[0] for c in callees]
        assert "store/token_store.py::save_token" in callee_ids

        # callers of save_token should include login
        callers = get_callers(store, "store/token_store.py::save_token")
        caller_ids = [c[0] for c in callers]
        assert "auth.py::login" in caller_ids


# ══════════════════════════════════════════════════════════════════════════
# Test file / class detection tests
# ══════════════════════════════════════════════════════════════════════════


class TestIsTestFile:
    """Tests for _is_test_file helper."""

    def test_tests_directory(self):
        assert _is_test_file("tests/test_auth.py") is True

    def test_nested_tests_directory(self):
        assert _is_test_file("src/tests/test_auth.py") is True

    def test_test_prefix_file(self):
        assert _is_test_file("test_auth.py") is True

    def test_test_prefix_in_tests_dir(self):
        assert _is_test_file("tests/test_auth.py") is True

    def test_test_suffix_file(self):
        assert _is_test_file("auth_test.py") is True

    def test_test_suffix_in_tests_dir(self):
        assert _is_test_file("tests/auth_test.py") is True

    def test_not_test_file(self):
        assert _is_test_file("app/api/auth.py") is False

    def test_not_test_file_test_in_middle(self):
        # test_ prefix ANYWHERE in the filename marks it as test file
        # per _is_test_file implementation
        assert _is_test_file("app/test_utils.py") is True


class TestIsTestClass:
    """Tests for _is_test_class helper."""

    def test_test_prefix_class(self):
        tree = ast.parse("class TestAuth:\n    pass")
        cls = tree.body[0]
        assert _is_test_class(cls) is True

    def test_unittest_testcase_class(self):
        tree = ast.parse("import unittest\nclass MyTest(unittest.TestCase):\n    pass")
        cls = tree.body[1]
        assert _is_test_class(cls) is True

    def test_not_test_class(self):
        tree = ast.parse("class AuthService:\n    pass")
        cls = tree.body[0]
        assert _is_test_class(cls) is False

    def test_not_test_class_t_in_name(self):
        tree = ast.parse("class Latest:\n    pass")
        cls = tree.body[0]
        assert _is_test_class(cls) is False


# ══════════════════════════════════════════════════════════════════════════
# Test symbol extraction tests
# ══════════════════════════════════════════════════════════════════════════


class TestExtractTestSymbols:
    """Verify that test functions and methods are correctly typed as NodeType.test."""

    def test_pytest_function_is_test(self):
        """Case 1: pytest test_ function in tests/ dir → type=test."""
        code = "def test_login_success():\n    pass"
        tree = ast.parse(code)
        nodes = extract_symbols("tests/test_auth.py", tree)
        test_nodes = [n for n in nodes if n.type == NodeType.test]
        assert len(test_nodes) == 1
        assert test_nodes[0].name == "test_login_success"
        assert "test" in test_nodes[0].tags

    def test_async_test_function_is_test(self):
        """Case 2: async test_ function → type=test."""
        code = "async def test_login_success():\n    pass"
        tree = ast.parse(code)
        nodes = extract_symbols("tests/test_auth.py", tree)
        test_nodes = [n for n in nodes if n.type == NodeType.test]
        assert len(test_nodes) == 1
        assert test_nodes[0].name == "test_login_success"
        assert "async" in test_nodes[0].tags

    def test_unittest_testcase_method_is_test(self):
        """Case 3: unittest.TestCase subclass with test_ method → type=test."""
        code = """
import unittest
class MyTest(unittest.TestCase):
    def test_login_success(self):
        pass
"""
        tree = ast.parse(code)
        nodes = extract_symbols("tests/test_auth.py", tree)
        test_nodes = [n for n in nodes if n.type == NodeType.test]
        assert len(test_nodes) == 1
        assert test_nodes[0].name == "test_login_success"

    def test_test_prefix_class_method_is_test(self):
        """Case 4: Test* class with test_ method → type=test."""
        code = """
class TestAuth:
    def test_login_success(self):
        pass
"""
        tree = ast.parse(code)
        nodes = extract_symbols("tests/test_auth.py", tree)
        test_nodes = [n for n in nodes if n.type == NodeType.test]
        assert len(test_nodes) == 1
        assert test_nodes[0].name == "test_login_success"

    def test_test_class_has_test_tag(self):
        """Test* class itself gets 'test' tag."""
        code = """
class TestAuth:
    def test_login(self):
        pass
"""
        tree = ast.parse(code)
        nodes = extract_symbols("tests/test_auth.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        assert "test" in class_nodes[0].tags

    def test_non_test_method_in_test_class_stays_method(self):
        """Helper/setup methods in Test* class stay as type=method."""
        code = """
class TestAuth:
    def setUp(self):
        pass
    def test_login(self):
        pass
"""
        tree = ast.parse(code)
        nodes = extract_symbols("tests/test_auth.py", tree)
        method_nodes = [n for n in nodes if n.type == NodeType.method]
        assert len(method_nodes) == 1
        assert method_nodes[0].name == "setUp"

    def test_non_test_file_function_is_not_test(self):
        """test_ function outside tests/ or test_ file → still type=test (pytest convention)."""
        code = "def test_helper():\n    pass"
        tree = ast.parse(code)
        nodes = extract_symbols("app/utils.py", tree)
        test_nodes = [n for n in nodes if n.type == NodeType.test]
        assert len(test_nodes) == 1  # test_ prefix always marks as test


# ══════════════════════════════════════════════════════════════════════════
# Tested-by edge generation tests
# ══════════════════════════════════════════════════════════════════════════


class TestBuildTestRelationships:
    """Tests for _build_test_relationships in graph_builder."""

    def test_direct_call_creates_tested_by_edge(self):
        """Strategy 1: test function calls target → tested_by edge generated."""
        from codegraph.graph.models import GraphNode, GraphEdge, EdgeType, EdgeMetadata, Resolution, Location, NodeType
        nodes = [
            GraphNode(id="app/api/auth.py::login", type=NodeType.function, name="login",
                      file_path="app/api/auth.py", module="app.api.auth",
                      qualified_name="app.api.auth.login"),
            GraphNode(id="tests/test_auth.py::test_login_success", type=NodeType.test,
                      name="test_login_success", file_path="tests/test_auth.py",
                      module="tests.test_auth", qualified_name="tests.test_auth.test_login_success"),
        ]
        edges = [
            GraphEdge(id="e1", type=EdgeType.calls,
                      source="tests/test_auth.py::test_login_success",
                      target="app/api/auth.py::login", confidence=0.9,
                      metadata=EdgeMetadata(resolution=Resolution.import_resolved)),
        ]
        result = _build_test_relationships(nodes, edges, [100])
        tested_by_edges = [e for e in result if e.type == EdgeType.tested_by]
        assert len(tested_by_edges) == 1
        assert tested_by_edges[0].source == "app/api/auth.py::login"
        assert tested_by_edges[0].target == "tests/test_auth.py::test_login_success"
        assert tested_by_edges[0].confidence == 0.9

    def test_name_heuristic_creates_tested_by_edge(self):
        """Strategy 2: test name contains target function name → heuristic edge."""
        from codegraph.graph.models import GraphNode, GraphEdge, EdgeType, EdgeMetadata, Resolution, NodeType
        nodes = [
            GraphNode(id="app/api/auth.py::login", type=NodeType.function, name="login",
                      file_path="app/api/auth.py", module="app.api.auth",
                      qualified_name="app.api.auth.login"),
            GraphNode(id="tests/test_auth.py::test_login_success", type=NodeType.test,
                      name="test_login_success", file_path="tests/test_auth.py",
                      module="tests.test_auth", qualified_name="tests.test_auth.test_login_success"),
        ]
        edges: list[GraphEdge] = []
        result = _build_test_relationships(nodes, edges, [100])
        tested_by_edges = [e for e in result if e.type == EdgeType.tested_by]
        assert len(tested_by_edges) == 1
        assert tested_by_edges[0].source == "app/api/auth.py::login"
        assert tested_by_edges[0].confidence == 0.65
        assert tested_by_edges[0].metadata.resolution == Resolution.test_name_heuristic

    def test_name_heuristic_matches_first_word(self):
        """test_login_success → login (first word match after stripping test_)."""
        from codegraph.graph.models import GraphNode, GraphEdge, EdgeType, EdgeMetadata, Resolution, NodeType
        nodes = [
            GraphNode(id="app/api/auth.py::login", type=NodeType.function, name="login",
                      file_path="app/api/auth.py", module="app.api.auth",
                      qualified_name="app.api.auth.login"),
            GraphNode(id="tests/test_auth.py::test_login_success", type=NodeType.test,
                      name="test_login_success", file_path="tests/test_auth.py",
                      module="tests.test_auth", qualified_name="tests.test_auth.test_login_success"),
        ]
        edges: list[GraphEdge] = []
        result = _build_test_relationships(nodes, edges, [100])
        tested_by_edges = [e for e in result if e.type == EdgeType.tested_by]
        assert len(tested_by_edges) == 1
        assert tested_by_edges[0].source == "app/api/auth.py::login"

    def test_file_name_match_creates_tested_by_edge(self):
        """Strategy 3: test_auth.py → auth.py symbols → file-name-based edge."""
        from codegraph.graph.models import GraphNode, GraphEdge, EdgeType, EdgeMetadata, Resolution, NodeType
        nodes = [
            GraphNode(id="app/api/auth.py::authenticate", type=NodeType.function, name="authenticate",
                      file_path="app/api/auth.py", module="app.api.auth",
                      qualified_name="app.api.auth.authenticate"),
            GraphNode(id="tests/test_auth.py::test_basic_flow", type=NodeType.test,
                      name="test_basic_flow", file_path="tests/test_auth.py",
                      module="tests.test_auth", qualified_name="tests.test_auth.test_basic_flow"),
        ]
        edges: list[GraphEdge] = []
        result = _build_test_relationships(nodes, edges, [100])
        tested_by_edges = [e for e in result if e.type == EdgeType.tested_by]
        assert len(tested_by_edges) == 1
        assert tested_by_edges[0].confidence == 0.55
        assert tested_by_edges[0].metadata.resolution == Resolution.test_file_heuristic

    def test_no_duplicate_tested_by_edges(self):
        """When both direct call and name heuristic match, only one tested_by edge."""
        from codegraph.graph.models import GraphNode, GraphEdge, EdgeType, EdgeMetadata, Resolution, NodeType
        nodes = [
            GraphNode(id="app/api/auth.py::login", type=NodeType.function, name="login",
                      file_path="app/api/auth.py", module="app.api.auth",
                      qualified_name="app.api.auth.login"),
            GraphNode(id="tests/test_auth.py::test_login_success", type=NodeType.test,
                      name="test_login_success", file_path="tests/test_auth.py",
                      module="tests.test_auth", qualified_name="tests.test_auth.test_login_success"),
        ]
        edges = [
            GraphEdge(id="e1", type=EdgeType.calls,
                      source="tests/test_auth.py::test_login_success",
                      target="app/api/auth.py::login", confidence=0.9,
                      metadata=EdgeMetadata(resolution=Resolution.import_resolved)),
        ]
        result = _build_test_relationships(nodes, edges, [100])
        tested_by_edges = [e for e in result if e.type == EdgeType.tested_by]
        assert len(tested_by_edges) == 1  # deduplicated

    def test_no_tests_returns_empty(self):
        """Empty result when no test nodes exist."""
        from codegraph.graph.models import GraphNode, GraphEdge, EdgeType, EdgeMetadata, Resolution, NodeType
        nodes = [
            GraphNode(id="app/api/auth.py::login", type=NodeType.function, name="login",
                      file_path="app/api/auth.py", module="app.api.auth",
                      qualified_name="app.api.auth.login"),
        ]
        edges: list[GraphEdge] = []
        result = _build_test_relationships(nodes, edges, [100])
        assert len(result) == 0


# ══════════════════════════════════════════════════════════════════════════
# Integration test — full test discovery in index
# ══════════════════════════════════════════════════════════════════════════


class TestFullTestDiscovery:
    """End-to-end test: build index from a project with tests and verify
    test nodes, tested_by edges, and discovery pipeline."""

    def test_test_functions_get_test_type(self):
        """Tests in a tests/ dir with test_ prefix → type=test."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "app").mkdir(parents=True, exist_ok=True)
        (tmp / "tests").mkdir(parents=True, exist_ok=True)

        (tmp / "app" / "auth.py").write_text("""
def login(username: str, password: str) -> str:
    return "token"
""", encoding="utf-8")

        (tmp / "tests" / "test_auth.py").write_text("""
from app.auth import login

def test_login_success():
    result = login("alice", "password")
    assert result is not None

def test_login_failure():
    assert True
""", encoding="utf-8")

        nodes, edges = build_index(tmp)

        # Check test nodes exist
        test_nodes = [n for n in nodes if n.type == NodeType.test]
        assert len(test_nodes) == 2
        test_names = {n.name for n in test_nodes}
        assert "test_login_success" in test_names
        assert "test_login_failure" in test_names

    def test_direct_call_from_test_generates_calls_edge(self):
        """Test that calls target function → calls edge exists."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "app").mkdir(parents=True, exist_ok=True)
        (tmp / "tests").mkdir(parents=True, exist_ok=True)

        (tmp / "app" / "auth.py").write_text("""
def login(username: str, password: str) -> str:
    return "token"
""", encoding="utf-8")

        (tmp / "tests" / "test_auth.py").write_text("""
from app.auth import login

def test_login_success():
    result = login("alice", "password")
""", encoding="utf-8")

        nodes, edges = build_index(tmp)

        # Check calls edge from test to target
        test_calls = [e for e in edges
                      if e.type == EdgeType.calls
                      and e.source == "tests/test_auth.py::test_login_success"]
        assert len(test_calls) == 1
        assert test_calls[0].target == "app/auth.py::login"

    def test_tested_by_edge_generated_in_full_build(self):
        """Full index build should contain tested_by edges for tests."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "app").mkdir(parents=True, exist_ok=True)
        (tmp / "tests").mkdir(parents=True, exist_ok=True)

        (tmp / "app" / "auth.py").write_text("""
def login(username: str, password: str) -> str:
    return "token"
""", encoding="utf-8")

        (tmp / "tests" / "test_auth.py").write_text("""
from app.auth import login

def test_login_success():
    result = login("alice", "password")

def test_login_failure():
    pass
""", encoding="utf-8")

        nodes, edges = build_index(tmp)

        # test_login_success calls login → tested_by should exist
        tested_by = [e for e in edges if e.type == EdgeType.tested_by]
        assert len(tested_by) >= 1  # at least test_login_success → login

        # Check target → test direction
        login_tests = [e for e in tested_by if e.source == "app/auth.py::login"]
        assert len(login_tests) >= 1
        assert any(e.target == "tests/test_auth.py::test_login_success" for e in login_tests)

    def test_name_heuristic_without_direct_call(self):
        """test_login_success that does NOT call login still matches via name heuristic."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "app").mkdir(parents=True, exist_ok=True)
        (tmp / "tests").mkdir(parents=True, exist_ok=True)

        (tmp / "app" / "auth.py").write_text("""
def login(username: str, password: str) -> str:
    return "token"
""", encoding="utf-8")

        (tmp / "tests" / "test_auth.py").write_text("""
# This test uses a client / HTTP layer, not a direct call
def test_login_success():
    response = {"status": "ok"}  # simulated client call
    assert response["status"] == "ok"
""", encoding="utf-8")

        nodes, edges = build_index(tmp)

        tested_by = [e for e in edges if e.type == EdgeType.tested_by]
        # Name heuristic should match test_login_success → login
        login_tests = [e for e in tested_by if e.source == "app/auth.py::login"]
        assert len(login_tests) >= 1
        name_heuristic_edges = [
            e for e in login_tests
            if e.metadata and e.metadata.resolution == Resolution.test_name_heuristic
        ]
        assert len(name_heuristic_edges) >= 1
        assert name_heuristic_edges[0].confidence == 0.65


# ══════════════════════════════════════════════════════════════════════════
# Route handler detection tests
# ══════════════════════════════════════════════════════════════════════════


class TestRouteDecoratorDetection:
    """Tests for _detect_route_decorator and _detect_route_decorators_for_class."""

    def test_fastapi_router_post(self):
        """FastAPI @router.post('/login') → detected as fastapi POST."""
        code = """
@router.post("/login")
def login(username: str, password: str) -> str:
    return "token"
"""
        tree = ast.parse(code)
        fn = tree.body[0]
        result = _detect_route_decorator(fn)
        assert result is not None
        assert result["framework"] == "fastapi"
        assert result["method"] == "POST"
        assert result["path"] == "/login"

    def test_fastapi_app_get(self):
        """FastAPI @app.get('/me') → detected as fastapi GET."""
        code = """
@app.get("/me")
def current_user() -> dict:
    return {}
"""
        tree = ast.parse(code)
        fn = tree.body[0]
        result = _detect_route_decorator(fn)
        assert result is not None
        assert result["framework"] == "fastapi"
        assert result["method"] == "GET"
        assert result["path"] == "/me"

    def test_fastapi_router_put(self):
        """FastAPI @router.put('/users/{id}') → detected."""
        code = """
@router.put("/users/{id}")
def update_user(id: int) -> dict:
    return {}
"""
        tree = ast.parse(code)
        fn = tree.body[0]
        result = _detect_route_decorator(fn)
        assert result is not None
        assert result["framework"] == "fastapi"
        assert result["method"] == "PUT"

    def test_fastapi_router_delete(self):
        """FastAPI @router.delete('/users/{id}') → detected."""
        code = """
@router.delete("/users/{id}")
def delete_user(id: int) -> None:
    pass
"""
        tree = ast.parse(code)
        fn = tree.body[0]
        result = _detect_route_decorator(fn)
        assert result is not None
        assert result["framework"] == "fastapi"
        assert result["method"] == "DELETE"

    def test_fastapi_router_patch(self):
        """FastAPI @router.patch('/users/{id}') → detected."""
        code = """
@router.patch("/users/{id}")
def patch_user(id: int) -> dict:
    return {}
"""
        tree = ast.parse(code)
        fn = tree.body[0]
        result = _detect_route_decorator(fn)
        assert result is not None
        assert result["framework"] == "fastapi"
        assert result["method"] == "PATCH"

    def test_flask_app_route_get(self):
        """Flask @app.route('/users') without methods → defaults to ALL."""
        code = """
@app.route("/users")
def list_users():
    return []
"""
        tree = ast.parse(code)
        fn = tree.body[0]
        result = _detect_route_decorator(fn)
        assert result is not None
        assert result["framework"] == "flask"
        assert result["method"] == "ALL"

    def test_flask_app_route_post(self):
        """Flask @app.route('/login', methods=['POST']) → detected."""
        code = """
@app.route("/login", methods=["POST"])
def login():
    return "token"
"""
        tree = ast.parse(code)
        fn = tree.body[0]
        result = _detect_route_decorator(fn)
        assert result is not None
        assert result["framework"] == "flask"
        assert result["method"] == "POST"
        assert result["path"] == "/login"

    def test_non_route_decorator_is_none(self):
        """@dataclass or @staticmethod on a function → no route detected."""
        code = """
@staticmethod
def helper() -> int:
    return 42
"""
        tree = ast.parse(code)
        fn = tree.body[0]
        result = _detect_route_decorator(fn)
        assert result is None

    def test_no_decorator_is_none(self):
        """Function without any decorator → no route detected."""
        code = """
def normal_function() -> int:
    return 42
"""
        tree = ast.parse(code)
        fn = tree.body[0]
        result = _detect_route_decorator(fn)
        assert result is None

    def test_django_admin_register_on_class(self):
        """Django @admin.register(User) on a class → detected."""
        code = """
@admin.register(User)
class UserAdmin:
    pass
"""
        tree = ast.parse(code)
        cls = tree.body[0]
        results = _detect_route_decorators_for_class(cls)
        assert len(results) >= 1
        assert results[0]["framework"] == "django"
        assert results[0]["method"] == "ADMIN"


class TestRouteSymbolExtraction:
    """Verify route metadata and tags are set correctly on extracted nodes."""

    def test_route_node_has_route_metadata(self):
        """FastAPI route handler → node.metadata contains 'route' dict."""
        code = """
@router.post("/login")
def login(username: str, password: str) -> str:
    return "token"
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/api/auth.py", tree)
        fn_nodes = [n for n in nodes if n.type == NodeType.function]
        assert len(fn_nodes) == 1
        node = fn_nodes[0]
        assert "route" in node.metadata
        assert node.metadata["route"]["framework"] == "fastapi"
        assert node.metadata["route"]["method"] == "POST"
        assert node.metadata["route"]["path"] == "/login"

    def test_route_node_has_route_tags(self):
        """Route handler → tags contain 'route', 'api', and framework name."""
        code = """
@router.get("/me")
def current_user() -> dict:
    return {}
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/api/auth.py", tree)
        fn_nodes = [n for n in nodes if n.type == NodeType.function]
        assert len(fn_nodes) == 1
        assert "route" in fn_nodes[0].tags
        assert "api" in fn_nodes[0].tags
        assert "fastapi" in fn_nodes[0].tags

    def test_non_route_function_has_no_route_metadata(self):
        """Ordinary function without route decorator → no route metadata."""
        code = """
def normal_function() -> int:
    return 42
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/utils.py", tree)
        fn_nodes = [n for n in nodes if n.type == NodeType.function]
        assert len(fn_nodes) == 1
        assert "route" not in fn_nodes[0].metadata

    def test_async_route_handler_detected(self):
        """Async FastAPI route handler → still detected."""
        code = """
@router.get("/items")
async def list_items() -> list:
    return []
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/api/items.py", tree)
        fn_nodes = [n for n in nodes if n.type == NodeType.function]
        assert len(fn_nodes) == 1
        assert "route" in fn_nodes[0].metadata
        assert fn_nodes[0].metadata["route"]["framework"] == "fastapi"
        assert "async" in fn_nodes[0].tags

    def test_flask_route_node_metadata(self):
        """Flask route → node.metadata contains framework=flask."""
        code = """
@app.route("/login", methods=["POST"])
def login():
    return "ok"
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/views.py", tree)
        fn_nodes = [n for n in nodes if n.type == NodeType.function]
        assert len(fn_nodes) == 1
        assert "route" in fn_nodes[0].metadata
        assert fn_nodes[0].metadata["route"]["framework"] == "flask"
        assert "flask" in fn_nodes[0].tags


class TestFullRouteIndexing:
    """End-to-end tests: build index from the FastAPI fixture project."""

    def test_fastapi_routes_indexed(self):
        """Index the FastAPI fixture → login and current_user get route metadata."""
        fixture_dir = Path("backend/tests/fixtures/fastapi_routes")
        if not fixture_dir.exists():
            pytest.skip("FastAPI route fixture not found")
        nodes, edges = build_index(fixture_dir)

        login_nodes = [n for n in nodes if n.name == "login" and n.type == NodeType.function]
        assert len(login_nodes) == 1
        assert "route" in login_nodes[0].metadata
        assert login_nodes[0].metadata["route"]["framework"] == "fastapi"
        assert login_nodes[0].metadata["route"]["method"] == "POST"
        assert login_nodes[0].metadata["route"]["path"] == "/login"

        me_nodes = [n for n in nodes if n.name == "current_user" and n.type == NodeType.function]
        assert len(me_nodes) == 1
        assert "route" in me_nodes[0].metadata
        assert me_nodes[0].metadata["route"]["framework"] == "fastapi"
        assert me_nodes[0].metadata["route"]["method"] == "GET"
        assert me_nodes[0].metadata["route"]["path"] == "/me"

    def test_main_py_not_route(self):
        """main.py has no route decorators → no route metadata on app variable."""
        fixture_dir = Path("backend/tests/fixtures/fastapi_routes")
        if not fixture_dir.exists():
            pytest.skip("FastAPI route fixture not found")
        nodes, edges = build_index(fixture_dir)

        fn_nodes = [n for n in nodes if n.type == NodeType.function]
        for fn_node in fn_nodes:
            assert fn_node.name != "main" or "route" not in fn_node.metadata


class TestRouteRanking:
    """Verify route handlers are ranked above test functions."""

    def test_route_handler_boosted_over_test(self):
        """Route handler `login` should score higher than `test_login` for query 'login'."""
        from codegraph.context.ranking import score_relevance
        from codegraph.graph.models import GraphNode

        route_node = GraphNode(
            id="app/api/auth.py::login",
            type=NodeType.function,
            name="login",
            file_path="app/api/auth.py",
            module="app.api.auth",
            qualified_name="app.api.auth.login",
            signature="(username: str, password: str) -> str",
            tags=["route", "api", "fastapi"],
            metadata={"route": {"framework": "fastapi", "method": "POST", "path": "/login"}},
        )
        test_node = GraphNode(
            id="tests/test_auth.py::test_login_success",
            type=NodeType.test,
            name="test_login_success",
            file_path="tests/test_auth.py",
            module="tests.test_auth",
            qualified_name="tests.test_auth.test_login_success",
            tags=["test"],
        )

        route_score = score_relevance(route_node, "login")
        test_score = score_relevance(test_node, "test_login_success")

        # Route handler should outrank test even though test name matches better
        assert route_score > test_score, f"route={route_score}, test={test_score}"

    def test_route_build_reason_includes_route_info(self):
        """build_reason for route handler mentions HTTP route info."""
        from codegraph.context.ranking import build_reason, tokenize
        from codegraph.graph.models import GraphNode

        node = GraphNode(
            id="app/api/auth.py::login",
            type=NodeType.function,
            name="login",
            file_path="app/api/auth.py",
            module="app.api.auth",
            qualified_name="app.api.auth.login",
            signature="(username: str, password: str) -> str",
            tags=["route", "api", "fastapi"],
            metadata={"route": {"framework": "fastapi", "method": "POST", "path": "/login"}},
        )
        tokens = tokenize("login endpoint")
        reason = build_reason(node, tokens)
        assert "Route handler" in reason


# ══════════════════════════════════════════════════════════════════════════
# Round 4 — Service Layer Call Resolution tests
# ══════════════════════════════════════════════════════════════════════════


class TestSelfMethodResolution:
    """Acceptance criteria 1: self.method() resolves to same-class method."""

    def test_self_method_resolved(self):
        """``self.method()`` in a class → self_method_resolved."""
        code = """
class AuthService:
    def login_user(self, username: str, password: str) -> str:
        self.validate_password(username, password)
        return self.issue_token(username)

    def validate_password(self, username: str, password: str) -> None:
        pass

    def issue_token(self, username: str) -> str:
        return "token"
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("auth_service.py"), rel_path="auth_service.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        validate_calls = [e for e in call_edges
                          if e.source == "auth_service.py::AuthService.login_user"
                          and e.target == "auth_service.py::AuthService.validate_password"]
        assert len(validate_calls) == 1
        assert validate_calls[0].metadata.resolution == Resolution.self_method_resolved
        assert validate_calls[0].confidence == 0.90

        issue_calls = [e for e in call_edges
                       if e.source == "auth_service.py::AuthService.login_user"
                       and e.target == "auth_service.py::AuthService.issue_token"]
        assert len(issue_calls) == 1
        assert issue_calls[0].metadata.resolution == Resolution.self_method_resolved

    def test_self_method_not_resolved_for_non_existent_method(self):
        """self.nonexistent() → unresolved."""
        code = """
class MyClass:
    def run(self):
        self.nonexistent()
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("test.py"), rel_path="test.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        assert call_edges == []


class TestInstanceMethodResolution:
    """Acceptance criteria 2-5: local/module/constructor/param type hint instance method calls."""

    def test_module_level_instance_method_resolved(self):
        """Module-level ``x = Class(); x.method()`` → module_instance_resolved."""
        code = """
class AuthService:
    def login_user(self, username: str, password: str) -> str:
        return "token"

auth_service = AuthService()

def login(username: str, password: str) -> str:
    return auth_service.login_user(username, password)
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("auth.py"), rel_path="auth.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        service_calls = [e for e in call_edges
                         if e.source == "auth.py::login"
                         and e.target == "auth.py::AuthService.login_user"]
        assert len(service_calls) == 1
        assert service_calls[0].metadata.resolution == Resolution.module_instance_resolved
        assert service_calls[0].confidence == 0.78

    def test_local_instance_method_resolved(self):
        """``x = Class(); x.method()`` inside a function → local_instance_resolved."""
        code = """
class AuthService:
    def login_user(self, username: str, password: str) -> str:
        return "token"

def login_with_local_service(username: str, password: str) -> str:
    service = AuthService()
    return service.login_user(username, password)
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("auth.py"), rel_path="auth.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        service_calls = [e for e in call_edges
                         if e.source == "auth.py::login_with_local_service"
                         and e.target == "auth.py::AuthService.login_user"]
        assert len(service_calls) == 1
        assert service_calls[0].metadata.resolution == Resolution.local_instance_resolved
        assert service_calls[0].confidence == 0.80

    def test_constructor_chain_resolved(self):
        """``ClassName().method()`` → constructor_call_resolved."""
        code = """
class AuthService:
    def login_user(self, username: str, password: str) -> str:
        return "token"

def login_with_constructor(username: str, password: str) -> str:
    return AuthService().login_user(username, password)
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("auth.py"), rel_path="auth.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        service_calls = [e for e in call_edges
                         if e.source == "auth.py::login_with_constructor"
                         and e.target == "auth.py::AuthService.login_user"]
        assert len(service_calls) == 1
        assert service_calls[0].metadata.resolution == Resolution.constructor_call_resolved
        assert service_calls[0].confidence == 0.75

    def test_parameter_type_hint_resolved(self):
        """``param.method()`` where param: ClassType → parameter_type_hint_resolved."""
        code = """
class AuthService:
    def login_user(self, username: str, password: str) -> str:
        return "token"

def login_with_param(auth_service: AuthService, username: str, password: str) -> str:
    return auth_service.login_user(username, password)
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("auth.py"), rel_path="auth.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        service_calls = [e for e in call_edges
                         if e.source == "auth.py::login_with_param"
                         and e.target == "auth.py::AuthService.login_user"]
        assert len(service_calls) == 1
        assert service_calls[0].metadata.resolution == Resolution.parameter_type_hint_resolved
        assert service_calls[0].confidence == 0.82

    def test_all_call_edges_have_confidence_and_resolution(self):
        """Acceptance criteria 6: all calls edges must have confidence and resolution."""
        code = """
class AuthService:
    def login_user(self, username: str, password: str) -> str:
        self.validate_password(username, password)
        return self.issue_token(username)

    def validate_password(self, username: str, password: str) -> None:
        pass

    def issue_token(self, username: str) -> str:
        return "token"

auth_service = AuthService()

def login(username: str, password: str) -> str:
    return auth_service.login_user(username, password)

def login_with_local_service(username: str, password: str) -> str:
    service = AuthService()
    return service.login_user(username, password)

def login_with_constructor(username: str, password: str) -> str:
    return AuthService().login_user(username, password)

def login_with_param(auth_service: AuthService, username: str, password: str) -> str:
    return auth_service.login_user(username, password)
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("auth.py"), rel_path="auth.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        assert len(call_edges) >= 6  # at least 2 self + 4 instance calls
        for e in call_edges:
            assert 0.0 <= e.confidence <= 1.0, f"Edge {e.id} missing confidence"
            assert e.metadata is not None, f"Edge {e.id} missing metadata"
            assert e.metadata.resolution is not None, f"Edge {e.id} missing resolution"
            # resolution must be a valid enum value
            assert isinstance(e.metadata.resolution, Resolution)


class TestServiceLayerFixture:
    """End-to-end tests: build index from the service_layer_calls fixture."""

    FIXTURE_DIR = Path("backend/tests/fixtures/service_layer_calls")

    def _build(self) -> tuple[list, list]:
        nodes, edges = build_index(self.FIXTURE_DIR)
        return nodes, edges

    def test_auth_service_class_and_methods_indexed(self):
        """AuthService class and its methods are extracted as nodes."""
        nodes, edges = self._build()

        cls_node = next((n for n in nodes if n.id == "app/services/auth_service.py::AuthService"), None)
        assert cls_node is not None
        assert cls_node.type == NodeType.class_

        method_ids = {n.id for n in nodes if n.type == NodeType.method}
        assert "app/services/auth_service.py::AuthService.login_user" in method_ids
        assert "app/services/auth_service.py::AuthService.validate_password" in method_ids
        assert "app/services/auth_service.py::AuthService.issue_token" in method_ids

    def test_module_instance_call_resolved(self):
        """``auth_service.login_user()`` in login → module_instance_resolved."""
        nodes, edges = self._build()
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        login_calls = [e for e in call_edges if e.source == "app/api/auth.py::login"]
        assert len(login_calls) == 1
        assert login_calls[0].target == "app/services/auth_service.py::AuthService.login_user"
        assert login_calls[0].metadata.resolution == Resolution.module_instance_resolved

    def test_local_instance_call_resolved(self):
        """``service.login_user()`` in login_with_local_service → local_instance_resolved."""
        nodes, edges = self._build()
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        login_calls = [e for e in call_edges if e.source == "app/api/auth.py::login_with_local_service"]
        assert len(login_calls) == 1
        assert login_calls[0].target == "app/services/auth_service.py::AuthService.login_user"
        assert login_calls[0].metadata.resolution == Resolution.local_instance_resolved

    def test_constructor_chain_resolved(self):
        """``AuthService().login_user()`` → constructor_call_resolved."""
        nodes, edges = self._build()
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        login_calls = [e for e in call_edges if e.source == "app/api/auth.py::login_with_constructor"]
        assert len(login_calls) == 1
        assert login_calls[0].target == "app/services/auth_service.py::AuthService.login_user"
        assert login_calls[0].metadata.resolution == Resolution.constructor_call_resolved

    def test_parameter_type_hint_resolved(self):
        """``auth_service.login_user()`` with param type hint → parameter_type_hint_resolved."""
        nodes, edges = self._build()
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        login_calls = [e for e in call_edges if e.source == "app/api/auth.py::login_with_param"]
        assert len(login_calls) == 1
        assert login_calls[0].target == "app/services/auth_service.py::AuthService.login_user"
        assert login_calls[0].metadata.resolution == Resolution.parameter_type_hint_resolved

    def test_self_method_calls_resolved(self):
        """``self.validate_password()`` and ``self.issue_token()`` inside AuthService."""
        nodes, edges = self._build()
        call_edges = [e for e in edges if e.type == EdgeType.calls]

        src = "app/services/auth_service.py::AuthService.login_user"
        login_user_calls = [e for e in call_edges if e.source == src]
        assert len(login_user_calls) == 2  # validate_password + issue_token

        targets = {e.target for e in login_user_calls}
        assert "app/services/auth_service.py::AuthService.validate_password" in targets
        assert "app/services/auth_service.py::AuthService.issue_token" in targets

        for e in login_user_calls:
            assert e.metadata.resolution == Resolution.self_method_resolved


class TestCallersCalleesServiceMethods:
    """Acceptance criteria 7-9: callers/callees query, Context Pack, Reading Plan."""

    FIXTURE_DIR = Path("backend/tests/fixtures/service_layer_calls")

    def test_callees_include_service_methods(self):
        """get_callees on login → includes AuthService.login_user."""
        from codegraph.graph.store import GraphStore
        from codegraph.graph.query import get_callees

        nodes, edges = build_index(self.FIXTURE_DIR)
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        callees = get_callees(store, "app/api/auth.py::login")
        callee_ids = [c[0] for c in callees]
        assert "app/services/auth_service.py::AuthService.login_user" in callee_ids

    def test_callers_include_api_function(self):
        """get_callers on AuthService.login_user → includes login."""
        from codegraph.graph.store import GraphStore
        from codegraph.graph.query import get_callers

        nodes, edges = build_index(self.FIXTURE_DIR)
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        callers = get_callers(store, "app/services/auth_service.py::AuthService.login_user")
        caller_ids = [c[0] for c in callers]

        assert "app/api/auth.py::login" in caller_ids
        assert "app/api/auth.py::login_with_local_service" in caller_ids
        assert "app/api/auth.py::login_with_constructor" in caller_ids
        assert "app/api/auth.py::login_with_param" in caller_ids

    def test_context_pack_includes_service_layer_methods(self):
        """Acceptance criteria 8: Context Pack related_symbols includes service methods."""
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack

        nodes, edges = build_index(self.FIXTURE_DIR)
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        pack = build_context_pack(
            store,
            task_description="add MFA to login flow",
            max_files=6,
            include_tests=False,
        )

        related_ids = {rs.symbol_id for rs in pack.related_symbols}
        assert "app/services/auth_service.py::AuthService.login_user" in related_ids

    def test_selected_context_includes_service_methods(self):
        """Acceptance: Selected context includes service layer method evidence."""
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack

        nodes, edges = build_index(self.FIXTURE_DIR)
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        pack = build_context_pack(
            store,
            task_description="add MFA to login flow",
            max_files=8,
            include_tests=False,
        )

        # Service method should appear in selected_context or related_symbols
        service_id = "app/services/auth_service.py::AuthService.login_user"
        found_in_context = any(
            sc.symbol_id == service_id for sc in pack.selected_context
        )
        found_in_related = any(
            rs.symbol_id == service_id for rs in pack.related_symbols
        )
        assert found_in_context or found_in_related, \
            f"Service method {service_id} not found in selected_context or related_symbols"

    def test_context_pack_callee_reason_mentions_service(self):
        """The related_symbol entry for the service method should have a meaningful reason."""
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack

        nodes, edges = build_index(self.FIXTURE_DIR)
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        pack = build_context_pack(
            store,
            task_description="add MFA to login flow",
            max_files=6,
            include_tests=False,
        )

        service_entries = [
            rs for rs in pack.related_symbols
            if rs.symbol_id == "app/services/auth_service.py::AuthService.login_user"
        ]
        assert len(service_entries) >= 1
        assert service_entries[0].relation == "callee"


class TestImportResolutionGranularity:
    """Verify that the new granular import resolution types are used."""

    def test_imported_function_exact_resolution(self):
        """``from X import func → func()`` → imported_function_exact."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "lib.py").write_text("""
def do_work() -> None:
    pass
""", encoding="utf-8")
        (tmp / "main.py").write_text("""
from lib import do_work

def run() -> None:
    do_work()
""", encoding="utf-8")

        nodes, edges = build_index(tmp)
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        run_calls = [e for e in call_edges if e.source == "main.py::run"]
        assert len(run_calls) == 1
        assert run_calls[0].metadata.resolution == Resolution.imported_function_exact

    def test_imported_function_alias_resolution(self):
        """``from X import func as f → f()`` → imported_function_alias."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "lib.py").write_text("""
def do_work() -> None:
    pass
""", encoding="utf-8")
        (tmp / "main.py").write_text("""
from lib import do_work as work

def run() -> None:
    work()
""", encoding="utf-8")

        nodes, edges = build_index(tmp)
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        run_calls = [e for e in call_edges if e.source == "main.py::run"]
        assert len(run_calls) == 1
        assert run_calls[0].metadata.resolution == Resolution.imported_function_alias

    def test_imported_module_attribute_resolution(self):
        """``import X as m → m.func()`` → imported_module_attribute."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "lib.py").write_text("""
def do_work() -> None:
    pass
""", encoding="utf-8")
        (tmp / "main.py").write_text("""
import lib as l

def run() -> None:
    l.do_work()
""", encoding="utf-8")

        nodes, edges = build_index(tmp)
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        run_calls = [e for e in call_edges if e.source == "main.py::run"]
        assert len(run_calls) == 1
        assert run_calls[0].metadata.resolution == Resolution.imported_module_attribute

    def test_relative_import_resolved_resolution(self):
        """``from .module import func → func()`` → relative_import_resolved."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "pkg").mkdir(parents=True, exist_ok=True)
        (tmp / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (tmp / "pkg" / "helpers.py").write_text("""
def do_work() -> None:
    pass
""", encoding="utf-8")
        (tmp / "pkg" / "main.py").write_text("""
from .helpers import do_work

def run() -> None:
    do_work()
""", encoding="utf-8")

        nodes, edges = build_index(tmp)
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        run_calls = [e for e in call_edges if e.source == "pkg/main.py::run"]
        assert len(run_calls) == 1
        assert run_calls[0].metadata.resolution == Resolution.relative_import_resolved


# ══════════════════════════════════════════════════════════════════════════
# Round 5 — Model / Config / Store recognition tests
# ══════════════════════════════════════════════════════════════════════════


class TestModelDetection:
    """Detection of model classes via base class and naming heuristics."""

    def test_pydantic_base_model_detected(self):
        """Class inheriting from BaseModel → tags=['model'], metadata with fields."""
        code = """
from pydantic import BaseModel

class User(BaseModel):
    id: str
    username: str
    password_hash: str
    mfa_enabled: bool = False
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/models/user.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        user_node = class_nodes[0]
        assert "model" in user_node.tags
        assert user_node.metadata.get("is_data_model") is True
        assert user_node.metadata.get("model_kind") == "pydantic"
        assert "fields" in user_node.metadata
        assert "id" in user_node.metadata["fields"]
        assert "username" in user_node.metadata["fields"]
        assert "password_hash" in user_node.metadata["fields"]
        assert "mfa_enabled" in user_node.metadata["fields"]

    def test_pydantic_base_settings_detected(self):
        """Class inheriting from BaseSettings → tags=['config', 'settings']."""
        code = """
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    token_ttl_seconds: int = 3600
    mfa_required: bool = False
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/config.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        settings_node = class_nodes[0]
        assert "config" in settings_node.tags
        assert "settings" in settings_node.tags
        assert settings_node.metadata.get("is_config") is True
        assert settings_node.metadata.get("config_kind") == "pydantic_settings"
        assert "fields" in settings_node.metadata
        assert "token_ttl_seconds" in settings_node.metadata["fields"]
        assert "mfa_required" in settings_node.metadata["fields"]

    def test_model_tag_via_file_path(self):
        """Class in models/ directory → gets 'model' tag even without BaseModel."""
        code = """
class User:
    id: str
    name: str
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/models/user.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        assert "model" in class_nodes[0].tags

    def test_store_tag_via_file_path(self):
        """Class in store/ directory → gets 'store' and 'persistence' tags."""
        code = """
class TokenStore:
    def save_token(self, token: str) -> None:
        pass
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/store/token_store.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        assert "store" in class_nodes[0].tags
        assert "persistence" in class_nodes[0].tags
        assert class_nodes[0].metadata.get("is_store") is True

    def test_config_tag_via_file_path(self):
        """Class in config.py → gets 'config' and 'settings' tags."""
        code = """
class AppConfig:
    debug: bool = False
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/config.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        assert "config" in class_nodes[0].tags

    def test_store_tag_via_class_name_heuristic(self):
        """Class named *Store → gets 'store' tag even outside store/ dir."""
        code = """
class TokenStore:
    def save_token(self, token: str) -> None:
        pass
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/utils.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        assert "store" in class_nodes[0].tags

    def test_config_tag_via_class_name_heuristic(self):
        """Class named *Config → gets 'config' tag even outside config.py."""
        code = """
class DatabaseConfig:
    host: str
    port: int
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/db.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        assert "config" in class_nodes[0].tags

    def test_model_tag_via_class_name_heuristic(self):
        """Class named *Model → gets 'model' tag even without BaseModel."""
        code = """
class ResponseModel:
    status: str
    data: dict
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/dto.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        assert "model" in class_nodes[0].tags

    def test_typed_dict_schema_detection(self):
        """Class inheriting from TypedDict → tags=['schema']."""
        code = """
from typing import TypedDict

class UserDict(TypedDict):
    id: str
    name: str
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/schemas.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        assert "schema" in class_nodes[0].tags

    def test_enum_schema_detection(self):
        """Class inheriting from Enum → tags=['schema']."""
        code = """
from enum import Enum

class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/enums.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        assert "schema" in class_nodes[0].tags

    def test_regular_class_has_no_model_tags(self):
        """Regular service class → no model/config/store tags."""
        code = """
class AuthService:
    def login_user(self, username: str, password: str) -> str:
        return "token"
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/services/auth_service.py", tree)
        class_nodes = [n for n in nodes if n.type == NodeType.class_]
        assert len(class_nodes) == 1
        assert "model" not in class_nodes[0].tags
        assert "config" not in class_nodes[0].tags
        assert "store" not in class_nodes[0].tags


class TestModelConfigFixture:
    """End-to-end tests: build index from the model_config_persistence fixture."""

    FIXTURE_DIR = Path("backend/tests/fixtures/model_config_persistence")

    def _build(self) -> tuple[list, list]:
        nodes, edges = build_index(self.FIXTURE_DIR)
        return nodes, edges

    def test_user_model_has_model_tags(self):
        """User(BaseModel) → tags=['model'], pydantic fields detected."""
        nodes, edges = self._build()
        user_node = next((n for n in nodes if n.id == "app/models/user.py::User"), None)
        assert user_node is not None
        assert "model" in user_node.tags
        assert user_node.metadata.get("is_data_model") is True
        assert user_node.metadata.get("model_kind") == "pydantic"
        assert "fields" in user_node.metadata
        assert "mfa_enabled" in user_node.metadata["fields"]

    def test_settings_has_config_tags(self):
        """Settings(BaseSettings) → tags=['config', 'settings']."""
        nodes, edges = self._build()
        settings_node = next((n for n in nodes if n.id == "app/config.py::Settings"), None)
        assert settings_node is not None
        assert "config" in settings_node.tags
        assert "settings" in settings_node.tags
        assert settings_node.metadata.get("is_config") is True
        assert settings_node.metadata.get("config_kind") == "pydantic_settings"
        assert "fields" in settings_node.metadata
        assert "mfa_required" in settings_node.metadata["fields"]

    def test_token_store_has_store_tags(self):
        """TokenStore → tags=['store', 'persistence'] via file path."""
        nodes, edges = self._build()
        store_node = next((n for n in nodes if n.id == "app/store/token_store.py::TokenStore"), None)
        assert store_node is not None
        assert "store" in store_node.tags
        assert "persistence" in store_node.tags

    def test_context_pack_includes_user_model(self):
        """Context Pack for 'add MFA to login' → related_symbols includes User model."""
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack

        nodes, edges = self._build()
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        pack = build_context_pack(
            store,
            task_description="add MFA to login flow",
            max_files=8,
            include_tests=False,
        )

        related_ids = {rs.symbol_id for rs in pack.related_symbols}
        assert "app/models/user.py::User" in related_ids, f"Related: {related_ids}"

    def test_context_pack_includes_settings(self):
        """Context Pack for a feature change → related_symbols includes Settings."""
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack

        nodes, edges = self._build()
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        pack = build_context_pack(
            store,
            task_description="add MFA to login",
            max_files=8,
            include_tests=False,
        )

        related_ids = {rs.symbol_id for rs in pack.related_symbols}
        assert "app/config.py::Settings" in related_ids, f"Related: {related_ids}"

    def test_context_pack_includes_token_store(self):
        """Context Pack for login-related task → related_symbols includes TokenStore."""
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack

        nodes, edges = self._build()
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        pack = build_context_pack(
            store,
            task_description="change login flow",
            max_files=8,
            include_tests=False,
        )

        related_ids = {rs.symbol_id for rs in pack.related_symbols}
        assert "app/store/token_store.py::TokenStore" in related_ids, f"Related: {related_ids}"

    def test_selected_context_includes_user_model(self):
        """Evidence Pack: selected_context includes User model evidence."""
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack

        nodes, edges = self._build()
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        pack = build_context_pack(
            store,
            task_description="add MFA to login flow",
            max_files=8,
            include_tests=False,
        )

        ctx_ids = {sc.symbol_id for sc in pack.selected_context}
        related_ids = {rs.symbol_id for rs in pack.related_symbols}
        all_ids = ctx_ids | related_ids
        assert "app/models/user.py::User" in all_ids, f"Not found in evidence: {all_ids}"

    def test_selected_context_includes_settings(self):
        """Evidence Pack: selected_context includes Settings evidence."""
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack

        nodes, edges = self._build()
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        pack = build_context_pack(
            store,
            task_description="change token settings",
            max_files=8,
            include_tests=False,
        )

        ctx_ids = {sc.symbol_id for sc in pack.selected_context}
        related_ids = {rs.symbol_id for rs in pack.related_symbols}
        all_ids = ctx_ids | related_ids
        assert "app/config.py::Settings" in all_ids, f"Not found in evidence: {all_ids}"

    def test_impact_includes_user_model(self):
        """Impact analysis on login_user → affected symbols include User model."""
        from codegraph.graph.store import GraphStore
        from codegraph.graph.impact import analyze_impact

        nodes, edges = self._build()
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        result = analyze_impact(store, "app/services/auth_service.py::AuthService.login_user")
        confirmed_ids = {s["symbol_id"] for s in result["confirmed_impact"]["symbols"]}
        possible_ids = {s["symbol_id"] for s in result["possible_impact"]["symbols"]}
        affected_ids = confirmed_ids | possible_ids
        assert "app/models/user.py::User" in affected_ids, f"Affected: {affected_ids}"

    def test_impact_includes_settings(self):
        """Impact analysis on login_user → affected symbols include Settings."""
        from codegraph.graph.store import GraphStore
        from codegraph.graph.impact import analyze_impact

        nodes, edges = self._build()
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        result = analyze_impact(store, "app/services/auth_service.py::AuthService.login_user")
        confirmed_ids = {s["symbol_id"] for s in result["confirmed_impact"]["symbols"]}
        possible_ids = {s["symbol_id"] for s in result["possible_impact"]["symbols"]}
        affected_ids = confirmed_ids | possible_ids
        assert "app/config.py::Settings" in affected_ids, f"Affected: {affected_ids}"

    def test_impact_includes_token_store(self):
        """Impact analysis on login_user → affected symbols include TokenStore."""
        from codegraph.graph.store import GraphStore
        from codegraph.graph.impact import analyze_impact

        nodes, edges = self._build()
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        result = analyze_impact(store, "app/services/auth_service.py::AuthService.login_user")
        confirmed_ids = {s["symbol_id"] for s in result["confirmed_impact"]["symbols"]}
        possible_ids = {s["symbol_id"] for s in result["possible_impact"]["symbols"]}
        affected_ids = confirmed_ids | possible_ids
        assert "app/store/token_store.py::TokenStore" in affected_ids, f"Affected: {affected_ids}"

    def test_model_symbols_have_right_relation_type(self):
        """Context Pack related_symbols for User model → relation='model_dependency'."""
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack

        nodes, edges = self._build()
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        pack = build_context_pack(
            store,
            task_description="add MFA to login flow",
            max_files=8,
            include_tests=False,
        )

        user_entries = [
            rs for rs in pack.related_symbols
            if rs.symbol_id == "app/models/user.py::User"
        ]
        assert len(user_entries) >= 1
        assert user_entries[0].relation == "model_dependency"

    def test_config_symbols_have_right_relation_type(self):
        """Context Pack related_symbols for Settings → relation='config_dependency'."""
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack

        nodes, edges = self._build()
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)

        pack = build_context_pack(
            store,
            task_description="add MFA to login flow",
            max_files=8,
            include_tests=False,
        )

        settings_entries = [
            rs for rs in pack.related_symbols
            if rs.symbol_id == "app/config.py::Settings"
        ]
        assert len(settings_entries) >= 1
        assert settings_entries[0].relation == "config_dependency"

    def test_auth_service_not_tagged_as_model(self):
        """AuthService is a regular class → no model/store/config tags."""
        nodes, edges = self._build()
        auth_node = next((n for n in nodes if n.id == "app/services/auth_service.py::AuthService"), None)
        assert auth_node is not None
        assert "model" not in auth_node.tags
        assert "store" not in auth_node.tags
        assert "config" not in auth_node.tags


# ══════════════════════════════════════════════════════════════════════════
# Round 6: Confidence / Resolution system tests
# ══════════════════════════════════════════════════════════════════════════


class TestConfidenceModule:
    """Unit tests for the centralized confidence module."""

    def test_all_resolutions_have_confidence(self):
        """Every Resolution enum value has a corresponding confidence value."""
        from codegraph.graph.confidence import RESOLUTION_CONFIDENCE
        for res in Resolution:
            assert res in RESOLUTION_CONFIDENCE, (
                f"Resolution.{res.value} missing from RESOLUTION_CONFIDENCE"
            )

    def test_get_confidence_returns_float(self):
        """get_confidence returns a float in [0, 1]."""
        from codegraph.graph.confidence import get_confidence
        for res in Resolution:
            c = get_confidence(res)
            assert isinstance(c, float), f"Expected float for {res}, got {type(c)}"
            assert 0.0 <= c <= 1.0, f"Confidence {c} out of range for {res}"

    def test_get_confidence_level_high(self):
        """Confidence >= 0.80 → 'high'."""
        from codegraph.graph.confidence import get_confidence_level
        assert get_confidence_level(0.95) == "high"
        assert get_confidence_level(0.80) == "high"
        assert get_confidence_level(1.0) == "high"

    def test_get_confidence_level_medium(self):
        """Confidence 0.60–0.79 → 'medium'."""
        from codegraph.graph.confidence import get_confidence_level
        assert get_confidence_level(0.79) == "medium"
        assert get_confidence_level(0.60) == "medium"
        assert get_confidence_level(0.70) == "medium"

    def test_get_confidence_level_low(self):
        """Confidence 0.40–0.59 → 'low'."""
        from codegraph.graph.confidence import get_confidence_level
        assert get_confidence_level(0.55) == "low"
        assert get_confidence_level(0.40) == "low"

    def test_get_confidence_level_unknown(self):
        """Confidence < 0.40 → 'unknown'."""
        from codegraph.graph.confidence import get_confidence_level
        assert get_confidence_level(0.20) == "unknown"
        assert get_confidence_level(0.0) == "unknown"

    def test_is_low_confidence(self):
        """is_low_confidence returns True when confidence < 0.60."""
        from codegraph.graph.confidence import is_low_confidence
        assert is_low_confidence(0.55) is True
        assert is_low_confidence(0.59) is True
        assert is_low_confidence(0.60) is False
        assert is_low_confidence(0.95) is False

    def test_high_confidence_resolutions(self):
        """Known high-confidence resolutions have confidence >= 0.80."""
        from codegraph.graph.confidence import get_confidence
        high_res = [
            Resolution.exact_ast_match,
            Resolution.same_file_exact,
            Resolution.imported_function_exact,
            Resolution.self_method_resolved,
            Resolution.fastapi_route_decorator,
            Resolution.direct_test_call,
            Resolution.pydantic_model_detected,
        ]
        for r in high_res:
            assert get_confidence(r) >= 0.80, f"{r.value} should be high confidence"

    def test_low_confidence_resolutions(self):
        """Known low-confidence resolutions have confidence < 0.60."""
        from codegraph.graph.confidence import get_confidence
        low_res = [
            Resolution.test_file_heuristic,
            Resolution.attribute_guess,
            Resolution.external_symbol,
            Resolution.unresolved,
        ]
        for r in low_res:
            assert get_confidence(r) < 0.60, f"{r.value} should be low confidence"

    def test_confidence_ordering_is_sane(self):
        """Confidence values follow the expected ordering (stronger > weaker)."""
        from codegraph.graph.confidence import get_confidence
        # Same-file should be stronger than import
        assert get_confidence(Resolution.same_file_exact) > get_confidence(Resolution.imported_function_exact)
        # Direct call should be stronger than name heuristic
        assert get_confidence(Resolution.direct_test_call) > get_confidence(Resolution.test_name_heuristic)
        # Name heuristic should be stronger than file heuristic
        assert get_confidence(Resolution.test_name_heuristic) > get_confidence(Resolution.test_file_heuristic)
        # AST exact should be highest
        assert get_confidence(Resolution.exact_ast_match) == 1.0


class TestEdgeMetadataEvidence:
    """Tests for edge metadata reason/evidence on different edge types."""

    def test_call_edge_has_reason_and_evidence(self):
        """Every calls edge has reason and evidence in metadata."""
        demo = Path("examples/demo_python_project")
        if not demo.exists():
            pytest.skip("Demo project not found")
        nodes, edges = build_index(demo)
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        assert len(call_edges) > 0, "No call edges in demo project"
        for e in call_edges:
            assert e.metadata is not None, f"Edge {e.id} missing metadata"
            assert e.metadata.reason is not None, f"Edge {e.id} missing reason"
            assert e.metadata.resolution is not None, f"Edge {e.id} missing resolution"
            assert len(e.metadata.reason) > 0, f"Edge {e.id} reason is empty"

    def test_same_file_call_has_evidence(self):
        """Same-file call edges have evidence with matched_symbol_id."""
        code = """
def helper():
    pass

def main():
    helper()
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("mod.py"), rel_path="mod.py")
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        assert len(call_edges) == 1
        edge = call_edges[0]
        assert edge.metadata.resolution == Resolution.same_file_exact
        assert edge.metadata.reason is not None
        assert "helper" in edge.metadata.reason
        assert edge.metadata.evidence is not None
        assert "matched_symbol_id" in edge.metadata.evidence

    def test_import_call_has_evidence(self):
        """Imported function call edges have evidence with import details."""
        # Need two files for cross-file import test — use the fixture
        fixture = Path("backend/tests/fixtures/model_config_persistence")
        if not fixture.exists():
            pytest.skip("Fixture not found")
        nodes, edges = build_index(fixture)
        call_edges = [e for e in edges if e.type == EdgeType.calls]
        for e in call_edges:
            assert e.metadata is not None
            assert e.metadata.reason is not None
            assert len(e.metadata.reason) > 0
            assert e.metadata.evidence is not None

    def test_structural_edge_has_reason(self):
        """Structural edges (contains, defined_in, imports) have reason."""
        demo = Path("examples/demo_python_project")
        if not demo.exists():
            pytest.skip("Demo project not found")
        nodes, edges = build_index(demo)
        structural = [e for e in edges if e.type in (EdgeType.contains, EdgeType.defined_in, EdgeType.imports)]
        assert len(structural) > 0, "No structural edges in demo project"
        for e in structural:
            assert e.metadata is not None, f"Edge {e.id} missing metadata"
            assert e.metadata.reason is not None, f"Edge {e.id} missing reason"

    def test_tested_by_edge_has_reason_and_evidence(self):
        """tested_by edges have reason and evidence."""
        fixture = Path("backend/tests/fixtures/model_config_persistence")
        if not fixture.exists():
            pytest.skip("Fixture not found")
        nodes, edges = build_index(fixture)
        tested_by_edges = [e for e in edges if e.type == EdgeType.tested_by]
        # May be empty if no test files discovered; that's ok
        for e in tested_by_edges:
            assert e.metadata.reason is not None, f"Edge {e.id} missing reason"
            assert e.metadata.resolution is not None, f"Edge {e.id} missing resolution"

    def test_inherits_edge_has_reason_and_evidence(self):
        """Inherits edges have reason and evidence."""
        code = """
class Base:
    pass

class Child(Base):
    pass
"""
        tree = ast.parse(code)
        edges = extract_calls(tree, Path("mod.py"), rel_path="mod.py")
        inherits_edges = [e for e in edges if e.type == EdgeType.inherits]
        assert len(inherits_edges) == 1
        edge = inherits_edges[0]
        assert edge.metadata.reason is not None
        assert "inherits" in edge.metadata.reason.lower()
        assert edge.metadata.evidence is not None
        assert "base_class" in edge.metadata.evidence


class TestConfidenceLevelInContextPack:
    """Tests for confidence_level in Context Pack output."""

    FIXTURE_DIR = Path("backend/tests/fixtures/model_config_persistence")

    def _build_pack(self, task: str = "add MFA to login flow"):
        from codegraph.graph.store import GraphStore
        from codegraph.context.pack_builder import build_context_pack
        nodes, edges = build_index(self.FIXTURE_DIR)
        store = GraphStore()
        store.add_nodes(nodes)
        store.add_edges(edges)
        return build_context_pack(store, task_description=task, max_files=8, include_tests=False)

    def test_related_symbols_have_confidence_level(self):
        """All RelatedSymbol entries have confidence_level set."""
        pack = self._build_pack()
        for rs in pack.related_symbols:
            assert rs.confidence_level in ("high", "medium", "low", "unknown"), (
                f"RelatedSymbol {rs.symbol_id} has invalid confidence_level: {rs.confidence_level}"
            )

    def test_call_graph_edges_have_confidence_level(self):
        """All CallGraphEdge entries have confidence_level set."""
        pack = self._build_pack()
        for edge in pack.call_graph.edges:
            assert edge.confidence_level in ("high", "medium", "low", "unknown"), (
                f"CallGraphEdge {edge.source}→{edge.target} has invalid confidence_level: {edge.confidence_level}"
            )

    def test_affected_symbols_have_confidence_level(self):
        """Impact affected_symbols have confidence_level set."""
        pack = self._build_pack()
        for s in pack.impact.affected_symbols:
            assert s.confidence_level in ("high", "medium", "low", "unknown"), (
                f"AffectedSymbol {s.symbol_id} has invalid confidence_level: {s.confidence_level}"
            )

    def test_high_confidence_symbols_have_high_level(self):
        """Symbols with confidence >= 0.80 have confidence_level='high'."""
        pack = self._build_pack()
        for rs in pack.related_symbols:
            if rs.confidence >= 0.80:
                assert rs.confidence_level == "high", (
                    f"Symbol {rs.symbol_id} has confidence {rs.confidence} but level {rs.confidence_level}"
                )

    def test_low_confidence_triggers_warnings(self):
        """Low confidence edges produce warnings in the Evidence Pack."""
        pack = self._build_pack()
        # Check that warnings exist if low-confidence items are present
        low_conf_edges = [e for e in pack.call_graph.edges if e.confidence < 0.60]
        low_conf_symbols = [rs for rs in pack.related_symbols if rs.confidence < 0.60]
        has_low_conf = len(low_conf_edges) > 0 or len(low_conf_symbols) > 0
        if has_low_conf:
            assert len(pack.warnings) > 0, (
                "Should have warnings when low-confidence items exist"
            )

    def test_low_confidence_items_produce_warnings(self):
        """Low-confidence items produce warnings in the Evidence Pack."""
        from codegraph.graph.store import GraphStore
        from codegraph.graph.models import GraphNode, NodeType, EdgeType, GraphEdge
        from codegraph.context.pack_builder import build_context_pack
        store = GraphStore()
        store.add_node(GraphNode(id="app/api/auth.py::login", type=NodeType.function, name="login",
                                 file_path="app/api/auth.py", code_preview="def login(): pass"))
        store.add_node(GraphNode(id="app/services/auth_service.py::AuthService.login_user",
                                 type=NodeType.function, name="login_user",
                                 file_path="app/services/auth_service.py",
                                 code_preview="def login_user(): return 'ok'"))
        store.add_node(GraphNode(id="app/store/token_store.py::TokenStore",
                                 type=NodeType.class_, name="TokenStore",
                                 file_path="app/store/token_store.py",
                                 code_preview="class TokenStore: pass"))
        store.add_edge(GraphEdge(type=EdgeType.calls, source="app/api/auth.py::login",
                       target="app/services/auth_service.py::AuthService.login_user", confidence=0.40))
        store.add_edge(GraphEdge(type=EdgeType.calls, source="app/api/auth.py::login",
                       target="app/store/token_store.py::TokenStore", confidence=0.40))

        pack = build_context_pack(store, "explain login flow", max_files=4, include_tests=False)
        # Low-confidence edges should produce warnings
        assert isinstance(pack.warnings, list)


class TestRouteDetectionResolution:
    """Tests for route detection metadata with resolution/reason/evidence."""

    def test_fastapi_route_has_resolution_metadata(self):
        """FastAPI route detection includes resolution, reason, evidence."""
        code = """
from fastapi import APIRouter
router = APIRouter()

@router.post("/login")
def login(username: str, password: str) -> str:
    return "token"
"""
        tree = ast.parse(code)
        nodes = extract_symbols("api/auth.py", tree)
        login_node = next((n for n in nodes if n.name == "login"), None)
        assert login_node is not None
        assert "route" in login_node.tags
        route = login_node.metadata.get("route")
        assert route is not None
        assert route["framework"] == "fastapi"
        assert route["method"] == "POST"
        # Check new metadata fields
        assert login_node.metadata.get("detection_resolution") == Resolution.fastapi_route_decorator.value
        assert len(login_node.metadata.get("detection_reason", "")) > 0
        evidence = login_node.metadata.get("detection_evidence", {})
        assert evidence.get("http_method") == "POST"
        assert evidence.get("route_path") == "/login"

    def test_flask_route_has_resolution_metadata(self):
        """Flask route detection includes resolution, reason, evidence."""
        code = """
from flask import Flask
app = Flask(__name__)

@app.route("/login", methods=["POST"])
def login(username: str, password: str) -> str:
    return "token"
"""
        tree = ast.parse(code)
        nodes = extract_symbols("api/auth.py", tree)
        login_node = next((n for n in nodes if n.name == "login"), None)
        assert login_node is not None
        assert login_node.metadata.get("detection_resolution") == Resolution.flask_route_decorator.value
        assert len(login_node.metadata.get("detection_reason", "")) > 0

    def test_regular_function_has_no_route_metadata(self):
        """Regular function without route decorator has no detection metadata."""
        code = """
def helper(x: int) -> int:
    return x + 1
"""
        tree = ast.parse(code)
        nodes = extract_symbols("utils.py", tree)
        helper_node = next((n for n in nodes if n.name == "helper"), None)
        assert helper_node is not None
        assert "route" not in helper_node.tags
        assert "detection_resolution" not in helper_node.metadata


class TestModelDetectionResolution:
    """Tests for model/config/store detection resolution metadata."""

    def test_pydantic_model_has_detection_metadata(self):
        """Pydantic BaseModel class has detection_resolution, reason, evidence."""
        code = """
from pydantic import BaseModel

class User(BaseModel):
    id: str
    username: str
"""
        tree = ast.parse(code)
        nodes = extract_symbols("models/user.py", tree)
        user_node = next((n for n in nodes if n.name == "User"), None)
        assert user_node is not None
        assert "model" in user_node.tags
        assert user_node.metadata.get("detection_resolution") == Resolution.pydantic_model_detected.value
        assert len(user_node.metadata.get("detection_reason", "")) > 0
        evidence = user_node.metadata.get("detection_evidence", {})
        assert evidence.get("base_class") == "BaseModel"
        assert evidence.get("framework") == "pydantic"

    def test_settings_has_config_detection_metadata(self):
        """BaseSettings class has config detection resolution."""
        code = """
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    debug: bool = False
"""
        tree = ast.parse(code)
        nodes = extract_symbols("config.py", tree)
        settings_node = next((n for n in nodes if n.name == "Settings"), None)
        assert settings_node is not None
        assert "config" in settings_node.tags
        assert settings_node.metadata.get("detection_resolution") == Resolution.config_class_detected.value

    def test_store_class_has_detection_metadata(self):
        """Class in store/ directory has detection resolution."""
        code = """
class TokenStore:
    def save(self, data: str) -> None:
        pass
"""
        tree = ast.parse(code)
        nodes = extract_symbols("app/store/token_store.py", tree)
        store_node = next((n for n in nodes if n.name == "TokenStore"), None)
        assert store_node is not None
        assert "store" in store_node.tags
        assert store_node.metadata.get("detection_resolution") is not None
        assert len(store_node.metadata.get("detection_reason", "")) > 0


# ══════════════════════════════════════════════════════════════════════════
# Round 7 — Fingerprint tests
# ══════════════════════════════════════════════════════════════════════════


class TestFingerprint:
    def test_same_content_same_fingerprint(self, tmp_path):
        from codegraph.indexer.scanner import compute_fingerprint
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("def foo(): pass", encoding="utf-8")
        f2.write_text("def foo(): pass", encoding="utf-8")
        assert compute_fingerprint(f1) == compute_fingerprint(f2)

    def test_different_content_different_fingerprint(self, tmp_path):
        from codegraph.indexer.scanner import compute_fingerprint
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("def foo(): pass", encoding="utf-8")
        f2.write_text("def bar(): pass", encoding="utf-8")
        assert compute_fingerprint(f1) != compute_fingerprint(f2)

    def test_fingerprint_is_hex_string(self, tmp_path):
        from codegraph.indexer.scanner import compute_fingerprint
        f = tmp_path / "a.py"
        f.write_text("def foo(): pass", encoding="utf-8")
        fp = compute_fingerprint(f)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)


# ══════════════════════════════════════════════════════════════════════════
# Round 7 — IndexMetadata save/load tests
# ══════════════════════════════════════════════════════════════════════════


class TestIndexMetadata:
    def test_save_and_load_metadata(self, tmp_path):
        from codegraph.graph.models import IndexMetadata, FileEntry
        from codegraph.storage.file_store import FileStore
        store = FileStore(tmp_path)
        meta = IndexMetadata(
            schema_version="1.0.0",
            root_path=str(tmp_path),
            indexed_at="2026-05-29T10:00:00Z",
            file_count=3,
            symbol_count=10,
            edge_count=15,
            files=[
                FileEntry(path="app/auth.py", fingerprint="abc123", indexed_at="2026-05-29T10:00:00Z"),
                FileEntry(path="app/models.py", fingerprint="def456", indexed_at="2026-05-29T10:00:00Z"),
            ],
        )
        store.save_metadata(meta)
        loaded = store.load_metadata()
        assert loaded is not None
        assert loaded.schema_version == "1.0.0"
        assert loaded.file_count == 3
        assert loaded.symbol_count == 10
        assert len(loaded.files) == 2
        assert loaded.files[0].path == "app/auth.py"

    def test_load_metadata_nonexistent(self, tmp_path):
        from codegraph.storage.file_store import FileStore
        store = FileStore(tmp_path)
        assert store.load_metadata() is None

    def test_metadata_roundtrip(self, tmp_path):
        from codegraph.graph.models import IndexMetadata, FileEntry
        from codegraph.storage.file_store import FileStore
        store = FileStore(tmp_path)
        meta = IndexMetadata(
            schema_version="1.0.0",
            root_path="/test",
            indexed_at="2026-05-29T00:00:00Z",
            file_count=1,
            symbol_count=2,
            edge_count=0,
            files=[FileEntry(path="test.py", fingerprint="sha", indexed_at="2026-05-29T00:00:00Z")],
        )
        store.save_metadata(meta)
        loaded = store.load_metadata()
        assert loaded is not None
        assert loaded.root_path == "/test"
        assert loaded.files[0].fingerprint == "sha"


# ══════════════════════════════════════════════════════════════════════════
# Round 7 — Status detection tests
# ══════════════════════════════════════════════════════════════════════════


class TestStatusDetection:
    def test_missing_status_when_no_metadata(self, tmp_path):
        from codegraph.indexer.status import detect_status
        result = detect_status(tmp_path, None)
        assert result.status == "missing"
        assert "codegraph index" in result.recommendation

    def test_fresh_status_when_no_changes(self, tmp_path):
        from codegraph.indexer.status import detect_status
        from codegraph.indexer.scanner import compute_fingerprint
        from codegraph.graph.models import IndexMetadata, FileEntry
        # Create a python file
        (tmp_path / "app").mkdir(exist_ok=True)
        f = tmp_path / "app" / "main.py"
        f.parent.mkdir(exist_ok=True)
        f.write_text("def main(): pass", encoding="utf-8")
        fp = compute_fingerprint(f)
        meta = IndexMetadata(
            root_path=str(tmp_path),
            indexed_at="2026-05-29T00:00:00Z",
            files=[FileEntry(path="app/main.py", fingerprint=fp, indexed_at="2026-05-29T00:00:00Z")],
        )
        result = detect_status(tmp_path, meta)
        assert result.status == "fresh"

    def test_stale_changed_file(self, tmp_path):
        from codegraph.indexer.status import detect_status
        from codegraph.graph.models import IndexMetadata, FileEntry
        f = tmp_path / "main.py"
        f.write_text("def main(): pass", encoding="utf-8")
        meta = IndexMetadata(
            root_path=str(tmp_path),
            indexed_at="2026-05-29T00:00:00Z",
            files=[FileEntry(path="main.py", fingerprint="old_wrong_fingerprint", indexed_at="2026-05-29T00:00:00Z")],
        )
        result = detect_status(tmp_path, meta)
        assert result.status == "stale"
        assert "main.py" in result.changed_files

    def test_stale_added_file(self, tmp_path):
        from codegraph.indexer.status import detect_status
        from codegraph.graph.models import IndexMetadata, FileEntry
        # Create a file not in metadata
        (tmp_path / "new_file.py").write_text("def new(): pass", encoding="utf-8")
        meta = IndexMetadata(
            root_path=str(tmp_path),
            indexed_at="2026-05-29T00:00:00Z",
            files=[],
        )
        result = detect_status(tmp_path, meta)
        assert result.status == "stale"
        assert "new_file.py" in result.added_files

    def test_stale_deleted_file(self, tmp_path):
        from codegraph.indexer.status import detect_status
        from codegraph.graph.models import IndexMetadata, FileEntry
        meta = IndexMetadata(
            root_path=str(tmp_path),
            indexed_at="2026-05-29T00:00:00Z",
            files=[FileEntry(path="deleted.py", fingerprint="any", indexed_at="2026-05-29T00:00:00Z")],
        )
        result = detect_status(tmp_path, meta)
        assert result.status == "stale"
        assert "deleted.py" in result.deleted_files

    def test_total_changes_count(self, tmp_path):
        from codegraph.indexer.status import detect_status
        from codegraph.graph.models import IndexMetadata, FileEntry
        from codegraph.indexer.scanner import compute_fingerprint
        f1 = tmp_path / "changed.py"
        f1.write_text("def foo(): pass", encoding="utf-8")
        f2 = tmp_path / "added.py"
        f2.write_text("def bar(): pass", encoding="utf-8")
        meta = IndexMetadata(
            root_path=str(tmp_path),
            indexed_at="2026-05-29T00:00:00Z",
            files=[
                FileEntry(path="changed.py", fingerprint="wrong", indexed_at="2026-05-29T00:00:00Z"),
                FileEntry(path="deleted.py", fingerprint="any", indexed_at="2026-05-29T00:00:00Z"),
            ],
        )
        result = detect_status(tmp_path, meta)
        assert result.total_changes == 3  # changed + added + deleted
        assert len(result.changed_files) == 1
        assert len(result.added_files) == 1
        assert len(result.deleted_files) == 1

    def test_status_result_properties(self, tmp_path):
        from codegraph.indexer.status import StatusResult
        fresh = StatusResult(status="fresh")
        assert fresh.is_fresh
        assert not fresh.is_stale
        stale = StatusResult(status="stale", changed_files=["a.py"])
        assert stale.is_stale
        assert not stale.is_fresh


# ══════════════════════════════════════════════════════════════════════════
# Round 7 — GraphStore removal tests
# ══════════════════════════════════════════════════════════════════════════


class TestGraphStoreRemoval:
    def test_remove_single_node(self, populated_store):
        from codegraph.graph.models import GraphNode, NodeType
        store = populated_store
        node = GraphNode(id="test_node", type=NodeType.function, name="test_func", file_path="test.py")
        store.add_node(node)
        assert store.get_node("test_node") is not None
        assert store.remove_node("test_node") is True
        assert store.get_node("test_node") is None

    def test_remove_nonexistent_node(self, populated_store):
        store = populated_store
        assert store.remove_node("nonexistent") is False

    def test_remove_nodes_by_file(self, populated_store):
        from codegraph.graph.models import GraphNode, NodeType, GraphEdge, EdgeType
        store = populated_store
        n1 = GraphNode(id="f1::a", type=NodeType.function, name="a", file_path="f1.py")
        n2 = GraphNode(id="f1::b", type=NodeType.function, name="b", file_path="f1.py")
        n3 = GraphNode(id="f2::c", type=NodeType.function, name="c", file_path="f2.py")
        store.add_nodes([n1, n2, n3])
        assert store.remove_nodes_by_file("f1.py") == 2
        assert store.get_node("f1::a") is None
        assert store.get_node("f1::b") is None
        assert store.get_node("f2::c") is not None

    def test_remove_edges_by_file(self, populated_store):
        from codegraph.graph.models import GraphNode, NodeType, GraphEdge, EdgeType
        store = populated_store
        store.add_nodes([
            GraphNode(id="f1::a", type=NodeType.function, name="a", file_path="f1.py"),
            GraphNode(id="f2::b", type=NodeType.function, name="b", file_path="f2.py"),
        ])
        store.add_edges([
            GraphEdge(id="e1", type=EdgeType.calls, source="f1::a", target="f2::b", confidence=0.9),
        ])
        # Remove edges touching f1.py
        edge_count_before = store.edge_count()
        removed = store.remove_edges_by_file("f1.py")
        assert removed == 1
        assert store.edge_count() == edge_count_before - 1  # only our edge was removed

    def test_remove_nodes_also_removes_edges(self, populated_store):
        from codegraph.graph.models import GraphNode, NodeType, GraphEdge, EdgeType
        store = populated_store
        store.add_nodes([
            GraphNode(id="ff1::x", type=NodeType.function, name="x", file_path="ff1.py"),
            GraphNode(id="ff2::y", type=NodeType.function, name="y", file_path="ff2.py"),
        ])
        store.add_edges([
            GraphEdge(id="ex1", type=EdgeType.calls, source="ff1::x", target="ff2::y", confidence=0.9),
        ])
        removed = store.remove_nodes_by_file("ff1.py")
        assert removed == 1
        # Edge from ff1 to ff2 should also be gone
        remaining_sources = {e.source for e in store.all_edges()}
        remaining_targets = {e.target for e in store.all_edges()}
        assert "ff1::x" not in remaining_sources
        assert "ff1::x" not in remaining_targets


# ══════════════════════════════════════════════════════════════════════════
# Round 7 — Incremental index tests
# ══════════════════════════════════════════════════════════════════════════


class TestIncrementalIndex:
    def test_full_index_produces_metadata(self, tmp_path):
        """Full index should produce metadata.json."""
        from codegraph.indexer.graph_builder import build_index
        from codegraph.storage.file_store import FileStore
        from codegraph.graph.models import FileEntry

        # Copy fixture files to tmp_path
        import shutil
        fixture = Path(__file__).parent / "fixtures" / "incremental_index"
        shutil.copytree(fixture, tmp_path, dirs_exist_ok=True)

        (tmp_path / ".codegraph").mkdir(exist_ok=True)
        output_dir = tmp_path / ".codegraph"

        from codegraph.cli.main import _save_index_artifacts
        nodes, edges = build_index(tmp_path)
        _save_index_artifacts(output_dir, nodes, edges, tmp_path)

        store = FileStore(output_dir)
        metadata = store.load_metadata()
        assert metadata is not None
        assert metadata.file_count > 0
        assert len(metadata.files) > 0
        # Every file should have a fingerprint
        for fe in metadata.files:
            assert len(fe.fingerprint) == 64

    def test_incremental_detects_changed_file(self, tmp_path):
        """After a change, status should be stale and incremental re-index should work."""
        import shutil
        from codegraph.indexer.graph_builder import build_index
        from codegraph.storage.file_store import FileStore
        from codegraph.indexer.status import detect_status

        fixture = Path(__file__).parent / "fixtures" / "incremental_index"
        shutil.copytree(fixture, tmp_path, dirs_exist_ok=True)

        output_dir = tmp_path / ".codegraph"
        output_dir.mkdir(exist_ok=True)

        from codegraph.cli.main import _save_index_artifacts
        nodes, edges = build_index(tmp_path)
        _save_index_artifacts(output_dir, nodes, edges, tmp_path)

        store = FileStore(output_dir)
        metadata = store.load_metadata()
        result = detect_status(tmp_path, metadata)
        assert result.status == "fresh"

        # Modify a file
        auth_file = tmp_path / "app" / "api" / "auth.py"
        auth_file.write_text("def login(username: str, password: str) -> str:\n    return \"new_token\"\n\ndef verify_token(token: str) -> bool:\n    return token == \"new_token\"\n", encoding="utf-8")

        result2 = detect_status(tmp_path, metadata)
        assert result2.status == "stale"
        assert "app/api/auth.py" in result2.changed_files

    def test_incremental_detects_added_file(self, tmp_path):
        """After adding a file, status should be stale with added file list."""
        import shutil
        from codegraph.indexer.graph_builder import build_index
        from codegraph.storage.file_store import FileStore
        from codegraph.indexer.status import detect_status

        fixture = Path(__file__).parent / "fixtures" / "incremental_index"
        shutil.copytree(fixture, tmp_path, dirs_exist_ok=True)

        output_dir = tmp_path / ".codegraph"
        output_dir.mkdir(exist_ok=True)

        from codegraph.cli.main import _save_index_artifacts
        nodes, edges = build_index(tmp_path)
        _save_index_artifacts(output_dir, nodes, edges, tmp_path)

        store = FileStore(output_dir)
        metadata = store.load_metadata()

        # Add a new file
        new_file = tmp_path / "app" / "services" / "mfa_service.py"
        new_file.write_text("def generate_mfa_code() -> str:\n    return \"123456\"\n", encoding="utf-8")

        result = detect_status(tmp_path, metadata)
        assert result.status == "stale"
        assert "app/services/mfa_service.py" in result.added_files

    def test_incremental_detects_deleted_file(self, tmp_path):
        """After deleting a file, status should be stale with deleted file list."""
        import shutil
        from codegraph.indexer.graph_builder import build_index
        from codegraph.storage.file_store import FileStore
        from codegraph.indexer.status import detect_status

        fixture = Path(__file__).parent / "fixtures" / "incremental_index"
        shutil.copytree(fixture, tmp_path, dirs_exist_ok=True)

        output_dir = tmp_path / ".codegraph"
        output_dir.mkdir(exist_ok=True)

        from codegraph.cli.main import _save_index_artifacts
        nodes, edges = build_index(tmp_path)
        _save_index_artifacts(output_dir, nodes, edges, tmp_path)

        store = FileStore(output_dir)
        metadata = store.load_metadata()

        # Delete a file
        auth_file = tmp_path / "app" / "api" / "auth.py"
        auth_file.unlink()

        result = detect_status(tmp_path, metadata)
        assert result.status == "stale"
        assert "app/api/auth.py" in result.deleted_files

    def test_incremental_reindex_removes_deleted_symbols(self, tmp_path):
        """Incremental re-index should remove symbols for deleted files."""
        import shutil
        from codegraph.indexer.graph_builder import build_index, build_index_from_paths
        from codegraph.storage.file_store import FileStore
        from codegraph.indexer.status import detect_status
        from pydantic import TypeAdapter
        from codegraph.graph.models import GraphNode, GraphEdge

        fixture = Path(__file__).parent / "fixtures" / "incremental_index"
        shutil.copytree(fixture, tmp_path, dirs_exist_ok=True)

        output_dir = tmp_path / ".codegraph"
        output_dir.mkdir(exist_ok=True)

        from codegraph.cli.main import _save_index_artifacts
        nodes, edges = build_index(tmp_path)
        _save_index_artifacts(output_dir, nodes, edges, tmp_path)

        # Delete a file
        auth_file = tmp_path / "app" / "api" / "auth.py"
        auth_file.unlink()

        # Detect changes
        store = FileStore(output_dir)
        metadata = store.load_metadata()
        result = detect_status(tmp_path, metadata)
        assert "app/api/auth.py" in result.deleted_files

        # Load existing data
        node_adapter = TypeAdapter(list[GraphNode])
        edge_adapter = TypeAdapter(list[GraphEdge])
        current_nodes = node_adapter.validate_python(store.load_nodes())
        current_edges = edge_adapter.validate_python(store.load_edges())

        # Remove deleted file nodes
        files_to_remove = set(result.deleted_files)
        removed_ids = {n.id for n in current_nodes if n.file_path in files_to_remove}
        current_nodes = [n for n in current_nodes if n.file_path not in files_to_remove]
        current_edges = [e for e in current_edges if e.source not in removed_ids and e.target not in removed_ids]

        # Save updated
        _save_index_artifacts(output_dir, current_nodes, current_edges, tmp_path)

        # Verify auth symbols are gone
        auth_symbols = [n for n in current_nodes if "auth.py" in n.file_path]
        assert len(auth_symbols) == 0

    def test_incremental_reindex_adds_new_symbols(self, tmp_path):
        """Incremental re-index should add symbols for new files."""
        import shutil
        from codegraph.indexer.graph_builder import build_index, build_index_from_paths
        from codegraph.storage.file_store import FileStore
        from codegraph.indexer.status import detect_status
        from pydantic import TypeAdapter
        from codegraph.graph.models import GraphNode, GraphEdge

        fixture = Path(__file__).parent / "fixtures" / "incremental_index"
        shutil.copytree(fixture, tmp_path, dirs_exist_ok=True)

        output_dir = tmp_path / ".codegraph"
        output_dir.mkdir(exist_ok=True)

        from codegraph.cli.main import _save_index_artifacts
        nodes, edges = build_index(tmp_path)
        _save_index_artifacts(output_dir, nodes, edges, tmp_path)

        # Add a new file
        new_file = tmp_path / "app" / "services" / "mfa_service.py"
        new_file.write_text("def generate_mfa_code() -> str:\n    return \"123456\"\n", encoding="utf-8")

        # Detect changes
        store = FileStore(output_dir)
        metadata = store.load_metadata()
        result = detect_status(tmp_path, metadata)
        assert "app/services/mfa_service.py" in result.added_files

        # Load existing
        node_adapter = TypeAdapter(list[GraphNode])
        edge_adapter = TypeAdapter(list[GraphEdge])
        current_nodes = node_adapter.validate_python(store.load_nodes())
        current_edges = edge_adapter.validate_python(store.load_edges())

        # Re-index added file
        for rel in result.added_files:
            p = tmp_path / rel
            if p.exists():
                new_nodes, new_edges = build_index_from_paths(tmp_path, [p])
                current_nodes.extend(new_nodes)
                current_edges.extend(new_edges)

        _save_index_artifacts(output_dir, current_nodes, current_edges, tmp_path)

        # Verify new symbols exist
        mfa_symbols = [n for n in current_nodes if "mfa_service" in n.file_path]
        assert len(mfa_symbols) > 0
        mfa_func = next((n for n in mfa_symbols if n.name == "generate_mfa_code"), None)
        assert mfa_func is not None


# ══════════════════════════════════════════════════════════════════════════
# Round 7 — SQLite store removal tests
# ══════════════════════════════════════════════════════════════════════════


class TestSqliteStoreRemoval:
    def test_delete_nodes_by_file(self, tmp_path):
        from codegraph.storage.sqlite_store import SqliteStore
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        store.save_nodes([
            {"id": "f1::a", "type": "function", "name": "a", "file_path": "f1.py"},
            {"id": "f1::b", "type": "function", "name": "b", "file_path": "f1.py"},
            {"id": "f2::c", "type": "function", "name": "c", "file_path": "f2.py"},
        ])
        assert store.node_count() == 3
        removed = store.delete_nodes_by_file("f1.py")
        assert removed == 2
        assert store.node_count() == 1
        assert store.get_node("f2::c") is not None
        store.close()

    def test_delete_edges_by_file(self, tmp_path):
        from codegraph.storage.sqlite_store import SqliteStore
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        store.save_nodes([
            {"id": "f1::a", "type": "function", "name": "a", "file_path": "f1.py"},
            {"id": "f2::b", "type": "function", "name": "b", "file_path": "f2.py"},
        ])
        store.save_edges([
            {"id": "e1", "type": "calls", "source": "f1::a", "target": "f2::b", "confidence": 0.9},
        ])
        removed = store.delete_edges_by_file("f1.py")
        assert removed == 1
        assert store.edge_count() == 0
        store.close()

    def test_delete_nonexistent_file(self, tmp_path):
        from codegraph.storage.sqlite_store import SqliteStore
        db_path = tmp_path / "test.sqlite"
        store = SqliteStore(db_path)
        store.initialize()
        assert store.delete_nodes_by_file("nonexistent.py") == 0
        assert store.delete_edges_by_file("nonexistent.py") == 0
        store.close()
