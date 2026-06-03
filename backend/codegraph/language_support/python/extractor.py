"""Python language extractor — wraps existing AST-based extraction.

Produces :class:`ExtractorResult` with the same symbols, call edges,
and structural edges as the current ``build_index_from_paths`` per-file
pipeline.  No semantic changes — only adds ``language_id`` / ``framework_id``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from codegraph.language_support.extractor import (
    LanguageExtractor,
    ExtractorResult,
    ImportInfo,
    ExportInfo,
    CallEdge,
    RefEdge,
    RouteInfo,
    TestInfo,
    ConfigInfo,
    Diagnostic,
)

from codegraph.graph.models import (
    GraphNode,
    GraphEdge,
    EdgeType,
    EdgeLocation,
    EdgeMetadata,
    NodeType,
    Resolution,
)
from codegraph.graph.confidence import get_confidence
from codegraph.indexer.scanner import normalize_path
from codegraph.indexer.symbol_extractor import extract_symbols
from codegraph.indexer.call_extractor import extract_calls


# ── Helpers (mirror graph_builder) ─────────────────────────────────────

def _module_id(rel: str) -> str:
    """Build module node ID, e.g. ``module:app.api.auth``."""
    return f"module:{rel.removesuffix('.py').removesuffix('/__init__').replace('/', '.')}"


def _next_eid(counter: list[int]) -> str:
    counter[0] += 1
    return f"edge_{counter[0]:04d}"


def _contains_edge(parent_id: str, child_id: str, counter: list[int]) -> GraphEdge:
    res = Resolution.exact_ast_match
    return GraphEdge(
        id=_next_eid(counter),
        type=EdgeType.contains,
        source=parent_id,
        target=child_id,
        confidence=get_confidence(res),
        metadata=EdgeMetadata(
            resolution=res,
            reason=f"`{parent_id}` contains `{child_id}`.",
        ),
    )


def _defined_in_edge(node_id: str, module_id: str, file_id: str, counter: list[int]) -> GraphEdge:
    res = Resolution.exact_ast_match
    return GraphEdge(
        id=_next_eid(counter),
        type=EdgeType.defined_in,
        source=node_id,
        target=module_id,
        confidence=get_confidence(res),
        metadata=EdgeMetadata(
            resolution=res,
            reason=f"`{node_id}` is defined in `{module_id}`.",
        ),
    )


def _build_structural_edges(
    nodes: list[GraphNode],
    rel: str,
    counter: list[int],
) -> list[GraphEdge]:
    """Build contains / defined_in / imports edges for a single file's nodes."""
    edges: list[GraphEdge] = []
    file_id = rel
    mod_id = _module_id(rel)

    class_nodes: dict[str, GraphNode] = {}
    method_nodes: list[GraphNode] = []
    function_nodes: list[GraphNode] = []
    import_nodes: list[GraphNode] = []
    class_methods: dict[str, list[GraphNode]] = {}

    for node in nodes:
        if node.type.value == "class":
            class_nodes[node.name] = node
            class_methods[node.name] = []
        elif node.type.value == "method":
            method_nodes.append(node)
            parts = node.qualified_name.split(".")
            if len(parts) >= 2:
                parent_class = parts[-2]
                if parent_class in class_methods:
                    class_methods[parent_class].append(node)
        elif node.type.value in ("function", "test"):
            function_nodes.append(node)
        elif node.type.value in ("import", "external_symbol"):
            import_nodes.append(node)

    # file / module contains
    for fn in function_nodes:
        edges.append(_contains_edge(file_id, fn.id, counter))
    for cls_node in class_nodes.values():
        edges.append(_contains_edge(file_id, cls_node.id, counter))

    # class contains method
    for cls_name, methods in class_methods.items():
        cls_id = class_nodes[cls_name].id
        for m in methods:
            edges.append(_contains_edge(cls_id, m.id, counter))

    # defined_in
    for fn in function_nodes:
        edges.append(_defined_in_edge(fn.id, mod_id, file_id, counter))
    for cls_node in class_nodes.values():
        edges.append(_defined_in_edge(cls_node.id, mod_id, file_id, counter))
    for m in method_nodes:
        edges.append(_defined_in_edge(m.id, mod_id, file_id, counter))

    # imports
    for imp in import_nodes:
        loc_line = imp.location.line_start if imp.location else 0
        res = Resolution.exact_ast_match
        edges.append(GraphEdge(
            id=_next_eid(counter),
            type=EdgeType.imports,
            source=file_id,
            target=imp.id,
            confidence=get_confidence(res),
            source_location=EdgeLocation(
                file_path=rel,
                line_start=loc_line,
                line_end=loc_line,
            ),
            metadata=EdgeMetadata(
                resolution=res,
                reason=f"File imports `{imp.qualified_name}`.",
                evidence={
                    "imported_symbol": imp.qualified_name,
                    "local_name": imp.name,
                },
            ),
        ))

    return edges


