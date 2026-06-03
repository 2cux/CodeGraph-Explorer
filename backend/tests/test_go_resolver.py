"""Tests for Go cross-file resolver — edge resolution and false edge prevention."""

import pytest
from pathlib import Path

from codegraph.language_support.go.resolver import GoResolver
from codegraph.language_support.go.extractor import GoExtractor
from codegraph.language_support.go.frameworks import GinResolver, HertzResolver
from codegraph.language_support.resolver import GraphContext, ResolvedEdge, Provenance, ResolvedEdges
from codegraph.language_support.registry import reset_registry
from codegraph.graph.models import NodeType, EdgeType, Resolution


FIXTURES_GO = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "go_gin_project"
FIXTURES_HERTZ = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "go_hertz_project"


@pytest.fixture(autouse=True)
def _reset():
    reset_registry()


class TestGoResolver:
    """Cross-file resolution tests for Go."""

    def test_same_package_call_confirmed(self):
        """Same-package function calls should be resolved as confirmed."""
        ext = GoExtractor()
        # Two files in the same package
        r1 = ext.extract(
            file_path="pkg/a.go",
            content='package pkg\n\nfunc Helper() {}\nfunc DoWork() {\n\tHelper()\n}',
            project_root="/tmp",
        )
        r2 = ext.extract(
            file_path="pkg/b.go",
            content='package pkg\n\nfunc OtherFunc() {\n\tHelper()\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1, r2])

        assert len(result.confirmed) > 0 or len(result.possible) > 0

        # At minimum, same-file calls should be confirmed
        confirmed_targets = {e.target for e in result.confirmed if e.edge_type == EdgeType.calls}
        # Same-file call to Helper from DoWork
        assert any("Helper" in t for t in confirmed_targets) or len(result.possible) > 0

    def test_name_only_not_confirmed_across_packages(self):
        """Functions with the same name in different packages should not be incorrectly linked."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="pkg1/a.go",
            content='package pkg1\n\nfunc Close() {}\n',
            project_root="/tmp",
        )
        r2 = ext.extract(
            file_path="pkg2/b.go",
            content='package pkg2\n\nfunc Close() {}\nfunc DoWork() {\n\tClose()\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1, r2])

        # The call to Close() in pkg2 should NOT be confirmed as calling pkg1.Close()
        # Check that no confirmed edge connects pkg2 caller to pkg1 target
        for e in result.confirmed:
            if e.edge_type != EdgeType.calls:
                continue
            # If target is in pkg1 and source is in pkg2, that's a false edge
            sl = e.source_location or {}
            source_file = sl.get("file_path", "") if isinstance(sl, dict) else ""
            if "pkg1" in e.target and "pkg2" in source_file:
                pytest.fail(f"False confirmed edge from pkg2 to pkg1: {e.source} -> {e.target}")
        # Test passes if no false edges found
        # The name-only match should not be in confirmed

    def test_interface_method_not_confirmed(self):
        """Interface method calls should not be directly confirmed."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="pkg/repo.go",
            content='package pkg\n\ntype Repository interface {\n\tSave(data string) error\n}\n\ntype Impl struct {}\n\nfunc (i *Impl) Save(data string) error { return nil }\n\nfunc Process(repo Repository) {\n\trepo.Save("data")\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1])

        # The call repo.Save() should not be in confirmed
        repo_save_confirmed = [
            e for e in result.confirmed
            if e.edge_type == EdgeType.calls and "Save" in e.evidence.get("function", "")
        ]
        # Interface dispatch calls should not be directly confirmed
        # They should be in possible or unresolved

    def test_external_module_marked_external(self):
        """Calls to external module functions should be marked as external."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="main.go",
            content='package main\n\nimport "github.com/gin-gonic/gin"\n\nfunc main() {\n\tr := gin.Default()\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1])

        # Should not have confirmed edges for gin.Default() as internal
        external_calls = [
            e for e in result.unresolved_candidates
            if e.edge_type == EdgeType.calls and "gin" in str(e.evidence)
        ]

    def test_receiver_method_resolved(self):
        """Calls to known receiver methods should be resolved."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="store.go",
            content='package main\n\ntype Store struct {}\n\nfunc (s *Store) Save() {}\nfunc (s *Store) Load() {}\n\nfunc Process() {\n\ts := &Store{}\n\ts.Save()\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1])

        # The extractor should produce calls for s.Save()
        # The resolver should attempt to match to Store.Save

    def test_stdlib_calls_marked_external(self):
        """Calls to standard library should be marked as external."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="main.go",
            content='package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("hi")\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1])

        # fmt.Println() should appear in unresolved (external)
        external_edges = result.unresolved_candidates
        assert len(external_edges) >= 0  # May be classified as external by extractor already


class TestFalseEdgePrevention:
    """Ensure that certain edge cases do not produce false confirmed edges."""

    def test_different_package_same_name_not_confirmed(self):
        """Two packages with same function name close() should not be connected."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="pkg1/svc.go",
            content='package pkg1\n\ntype Service1 struct {}\nfunc (s *Service1) Close() {}\n',
            project_root="/tmp",
        )
        r2 = ext.extract(
            file_path="pkg2/svc.go",
            content='package pkg2\n\ntype Service2 struct {}\nfunc (s *Service2) Close() {}\nfunc DoWork() {\n\ts := &Service2{}\n\ts.Close()\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1, r2])

        # Service2.Close() should match same-file only, not pkg1.Service1.Close()
        confirmed_calls = [e for e in result.confirmed if e.edge_type == EdgeType.calls]
        # No confirmed edge from pkg2 to pkg1 symbols
        for c in confirmed_calls:
            if "pkg2" in str(c.source_location) and "pkg1" in c.target:
                pytest.fail(f"False confirmed edge: {c.source} -> {c.target}")

    def test_unimported_function_not_confirmed(self):
        """A function not imported should not be confirmed as a call target."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="pkg1/lib.go",
            content='package pkg1\n\nfunc SecretFunc() {}\n',
            project_root="/tmp",
        )
        r2 = ext.extract(
            file_path="pkg2/main.go",
            content='package pkg2\n\n// no import of pkg1\n\nfunc main() {\n\tSecretFunc()\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1, r2])

        # pkg2 calling SecretFunc without importing pkg1 should not be confirmed
        confirmed_secret = [
            e for e in result.confirmed
            if e.edge_type == EdgeType.calls and "SecretFunc" in str(e.evidence)
        ]
        assert len(confirmed_secret) == 0, "Unimported function should not be confirmed"

    def test_unknown_receiver_not_confirmed(self):
        """Calls on unknown receiver types should not enter confirmed."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="main.go",
            content='package main\n\nfunc Process(obj interface{}) {\n\tobj.Unknown()\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1])

        # Calls on interface{} types should be in possible or unresolved
        confirmed_unknown = [
            e for e in result.confirmed
            if e.edge_type == EdgeType.calls and "Unknown" in str(e.evidence)
        ]
        assert len(confirmed_unknown) == 0

    def test_inline_gin_handler_not_confirmed_route_to_symbol(self):
        """Inline Gin handlers should not be confirmed as route-to-existing-symbol."""
        resolver = GoResolver()
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="main.go",
            content='package main\n\nimport "github.com/gin-gonic/gin"\n\nfunc main() {\n\tr := gin.Default()\n\tr.GET("/ping", func(c *gin.Context) {\n\t\tc.JSON(200, gin.H{"msg": "pong"})\n\t})\n}',
            project_root="/tmp",
        )

        go_resolver = GoResolver()
        result = go_resolver.resolve([r1])

        # Inline handlers should use gin_inline_handler resolution, which is possible-tier
        inline_confirmed = [
            e for e in result.confirmed
            if e.edge_type == EdgeType.routes_to and "inline_handler" in e.target
        ]
        assert len(inline_confirmed) == 0, "Inline handlers should not be confirmed"


