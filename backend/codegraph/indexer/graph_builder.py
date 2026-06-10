"""Graph builder that orchestrates indexing and constructs the code graph."""

from pathlib import Path
from typing import Any

from codegraph.graph.models import GraphNode, GraphEdge, EdgeType, EdgeLocation, EdgeMetadata, NodeType, Resolution
from codegraph.graph.confidence import get_confidence
from codegraph.indexer.scanner import scan_python_files, scan_supported_files, read_file, normalize_path
from codegraph.indexer.parser_python import parse_file
from codegraph.indexer.symbol_extractor import extract_symbols
from codegraph.indexer.call_extractor import extract_calls


def _rel_path(root: Path, path: Path) -> str:
    """Return path relative to root, using POSIX forward slashes."""
    return normalize_path(path.relative_to(root))


# File extensions supported by the multi-language pipeline.
# Used by _module_id to strip extensions when building module node IDs.
_SUPPORTED_EXTS: tuple[str, ...] = (
    '.py', '.pyi', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
    '.java', '.go', '.cs',
)


def _strip_ext(rel: str) -> str:
    """Remove a supported file extension from *rel*, if any."""
    for ext in _SUPPORTED_EXTS:
        if rel.endswith(ext):
            return rel[:-len(ext)]
    return rel


def _module_id(rel: str) -> str:
    """Build module node ID, e.g. ``module:app.api.auth``."""
    stem = _strip_ext(rel)
    stem = stem.removesuffix('/__init__')
    return f"module:{stem.replace('/', '.')}"


def build_index(root: Path) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Scan, parse, extract symbols and calls, and return the complete graph.

    Delegates to the multi-language :func:`build_index_v2` pipeline and adds
    structural edges (contains, defined_in, imports), test relationships,
    and external-edge resolution on top.

    Returns ``(nodes, edges)`` with structural relationships plus call edges.
    """
    # ── Multi-language extraction + cross-file resolution ──────────────
    nodes, edges = build_index_v2(root)

    if not nodes:
        return [], []

    # ── Post-processing: structural edges ──────────────────────────────
    # build_index_v2 produces nodes + call edges via language extractors
    # and resolvers.  We add structural edges (contains, defined_in,
    # imports) here because they are language-agnostic and work on the
    # full node set.
    edge_counter = [len(edges)]  # continue numbering after v2 edges
    struct_edges = _build_structural_edges_from_nodes(nodes, edge_counter)
    edges.extend(struct_edges)

    # ── Resolve external: prefix edges to internal node IDs ────────────
    edges = _resolve_external_edges(edges, nodes)

    # ── Build test relationships ───────────────────────────────────────
    test_edges = _build_test_relationships(nodes, edges, edge_counter)
    edges.extend(test_edges)

    # ── Final deduplication ────────────────────────────────────────────
    edges = _deduplicate_edges(edges)

    # ── Renumber IDs for global uniqueness ──────────────────────────────
    # Each language extractor uses its own counter, so node/edge IDs
    # from different files may collide (e.g. ``external:typing.Optional``
    # or ``edge_0001``).  SQLite INSERT OR REPLACE on id would silently
    # overwrite duplicates.  Renumber to guarantee unique IDs.
    nodes, edges = _renumber_ids(nodes, edges)

    return nodes, edges


def _renumber_ids(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Assign globally unique sequential IDs to nodes and edges.

    Merges duplicate node IDs (keeping the first occurrence) and
    renumbers all edges with ``edge_NNNN`` format.
    """
    # Deduplicate nodes by ID — keep first occurrence
    seen_ids: set[str] = set()
    unique_nodes: list[GraphNode] = []
    for node in nodes:
        if node.id not in seen_ids:
            seen_ids.add(node.id)
            unique_nodes.append(node)
    # (Drop duplicate nodes rather than renumbering them, since they
    #  represent the same symbol — e.g. external:typing.Optional.)

    # Renumber edges
    for i, edge in enumerate(edges):
        edge.id = f"edge_{i:04d}"

    return unique_nodes, edges


def _renumber_edge_ids(edges: list[GraphEdge]) -> list[GraphEdge]:
    """Renumber edge IDs for global uniqueness (convenience wrapper)."""
    return _renumber_ids([], edges)[1]


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

        # Phase 1: ensure language_id is set on all nodes
        for node in nodes:
            if not node.language_id or node.language_id == "python":
                node.language_id = "python"
            node.language = node.language_id

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


