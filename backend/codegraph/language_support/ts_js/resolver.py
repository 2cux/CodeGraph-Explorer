"""TypeScript / JavaScript cross-file Resolver.

Resolves import paths, rewrites external targets to internal node IDs,
classifies edges into confirmed / possible / unresolved tiers, and
builds ``tested_by`` relationships.

Implements the ``Resolver`` interface defined in
``codegraph.language_support.resolver``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from codegraph.graph.models import (
    GraphNode,
    GraphEdge,
    EdgeType,
    Resolution,
    EdgeMetadata,
    NodeType,
)
from codegraph.graph.impact import (
    is_confirmed_resolution,
    is_possible_resolution,
    is_unresolved_resolution,
)
from codegraph.language_support.resolver import (
    Resolver,
    ResolvedEdge,
    ResolvedEdges,
    GraphContext,
    Provenance,
)
from codegraph.language_support.extractor import ExtractorResult, ImportInfo, CallEdge

# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_INDEX_FILES = tuple(f"/index{ext}" for ext in _TS_EXTENSIONS)


def _resolve_relative_import(
    from_file: str, import_path: str, project_root: str, all_files: list[str]
) -> str | None:
    """Resolve a relative import path to a concrete file.

    Args:
        from_file: e.g. ``src/components/Button.tsx``
        import_path: e.g. ``./utils/helpers`` or ``../types``
        project_root: absolute project root
        all_files: list of relative file paths in the project

    Returns the resolved relative file path, or ``None``.
    """
    from_dir = Path(from_file).parent.as_posix()

    # Normalize: join, then resolve parent references (..)
    joined = os.path.normpath(f"{from_dir}/{import_path}").replace("\\", "/")

    # Prevent traversal outside project
    if joined.startswith(".."):
        return None

    # Try exact match first
    if joined in all_files:
        return joined

    # Try extensionless → try each extension
    for ext in _TS_EXTENSIONS:
        candidate = joined + ext
        if candidate in all_files:
            return candidate

    # Try index file
    for ext in _TS_EXTENSIONS:
        candidate = f"{joined}/index{ext}"
        if candidate in all_files:
            return candidate

    # Normalize paths for comparison (handle ./ and ../)
    for f in all_files:
        if f == joined:
            return f
        if f.startswith(joined + "/index"):
            return f

    return None


# ---------------------------------------------------------------------------
# Base TS Resolver
# ---------------------------------------------------------------------------


class BaseTSResolver(Resolver):
    """Shared cross-file resolution logic for TypeScript and JavaScript.

    Subclasses set ``language_id``.
    """

    language_id: str = "typescript"

    def resolve(
        self,
        extractor_results: list[Any],
        graph_context: GraphContext | None = None,
        import_index: dict[str, Any] | None = None,
    ) -> ResolvedEdges:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        # Gather all symbols and edges from extractor results
        all_symbols: list[GraphNode] = []
        all_raw_edges: list[GraphEdge] = []
        file_list: list[str] = []
        imports_by_file: dict[str, list[ImportInfo]] = {}

        for er in extractor_results:
            r: ExtractorResult = er
            all_symbols.extend(r.symbols)
            raw = getattr(r, "_raw_edges", [])
            all_raw_edges.extend(raw)
            file_list.append(r.file_path)
            imports_by_file[r.file_path] = r.imports

        # Build GraphContext if not provided
        ctx = graph_context or self._build_context(all_symbols, file_list)

        # Phase 1: Resolve import edges (external: → internal node_id)
        resolved_import_edges = self._resolve_imports(
            all_raw_edges, imports_by_file, ctx, file_list,
        )
        confirmed.extend(resolved_import_edges)

        # Phase 2: Resolve call edges
        call_confirmed, call_possible, call_unresolved = self._resolve_calls(
            all_raw_edges, ctx, imports_by_file, file_list,
        )
        confirmed.extend(call_confirmed)
        possible.extend(call_possible)
        unresolved.extend(call_unresolved)

        # Phase 3: Resolve framework-specific edges
        fw_confirmed, fw_possible, fw_unresolved = self._resolve_framework_edges(
            all_raw_edges, ctx, imports_by_file, file_list,
        )
        confirmed.extend(fw_confirmed)
        possible.extend(fw_possible)
        unresolved.extend(fw_unresolved)

        # Phase 4: Build test relationships
        test_edges = self._build_test_relationships(all_symbols, all_raw_edges, ctx)
        confirmed.extend(test_edges)

        return ResolvedEdges(
            confirmed=confirmed,
            possible=possible,
            unresolved_candidates=unresolved,
        )

    # ── GraphContext construction ────────────────────────────────────────

    def _build_context(
        self, symbols: list[GraphNode], file_list: list[str]
    ) -> GraphContext:
        """Build a ``GraphContext`` from a list of symbols."""
        qual_to_id: dict[str, str] = {}
        name_to_ids: dict[str, list[str]] = {}
        file_to_ids: dict[str, list[str]] = {}

        # Priority: function > class > method > variable
        type_priority = {
            NodeType.function: 0,
            NodeType.class_: 1,
            NodeType.method: 2,
            NodeType.import_: 3,
            NodeType.external_symbol: 4,
            NodeType.test: 5,
            NodeType.route: 6,
            NodeType.controller: 6,
            NodeType.service: 6,
            NodeType.component: 6,
        }

        for s in symbols:
            qual_to_id[s.qualified_name] = s.id
            name_to_ids.setdefault(s.name, []).append(s.id)

            stem = Path(s.file_path).stem if s.file_path else ""
            file_to_ids.setdefault(stem, []).append(s.id)

        return GraphContext(
            language_id=self.language_id,
            qual_to_id=qual_to_id,
            name_to_ids=name_to_ids,
            file_to_ids=file_to_ids,
            node_count=len(symbols),
        )

    # ── Import resolution ────────────────────────────────────────────────

    def _resolve_imports(
        self,
        raw_edges: list[GraphEdge],
        imports_by_file: dict[str, list[ImportInfo]],
        ctx: GraphContext,
        file_list: list[str],
    ) -> list[ResolvedEdge]:
        """Resolve import edges: rewrite ``external:module.name`` → internal node_id."""
        resolved: list[ResolvedEdge] = []
        project_root = ""  # inferred later if needed

        for edge in raw_edges:
            if edge.type != EdgeType.imports:
                continue

            target = edge.target
            if not target.startswith("external:"):
                # Already internal
                resolved.append(ResolvedEdge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.type,
                    confidence=edge.confidence,
                    resolution=edge.metadata.resolution if edge.metadata else Resolution.imported_function_exact,
                    provenance=Provenance.IMPORT_RESOLVER,
                    evidence={"import_resolved": True},
                    source_location={"file_path": edge.source_location.file_path if edge.source_location else ""},
                ))
                continue

            # external:lodash.debounce → package_external
            # external:./utils.helpers → try to resolve as relative
            external_name = target[len("external:"):]
            parts = external_name.split(".", 1)
            module_part = parts[0]
            symbol_part = parts[1] if len(parts) > 1 else "default"

            # Check if module_part looks like a relative path
            if module_part.startswith("./") or module_part.startswith("../"):
                # Try to resolve
                source_file = edge.source_location.file_path if edge.source_location else ""
                resolved_file = _resolve_relative_import(
                    source_file, module_part, project_root, file_list,
                )
                if resolved_file:
                    # Find the symbol in the resolved file
                    target_id = None
                    for qname, nid in ctx.qual_to_id.items():
                        if qname.startswith(resolved_file + "::") and symbol_part in qname:
                            target_id = nid
                            break
                    if target_id:
                        resolved.append(ResolvedEdge(
                            source=edge.source,
                            target=target_id,
                            edge_type=edge.type,
                            confidence=0.90,
                            resolution=Resolution.relative_import_exact,
                            provenance=Provenance.IMPORT_RESOLVER,
                            evidence={"source_file": source_file, "resolved_file": resolved_file, "symbol": symbol_part},
                            source_location={"file_path": source_file},
                        ))
                        continue

            # Package import → external (confirmed for imports, but marked as package_external)
            resolved.append(ResolvedEdge(
                source=edge.source,
                target=f"external:{external_name}",
                edge_type=edge.type,
                confidence=0.50,
                resolution=Resolution.package_external,
                provenance=Provenance.IMPORT_RESOLVER,
                evidence={"import_source": module_part, "imported_name": symbol_part},
            ))

        return resolved

    # ── Call resolution ──────────────────────────────────────────────────

    def _resolve_calls(
        self,
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        file_list: list[str],
    ) -> tuple[list[ResolvedEdge], list[ResolvedEdge], list[ResolvedEdge]]:
        """Resolve call edges to known symbols."""
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        for edge in raw_edges:
            if edge.type != EdgeType.calls:
                continue

            target = edge.target
            resolution = edge.metadata.resolution if edge.metadata else Resolution.name_match_candidate

            # this.method() calls — check both "this." and "unresolved:this." prefixes
            this_method = target
            if target.startswith("unresolved:"):
                this_method = target[len("unresolved:"):]
            if this_method.startswith("this."):
                method_name = this_method[5:]
                # Try to find method in the same file
                source_file = edge.source_location.file_path if edge.source_location else ""
                found = False
                for qname, nid in ctx.qual_to_id.items():
                    if qname.startswith(source_file + "::") and qname.endswith("." + method_name):
                        confirmed.append(ResolvedEdge(
                            source=edge.source,
                            target=nid,
                            edge_type=edge.type,
                            confidence=0.90,
                            resolution=Resolution.this_method_exact,
                            provenance=Provenance.AST,
                            evidence={"this_method": method_name, "source_file": source_file},
                            source_location={"file_path": source_file},
                        ))
                        found = True
                        break
                if not found:
                    possible.append(ResolvedEdge(
                        source=edge.source,
                        target=f"unresolved:this.{method_name}",
                        edge_type=edge.type,
                        confidence=0.35,
                        resolution=Resolution.object_method_unknown,
                        provenance=Provenance.HEURISTIC,
                        evidence={"this_method": method_name, "reason": "class not resolved"},
                    ))
                continue

            # Imported function calls
            if target.startswith("unresolved:"):
                expr = target[len("unresolved:"):]
                # Try to match against imports
                source_file = edge.source_location.file_path if edge.source_location else ""
                file_imports = imports_by_file.get(source_file, [])

                matched = False
                for imp in file_imports:
                    if imp.local_name == expr:
                        # This is an imported function call
                        if imp.is_external:
                            unresolved.append(ResolvedEdge(
                                source=edge.source,
                                target=f"external:{imp.module_path}.{imp.imported_name}",
                                edge_type=edge.type,
                                confidence=0.30,
                                resolution=Resolution.package_external,
                                provenance=Provenance.IMPORT_RESOLVER,
                                evidence={"imported_from": imp.module_path},
                                source_location={"file_path": source_file},
                            ))
                        else:
                            # Relative import — resolve path
                            resolved_file = _resolve_relative_import(
                                source_file, imp.module_path, "", file_list,
                            )
                            if resolved_file:
                                target_sym = imp.imported_name if imp.imported_name != "default" else expr
                                # Find the symbol in the resolved file
                                found_sym = False
                                for qname, nid in ctx.qual_to_id.items():
                                    if qname.startswith(resolved_file + "::") and target_sym in qname:
                                        confirmed.append(ResolvedEdge(
                                            source=edge.source,
                                            target=nid,
                                            edge_type=edge.type,
                                            confidence=0.90,
                                            resolution=Resolution.imported_symbol_exact,
                                            provenance=Provenance.IMPORT_RESOLVER,
                                            evidence={"resolved_file": resolved_file, "imported_name": target_sym},
                                            source_location={"file_path": source_file},
                                        ))
                                        found_sym = True
                                        break
                                if not found_sym:
                                    possible.append(ResolvedEdge(
                                        source=edge.source,
                                        target=f"unresolved:{resolved_file}::{target_sym}",
                                        edge_type=edge.type,
                                        confidence=0.35,
                                        resolution=Resolution.name_match_candidate,
                                        provenance=Provenance.IMPORT_RESOLVER,
                                        evidence={"reason": "imported symbol not found in target file"},
                                    ))
                            else:
                                unresolved.append(ResolvedEdge(
                                    source=edge.source,
                                    target=f"external:{imp.module_path}.{imp.imported_name}",
                                    edge_type=edge.type,
                                    confidence=0.20,
                                    resolution=Resolution.require_unknown,
                                    provenance=Provenance.IMPORT_RESOLVER,
                                    evidence={"reason": "relative import could not be resolved"},
                                ))
                        matched = True
                        break

                if not matched:
                    # Name-only — try to find in project
                    name_matches = ctx.name_to_ids.get(expr, [])
                    if len(name_matches) >= 1:
                        possible.append(ResolvedEdge(
                            source=edge.source,
                            target=name_matches[0],
                            edge_type=edge.type,
                            confidence=0.35,
                            resolution=Resolution.name_match_candidate,
                            provenance=Provenance.HEURISTIC,
                            evidence={"name_matches": len(name_matches), "reason": "name-only match, not imported"},
                        ))
                    else:
                        unresolved.append(ResolvedEdge(
                            source=edge.source,
                            target=f"external:{expr}",
                            edge_type=edge.type,
                            confidence=0.20,
                            resolution=Resolution.unknown_external,
                            provenance=Provenance.HEURISTIC,
                            evidence={"reason": "no matching import or symbol found"},
                        ))
                continue

            # Direct same-file call
            if resolution == Resolution.same_file_exact:
                confirmed.append(ResolvedEdge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.type,
                    confidence=edge.confidence,
                    resolution=resolution,
                    provenance=Provenance.AST,
                    evidence={"same_file": True},
                    source_location={"file_path": edge.source_location.file_path if edge.source_location else ""},
                ))
                continue

            # Fallback
            if is_confirmed_resolution(resolution):
                confirmed.append(ResolvedEdge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.type,
                    confidence=edge.confidence,
                    resolution=resolution,
                    provenance=Provenance.AST,
                    evidence={},
                ))
            elif is_possible_resolution(resolution):
                possible.append(ResolvedEdge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.type,
                    confidence=edge.confidence,
                    resolution=resolution,
                    provenance=Provenance.HEURISTIC,
                    evidence={},
                ))
            else:
                unresolved.append(ResolvedEdge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.type,
                    confidence=edge.confidence,
                    resolution=resolution,
                    provenance=Provenance.HEURISTIC,
                    evidence={},
                ))

        return confirmed, possible, unresolved

    # ── Framework edge resolution ───────────────────────────────────────

    def _resolve_framework_edges(
        self,
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        file_list: list[str],
    ) -> tuple[list[ResolvedEdge], list[ResolvedEdge], list[ResolvedEdge]]:
        confirmed: list[ResolvedEdge] = []
        possible: list[ResolvedEdge] = []
        unresolved: list[ResolvedEdge] = []

        framework_edge_types = {EdgeType.routes_to, EdgeType.references, EdgeType.depends_on}
        for edge in raw_edges:
            if edge.type not in framework_edge_types:
                continue
            meta = edge.metadata
            resolution = meta.resolution if meta else Resolution.framework_route_resolved
            provenance = Provenance.FRAMEWORK_RESOLVER
            evidence = dict(meta.evidence or {}) if meta and meta.evidence else {}
            source_file = edge.source_location.file_path if edge.source_location else evidence.get("file_path", "")

            if resolution in {
                Resolution.inline_handler,
                Resolution.object_method_unknown,
                Resolution.callback_candidate,
            }:
                possible.append(self._resolved_from_edge(edge, edge.target, resolution, provenance, evidence))
                continue

            if not edge.target.startswith("unresolved:"):
                target_node = ctx.qual_to_id.get(edge.target)
                if target_node or edge.target in self._all_node_ids(ctx):
                    confirmed.append(self._resolved_from_edge(edge, edge.target, resolution, provenance, evidence))
                else:
                    unresolved.append(self._resolved_from_edge(edge, edge.target, Resolution.unresolved, provenance, evidence))
                continue

            expr = edge.target[len("unresolved:"):]
            if "." in expr and edge.type != EdgeType.depends_on:
                possible.append(self._resolved_from_edge(
                    edge, edge.target, Resolution.object_method_unknown, provenance,
                    {**evidence, "reason": "object method type unknown"},
                ))
                continue

            target_id = self._resolve_framework_symbol(
                expr=expr,
                source_file=source_file,
                ctx=ctx,
                imports_by_file=imports_by_file,
                file_list=file_list,
            )
            if target_id:
                confirmed.append(self._resolved_from_edge(edge, target_id, resolution, provenance, evidence))
            else:
                unresolved.append(self._resolved_from_edge(
                    edge,
                    edge.target,
                    Resolution.import_not_found,
                    provenance,
                    {**evidence, "reason": "framework target was not defined in file or resolved imports"},
                ))

        return confirmed, possible, unresolved

    def _resolved_from_edge(
        self,
        edge: GraphEdge,
        target: str,
        resolution: Resolution,
        provenance: Provenance,
        evidence: dict[str, Any],
    ) -> ResolvedEdge:
        return ResolvedEdge(
            source=edge.source,
            target=target,
            edge_type=edge.type,
            confidence=getattr(edge, "confidence", 0.0) or 0.0,
            resolution=resolution,
            provenance=provenance,
            evidence=evidence,
            source_location=(
                {
                    "file_path": edge.source_location.file_path,
                    "line_start": edge.source_location.line_start,
                    "line_end": edge.source_location.line_end,
                }
                if edge.source_location else None
            ),
        )

    def _all_node_ids(self, ctx: GraphContext) -> set[str]:
        ids: set[str] = set(ctx.qual_to_id.values())
        for values in ctx.name_to_ids.values():
            ids.update(values)
        return ids

    def _resolve_framework_symbol(
        self,
        expr: str,
        source_file: str,
        ctx: GraphContext,
        imports_by_file: dict[str, list[ImportInfo]],
        file_list: list[str],
    ) -> str | None:
        same_file = self._find_symbol_in_file(ctx, source_file, expr)
        if same_file:
            return same_file

        for imp in imports_by_file.get(source_file, []):
            if imp.local_name != expr:
                continue
            if imp.is_external:
                return None
            resolved_file = _resolve_relative_import(source_file, imp.module_path, "", file_list)
            if not resolved_file:
                return None
            imported_name = imp.imported_name or expr
            target_name = expr if imported_name in ("default", "*") else imported_name
            return self._find_symbol_in_file(ctx, resolved_file, target_name)
        return None

    def _find_symbol_in_file(self, ctx: GraphContext, file_path: str, name: str) -> str | None:
        if not file_path:
            return None
        exact = f"{file_path}::{name}"
        if exact in ctx.qual_to_id:
            return ctx.qual_to_id[exact]
        suffixes = (f"::{name}", f".{name}")
        for qname, nid in ctx.qual_to_id.items():
            if qname.startswith(file_path + "::") and qname.endswith(suffixes):
                return nid
        return None

    # ── Test relationships ───────────────────────────────────────────────

    def _build_test_relationships(
        self,
        symbols: list[GraphNode],
        raw_edges: list[GraphEdge],
        ctx: GraphContext,
    ) -> list[ResolvedEdge]:
        """Build ``tested_by`` edges for TS/JS test files.

        Strategies:
        1. Direct calls from test → target (confidence 0.90)
        2. Test name heuristic: ``testFoo`` / ``it('does X')`` → ``Foo`` (0.65)
        3. File name match: ``foo.test.ts`` → ``foo.ts`` (0.55)
        """
        edges: list[ResolvedEdge] = []

        test_symbols = [s for s in symbols if s.type == NodeType.test or "test" in s.tags]
        test_files = {s.file_path for s in test_symbols}

        # Strategy 3: File name match
        for test_file in test_files:
            stem = Path(test_file).stem
            # Remove .test, .spec suffixes
            for suffix in (".test", ".spec", "_test", "_spec", "test", "spec"):
                if stem.endswith(suffix):
                    target_stem = stem[: -len(suffix)] if not stem == suffix else stem
                    break
            else:
                target_stem = stem

            # Find matching source files
            for src_file in {s.file_path for s in symbols if s.file_path}:
                if not src_file:
                    continue
                src_stem = Path(src_file).stem
                if (
                    src_stem == target_stem
                    or src_stem == "index"
                    or target_stem in src_stem
                ):
                    # Find a likely target symbol in the source file
                    for s in symbols:
                        if s.file_path == src_file and s.type in (NodeType.function, NodeType.class_):
                            edges.append(ResolvedEdge(
                                source=s.id,
                                target="",  # will be enriched later
                                edge_type=EdgeType.tested_by,
                                confidence=0.55,
                                resolution=Resolution.test_file_heuristic,
                                provenance=Provenance.HEURISTIC,
                                evidence={
                                    "test_file": test_file,
                                    "source_file": src_file,
                                    "strategy": "file_name_match",
                                },
                            ))
                            break

        return edges


# ---------------------------------------------------------------------------
# Concrete resolvers
# ---------------------------------------------------------------------------


class TypeScriptResolver(BaseTSResolver):
    language_id = "typescript"


class JavaScriptResolver(BaseTSResolver):
    language_id = "javascript"