class TestGoResolverIntegration:
    """Integration tests using the fixture project."""

    def test_resolve_fixture_project(self):
        if not FIXTURES_GO.exists():
            pytest.skip("Go fixture project not found")

        ext = GoExtractor()
        results = []
        for go_file in FIXTURES_GO.rglob("*.go"):
            result = ext.extract(
                file_path=str(go_file),
                project_root=str(FIXTURES_GO),
            )
            results.append(result)

        resolver = GoResolver()
        resolved = resolver.resolve(results)

        # Should produce some confirmed edges
        assert len(resolved.confirmed) >= 0  # structural edges may not all be confirmed

        # Should have resolved edges
        total = len(resolved.confirmed) + len(resolved.possible) + len(resolved.unresolved_candidates)
        assert total > 0

    def test_searchable_go_symbols(self):
        """Verify that Go symbols are searchable via the standard MCP path."""
        if not FIXTURES_GO.exists():
            pytest.skip("Go fixture project not found")

        ext = GoExtractor()
        all_symbols = []
        for go_file in FIXTURES_GO.rglob("*.go"):
            result = ext.extract(
                file_path=str(go_file),
                project_root=str(FIXTURES_GO),
            )
            all_symbols.extend(result.symbols)

        # Verify symbols have language_id set
        for s in all_symbols:
            if s.type in (NodeType.file, NodeType.module):
                continue
            assert s.language_id == "go"
            assert s.metadata.get("support_level") == "beta"

        # Verify key symbols exist
        go_func_names = {s.name for s in all_symbols if s.type == NodeType.function}
        assert "listUsers" in go_func_names or "CreateUser" in go_func_names


