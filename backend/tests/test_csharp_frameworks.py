"""Tests for ASP.NET Core framework extraction — controllers, minimal API, DI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest

from codegraph.language_support.csharp.frameworks import (
    AspNetCoreResolver,
    FrameworkExtraction,
)
from codegraph.graph.models import GraphNode, NodeType, EdgeType


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "csharp_aspnet_project"


@pytest.fixture
def framework():
    return AspNetCoreResolver()


# ── Controller route ──────────────────────────────────────────────────────────

class TestControllerRoute:
    def test_controller_route_attribute(self, framework):
        src = ('[ApiController]\n[Route("api/[controller]")]\n'
               'public class UsersController : ControllerBase {\n'
               '[HttpGet]\npublic string GetAll() => "ok";\n'
               '}')
        result = framework.extract(
            rel="Controllers/UsersController.cs",
            src=src,
            symbols=[],
            imports=[],
            language_id="csharp",
        )
        routes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(routes) >= 1
        # Should have GET route
        get_routes = [r for r in routes if r.metadata.get("http_method") == "GET"]
        assert len(get_routes) >= 1
        # Route path should have [controller] resolved to "users"
        assert "users" in get_routes[0].metadata.get("route_path", "").lower()

    def test_controller_route_with_path(self, framework):
        src = ('[ApiController]\n[Route("api/v1/[controller]")]\n'
               'public class ProductsController : ControllerBase {\n'
               '[HttpGet("{id}")]\npublic string GetById(int id) => "x";\n'
               '}')
        result = framework.extract(
            rel="Controllers/ProductsController.cs",
            src=src,
            symbols=[],
            imports=[],
            language_id="csharp",
        )
        routes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(routes) >= 1
        route_paths = [r.metadata.get("route_path", "") for r in routes]
        assert any("products" in p and "{id}" in p for p in route_paths)

    def test_multiple_http_methods(self, framework):
        src = ('[ApiController]\n[Route("api/[controller]")]\n'
               'public class ItemsController : ControllerBase {\n'
               '[HttpGet]\npublic void GetAll() { }\n'
               '[HttpPost]\npublic void Create() { }\n'
               '[HttpPut("{id}")]\npublic void Update() { }\n'
               '[HttpDelete("{id}")]\npublic void Delete() { }\n'
               '}')
        result = framework.extract(
            rel="Controllers/ItemsController.cs",
            src=src,
            symbols=[],
            imports=[],
            language_id="csharp",
        )
        routes = [n for n in result.nodes if n.type == NodeType.route]
        methods = {r.metadata.get("http_method") for r in routes}
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods

    def test_routes_to_edge(self, framework):
        src = ('[ApiController]\n[Route("api/[controller]")]\n'
               'public class UsersController : ControllerBase {\n'
               '[HttpGet]\npublic string GetAll() => "ok";\n'
               '}')
        result = framework.extract(
            rel="Controllers/UsersController.cs",
            src=src,
            symbols=[],
            imports=[],
            language_id="csharp",
        )
        route_edges = [e for e in result.edges if e.type == EdgeType.routes_to]
        assert len(route_edges) >= 1


# ── Minimal API ───────────────────────────────────────────────────────────────

class TestMinimalApi:
    def test_map_get(self, framework):
        src = 'app.MapGet("/health", () => Results.Ok(new { Status = "OK" }));'
        result = framework.extract(
            rel="Program.cs", src=src, symbols=[], imports=[],
            language_id="csharp",
        )
        routes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(routes) >= 1
        health_routes = [r for r in routes if "/health" in r.metadata.get("route_path", "")]
        assert len(health_routes) >= 1

    def test_map_post(self, framework):
        src = 'app.MapPost("/api/users", CreateUser);'
        result = framework.extract(
            rel="Program.cs", src=src, symbols=[], imports=[],
            language_id="csharp",
        )
        routes = [n for n in result.nodes if n.type == NodeType.route]
        post_routes = [r for r in routes if r.metadata.get("http_method") == "POST"]
        assert len(post_routes) >= 1

    def test_map_group(self, framework):
        src = ('var usersGroup = app.MapGroup("/api/users");\n'
               'usersGroup.MapGet("/", GetAllUsers);\n'
               'usersGroup.MapPost("/", CreateUser);')
        result = framework.extract(
            rel="Program.cs", src=src, symbols=[], imports=[],
            language_id="csharp",
        )
        routes = [n for n in result.nodes if n.type == NodeType.route]
        assert len(routes) >= 2
        # Should have correct MapGroup prefix
        route_paths = [r.metadata.get("route_path", "") for r in routes]
        assert any(p.startswith("/api/users") for p in route_paths)

    def test_lambda_handler_not_confirmed_as_existing_method(self, framework):
        """Lambda handler should get inline_handler, not point to an existing method."""
        src = 'app.MapGet("/api/status", async (HttpContext context) => { await context.Response.WriteAsync("OK"); });'
        result = framework.extract(
            rel="Program.cs", src=src, symbols=[], imports=[],
            language_id="csharp",
        )
        # Should have inline handler node
        inline_nodes = [n for n in result.nodes if "inline_handler" in n.tags]
        assert len(inline_nodes) >= 1

    def test_handler_reference_resolves_to_method(self, framework):
        """Handler reference should link to the named method."""
        symbols = [
            GraphNode(
                id="Program.cs::GetApiInfo",
                type=NodeType.function,
                name="GetApiInfo",
                file_path="Program.cs",
                language_id="csharp",
                language="csharp",
            ),
        ]
        src = 'app.MapGet("/api/info", GetApiInfo);'
        result = framework.extract(
            rel="Program.cs", src=src, symbols=symbols, imports=[],
            language_id="csharp",
        )
        route_edges = [e for e in result.edges if e.type == EdgeType.routes_to]
        assert len(route_edges) >= 1
        assert "GetApiInfo" in route_edges[0].target


# ── DI ────────────────────────────────────────────────────────────────────────

class TestDependencyInjection:
    def test_constructor_injection(self, framework):
        src = ('public class UserService {\n'
               '    private readonly IUserRepository _repo;\n'
               '    public UserService(IUserRepository repo, ILogger<UserService> logger) { }\n'
               '}')
        result = framework.extract(
            rel="Services/UserService.cs", src=src, symbols=[], imports=[],
            language_id="csharp",
        )
        depends_edges = [e for e in result.edges if e.type == EdgeType.depends_on]
        assert len(depends_edges) >= 1
        # Should detect IUserRepository injection
        evidence_text = str([e.metadata.evidence for e in depends_edges if e.metadata])
        assert "IUserRepository" in evidence_text or any(
            "IUserRepository" in str(e.evidence) for e in depends_edges)

    def test_service_registration_detected(self, framework):
        src = 'builder.Services.AddScoped<IUserService, UserService>();'
        result = framework.extract(
            rel="Program.cs", src=src, symbols=[], imports=[],
            language_id="csharp",
        )
        # Should produce a diagnostic about service registration
        diag_messages = [d.message for d in result.diagnostics]
        assert any("AddScoped" in m for m in diag_messages)


# ── Integration: full fixture project ─────────────────────────────────────────

class TestFullFixtureProject:
    def test_users_controller_routes(self, framework):
        src = (FIXTURES / "Controllers" / "UsersController.cs").read_text(encoding="utf-8")
        result = framework.extract(
            rel="Controllers/UsersController.cs",
            src=src,
            symbols=[],
            imports=[],
            language_id="csharp",
        )
        routes = [n for n in result.nodes if n.type == NodeType.route]
        route_edges = [e for e in result.edges if e.type == EdgeType.routes_to]

        methods = {r.metadata.get("http_method") for r in routes}
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods

        assert len(route_edges) >= 5  # 5 HTTP methods

    def test_program_cs_routes(self, framework):
        src = (FIXTURES / "Program.cs").read_text(encoding="utf-8")
        result = framework.extract(
            rel="Program.cs",
            src=src,
            symbols=[],
            imports=[],
            language_id="csharp",
        )
        routes = [n for n in result.nodes if n.type == NodeType.route]
        route_paths = {r.metadata.get("route_path", "") for r in routes}

        assert any("/health" in p for p in route_paths)
        assert any("/api/info" in p for p in route_paths)
        assert any("/api/users" in p for p in route_paths)
        assert any("/api/status" in p for p in route_paths)

    def test_user_service_di(self, framework):
        src = (FIXTURES / "Services" / "UserService.cs").read_text(encoding="utf-8")
        result = framework.extract(
            rel="Services/UserService.cs",
            src=src,
            symbols=[],
            imports=[],
            language_id="csharp",
        )
        depends_edges = [e for e in result.edges if e.type == EdgeType.depends_on]
        # UserService should have DI dependencies
        assert len(depends_edges) >= 1
