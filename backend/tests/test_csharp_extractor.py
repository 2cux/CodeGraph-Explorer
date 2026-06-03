"""Tests for CSharpExtractor — namespace, using, class, method, property extraction."""

import sys
import os
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest

from codegraph.language_support.csharp.extractor import CSharpExtractor
from codegraph.graph.models import NodeType


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "csharp_aspnet_project"


def _read(fname: str) -> str:
    return (FIXTURES / fname).read_text(encoding="utf-8")


@pytest.fixture
def extractor():
    return CSharpExtractor()


# ── Namespace ───────────────────────────────────────────────────────────────

class TestNamespaceExtraction:
    def test_extracts_namespace(self, extractor):
        src = "namespace MyApp.Services;\n\npublic class UserService { }"
        result = extractor.extract("test.cs", content=src)
        ns_nodes = [s for s in result.symbols if s.metadata.get("kind") == "namespace"]
        assert len(ns_nodes) == 1
        assert ns_nodes[0].name == "MyApp.Services"

    def test_extracts_block_namespace(self, extractor):
        src = "namespace MyApp.Controllers {\n    public class HomeController { }\n}"
        result = extractor.extract("test.cs", content=src)
        ns_nodes = [s for s in result.symbols if s.metadata.get("kind") == "namespace"]
        assert len(ns_nodes) >= 1
        assert any(n.name == "MyApp.Controllers" for n in ns_nodes)


# ── Using ────────────────────────────────────────────────────────────────────

class TestUsingExtraction:
    def test_extracts_using_namespace(self, extractor):
        src = "using System;\nusing MyApp.Services;\n\nnamespace X { class C { } }"
        result = extractor.extract("test.cs", content=src)
        module_paths = [i.module_path for i in result.imports]
        assert "System" in module_paths
        assert "MyApp.Services" in module_paths

    def test_using_alias(self, extractor):
        src = 'using Json = Newtonsoft.Json.JsonConvert;\n\nclass C { }'
        result = extractor.extract("test.cs", content=src)
        aliases = [i for i in result.imports if i.local_name == "Json"]
        assert len(aliases) >= 1
        assert aliases[0].module_path == "Newtonsoft.Json.JsonConvert"

    def test_system_is_external(self, extractor):
        src = "using System.Collections.Generic;\n\nclass C { }"
        result = extractor.extract("test.cs", content=src)
        system_imports = [i for i in result.imports if i.module_path.startswith("System")]
        assert len(system_imports) >= 1
        assert system_imports[0].is_external is True

    def test_project_using_is_not_external(self, extractor):
        src = "using MyApp.Utils;\n\nclass C { }"
        result = extractor.extract("test.cs", content=src)
        myapp_imports = [i for i in result.imports if i.module_path.startswith("MyApp")]
        assert len(myapp_imports) >= 1
        assert myapp_imports[0].is_external is False


# ── Class ────────────────────────────────────────────────────────────────────

class TestClassExtraction:
    def test_extracts_class(self, extractor):
        src = "namespace X;\npublic class UserService { }"
        result = extractor.extract("test.cs", content=src)
        classes = [s for s in result.symbols if s.type in (NodeType.class_, NodeType.service)]
        assert any(c.name == "UserService" for c in classes)

    def test_class_with_base(self, extractor):
        src = "public class UsersController : ControllerBase { }"
        result = extractor.extract("test.cs", content=src)
        classes = [s for s in result.symbols if s.type in (NodeType.class_, NodeType.controller)]
        assert any(c.name == "UsersController" for c in classes)
        ctrl = [c for c in classes if c.name == "UsersController"][0]
        assert "ControllerBase" in str(ctrl.metadata.get("base_types", []))

    def test_interface(self, extractor):
        src = "namespace X;\npublic interface IUserRepository { }"
        result = extractor.extract("test.cs", content=src)
        ifaces = [s for s in result.symbols if "interface" in s.tags]
        assert len(ifaces) >= 1
        assert any(i.name == "IUserRepository" for i in ifaces)

    def test_enum(self, extractor):
        src = "namespace X;\npublic enum UserRole { Admin, User, Guest }"
        result = extractor.extract("test.cs", content=src)
        enums = [s for s in result.symbols if "enum" in s.tags]
        assert len(enums) >= 1
        assert any(e.name == "UserRole" for e in enums)

    def test_controller_detection_by_name(self, extractor):
        src = "public class UsersController { public void Get() { } }"
        result = extractor.extract("test.cs", content=src)
        controllers = [s for s in result.symbols if s.type == NodeType.controller]
        assert len(controllers) >= 1
        assert controllers[0].name == "UsersController"

    def test_service_detection_by_name(self, extractor):
        src = "public class UserService { }"
        result = extractor.extract("test.cs", content=src)
        services = [s for s in result.symbols if s.type == NodeType.service]
        assert len(services) >= 1
        assert services[0].name == "UserService"


# ── Method ───────────────────────────────────────────────────────────────────

class TestMethodExtraction:
    def test_extracts_method(self, extractor):
        src = "public class Calc { public int Add(int a, int b) { return a + b; } }"
        result = extractor.extract("test.cs", content=src)
        methods = [s for s in result.symbols if s.type == NodeType.method]
        assert any(m.name == "Add" for m in methods)

    def test_async_method(self, extractor):
        src = "public class Service { public async Task<int> GetAsync() { return 1; } }"
        result = extractor.extract("test.cs", content=src)
        methods = [s for s in result.symbols if s.type == NodeType.method]
        get_methods = [m for m in methods if m.name == "GetAsync"]
        assert len(get_methods) >= 1

    def test_constructor(self, extractor):
        src = "public class UserService { public UserService(ILogger log) { } }"
        result = extractor.extract("test.cs", content=src)
        ctors = [s for s in result.symbols if "constructor" in s.tags]
        assert len(ctors) >= 1