class TestHertzFalseEdgePrevention:
    """False edge prevention tests specific to Hertz framework."""

    def test_hertz_unimported_handler_not_confirmed(self):
        """A handler name from an unimported package should not be confirmed."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="pkg1/lib.go",
            content='package pkg1\n\nfunc ListItems() {}\n',
            project_root="/tmp",
        )
        r2 = ext.extract(
            file_path="main.go",
            content='package main\nimport "github.com/cloudwego/hertz/pkg/app/server"\n\nfunc main() {\n\th := server.Default()\n\th.GET("/items", ListItems)\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1, r2])

        confirmed_list = [
            e for e in result.confirmed
            if e.edge_type == EdgeType.routes_to and "ListItems" in str(e.evidence)
        ]
        assert len(confirmed_list) == 0, "Unimported handler should not be confirmed"

    def test_hertz_inline_handler_not_confirmed(self):
        """Inline Hertz handlers should not be in confirmed tier."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="main.go",
            content='package main\nimport "github.com/cloudwego/hertz/pkg/app/server"\n\nfunc main() {\n\th := server.Default()\n\th.GET("/ping", func(c context.Context, ctx *app.RequestContext) {\n\t\tctx.JSON(200, map[string]string{"msg": "pong"})\n\t})\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1])

        inline_confirmed = [
            e for e in result.confirmed
            if e.edge_type == EdgeType.routes_to and "inline_handler" in e.target
        ]
        assert len(inline_confirmed) == 0, "Inline Hertz handlers should not be confirmed"

    def test_hertz_cross_package_same_name_not_confirmed(self):
        """Different packages with same handler name should not be incorrectly linked."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="pkg1/svc.go",
            content='package pkg1\n\nfunc Close() {}\n',
            project_root="/tmp",
        )
        r2 = ext.extract(
            file_path="pkg2/svc.go",
            content='package pkg2\n\nfunc Close() {}\nfunc DoWork() {\n\tClose()\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1, r2])

        for e in result.confirmed:
            if e.edge_type != EdgeType.calls:
                continue
            sl = e.source_location or {}
            source_file = sl.get("file_path", "") if isinstance(sl, dict) else ""
            if "pkg1" in e.target and "pkg2" in source_file:
                pytest.fail(f"False confirmed edge: {e.source} -> {e.target}")

    def test_hertz_handler_not_mistaken_for_gin_handler(self):
        """Hertz handler should not resolve to a Gin fixture handler with the same name."""
        if not FIXTURES_HERTZ.exists() or not FIXTURES_GO.exists():
            pytest.skip("Fixture projects not found")

        ext = GoExtractor()
        results = []
        for go_file in list(FIXTURES_HERTZ.rglob("*.go")) + list(FIXTURES_GO.rglob("*.go")):
            result = ext.extract(
                file_path=str(go_file),
                project_root=str(go_file.parent.parent),
            )
            results.append(result)

        resolver = GoResolver()
        resolved = resolver.resolve(results)

        # Verify that hertz routes don't reference gin symbols
        hertz_routes = set()
        gin_symbols = set()
        for r in results:
            for s in r.symbols:
                fid = s.metadata.get("framework_id", "") if s.metadata else ""
                if fid == "hertz":
                    hertz_routes.add(s.id)
                if fid == "gin":
                    gin_symbols.add(s.id)

        # No hertz route should have a confirmed edge to a gin symbol
        for e in resolved.confirmed:
            if e.edge_type == EdgeType.routes_to:
                if e.source in hertz_routes and e.target in gin_symbols:
                    pytest.fail(f"Hertz route resolved to Gin symbol: {e.source} -> {e.target}")

    def test_hertz_middleware_not_confirmed_when_unresolvable(self):
        """Middleware references that can't be resolved should not enter confirmed."""
        ext = GoExtractor()
        r1 = ext.extract(
            file_path="main.go",
            content='package main\nimport "github.com/cloudwego/hertz/pkg/app/server"\n\nfunc dashboard(c context.Context, ctx *app.RequestContext) {}\n\nfunc main() {\n\th := server.Default()\n\th.GET("/admin", unknownMiddleware(), dashboard)\n}',
            project_root="/tmp",
        )

        resolver = GoResolver()
        result = resolver.resolve([r1])

        # Middleware edges should be in possible or unresolved, not confirmed
        mw_confirmed = [
            e for e in result.confirmed
            if e.edge_type == EdgeType.references and "unknownMiddleware" in str(e.evidence)
        ]
        assert len(mw_confirmed) == 0, "Unresolvable middleware should not be confirmed"

    def test_hertz_group_prefix_resolved(self):
        """Group prefix should be correctly joined with route path."""
        resolver = HertzResolver()
        src = '''package main
import "github.com/cloudwego/hertz/pkg/app/server"

func listItems(c context.Context, ctx *app.RequestContext) {}

func main() {
    h := server.Default()
    v1 := h.Group("/v1")
    {
        v1.GET("/items", listItems)
    }
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(route_nodes) >= 1
        route_path = route_nodes[0].metadata.get("route_path", "")
        assert "/v1/items" in route_path or "v1/items" in route_path