def _build_structural_edges_from_nodes(
    all_nodes: list[GraphNode],
    counter: list[int],
) -> list[GraphEdge]:
    """Generate structural edges (contains, defined_in, imports) for the
    full node set, grouped by file.

    This is the multi-language equivalent of the per-file structural edge
    generation in :func:`build_index_from_paths`.  It groups nodes by
    ``file_path`` and calls :func:`_build_structural_edges` for each group.
    """
    # Group nodes by file_path
    nodes_by_file: dict[str, list[GraphNode]] = {}
    for node in all_nodes:
        fp = node.file_path or ""
        if fp:
            nodes_by_file.setdefault(fp, []).append(node)

    all_struct_edges: list[GraphEdge] = []
    for rel, file_nodes in nodes_by_file.items():
        struct_edges = _build_structural_edges(file_nodes, rel, counter)
        all_struct_edges.extend(struct_edges)

    return all_struct_edges


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

    # Resolution types that should NOT be rewritten to internal node IDs.
    # These are low-confidence / name-only matches — rewriting them would
    # incorrectly upgrade a weak signal to look like a confirmed edge.
    _NO_REWRITE_RESOLUTIONS: set[Resolution] = {
        Resolution.name_match_candidate,
        Resolution.unknown_external,
        Resolution.external_symbol,
        Resolution.unresolved,
        Resolution.filename_heuristic,
        Resolution.docstring_reference,
    }

    for edge in edges:
        key = (edge.type.value if hasattr(edge.type, 'value') else str(edge.type))
        if key != "calls":
            continue
        if not edge.target.startswith("external:"):
            continue

        # Don't rewrite low-confidence edges — they must stay as external:
        edge_res = edge.metadata.resolution if edge.metadata else None
        if edge_res in _NO_REWRITE_RESOLUTIONS:
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


# ── Phase 1: Language abstraction pipeline ─────────────────────────────

# ── Extractor / Resolver factory ──────────────────────────────────────────
# Lazy-import per language so optional dependencies (e.g. tree-sitter)
# are only required when a file of that language is actually encountered.

_EXTRACTOR_FACTORIES: dict[str, Any] = {}
_RESOLVER_FACTORIES: dict[str, Any] = {}


def _get_extractor(lang_id: str) -> Any | None:
    """Return a :class:`LanguageExtractor` for *lang_id*, or ``None``."""
    if lang_id not in _EXTRACTOR_FACTORIES:
        if lang_id == "python":
            from codegraph.language_support.python.extractor import PythonExtractor
            _EXTRACTOR_FACTORIES[lang_id] = PythonExtractor()
        elif lang_id == "typescript":
            from codegraph.language_support.ts_js.extractor import TypeScriptExtractor
            _EXTRACTOR_FACTORIES[lang_id] = TypeScriptExtractor()
        elif lang_id == "javascript":
            from codegraph.language_support.ts_js.extractor import JavaScriptExtractor
            _EXTRACTOR_FACTORIES[lang_id] = JavaScriptExtractor()
        elif lang_id == "go":
            from codegraph.language_support.go.extractor import GoExtractor
            _EXTRACTOR_FACTORIES[lang_id] = GoExtractor()
        elif lang_id == "java":
            from codegraph.language_support.java.extractor import JavaExtractor
            _EXTRACTOR_FACTORIES[lang_id] = JavaExtractor()
        elif lang_id == "csharp":
            from codegraph.language_support.csharp.extractor import CSharpExtractor
            _EXTRACTOR_FACTORIES[lang_id] = CSharpExtractor()
        else:
            return None
    return _EXTRACTOR_FACTORIES[lang_id]


def _get_resolver(lang_id: str) -> Any | None:
    """Return a :class:`Resolver` for *lang_id*, or ``None``."""
    if lang_id not in _RESOLVER_FACTORIES:
        if lang_id == "python":
            from codegraph.language_support.python.resolver import PythonResolver
            _RESOLVER_FACTORIES[lang_id] = PythonResolver()
        elif lang_id == "typescript":
            from codegraph.language_support.ts_js.resolver import TypeScriptResolver
            _RESOLVER_FACTORIES[lang_id] = TypeScriptResolver()
        elif lang_id == "javascript":
            from codegraph.language_support.ts_js.resolver import JavaScriptResolver
            _RESOLVER_FACTORIES[lang_id] = JavaScriptResolver()
        elif lang_id == "go":
            from codegraph.language_support.go.resolver import GoResolver
            _RESOLVER_FACTORIES[lang_id] = GoResolver()
        elif lang_id == "java":
            from codegraph.language_support.java.resolver import JavaResolver
            _RESOLVER_FACTORIES[lang_id] = JavaResolver()
        elif lang_id == "csharp":
            from codegraph.language_support.csharp.resolver import CSharpResolver
            _RESOLVER_FACTORIES[lang_id] = CSharpResolver()
        else:
            return None
    return _RESOLVER_FACTORIES[lang_id]