# ── Property ─────────────────────────────────────────────────────────────────

class TestPropertyExtraction:
    def test_extracts_property(self, extractor):
        src = "public class User { public string Name { get; set; } }"
        result = extractor.extract("test.cs", content=src)
        props = [s for s in result.symbols if "property" in s.tags]
        assert len(props) >= 1
        assert any(p.name == "Name" for p in props)

    def test_expression_bodied_property(self, extractor):
        src = "public class User { public string FullName => $\"{FirstName} {LastName}\"; }"
        result = extractor.extract("test.cs", content=src)
        props = [s for s in result.symbols if "property" in s.tags]
        assert len(props) >= 1


# ── Call extraction ──────────────────────────────────────────────────────────

class TestCallExtraction:
    def test_this_method_call(self, extractor):
        src = "public class Calc { public void Run() { this.Helper(); } public void Helper() { } }"
        result = extractor.extract("test.cs", content=src)
        this_calls = [c for c in result.calls if "this." in c.target_expression]
        assert len(this_calls) >= 1

    def test_static_method_call(self, extractor):
        src = "public class App { public void Run() { Logger.Log(\"msg\"); } }"
        result = extractor.extract("test.cs", content=src)
        member_calls = [c for c in result.calls if "." in c.target_expression]
        assert any("Logger" in c.target_expression for c in member_calls)

    def test_constructor_call(self, extractor):
        src = "public class Factory { public object Create() { return new User(); } }"
        result = extractor.extract("test.cs", content=src)
        new_calls = [c for c in result.calls if c.call_expr and "new " in c.call_expr]
        assert len(new_calls) >= 1

    def test_base_method_call(self, extractor):
        src = "public class Derived : Base { public void Run() { base.Init(); } }"
        result = extractor.extract("test.cs", content=src)
        base_calls = [c for c in result.calls if "base." in c.target_expression]
        assert len(base_calls) >= 1


# ── Attribute ────────────────────────────────────────────────────────────────

class TestAttributeExtraction:
    def test_api_controller_attribute(self, extractor):
        src = "[ApiController]\n[Route(\"api/[controller]\")]\npublic class UsersController : ControllerBase { }"
        result = extractor.extract("test.cs", content=src)
        controllers = [s for s in result.symbols if s.type == NodeType.controller]
        assert len(controllers) >= 1

    def test_http_method_attributes(self, extractor):
        src = ('[ApiController]\npublic class TestController : ControllerBase {\n'
               '[HttpGet]\npublic string Get() => "ok";\n'
               '[HttpPost]\npublic void Post() { }\n}')
        result = extractor.extract("test.cs", content=src)
        methods = [s for s in result.symbols if s.type == NodeType.method]
        get_m = [m for m in methods if m.metadata.get("http_method") == "GET"]
        post_m = [m for m in methods if m.metadata.get("http_method") == "POST"]
        assert len(get_m) >= 1
        assert len(post_m) >= 1


# ── Integration: full file ───────────────────────────────────────────────────

class TestFullFileIntegration:
    def test_users_controller(self, extractor):
        src = _read("Controllers/UsersController.cs")
        result = extractor.extract("Controllers/UsersController.cs", content=src)
        symbols = result.symbols

        # Should have class
        classes = [s for s in symbols if s.name == "UsersController"]
        assert len(classes) >= 1

        # Should have methods
        methods = [s for s in symbols if s.type == NodeType.method]
        method_names = {m.name for m in methods}
        assert "GetAll" in method_names
        assert "GetById" in method_names
        assert "Create" in method_names
        assert "Update" in method_names
        assert "Delete" in method_names

        # Should have HTTP method metadata
        http_methods = {m.metadata.get("http_method") for m in methods}
        assert "GET" in http_methods
        assert "POST" in http_methods
        assert "PUT" in http_methods
        assert "DELETE" in http_methods

    def test_program_cs(self, extractor):
        src = _read("Program.cs")
        result = extractor.extract("Program.cs", content=src)

        # Should have route symbols from framework extraction
        routes = [s for s in result.symbols if s.type == NodeType.route]
        assert len(routes) >= 3  # health, api/info, api/users + api/status

    def test_service_file(self, extractor):
        src = _read("Services/UserService.cs")
        result = extractor.extract("Services/UserService.cs", content=src)

        # Should have interface
        ifaces = [s for s in result.symbols if "interface" in s.tags]
        assert any(i.name == "IUserService" for i in ifaces)

        # Should have class
        classes = [s for s in result.symbols if s.name == "UserService"]
        assert len(classes) >= 1

        # Should have methods
        methods = [s for s in result.symbols if s.type == NodeType.method]
        method_names = {m.name for m in methods}
        assert "GetAllUsersAsync" in method_names
        assert "GetUserByIdAsync" in method_names
        assert "CreateUserAsync" in method_names

    def test_language_id_set(self, extractor):
        src = "namespace X;\npublic class Foo { }"
        result = extractor.extract("test.cs", content=src)
        for s in result.symbols:
            if s.type != NodeType.file:
                assert s.language_id == "csharp"
                assert s.language == "csharp"
                assert s.metadata.get("support_level") == "beta"

    def test_support_level_beta(self, extractor):
        src = "namespace X;\npublic class Foo { }"
        result = extractor.extract("test.cs", content=src)
        non_file = [s for s in result.symbols if s.type != NodeType.file]
        assert all(s.metadata.get("support_level") == "beta" for s in non_file)
