"""Tests for Go language extractor."""

import pytest
from pathlib import Path

from codegraph.language_support.go.extractor import GoExtractor
from codegraph.language_support.registry import reset_registry
from codegraph.graph.models import NodeType


FIXTURES_GO = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "go_gin_project"
FIXTURES_HERTZ = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "go_hertz_project"


@pytest.fixture(autouse=True)
def _reset():
    reset_registry()


class TestGoExtractor:
    """Extraction tests for Go (.go) files."""

    # ── Package and imports ────────────────────────────────────────────

    def test_extract_package_declaration(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\nfunc main() {}',
            project_root="/tmp",
        )
        assert result.language_id == "go"
        modules = [s for s in result.symbols if s.type == NodeType.module]
        assert len(modules) >= 1
        assert any(m.name == "main" for m in modules)

    def test_extract_single_import(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\nimport "fmt"\n\nfunc main() { fmt.Println("hi") }',
            project_root="/tmp",
        )
        assert len(result.imports) >= 1
        import_paths = [i.module_path for i in result.imports]
        assert "fmt" in import_paths

    def test_extract_aliased_import(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\nimport f "fmt"\n\nfunc main() { f.Println("hi") }',
            project_root="/tmp",
        )
        aliased = [i for i in result.imports if i.local_name == "f"]
        assert len(aliased) == 1
        assert aliased[0].module_path == "fmt"

    def test_extract_import_block(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\nimport (\n\t"fmt"\n\t"os"\n\t"strings"\n)\n\nfunc main() {}',
            project_root="/tmp",
        )
        paths = {i.module_path for i in result.imports}
        assert "fmt" in paths
        assert "os" in paths
        assert "strings" in paths

    def test_external_module_detection(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\nimport "github.com/gin-gonic/gin"\n\nfunc main() {}',
            project_root="/tmp",
        )
        gin_imports = [i for i in result.imports if "gin" in i.module_path]
        assert len(gin_imports) == 1
        assert gin_imports[0].is_external is True

    def test_stdlib_not_external(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\nimport "fmt"\nimport "net/http"\n\nfunc main() {}',
            project_root="/tmp",
        )
        for imp in result.imports:
            assert imp.is_external is False, f"{imp.module_path} should not be external"

    # ── Functions ──────────────────────────────────────────────────────

    def test_extract_function(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\nfunc Hello(name string) string {\n\treturn "Hi, " + name\n}',
            project_root="/tmp",
        )
        funcs = [s for s in result.symbols if s.type == NodeType.function]
        names = {f.name for f in funcs}
        assert "Hello" in names

    def test_extract_function_with_params(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\nfunc Add(a int, b int) int {\n\treturn a + b\n}',
            project_root="/tmp",
        )
        funcs = [s for s in result.symbols if s.name == "Add"]
        assert len(funcs) == 1
        assert funcs[0].signature is not None
        assert "Add" in funcs[0].signature

    def test_extract_test_function(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\nimport "testing"\n\nfunc TestHello(t *testing.T) {\n\tt.Log("test")\n}',
            project_root="/tmp",
        )
        tests = [s for s in result.symbols if s.type == NodeType.test]
        assert len(tests) == 1
        assert tests[0].name == "TestHello"

    # ── Methods ────────────────────────────────────────────────────────

    def test_extract_method_with_receiver(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\ntype User struct { Name string }\n\nfunc (u *User) GetName() string {\n\treturn u.Name\n}',
            project_root="/tmp",
        )
        methods = [s for s in result.symbols if s.type == NodeType.method]
        assert len(methods) == 1
        assert methods[0].name == "GetName"
        assert methods[0].metadata.get("receiver_type") == "User"

    def test_extract_method_with_value_receiver(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\ntype Rect struct { W, H int }\n\nfunc (r Rect) Area() int {\n\treturn r.W * r.H\n}',
            project_root="/tmp",
        )
        methods = [s for s in result.symbols if s.type == NodeType.method]
        assert len(methods) == 1
        assert methods[0].metadata.get("receiver_type") == "Rect"
        assert methods[0].metadata.get("is_pointer_receiver") is False

    # ── Structs ────────────────────────────────────────────────────────

    def test_extract_struct(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\ntype User struct {\n\tName string\n\tAge  int\n}',
            project_root="/tmp",
        )
        structs = [s for s in result.symbols if "struct" in s.tags]
        assert len(structs) == 1
        assert structs[0].name == "User"
        assert structs[0].metadata.get("go_kind") == "struct"

    def test_extract_struct_with_embedding(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\ntype UserRepository interface {\n\tGetAll() []User\n}\n\ntype UserStore struct {\n\tUserRepository\n\tusers map[string]User\n}',
            project_root="/tmp",
        )
        structs = [s for s in result.symbols if "struct" in s.tags]
        assert len(structs) == 1
        # Should have a reference edge for the embedded type
        ref_edges = result.references
        emb_edges = [r for r in ref_edges if r.target_expression == "UserRepository"]
        assert len(emb_edges) == 1

    # ── Interfaces ─────────────────────────────────────────────────────

    def test_extract_interface(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\ntype Reader interface {\n\tRead(p []byte) (n int, err error)\n}',
            project_root="/tmp",
        )
        interfaces = [s for s in result.symbols if "interface" in s.tags]
        assert len(interfaces) == 1
        assert interfaces[0].name == "Reader"
        assert interfaces[0].metadata.get("go_kind") == "interface"

    # ── Constants and variables ────────────────────────────────────────

    def test_extract_const(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\nconst MaxUsers = 1000\nconst DefaultName = "guest"',
            project_root="/tmp",
        )
        consts = [s for s in result.symbols if "const" in s.tags]
        assert len(consts) == 2
        names = {c.name for c in consts}
        assert "MaxUsers" in names
        assert "DefaultName" in names

    def test_extract_var(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\nvar counter int\nvar mutex sync.Mutex',
            project_root="/tmp",
        )
        vars_ = [s for s in result.symbols if "var" in s.tags]
        assert len(vars_) == 2

    # ── Call extraction ───────────────────────────────────────────────

    def test_extract_function_call(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\nfunc helper() {}\n\nfunc main() {\n\thelper()\n}',
            project_root="/tmp",
        )
        calls = result.calls
        assert len(calls) >= 1
        call_exprs = [c.target_expression for c in calls]
        assert "helper" in call_exprs

    def test_extract_package_function_call(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("hi")\n}',
            project_root="/tmp",
        )
        calls = result.calls
        pkg_calls = [c for c in calls if "." in (c.target_expression or "")]
        assert len(pkg_calls) >= 1
        assert any("fmt.Println" in c.target_expression for c in pkg_calls)

    def test_extract_constructor_call(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\ntype Service struct {}\n\nfunc NewService() *Service {\n\treturn &Service{}\n}\n\nfunc main() {\n\tsvc := NewService()\n}',
            project_root="/tmp",
        )
        calls = result.calls
        assert any("NewService" in c.target_expression for c in calls)

    # ── Export extraction ──────────────────────────────────────────────

    def test_export_capitalized_names(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\nfunc PublicFunc() {}\nfunc privateFunc() {}',
            project_root="/tmp",
        )
        export_names = {e.name for e in result.exports}
        assert "PublicFunc" in export_names
        assert "privateFunc" not in export_names

    # ── File node and module node ──────────────────────────────────────

    def test_file_and_module_nodes(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="src/test.go",
            content='package main\n\nfunc main() {}',
            project_root="/tmp",
        )
        files = [s for s in result.symbols if s.type == NodeType.file]
        modules = [s for s in result.symbols if s.type == NodeType.module]
        assert len(files) >= 1
        assert len(modules) >= 1

    # ── Diagnostics ────────────────────────────────────────────────────

    def test_cgo_diagnostic(self):
        ext = GoExtractor()
        result = ext.extract(
            file_path="test.go",
            content='package main\n\n/*\n#cgo LDFLAGS: -lm\n*/\nimport "C"\n\nfunc main() {}',
            project_root="/tmp",
        )
        cgo_diags = [d for d in result.diagnostics if "cgo" in d.message.lower()]
        assert len(cgo_diags) >= 1

    # ── Integration: fixture project ──────────────────────────────────

    def test_extract_fixture_main(self):
        if not FIXTURES_GO.exists():
            pytest.skip("Go fixture project not found")
        ext = GoExtractor()
        main_file = FIXTURES_GO / "main.go"
        result = ext.extract(
            file_path=str(main_file),
            project_root=str(FIXTURES_GO),
        )
        assert result.language_id == "go"
        assert len(result.symbols) > 0

        # Should find functions
        func_names = {s.name for s in result.symbols if s.type in (NodeType.function, NodeType.test)}
        assert "listUsers" in func_names
        assert "healthCheck" in func_names
        assert "authMiddleware" in func_names

        # Should find imports
        import_paths = {i.module_path for i in result.imports}
        assert "github.com/gin-gonic/gin" in import_paths
        assert "fmt" in import_paths

    def test_extract_fixture_models(self):
        if not FIXTURES_GO.exists():
            pytest.skip("Go fixture project not found")
        ext = GoExtractor()
        models_file = FIXTURES_GO / "models" / "user.go"
        result = ext.extract(
            file_path=str(models_file),
            project_root=str(FIXTURES_GO),
        )
        assert result.language_id == "go"

        # Should find struct
        struct_names = {s.name for s in result.symbols if "struct" in s.tags}
        assert "User" in struct_names
        assert "InMemoryUserStore" in struct_names

        # Should find interface
        iface_names = {s.name for s in result.symbols if "interface" in s.tags}
        assert "UserRepository" in iface_names

        # Should find methods
        method_names = {s.name for s in result.symbols if s.type == NodeType.method}
        assert "GetAll" in method_names
        assert "Add" in method_names
        assert "Close" in method_names  # from UserService

    def test_extract_fixture_handlers(self):
        if not FIXTURES_GO.exists():
            pytest.skip("Go fixture project not found")
        ext = GoExtractor()
        handler_file = FIXTURES_GO / "handlers" / "user_handler.go"
        result = ext.extract(
            file_path=str(handler_file),
            project_root=str(FIXTURES_GO),
        )
        assert result.language_id == "go"
        func_names = {s.name for s in result.symbols if s.type == NodeType.function}
        assert "CreateUser" in func_names
        assert "UpdateUser" in func_names
        assert "validateUser" in func_names

    # ── Hertz fixture integration ───────────────────────────────────

    def test_extract_fixture_hertz_main(self):
        if not FIXTURES_HERTZ.exists():
            pytest.skip("Hertz fixture project not found")
        ext = GoExtractor()
        main_file = FIXTURES_HERTZ / "main.go"
        result = ext.extract(
            file_path=str(main_file),
            project_root=str(FIXTURES_HERTZ),
        )
        assert result.language_id == "go"
        assert len(result.symbols) > 0

        # Should find functions
        func_names = {s.name for s in result.symbols if s.type in (NodeType.function, NodeType.test)}
        assert "listUsers" in func_names
        assert "healthCheck" in func_names
        assert "authMiddleware" in func_names

        # Should find imports
        import_paths = {i.module_path for i in result.imports}
        assert "github.com/cloudwego/hertz/pkg/app/server" in import_paths
        assert "fmt" in import_paths

        # Should find Hertz routes
        route_symbols = [s for s in result.symbols if s.type == NodeType.route]
        assert len(route_symbols) > 0, "Should detect Hertz routes"

    def test_extract_fixture_hertz_models(self):
        if not FIXTURES_HERTZ.exists():
            pytest.skip("Hertz fixture project not found")
        ext = GoExtractor()
        models_file = FIXTURES_HERTZ / "models" / "user.go"
        result = ext.extract(
            file_path=str(models_file),
            project_root=str(FIXTURES_HERTZ),
        )
        assert result.language_id == "go"

        # Should find struct
        struct_names = {s.name for s in result.symbols if "struct" in s.tags}
        assert "User" in struct_names
        assert "InMemoryUserStore" in struct_names

        # Should find interface
        iface_names = {s.name for s in result.symbols if "interface" in s.tags}
        assert "UserRepository" in iface_names

        # Should find methods
        method_names = {s.name for s in result.symbols if s.type == NodeType.method}
        assert "GetAll" in method_names
        assert "Add" in method_names
        assert "Close" in method_names  # from UserService

    def test_extract_fixture_hertz_handlers(self):
        if not FIXTURES_HERTZ.exists():
            pytest.skip("Hertz fixture project not found")
        ext = GoExtractor()
        handler_file = FIXTURES_HERTZ / "handlers" / "user_handler.go"
        result = ext.extract(
            file_path=str(handler_file),
            project_root=str(FIXTURES_HERTZ),
        )
        assert result.language_id == "go"
        func_names = {s.name for s in result.symbols if s.type == NodeType.function}
        assert "CreateUser" in func_names
        assert "UpdateUser" in func_names
        assert "validateUser" in func_names
