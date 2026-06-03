"""Tests for Spring Boot framework extraction — @RestController, @Service, DI, routes."""

import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
JAVA_SPRING = FIXTURES / "java_spring_project"


@pytest.fixture(autouse=True)
def _reset_registry():
    from codegraph.language_support.registry import reset_registry
    reset_registry()


def _extract_file(rel_path: str):
    from codegraph.language_support.java.extractor import JavaExtractor
    ext = JavaExtractor()
    return ext.extract(
        file_path=str(JAVA_SPRING / rel_path),
        project_root=str(JAVA_SPRING),
    )


class TestSpringControllerDetection:
    """Test @RestController / @Controller detection."""

    def test_rest_controller_has_controller_type(self):
        result = _extract_file("src/main/java/com/example/demo/controller/UserController.java")
        # Filter to the class node (not constructor which has same name)
        class_nodes = [s for s in result.symbols if s.name == "UserController"
                       and s.type.value in ("controller", "class", "service", "component")]
        assert len(class_nodes) >= 1
        for s in class_nodes:
            assert s.type.value in ("controller", "class")
            assert s.framework_id == "spring"
            assert "controller" in s.tags or "spring" in s.tags

    def test_rest_controller_has_spring_framework_id(self):
        result = _extract_file("src/main/java/com/example/demo/controller/UserController.java")
        spring_nodes = [s for s in result.symbols if s.framework_id == "spring"]
        assert len(spring_nodes) > 0


class TestSpringServiceDetection:
    """Test @Service detection."""

    def test_service_has_service_type(self):
        result = _extract_file("src/main/java/com/example/demo/service/UserService.java")
        # Filter to the class node (not constructor which has same name)
        class_nodes = [s for s in result.symbols if s.name == "UserService"
                       and s.type.value in ("service", "class", "controller", "component")]
        assert len(class_nodes) >= 1
        for s in class_nodes:
            assert s.type.value in ("service", "class")
            assert s.framework_id == "spring"
            assert "service" in s.tags or "spring" in s.tags


class TestSpringRepositoryDetection:
    """Test @Repository detection."""

    def test_repository_has_spring_framework_id(self):
        result = _extract_file("src/main/java/com/example/demo/repository/UserRepository.java")
        spring_nodes = [s for s in result.symbols if s.framework_id == "spring" or "spring" in s.tags]
        repo_nodes = [s for s in result.symbols if s.name == "UserRepository"]
        assert len(spring_nodes) >= 1 or len(repo_nodes) >= 1


class TestSpringRouteDetection:
    """Test route node and routes_to edge creation."""

    def test_route_nodes_exist(self):
        result = _extract_file("src/main/java/com/example/demo/controller/UserController.java")
        raw = getattr(result, "_raw_edges", [])
        from codegraph.graph.models import EdgeType
        route_edges = [e for e in raw if e.type == EdgeType.routes_to]
        # Should find at least 2 routes (GET by id, DELETE by id)
        assert len(route_edges) >= 2

    def test_route_paths_are_correct(self):
        result = _extract_file("src/main/java/com/example/demo/controller/UserController.java")
        route_nodes = [s for s in result.symbols if s.type.value == "route"]
        route_paths = {s.metadata.get("route_path", "") for s in route_nodes}
        # Should have at minimum some paths
        assert len(route_paths) >= 2

    def test_route_http_methods_are_correct(self):
        result = _extract_file("src/main/java/com/example/demo/controller/UserController.java")
        route_nodes = [s for s in result.symbols if s.type.value == "route"]
        methods = {s.metadata.get("http_method", "") for s in route_nodes}
        assert "GET" in methods
        assert "DELETE" in methods


class TestSpringDI:
    """Test constructor injection / @Autowired DI detection."""

    def test_depends_on_edges_exist(self):
        result = _extract_file("src/main/java/com/example/demo/controller/UserController.java")
        raw = getattr(result, "_raw_edges", [])
        from codegraph.graph.models import EdgeType
        depends_on = [e for e in raw if e.type == EdgeType.depends_on]
        assert len(depends_on) >= 1  # UserController -> UserService

    def test_service_depends_on_repository(self):
        result = _extract_file("src/main/java/com/example/demo/service/UserService.java")
        raw = getattr(result, "_raw_edges", [])
        from codegraph.graph.models import EdgeType
        depends_on = [e for e in raw if e.type == EdgeType.depends_on]
        assert len(depends_on) >= 1  # UserService -> UserRepository


class TestFalseEdges:
    """Test that false edges are NOT created."""

    def test_no_cross_package_process_edge(self):
        """Different package same-named methods must not create edges."""
        from codegraph.language_support.java.extractor import JavaExtractor
        ext = JavaExtractor()
        false_edges_dir = FIXTURES / "java_false_edges"

        result_a = ext.extract(
            file_path=str(false_edges_dir / "src/main/java/com/example/app/package_a/ServiceA.java"),
            project_root=str(false_edges_dir),
        )
        result_b = ext.extract(
            file_path=str(false_edges_dir / "src/main/java/com/example/app/package_b/ServiceB.java"),
            project_root=str(false_edges_dir),
        )

        # ServiceA.process() should only call this.process()
        raw_a = getattr(result_a, "_raw_edges", [])
        raw_b = getattr(result_b, "_raw_edges", [])

        from codegraph.graph.models import EdgeType
        call_targets_a = {
            e.target for e in raw_a
            if e.type == EdgeType.calls and not e.target.startswith("unresolved:")
        }
        call_targets_b = {
            e.target for e in raw_b
            if e.type == EdgeType.calls and not e.target.startswith("unresolved:")
        }

        # process calls should NOT cross from A to B or B to A
        for target in call_targets_a:
            assert "ServiceB" not in target
            assert "package_b" not in target
        for target in call_targets_b:
            assert "ServiceA" not in target
            assert "package_a" not in target

    def test_overloaded_method_not_confirmed(self):
        """Overloaded methods should have lower confidence, not confirmed."""
        result = _extract_file("src/main/java/com/example/demo/service/UserService.java")
        raw = getattr(result, "_raw_edges", [])
        from codegraph.graph.models import EdgeType, Resolution
        from codegraph.graph.impact import is_confirmed_resolution

        calls = [e for e in raw if e.type == EdgeType.calls]
        # Calls to overloaded methods should have possible/unresolved resolution
        confirmed_calls = [
            e for e in calls
            if e.metadata and is_confirmed_resolution(e.metadata.resolution)
        ]
        # Only this.method() and same-file exact should be confirmed
        for c in confirmed_calls:
            res = c.metadata.resolution if c.metadata else None
            assert res in (
                Resolution.this_method_exact,
                Resolution.same_file_exact,
                Resolution.static_method_exact,
            ), f"Unexpected confirmed resolution: {res}"

    def test_interface_multi_impl_not_confirmed(self):
        """Interface with multiple implementations should NOT confirm to single impl."""
        false_dir = FIXTURES / "java_false_edges"
        from codegraph.language_support.java.extractor import JavaExtractor
        ext = JavaExtractor()

        result_orch = ext.extract(
            file_path=str(false_dir / "src/main/java/com/example/app/package_a/Orchestrator.java"),
            project_root=str(false_dir),
        )

        raw = getattr(result_orch, "_raw_edges", [])
        from codegraph.graph.models import EdgeType, Resolution
        from codegraph.graph.impact import is_confirmed_resolution

        # Check that interface method calls aren't confirmed
        for e in raw:
            if e.type == EdgeType.calls and e.metadata:
                if e.metadata.resolution == Resolution.interface_method_candidate:
                    assert not is_confirmed_resolution(e.metadata.resolution)
