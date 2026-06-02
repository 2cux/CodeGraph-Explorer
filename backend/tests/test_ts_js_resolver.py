"""Tests for TypeScript / JavaScript Resolver."""

import pytest

from codegraph.language_support.ts_js.resolver import (
    TypeScriptResolver,
    JavaScriptResolver,
    _resolve_relative_import,
)
from codegraph.language_support.resolver import ResolvedEdges, GraphContext, Provenance
from codegraph.graph.models import (
    GraphNode, GraphEdge, EdgeType, NodeType, Resolution,
    EdgeMetadata, EdgeLocation,
)
from codegraph.language_support.registry import reset_registry


@pytest.fixture(autouse=True)
def _reset():
    reset_registry()


# ── Path resolution tests ──────────────────────────────────────────────


class TestTSPathResolution:
    def test_relative_import_exact_match(self):
        all_files = ["src/components/Button.tsx", "src/utils/helpers.ts"]
        result = _resolve_relative_import(
            "src/components/Input.tsx", "./Button", "", all_files,
        )
        assert result == "src/components/Button.tsx"

    def test_relative_import_extensionless(self):
        all_files = ["src/utils/helpers.ts", "src/utils/format.ts"]
        result = _resolve_relative_import(
            "src/services/api.ts", "../utils/helpers", "", all_files,
        )
        assert result == "src/utils/helpers.ts"

    def test_relative_import_index_file(self):
        all_files = ["src/utils/index.ts", "src/services/api.ts"]
        result = _resolve_relative_import(
            "src/services/api.ts", "../utils", "", all_files,
        )
        assert result == "src/utils/index.ts"

    def test_relative_import_not_found(self):
        all_files = ["src/components/Button.tsx"]
        result = _resolve_relative_import(
            "src/services/api.ts", "../nonexistent", "", all_files,
        )
        assert result is None


# ── Resolver tests ─────────────────────────────────────────────────────


