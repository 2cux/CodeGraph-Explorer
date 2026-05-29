"""Graph builder that orchestrates indexing and constructs the code graph."""

from pathlib import Path

from codegraph.graph.models import GraphNode, GraphEdge, EdgeType, EdgeLocation, EdgeMetadata, NodeType, Resolution
from codegraph.graph.confidence import get_confidence
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
    test_edges = _build_test_relationships(all_nodes, all_edges, edge_counter)
    all_edges.extend(test_edges)
    all_edges = _deduplicate_edges(all_edges)
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


def _build_test_relationships(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    counter: list[int],
) -> list[GraphEdge]:
    """Generate ``tested_by`` edges from target symbols to their tests.

    Three strategies, in descending confidence order:

    1. **Direct calls** — a test function directly calls a target symbol.
       The ``calls`` edge already exists; this creates the reverse
       ``target --tested_by--> test`` edge (confidence 0.9).

    2. **Test name heuristic** — the test name contains a target symbol's
       name (e.g. ``test_login_success`` → ``login``). Uses
       ``test_name_heuristic`` resolution (confidence 0.65).

    3. **File name match** — the test file stem corresponds to a module
       name (e.g. ``test_auth.py`` → ``auth.py``). Uses
       ``attribute_guess`` resolution (confidence 0.55).
    """
    test_edges: list[GraphEdge] = []

    test_nodes = [n for n in nodes if n.type == NodeType.test]
    if not test_nodes:
        return test_edges

    # Build lookup tables from the full node set
    _callable_types = {NodeType.function, NodeType.method, NodeType.class_}
    name_to_ids: dict[str, list[str]] = {}
    for n in nodes:
        if n.type in _callable_types and not n.id.startswith("external:"):
            name_to_ids.setdefault(n.name, []).append(n.id)

    # File stem → symbols (for file-name matching)
    file_to_ids: dict[str, list[str]] = {}
    for n in nodes:
        if n.type in _callable_types and n.file_path:
            stem = n.file_path.rsplit("/", 1)[-1].replace(".py", "")
            file_to_ids.setdefault(stem, []).append(n.id)

    # Track which (target, test) pairs we've already covered to avoid
    # weaker strategies when a stronger one already produced an edge.
    covered: set[tuple[str, str]] = set()

    def _add_edge(target_id: str, test_id: str, confidence: float,
                  resolution: Resolution, reason: str = "",
                  evidence: dict | None = None) -> None:
        key = (target_id, test_id)
        if key in covered:
            return
        covered.add(key)
        test_edges.append(GraphEdge(
            id=_next_eid(counter),
            type=EdgeType.tested_by,
            source=target_id,
            target=test_id,
            confidence=confidence,
            metadata=EdgeMetadata(
                resolution=resolution,
                reason=reason,
                evidence=evidence,
            ),
        ))

    for test_node in test_nodes:
        # ── Strategy 1: Direct calls from test → target ──────────────
        for edge in edges:
            if edge.type != EdgeType.calls:
                continue
            if edge.source == test_node.id:
                target_node_id = edge.target
                if not target_node_id.startswith("external:"):
                    res = Resolution.direct_test_call
                    _add_edge(
                        target_node_id, test_node.id,
                        get_confidence(res), res,
                        reason=f"Test `{test_node.name}` directly calls this symbol.",
                        evidence={
                            "test_symbol": test_node.id,
                            "target_symbol": target_node_id,
                            "call_expr": edge.metadata.call_expr if edge.metadata else None,
                        },
                    )

        # ── Strategy 2: Name heuristic ───────────────────────────────
        test_name = test_node.name
        if test_name.startswith("test_"):
            remainder = test_name[len("test_"):]
            parts = remainder.split("_")
            for i in range(len(parts), 0, -1):
                candidate = "_".join(parts[:i])
                if candidate in name_to_ids:
                    for sym_id in name_to_ids[candidate]:
                        res = Resolution.test_name_heuristic
                        _add_edge(
                            sym_id, test_node.id,
                            get_confidence(res), res,
                            reason=f"Test name `{test_node.name}` contains symbol name `{candidate}`.",
                            evidence={
                                "test_name": test_node.name,
                                "matched_candidate": candidate,
                                "matched_symbol_id": sym_id,
                            },
                        )
                    break

        # ── Strategy 3: File name match ─────────────────────────────
        test_file = test_node.file_path
        if test_file:
            test_stem = test_file.rsplit("/", 1)[-1].replace(".py", "")
            for prefix in ("test_",):
                if test_stem.startswith(prefix):
                    module_stem = test_stem[len(prefix):]
                    if module_stem in file_to_ids:
                        for sym_id in file_to_ids[module_stem]:
                            res = Resolution.test_file_heuristic
                            _add_edge(
                                sym_id, test_node.id,
                                get_confidence(res), res,
                                reason=f"Test file `{test_file}` matches module `{module_stem}`.",
                                evidence={
                                    "test_file": test_file,
                                    "matched_module": module_stem,
                                },
                            )
                    break
            # Also try _test suffix
            if test_stem.endswith("_test"):
                module_stem = test_stem[:-len("_test")]
                if module_stem in file_to_ids:
                    for sym_id in file_to_ids[module_stem]:
                        res = Resolution.test_file_heuristic
                        _add_edge(
                            sym_id, test_node.id,
                            get_confidence(res), res,
                            reason=f"Test file `{test_file}` matches module `{module_stem}` via _test suffix.",
                            evidence={
                                "test_file": test_file,
                                "matched_module": module_stem,
                            },
                        )

    return test_edges


def _next_eid(counter: list[int]) -> str:
    counter[0] += 1
    return f"edge_{counter[0]:04d}"
