"""Tests for Gin framework detection in Go files."""

import pytest
from pathlib import Path

from codegraph.language_support.go.frameworks import GinResolver, HertzResolver, extract_go_frameworks
from codegraph.language_support.go.extractor import GoExtractor
from codegraph.language_support.registry import reset_registry
from codegraph.graph.models import NodeType, EdgeType, Resolution


FIXTURES_GO = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "go_gin_project"
FIXTURES_HERTZ = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "go_hertz_project"


@pytest.fixture(autouse=True)
def _reset():
    reset_registry()


class TestGinResolver:
    """Gin framework route detection tests."""

    def test_detect_gin_default(self):
        resolver = GinResolver()
        result = resolver.extract(
            rel="test.go",
            src='package main\nimport "github.com/gin-gonic/gin"\n\nfunc main() {\n\tr := gin.Default()\n}',
            symbols=[],
            imports=[],
            language_id="go",
        )
        assert len(result.diagnostics) >= 1
        assert any("Gin engine detected" in d.message for d in result.diagnostics)

    def test_detect_gin_new(self):
        resolver = GinResolver()
        result = resolver.extract(
            rel="test.go",
            src='package main\nimport "github.com/gin-gonic/gin"\n\nfunc main() {\n\tr := gin.New()\n}',
            symbols=[],
            imports=[],
            language_id="go",
        )
        assert any("Gin engine detected" in d.message for d in result.diagnostics)

    def test_detect_get_route(self):
        resolver = GinResolver()
        result = resolver.extract(
            rel="test.go",
            src='package main\nimport "github.com/gin-gonic/gin"\n\nfunc listUsers(c *gin.Context) {}\n\nfunc main() {\n\tr := gin.Default()\n\tr.GET("/users", listUsers)\n}',
            symbols=[],
            imports=[],
            language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(route_nodes) >= 1
        route = route_nodes[0]
        assert route.metadata.get("http_method") == "GET"
        assert "/users" in route.metadata.get("route_path", "")

        # Should have a routes_to edge
        route_edges = [e for e in result.edges if e.type == EdgeType.routes_to]
        assert len(route_edges) >= 1

    def test_detect_post_route(self):
        resolver = GinResolver()
        result = resolver.extract(
            rel="test.go",
            src='package main\nimport "github.com/gin-gonic/gin"\n\nfunc createUser(c *gin.Context) {}\n\nfunc main() {\n\tr := gin.Default()\n\tr.POST("/users", createUser)\n}',
            symbols=[],
            imports=[],
            language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(route_nodes) >= 1
        assert route_nodes[0].metadata.get("http_method") == "POST"

    def test_detect_put_delete_routes(self):
        resolver = GinResolver()
        src = '''package main
import "github.com/gin-gonic/gin"

func updateUser(c *gin.Context) {}
func deleteUser(c *gin.Context) {}

func main() {
    r := gin.Default()
    r.PUT("/users/:id", updateUser)
    r.DELETE("/users/:id", deleteUser)
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        methods = {n.metadata.get("http_method") for n in route_nodes}
        assert "PUT" in methods
        assert "DELETE" in methods

    def test_detect_route_group(self):
        resolver = GinResolver()
        src = '''package main
import "github.com/gin-gonic/gin"

func listUsers(c *gin.Context) {}

func main() {
    r := gin.Default()
    api := r.Group("/api")
    {
        api.GET("/users", listUsers)
    }
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(route_nodes) >= 1

    def test_inline_handler_marked_possible(self):
        resolver = GinResolver()
        src = '''package main
import "github.com/gin-gonic/gin"

func main() {
    r := gin.Default()
    r.GET("/ping", func(c *gin.Context) {
        c.JSON(200, gin.H{"message": "pong"})
    })
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_edges = [e for e in result.edges if e.type == EdgeType.routes_to]
        assert len(route_edges) >= 1
        edge = route_edges[0]
        assert edge.metadata is not None
        assert edge.metadata.resolution == Resolution.gin_inline_handler

    def test_imported_handler(self):
        resolver = GinResolver()
        src = '''package main
import "github.com/gin-gonic/gin"
import "myapp/handlers"

func main() {
    r := gin.Default()
    r.GET("/users", handlers.CreateUser)
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_edges = [e for e in result.edges if e.type == EdgeType.routes_to]
        assert len(route_edges) >= 1
        # Should target unresolved handler
        assert "handlers.CreateUser" in route_edges[0].target or "unresolved" in route_edges[0].target

    def test_middleware_references(self):
        resolver = GinResolver()
        src = '''package main
import "github.com/gin-gonic/gin"

func authMiddleware() gin.HandlerFunc { return nil }
func dashboard(c *gin.Context) {}

func main() {
    r := gin.Default()
    r.GET("/admin", authMiddleware(), dashboard)
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        # Should have middleware reference
        ref_edges = [e for e in result.edges if e.type == EdgeType.references]
        assert len(ref_edges) >= 1

    def test_no_gin_import_no_routes(self):
        resolver = GinResolver()
        src = '''package main

func main() {
    http.HandleFunc("/", handler)
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(route_nodes) == 0


class TestGinFrameworkIntegration:
    """Integration tests using fixture project."""

    def test_fixture_main_gin_routes(self):
        if not FIXTURES_GO.exists():
            pytest.skip("Go fixture project not found")

        ext = GoExtractor()
        main_file = FIXTURES_GO / "main.go"
        result = ext.extract(
            file_path=str(main_file),
            project_root=str(FIXTURES_GO),
        )

        # Check for route nodes in extractor output
        route_symbols = [s for s in result.symbols if s.type == NodeType.route]
        assert len(route_symbols) > 0, "Should detect at least one Gin route"

        # Check for routes_to edges
        raw_edges = getattr(result, "_raw_edges", [])
        route_edges = [e for e in raw_edges if e.type == EdgeType.routes_to]
        assert len(route_edges) > 0, "Should have routes_to edges"

        # Check route paths
        route_paths = set()
        for r in route_symbols:
            path = r.metadata.get("route_path", "")
            if path:
                route_paths.add(path)
        assert "/users" in route_paths or any("users" in p for p in route_paths)

    def test_gin_routes_have_framework_id(self):
        if not FIXTURES_GO.exists():
            pytest.skip("Go fixture project not found")

        ext = GoExtractor()
        main_file = FIXTURES_GO / "main.go"
        result = ext.extract(
            file_path=str(main_file),
            project_root=str(FIXTURES_GO),
        )

        route_symbols = [s for s in result.symbols if s.type == NodeType.route]
        for route in route_symbols:
            assert route.framework_id == "gin", f"Route {route.name} should have framework_id='gin'"
            assert route.metadata.get("framework_id") == "gin"

    def test_different_methods_detected(self):
        if not FIXTURES_GO.exists():
            pytest.skip("Go fixture project not found")

        ext = GoExtractor()
        main_file = FIXTURES_GO / "main.go"
        result = ext.extract(
            file_path=str(main_file),
            project_root=str(FIXTURES_GO),
        )

        route_symbols = [s for s in result.symbols if s.type == NodeType.route]
        methods = {r.metadata.get("http_method") for r in route_symbols}
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods


class TestHertzResolver:
    """Hertz framework route detection tests."""

    def test_detect_hertz_default(self):
        resolver = HertzResolver()
        result = resolver.extract(
            rel="test.go",
            src='package main\nimport "github.com/cloudwego/hertz/pkg/app/server"\n\nfunc main() {\n\th := server.Default()\n}',
            symbols=[],
            imports=[],
            language_id="go",
        )
        assert len(result.diagnostics) >= 1
        assert any("Hertz engine detected" in d.message for d in result.diagnostics)

    def test_detect_hertz_new(self):
        resolver = HertzResolver()
        result = resolver.extract(
            rel="test.go",
            src='package main\nimport "github.com/cloudwego/hertz/pkg/app/server"\n\nfunc main() {\n\th := server.New()\n}',
            symbols=[],
            imports=[],
            language_id="go",
        )
        assert any("Hertz engine detected" in d.message for d in result.diagnostics)

    def test_detect_get_route(self):
        resolver = HertzResolver()
        result = resolver.extract(
            rel="test.go",
            src='package main\nimport "github.com/cloudwego/hertz/pkg/app/server"\n\nfunc listUsers(c context.Context, ctx *app.RequestContext) {}\n\nfunc main() {\n\th := server.Default()\n\th.GET("/users", listUsers)\n}',
            symbols=[],
            imports=[],
            language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(route_nodes) >= 1
        route = route_nodes[0]
        assert route.metadata.get("http_method") == "GET"
        assert "/users" in route.metadata.get("route_path", "")

        route_edges = [e for e in result.edges if e.type == EdgeType.routes_to]
        assert len(route_edges) >= 1

    def test_detect_post_route(self):
        resolver = HertzResolver()
        result = resolver.extract(
            rel="test.go",
            src='package main\nimport "github.com/cloudwego/hertz/pkg/app/server"\n\nfunc createUser(c context.Context, ctx *app.RequestContext) {}\n\nfunc main() {\n\th := server.Default()\n\th.POST("/users", createUser)\n}',
            symbols=[],
            imports=[],
            language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(route_nodes) >= 1
        assert route_nodes[0].metadata.get("http_method") == "POST"

    def test_detect_put_delete_routes(self):
        resolver = HertzResolver()
        src = '''package main
import "github.com/cloudwego/hertz/pkg/app/server"

func updateUser(c context.Context, ctx *app.RequestContext) {}
func deleteUser(c context.Context, ctx *app.RequestContext) {}

func main() {
    h := server.Default()
    h.PUT("/users/:id", updateUser)
    h.DELETE("/users/:id", deleteUser)
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        methods = {n.metadata.get("http_method") for n in route_nodes}
        assert "PUT" in methods
        assert "DELETE" in methods

    def test_detect_route_group(self):
        resolver = HertzResolver()
        src = '''package main
import "github.com/cloudwego/hertz/pkg/app/server"

func listUsers(c context.Context, ctx *app.RequestContext) {}

func main() {
    h := server.Default()
    api := h.Group("/api")
    {
        api.GET("/users", listUsers)
    }
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(route_nodes) >= 1

    def test_inline_handler_marked_possible(self):
        resolver = HertzResolver()
        src = '''package main
import "github.com/cloudwego/hertz/pkg/app/server"

func main() {
    h := server.Default()
    h.GET("/ping", func(c context.Context, ctx *app.RequestContext) {
        ctx.JSON(200, map[string]string{"message": "pong"})
    })
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_edges = [e for e in result.edges if e.type == EdgeType.routes_to]
        assert len(route_edges) >= 1
        edge = route_edges[0]
        assert edge.metadata is not None
        assert edge.metadata.resolution == Resolution.hertz_inline_handler

    def test_imported_handler(self):
        resolver = HertzResolver()
        src = '''package main
import "github.com/cloudwego/hertz/pkg/app/server"
import "myapp/handlers"

func main() {
    h := server.Default()
    h.GET("/users", handlers.CreateUser)
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_edges = [e for e in result.edges if e.type == EdgeType.routes_to]
        assert len(route_edges) >= 1
        assert "handlers.CreateUser" in route_edges[0].target or "unresolved" in route_edges[0].target

    def test_middleware_references(self):
        resolver = HertzResolver()
        src = '''package main
import "github.com/cloudwego/hertz/pkg/app/server"

func authMiddleware() app.HandlerFunc { return nil }
func dashboard(c context.Context, ctx *app.RequestContext) {}

func main() {
    h := server.Default()
    h.GET("/admin", authMiddleware(), dashboard)
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        ref_edges = [e for e in result.edges if e.type == EdgeType.references]
        assert len(ref_edges) >= 1

    def test_no_hertz_import_no_routes(self):
        resolver = HertzResolver()
        src = '''package main

func main() {
    http.HandleFunc("/", handler)
}'''
        result = resolver.extract(
            rel="test.go", src=src, symbols=[], imports=[], language_id="go",
        )
        route_nodes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(route_nodes) == 0


class TestHertzFrameworkIntegration:
    """Integration tests using Hertz fixture project."""

    def test_fixture_main_hertz_routes(self):
        if not FIXTURES_HERTZ.exists():
            pytest.skip("Hertz fixture project not found")

        ext = GoExtractor()
        main_file = FIXTURES_HERTZ / "main.go"
        result = ext.extract(
            file_path=str(main_file),
            project_root=str(FIXTURES_HERTZ),
        )

        route_symbols = [s for s in result.symbols if s.type == NodeType.route]
        assert len(route_symbols) > 0, "Should detect at least one Hertz route"

        raw_edges = getattr(result, "_raw_edges", [])
        route_edges = [e for e in raw_edges if e.type == EdgeType.routes_to]
        assert len(route_edges) > 0, "Should have routes_to edges"

        route_paths = set()
        for r in route_symbols:
            path = r.metadata.get("route_path", "")
            if path:
                route_paths.add(path)
        assert "/users" in route_paths or any("users" in p for p in route_paths)

    def test_hertz_routes_have_framework_id(self):
        if not FIXTURES_HERTZ.exists():
            pytest.skip("Hertz fixture project not found")

        ext = GoExtractor()
        main_file = FIXTURES_HERTZ / "main.go"
        result = ext.extract(
            file_path=str(main_file),
            project_root=str(FIXTURES_HERTZ),
        )

        route_symbols = [s for s in result.symbols if s.type == NodeType.route]
        assert len(route_symbols) > 0
        for route in route_symbols:
            assert route.framework_id == "hertz", f"Route {route.name} should have framework_id='hertz'"
            assert route.metadata.get("framework_id") == "hertz"

    def test_different_methods_detected(self):
        if not FIXTURES_HERTZ.exists():
            pytest.skip("Hertz fixture project not found")

        ext = GoExtractor()
        main_file = FIXTURES_HERTZ / "main.go"
        result = ext.extract(
            file_path=str(main_file),
            project_root=str(FIXTURES_HERTZ),
        )

        route_symbols = [s for s in result.symbols if s.type == NodeType.route]
        methods = {r.metadata.get("http_method") for r in route_symbols}
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods
