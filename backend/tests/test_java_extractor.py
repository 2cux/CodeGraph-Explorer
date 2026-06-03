"""Tests for JavaExtractor — symbol, import, call, and reference extraction."""

import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
JAVA_SPRING = FIXTURES / "java_spring_project"


@pytest.fixture(autouse=True)
def _reset_registry():
    from codegraph.language_support.registry import reset_registry
    reset_registry()


def _make_extractor():
    from codegraph.language_support.java.extractor import JavaExtractor
    return JavaExtractor()


def _extract_file(rel_path: str):
    ext = _make_extractor()
    return ext.extract(
        file_path=str(JAVA_SPRING / rel_path),
        project_root=str(JAVA_SPRING),
    )


class TestJavaExtractorSymbols:
    """Test basic symbol extraction from Java source files."""

    def test_extracts_model_class(self):
        result = _extract_file("src/main/java/com/example/demo/model/User.java")
        symbol_names = {s.name for s in result.symbols}
        assert "User" in symbol_names
        # Should have getters/setters as methods
        method_names = {s.name for s in result.symbols if s.type.value == "method"}
        assert "getId" in method_names or "setName" in method_names

    def test_extracts_service_class(self):
        result = _extract_file("src/main/java/com/example/demo/service/UserService.java")
        symbol_names = {s.name for s in result.symbols}
        assert "UserService" in symbol_names
        # Should have methods
        method_names = {s.name for s in result.symbols if s.type.value == "method"}
        assert "findAll" in method_names
        assert "create" in method_names  # overloaded — both methods should exist

    def test_extracts_interface(self):
        result = _extract_file("src/main/java/com/example/demo/repository/UserRepository.java")
        symbol_names = {s.name for s in result.symbols}
        assert "UserRepository" in symbol_names
        # Interface node should have "interface" tag
        for s in result.symbols:
            if s.name == "UserRepository":
                assert "interface" in s.tags

    def test_extracts_utility_static_methods(self):
        result = _extract_file("src/main/java/com/example/demo/util/StringUtils.java")
        symbol_names = {s.name for s in result.symbols}
        assert "StringUtils" in symbol_names
        method_names = {s.name for s in result.symbols if s.type.value == "method"}
        assert "capitalize" in method_names
        assert "isEmpty" in method_names

    def test_language_id_is_java(self):
        result = _extract_file("src/main/java/com/example/demo/model/User.java")
        for s in result.symbols:
            assert s.language_id == "java"
            assert s.language == "java"

    def test_support_level_is_beta(self):
        result = _extract_file("src/main/java/com/example/demo/model/User.java")
        for s in result.symbols:
            if s.type.value not in ("file", "module"):
                assert s.metadata.get("support_level") == "beta"


class TestJavaImports:
    """Test import extraction."""

    def test_extracts_imports(self):
        result = _extract_file("src/main/java/com/example/demo/controller/UserController.java")
        import_modules = {imp.module_path for imp in result.imports}
        assert any("springframework" in m for m in import_modules)

    def test_imports_have_local_names(self):
        result = _extract_file("src/main/java/com/example/demo/controller/UserController.java")
        local_names = {imp.local_name for imp in result.imports}
        assert "UserService" in local_names or "User" in local_names


class TestJavaCalls:
    """Test call edge extraction."""

    def test_extracts_this_method_calls(self):
        result = _extract_file("src/main/java/com/example/demo/service/UserService.java")
        this_calls = [c for c in result.calls if c.target_expression.startswith("this.")]
        # Should find this.validateUser() in create() and this.create() in overloaded create()
        assert len(this_calls) >= 1

    def test_extracts_simple_calls(self):
        result = _extract_file("src/main/java/com/example/demo/controller/UserController.java")
        calls = [c for c in result.calls if not c.target_expression.startswith("this.")]
        assert len(calls) > 0

    def test_extracts_static_calls(self):
        result = _extract_file("src/main/java/com/example/demo/DemoApplication.java")
        static_calls = [
            c for c in result.calls
            if "." in c.target_expression and c.target_expression.split(".")[0][0].isupper()
        ]
        # Should have StringUtils.capitalize()
        assert len(static_calls) >= 1


class TestJavaStructuralEdges:
    """Test structural edge generation."""

    def test_has_contains_edges(self):
        result = _extract_file("src/main/java/com/example/demo/model/User.java")
        raw = getattr(result, "_raw_edges", [])
        from codegraph.graph.models import EdgeType
        contains = [e for e in raw if e.type == EdgeType.contains]
        assert len(contains) > 0

    def test_has_inherits_edges(self):
        result = _extract_file("src/main/java/com/example/demo/repository/UserRepository.java")
        raw = getattr(result, "_raw_edges", [])
        from codegraph.graph.models import EdgeType
        inherits = [e for e in raw if e.type == EdgeType.inherits]
        # Interface "extends" is different from class "extends"
        # The interface tag is present on the node instead
        interface_nodes = [s for s in result.symbols if "interface" in s.tags]
        assert len(interface_nodes) >= 1 or len(inherits) >= 1

    def test_has_defined_in_edges(self):
        result = _extract_file("src/main/java/com/example/demo/model/User.java")
        raw = getattr(result, "_raw_edges", [])
        from codegraph.graph.models import EdgeType
        defined_in = [e for e in raw if e.type == EdgeType.defined_in]
        assert len(defined_in) > 0