def build_index_v2(root: Path) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Build the code graph using the language abstraction layer.

    Uses :class:`~codegraph.language_support.LanguageRegistry` to detect
    the language of each file, then routes to the appropriate extractor
    and resolver.

    Supported languages (Phase 2):
    - Python (.py, .pyi) — production
    - TypeScript (.ts, .tsx) — beta
    - JavaScript (.js, .jsx, .mjs, .cjs) — beta

    Unsupported files are skipped without error.  Parser errors are captured
    as diagnostics and do not fail the index.
    """
    from codegraph.language_support.registry import get_registry

    registry = get_registry()

    # Scan for all supported files (not just .py)
    files = scan_supported_files(root, registry)

    if not files:
        return [], []

    # Phase 1a: Per-file extraction, grouped by language
    extractor_results_by_lang: dict[str, list[Any]] = {}
    all_nodes: list[GraphNode] = []
    all_edges: list[GraphEdge] = []

    for path in files:
        rel = _rel_path(root, path)

        lang_id = registry.detect(rel)
        if lang_id is None:
            continue

        extractor = _get_extractor(lang_id)
        if extractor is None:
            continue

        try:
            result = extractor.extract(
                file_path=str(path),
                project_root=str(root),
            )
        except Exception:
            # A single broken extractor must not fail the whole index
            continue

        extractor_results_by_lang.setdefault(lang_id, []).append(result)
        all_nodes.extend(result.symbols)
        if hasattr(result, '_raw_edges'):
            all_edges.extend(result._raw_edges)

    # Phase 1b: Cross-file resolution per language
    for lang_id, results in extractor_results_by_lang.items():
        resolver = _get_resolver(lang_id)
        if resolver is None:
            continue
        try:
            resolved = resolver.resolve(results)
            all_edges = _merge_resolved_edges(all_edges, resolved)
        except Exception:
            continue

    # Deduplicate
    all_edges = _deduplicate_edges(all_edges)

    return all_nodes, all_edges


def _merge_resolved_edges(
    raw_edges: list[GraphEdge],
    resolved: Any,  # ResolvedEdges
) -> list[GraphEdge]:
    """Merge resolved confirmed edges into the raw edge set.

    Existing raw edges (from extractors) are preserved. Resolved confirmed
    edges that add provenance information are added or replace their
    raw equivalents.
    """
    from codegraph.language_support.resolver import Provenance

    # Build lookup for existing edges
    edge_keys: dict[tuple[str, str, str], GraphEdge] = {}
    for e in raw_edges:
        key = (e.source, e.target, e.type.value if hasattr(e.type, 'value') else str(e.type))
        edge_keys[key] = e

    # Apply provenance from confirmed resolved edges
    for re in resolved.confirmed:
        key = (re.source, re.target, re.edge_type.value if hasattr(re.edge_type, 'value') else str(re.edge_type))
        if key in edge_keys:
            existing = edge_keys[key]
            # Add resolved metadata to existing edge.
            existing.confidence = max(existing.confidence, re.confidence)
            existing.metadata = EdgeMetadata(
                resolution=re.resolution,
                provenance=re.provenance.value if hasattr(re.provenance, 'value') else str(re.provenance),
                evidence=re.evidence,
                reason=existing.metadata.reason if existing.metadata else None,
                call_expr=existing.metadata.call_expr if existing.metadata else None,
                is_dynamic=existing.metadata.is_dynamic if existing.metadata else False,
            )
            if re.source_location:
                existing.source_location = EdgeLocation(
                    file_path=re.source_location.get("file_path", ""),
                    line_start=re.source_location.get("line_start", 0),
                    line_end=re.source_location.get("line_end", re.source_location.get("line_start", 0)),
                )
        else:
            # New confirmed edge — create GraphEdge
            edge_id = f"edge_resolved_{len(raw_edges):04d}"
            meta = EdgeMetadata(
                resolution=re.resolution,
                provenance=re.provenance.value if hasattr(re.provenance, 'value') else str(re.provenance),
                evidence=re.evidence,
            )
            raw_edges.append(GraphEdge(
                id=edge_id,
                type=re.edge_type,
                source=re.source,
                target=re.target,
                confidence=re.confidence,
                source_location=(
                    EdgeLocation(
                        file_path=re.source_location.get("file_path", ""),
                        line_start=re.source_location.get("line_start", 0),
                        line_end=re.source_location.get("line_end", re.source_location.get("line_start", 0)),
                    )
                    if re.source_location else None
                ),
                metadata=meta,
            ))

    return raw_edges