# ── Extractor ───────────────────────────────────────────────────────────

class PythonExtractor(LanguageExtractor):
    """Python language extractor using the built-in ``ast`` module.

    Delegates to the existing :mod:`codegraph.indexer` pipeline:
    ``parse_file`` → ``extract_symbols`` → ``extract_calls`` →
    ``_build_structural_edges``.

    Output is identical to the current per-file processing in
    :func:`codegraph.indexer.graph_builder.build_index_from_paths`,
    with the addition of ``language_id`` and ``framework_id`` on
    every symbol.
    """

    language_id = "python"

    def extract(self, file_path: str, content: str | None = None,
                project_root: str | None = None,
                config: dict[str, Any] | None = None) -> ExtractorResult:
        """Extract symbols and edges from a single Python file.

        Args:
            file_path: Path to the ``.py`` file.
            content: File source. If ``None``, reads from disk.
            project_root: Root directory for relative-path computation.
            config: Unused for Python (reserved for future use).

        Returns:
            :class:`ExtractorResult` with symbols and intra-file edges.
        """
        path = Path(file_path)
        root = Path(project_root) if project_root else None

        # Relative path for node IDs
        if root:
            rel = normalize_path(path.relative_to(root))
        else:
            rel = normalize_path(path)

        # Parse (handle optional content override)
        if content is not None:
            source = content
        else:
            source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        nodes = extract_symbols(rel, tree)

        # Set language_id and support_level on all nodes
        for node in nodes:
            node.language = self.language_id
            node.language_id = self.language_id
            node.support_level = "production"

        # Extract call edges (intra-file + pending cross-file)
        edge_counter = [0]
        call_edges = extract_calls(tree, path, rel_path=rel, edge_counter=edge_counter)

        # Build structural edges
        struct_edges = _build_structural_edges(nodes, rel, edge_counter)

        # Collect all edges (calls + structural)
        all_edges = call_edges + struct_edges

        # Populate structured sub-results from the extracted data
        imports = self._collect_imports(nodes)
        exports = self._collect_exports(nodes)
        routes = self._collect_routes(nodes)
        tests = self._collect_tests(nodes)
        configs = self._collect_configs(nodes)

        result = ExtractorResult(
            language_id=self.language_id,
            file_path=rel,
            symbols=nodes,
            imports=imports,
            exports=exports,
            routes=routes,
            tests=tests,
            configs=configs,
        )

        # Attach raw edges for the resolver (internal transport, not part of
        # the ExtractorResult schema).
        result._raw_edges = all_edges  # type: ignore[attr-defined]

        return result

    # ── Structured sub-result collectors ──────────────────────────────

    def _collect_imports(self, nodes: list[GraphNode]) -> list[ImportInfo]:
        result: list[ImportInfo] = []
        for node in nodes:
            if node.type in (NodeType.import_, NodeType.external_symbol):
                is_ext = node.type == NodeType.external_symbol or node.id.startswith("external:")
                name = node.name
                module = node.module or ""
                result.append(ImportInfo(
                    local_name=name,
                    module_path=module,
                    imported_name=node.qualified_name if node.qualified_name else None,
                    is_external=is_ext,
                    line=node.location.line_start if node.location else 0,
                ))
        return result

    def _collect_exports(self, nodes: list[GraphNode]) -> list[ExportInfo]:
        result: list[ExportInfo] = []
        exported_types = {NodeType.function, NodeType.method, NodeType.class_, NodeType.test}
        for node in nodes:
            if node.type in exported_types and node.visibility == "public":
                result.append(ExportInfo(
                    name=node.name,
                    node_id=node.id,
                ))
        return result

    def _collect_routes(self, nodes: list[GraphNode]) -> list[RouteInfo]:
        result: list[RouteInfo] = []
        for node in nodes:
            if "route" in node.tags and node.metadata:
                route_meta = node.metadata.get("route")
                if route_meta:
                    result.append(RouteInfo(
                        framework=route_meta.get("framework", "unknown"),
                        method=route_meta.get("method", "GET"),
                        path=route_meta.get("path", "/"),
                        handler_node_id=node.id,
                    ))
        return result

    def _collect_tests(self, nodes: list[GraphNode]) -> list[TestInfo]:
        result: list[TestInfo] = []
        for node in nodes:
            if node.type == NodeType.test or "test" in node.tags:
                test_type = "class" if node.type == NodeType.class_ else "function"
                if node.type == NodeType.method:
                    test_type = "method"
                result.append(TestInfo(
                    node_id=node.id,
                    test_type=test_type,
                ))
        return result

    def _collect_configs(self, nodes: list[GraphNode]) -> list[ConfigInfo]:
        result: list[ConfigInfo] = []
        for node in nodes:
            if "config" in node.tags or "settings" in node.tags:
                ctype = "constant" if node.type == NodeType.function else "class"
                result.append(ConfigInfo(
                    node_id=node.id,
                    config_type=ctype,
                ))
        return result