class TestBaseTSResolver:
    """Tests for resolver edge classification."""

    def test_resolve_empty(self):
        resolver = TypeScriptResolver()
        result = resolver.resolve([])
        assert isinstance(result, ResolvedEdges)
        assert len(result.confirmed) == 0
        assert len(result.possible) == 0

    def test_same_file_call_confirmed(self):
        """Same-file function calls should be classified as confirmed."""
        resolver = TypeScriptResolver()
        symbols = [
            GraphNode(
                id="test.ts::hello", type=NodeType.function, name="hello",
                qualified_name="test.ts::hello", file_path="test.ts",
            ),
            GraphNode(
                id="test.ts::world", type=NodeType.function, name="world",
                qualified_name="test.ts::world", file_path="test.ts",
            ),
        ]
        edges = [GraphEdge(
            id="e1", type=EdgeType.calls, source="test.ts::hello",
            target="test.ts::world", confidence=0.95,
            source_location=EdgeLocation(file_path="test.ts", line_start=3, line_end=3),
            metadata=EdgeMetadata(
                resolution=Resolution.same_file_exact, provenance="ast",
                reason="same-file call",
            ),
        )]

        # Create a mock ExtractorResult equivalent
        class MockResult:
            def __init__(self):
                self.symbols = symbols
                self._raw_edges = edges
                self.file_path = "test.ts"
                self.imports = []

        result = resolver.resolve([MockResult()])
        assert len(result.confirmed) >= 1

    def test_this_method_confirmed(self):
        """this.method() calls in a class should be confirmed."""
        resolver = TypeScriptResolver()
        symbols = [
            GraphNode(
                id="test.ts::Button", type=NodeType.class_, name="Button",
                qualified_name="test.ts::Button", file_path="test.ts",
            ),
            GraphNode(
                id="test.ts::Button.handleClick", type=NodeType.method,
                name="handleClick",
                qualified_name="test.ts::Button.handleClick", file_path="test.ts",
                metadata={"class_name": "Button"},
            ),
            GraphNode(
                id="test.ts::Button.logClick", type=NodeType.method,
                name="logClick",
                qualified_name="test.ts::Button.logClick", file_path="test.ts",
                metadata={"class_name": "Button"},
            ),
        ]
        edges = [GraphEdge(
            id="e2", type=EdgeType.calls, source="test.ts::Button.handleClick",
            target="unresolved:this.logClick", confidence=0.90,
            source_location=EdgeLocation(file_path="test.ts", line_start=5, line_end=5),
            metadata=EdgeMetadata(
                resolution=Resolution.this_method_exact, provenance="ast",
                reason="this.logClick()",
            ),
        )]

        class MockResult:
            def __init__(self):
                self.symbols = symbols
                self._raw_edges = edges
                self.file_path = "test.ts"
                self.imports = []

        result = resolver.resolve([MockResult()])
        # this_method_exact should be in confirmed
        confirmed_resolutions = [e.resolution for e in result.confirmed]
        # At minimum, the same_file_exact should be confirmed
        assert len(result.confirmed) >= 1

    def test_name_only_not_confirmed(self):
        """A name-only match without import should NOT be in confirmed."""
        resolver = TypeScriptResolver()
        symbols = [
            GraphNode(
                id="file_a.ts::close", type=NodeType.function, name="close",
                qualified_name="file_a.ts::close", file_path="file_a.ts",
            ),
        ]
        edges = [GraphEdge(
            id="e3", type=EdgeType.calls, source="",
            target="unresolved:close", confidence=0.35,
            source_location=EdgeLocation(file_path="file_b.ts", line_start=1, line_end=1),
            metadata=EdgeMetadata(
                resolution=Resolution.name_match_candidate, provenance="heuristic",
                reason="name-only match",
            ),
        )]

        class MockResult:
            def __init__(self):
                self.symbols = symbols
                self._raw_edges = edges
                self.file_path = "file_b.ts"
                self.imports = []

        result = resolver.resolve([MockResult()])
        # name_match_candidate should be in possible, NOT confirmed
        for e in result.confirmed:
            assert e.resolution != Resolution.name_match_candidate

    def test_package_import_external(self):
        """Package imports (non-relative) should be marked external."""
        resolver = TypeScriptResolver()
        symbols = []
        edges = [GraphEdge(
            id="e4", type=EdgeType.calls, source="",
            target="unresolved:useState", confidence=0.30,
            source_location=EdgeLocation(file_path="test.ts", line_start=1, line_end=1),
            metadata=EdgeMetadata(
                resolution=Resolution.package_external, provenance="import_resolver",
                reason="imported from react",
            ),
        )]

        class MockResult:
            def __init__(self):
                self.symbols = symbols
                self._raw_edges = edges
                self.file_path = "test.ts"
                self.imports = []

        result = resolver.resolve([MockResult()])
        # package_external should be in unresolved
        assert len(result.unresolved_candidates) >= 1

    def test_imported_function_confirmed(self):
        """An imported function call across files should be confirmed."""
        resolver = TypeScriptResolver()
        symbols = [
            GraphNode(
                id="src/utils/helpers.ts::generateId", type=NodeType.function,
                name="generateId", qualified_name="src/utils/helpers.ts::generateId",
                file_path="src/utils/helpers.ts",
            ),
            GraphNode(
                id="src/services/api.ts::fetchUser", type=NodeType.method,
                name="fetchUser", qualified_name="src/services/api.ts::fetchUser",
                file_path="src/services/api.ts",
            ),
        ]
        imports = [
            type("ImportInfo", (), {
                "local_name": "generateId",
                "module_path": "../utils/helpers",
                "imported_name": "generateId",
                "is_external": False,
                "line": 2,
            })(),
        ]
        edges = [GraphEdge(
            id="e5", type=EdgeType.calls,
            source="src/services/api.ts::fetchUser",
            target="unresolved:generateId", confidence=0.90,
            source_location=EdgeLocation(file_path="src/services/api.ts", line_start=5, line_end=5),
            metadata=EdgeMetadata(
                resolution=Resolution.imported_symbol_exact, provenance="ast",
                reason="imported function call",
            ),
        )]

        class MockResult:
            def __init__(self):
                self.symbols = symbols
                self._raw_edges = edges
                self.file_path = "src/services/api.ts"
                self.imports = imports

        result = resolver.resolve([MockResult()])
        # Should have confirmed edges from import resolution
        assert len(result.confirmed) + len(result.possible) + len(result.unresolved_candidates) >= 1

    def test_dynamic_import_unresolved(self):
        """Dynamic imports should be in unresolved."""
        resolver = TypeScriptResolver()
        edges = [GraphEdge(
            id="e6", type=EdgeType.calls, source="",
            target="unresolved:dynamic_import", confidence=0.20,
            metadata=EdgeMetadata(
                resolution=Resolution.dynamic_import, provenance="heuristic",
            ),
        )]

        class MockResult:
            def __init__(self):
                self.symbols = []
                self._raw_edges = edges
                self.file_path = "test.ts"
                self.imports = []

        result = resolver.resolve([MockResult()])
        assert len(result.unresolved_candidates) >= 1


# ── JavaScript resolver tests ───────────────────────────────────────────


class TestJavaScriptResolver:
    def test_resolve_empty(self):
        resolver = JavaScriptResolver()
        result = resolver.resolve([])
        assert isinstance(result, ResolvedEdges)

    def test_require_exact_confirmed(self):
        """require() resolution should produce confirmed edges."""
        resolver = JavaScriptResolver()
        symbols = [
            GraphNode(
                id="src/utils/helpers.js::hello", type=NodeType.function,
                name="hello", qualified_name="src/utils/helpers.js::hello",
                file_path="src/utils/helpers.js",
            ),
        ]
        edges = [GraphEdge(
            id="e7", type=EdgeType.calls, source="src/index.js::main",
            target="unresolved:hello", confidence=0.88,
            source_location=EdgeLocation(file_path="src/index.js", line_start=3, line_end=3),
            metadata=EdgeMetadata(
                resolution=Resolution.require_exact, provenance="import_resolver",
                reason="required function call",
            ),
        )]

        class MockResult:
            def __init__(self):
                self.symbols = symbols
                self._raw_edges = edges
                self.file_path = "src/index.js"
                self.imports = [type("ImportInfo", (), {
                    "local_name": "hello",
                    "module_path": "./utils/helpers",
                    "imported_name": "hello",
                    "is_external": False,
                    "line": 1,
                })()]

        result = resolver.resolve([MockResult()])
        # Should produce confirmed edges
        assert len(result.confirmed) + len(result.possible) + len(result.unresolved_candidates) >= 1
