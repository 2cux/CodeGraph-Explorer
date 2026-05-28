"""Graph builder that orchestrates indexing and constructs the code graph."""

from pathlib import Path

from codegraph.graph.models import GraphNode, GraphEdge, EdgeType, EdgeLocation, EdgeMetadata, NodeType, Resolution
from codegraph.indexer.scanner import scan_python_files, read_file
from codegraph.indexer.parser_python import parse_file
from codegraph.indexer.symbol_extractor import extract_symbols
from codegraph.indexer.call_extractor import extract_calls


def _rel_path(root: Path, path: Path) -> str:
    """Return path relative to root, using forward slashes."""
    return path.relative_to(root).as_posix()


def _module_id(rel: str) -> str:
    """Build module node ID, e.g. ``module:app.api.auth``."""
    return f"module:{rel.removesuffix('.py').removesuffix('/__init__').replace('/', '.')}"


def build_index(root: Path) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Scan, parse, extract symbols and calls, and return the complete graph.

    Returns ``(nodes, edges)`` with structural relationships
    (contains, defined_in, imports) plus call edges.
    """
    files = scan_python_files(root)
    return build_index_from_paths(root, files)


def _deduplicate_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    """Remove duplicate edges sharing the same (source, target, type)."""
    seen: set[tuple[str, str, str]] = set()
    result: list[GraphEdge] = []
    for e in edges:
        key = (e.source, e.target, e.type.value if hasattr(e.type, 'value') else str(e.type))
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


def build_index_from_paths(root: Path, paths: list[Path]) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Build index from a pre-discovered list of file paths."""
    all_nodes: list[GraphNode] = []
    all_edges: list[GraphEdge] = []
    edge_counter = [0]  # mutable counter for edge IDs — shared across all files

    for path in paths:
        rel = _rel_path(root, path)
        tree = parse_file(path)
        nodes = extract_symbols(rel, tree)
        call_edges = extract_calls(tree, path, rel_path=rel, edge_counter=edge_counter)

        all_nodes.extend(nodes)
        all_edges.extend(call_edges)

        # Add structural edges for this file
        struct_edges = _build_structural_edges(nodes, rel, edge_counter)
        all_edges.extend(struct_edges)

    all_edges = _deduplicate_edges(all_edges)
    all_edges = _resolve_external_edges(all_edges, all_nodes)
    return all_nodes, all_edges


def _build_structural_edges(
    nodes: list[GraphNode],
    rel: str,
    counter: list[int],
) -> list[GraphEdge]:
    """Build contains / defined_in / imports / inherits edges for a single file's nodes."""
    edges: list[GraphEdge] = []
    file_id = rel
    module_id = _module_id(rel)

    # Track what we've found
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
            # Find parent class from qualified_name
            parts = node.qualified_name.split(".")
            if len(parts) >= 2:
                parent_class = parts[-2]
                if parent_class in class_methods:
                    class_methods[parent_class].append(node)
        elif node.type.value in ("function", "test"):
            function_nodes.append(node)
        elif node.type.value in ("import", "external_symbol"):
            import_nodes.append(node)

    # ── file / module contains ─────────────────────────────────────
    for fn in function_nodes:
        edges.append(_contains_edge(file_id, fn.id, counter))
    for cls_node in class_nodes.values():
        edges.append(_contains_edge(file_id, cls_node.id, counter))

    # class contains method
    for cls_name, methods in class_methods.items():
        cls_id = class_nodes[cls_name].id
        for m in methods:
            edges.append(_contains_edge(cls_id, m.id, counter))

    # ── defined_in ─────────────────────────────────────────────────
    for fn in function_nodes:
        edges.append(_defined_in_edge(fn.id, module_id, file_id, counter))
    for cls_node in class_nodes.values():
        edges.append(_defined_in_edge(cls_node.id, module_id, file_id, counter))
    for m in method_nodes:
        edges.append(_defined_in_edge(m.id, module_id, file_id, counter))

    # ── imports ────────────────────────────────────────────────────
    for imp in import_nodes:
        loc_line = imp.location.line_start if imp.location else 0
        edges.append(GraphEdge(
            id=_next_eid(counter),
            type=EdgeType.imports,
            source=file_id,
            target=imp.id,
            confidence=1.0,
            source_location=EdgeLocation(
                file_path=rel,
                line_start=loc_line,
                line_end=loc_line,
            ),
            metadata=EdgeMetadata(
                resolution=Resolution.exact_ast_match,
            ),
        ))

    return edges


def _contains_edge(parent_id: str, child_id: str, counter: list[int]) -> GraphEdge:
    return GraphEdge(
        id=_next_eid(counter),
        type=EdgeType.contains,
        source=parent_id,
        target=child_id,
        confidence=1.0,
        metadata=EdgeMetadata(resolution=Resolution.exact_ast_match),
    )


def _defined_in_edge(node_id: str, module_id: str, file_id: str, counter: list[int]) -> GraphEdge:
    return GraphEdge(
        id=_next_eid(counter),
        type=EdgeType.defined_in,
        source=node_id,
        target=module_id,
        confidence=1.0,
        metadata=EdgeMetadata(resolution=Resolution.exact_ast_match),
    )


def _resolve_external_edges(edges: list[GraphEdge], nodes: list[GraphNode]) -> list[GraphEdge]:
    """Post-process edges to map ``external:module.qualname`` targets to real node IDs.

    The call extractor can only resolve cross-file calls to ``external:module.symbol``
    because it doesn't know the file path for imported symbols at parse time.
    After all nodes are collected, this step builds a qualified_name → node.id
    lookup table and rewrites matching external targets.

    Genuinely external symbols (stdlib, third-party) that don't appear in the
    project's node set keep their ``external:`` prefix.
    """
    # Build qualified_name → node.id lookup (only for project-internal nodes)
    # Prefer function/class/method nodes over import/proxy nodes. Import nodes
    # share the same qualified_name as the symbol they import but must not
    # shadow the real definition.
    _TYPE_PRIORITY = {
        NodeType.import_: 0,
        NodeType.external_symbol: 0,
        NodeType.module: 1,
        NodeType.file: 1,
        NodeType.method: 3,
        NodeType.function: 3,
        NodeType.class_: 3,
        NodeType.test: 3,
        NodeType.repository: 0,
    }
    qual_to_id: dict[str, str] = {}
    qual_type: dict[str, NodeType] = {}
    for node in nodes:
        if node.qualified_name and not node.id.startswith("external:"):
            prev = qual_type.get(node.qualified_name)
            new_prio = _TYPE_PRIORITY.get(node.type, 0)
            prev_prio = _TYPE_PRIORITY.get(prev, -1) if prev else -1
            if prev is None or new_prio > prev_prio:
                qual_to_id[node.qualified_name] = node.id
                qual_type[node.qualified_name] = node.type

    for edge in edges:
        key = (edge.type.value if hasattr(edge.type, 'value') else str(edge.type))
        if key != "calls":
            continue
        if not edge.target.startswith("external:"):
            continue

        qual_name = edge.target[len("external:"):]
        if qual_name in qual_to_id:
            edge.target = qual_to_id[qual_name]

    return edges


def _next_eid(counter: list[int]) -> str:
    counter[0] += 1
    return f"edge_{counter[0]:04d}"
