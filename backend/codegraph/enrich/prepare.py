"""Generate bounded input for agent-side enrichment analysis.

Reads the graph store and produces a ``PrepareOutput`` JSON file
with per-file metadata (symbols, imports, exports, callers, callees,
snippets) within configured limits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.enrich.models import (
    PrepareConstraints,
    PrepareFile,
    PrepareOutput,
    PrepareProject,
    PrepareSymbol,
)
from codegraph.graph.store import GraphStore


def generate_prepare_output(
    store: GraphStore,
    cg_dir: Path,
    project_name: str = "",
    max_files: int = 100,
    max_symbols_per_file: int = 20,
    max_callers_per_file: int = 5,
    max_callees_per_file: int = 5,
    max_snippet_lines: int = 30,
) -> PrepareOutput:
    """Generate bounded input JSON for enrichment agents.

    Args:
        store: The loaded graph store.
        cg_dir: Path to the ``.codegraph/`` directory.
        project_name: Project name (defaults to cg_dir parent name).
        max_files: Maximum number of files to include.
        max_symbols_per_file: Maximum symbols per file.
        max_callers_per_file: Maximum caller entries per file.
        max_callees_per_file: Maximum callee entries per file.
        max_snippet_lines: Maximum lines to include per file snippet.

    Returns:
        A ``PrepareOutput`` ready for serialization to JSON.
    """
    project_name = project_name or cg_dir.parent.name

    # Determine primary language
    language_counts: dict[str, int] = {}
    for node in store.all_nodes():
        lang = getattr(node, "language_id", None) or getattr(node, "language", "python")
        language_counts[lang] = language_counts.get(lang, 0) + 1
    primary_language = max(language_counts, key=language_counts.get) if language_counts else "python"

    project = PrepareProject(
        name=project_name,
        root=str(cg_dir.parent.resolve()),
        language=primary_language,
    )

    # Collect files and their symbols
    file_map: dict[str, dict[str, Any]] = {}
    for node in store.all_nodes():
        fp = _norm_path(getattr(node, "file_path", ""))
        if not fp:
            continue
        if fp not in file_map:
            file_map[fp] = {
                "symbols": [],
                "language": getattr(node, "language_id", None) or getattr(node, "language", "python"),
                "imports": set(),
                "exports": set(),
                "callers": [],
                "callees": [],
            }
        entry = file_map[fp]
        if node.type and node.type.value not in ("file", "module", "import", "external_symbol", "repository"):
            entry["symbols"].append(node)

    # Collect callers/callees per file from edges
    for edge in store.all_edges():
        edge_type = edge.type.value if hasattr(edge.type, "value") else str(edge.type)
        if edge_type == "calls":
            src_fp = _node_file(store, edge.source)
            tgt_fp = _node_file(store, edge.target)
            tgt_name = _node_name(store, edge.target)
            if src_fp and tgt_fp and src_fp == tgt_fp:
                continue  # skip same-file calls (already visible in symbols)
            if src_fp and tgt_name:
                _add_to_list(
                    file_map, src_fp, "callees",
                    {"symbol": tgt_name, "file": tgt_fp or ""},
                    max_callees_per_file,
                )
            if tgt_fp and src_fp:
                src_name = _node_name(store, edge.source)
                _add_to_list(
                    file_map, tgt_fp, "callers",
                    {"symbol": src_name, "file": src_fp},
                    max_callers_per_file,
                )

    # Build file entries (prioritize files with most symbols)
    sorted_files = sorted(
        file_map.items(),
        key=lambda kv: (len(kv[1]["symbols"]), kv[0]),
        reverse=True,
    )

    files: list[PrepareFile] = []
    for fp, entry in sorted_files[:max_files]:
        symbols = entry["symbols"][:max_symbols_per_file]
        prepare_symbols = [
            PrepareSymbol(
                name=s.name,
                type=s.type.value if hasattr(s.type, "value") else str(s.type),
                signature=getattr(s, "signature", None),
                docstring=getattr(s, "docstring", None),
                snippet=_truncate_lines(getattr(s, "code_preview", None), max_snippet_lines),
            )
            for s in symbols
        ]

        # Read file snippet if available
        file_snippet = None
        abs_path = cg_dir.parent / fp
        if abs_path.exists():
            try:
                lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
                file_snippet = "\n".join(lines[:max_snippet_lines])
            except (OSError, UnicodeDecodeError):
                pass

        files.append(
            PrepareFile(
                path=fp,
                language=entry["language"],
                symbols=prepare_symbols,
                imports=sorted(entry["imports"])[:50],
                exports=sorted(entry["exports"])[:50],
                callers=entry["callers"][:max_callers_per_file],
                callees=entry["callees"][:max_callees_per_file],
                snippet=file_snippet,
            )
        )

    return PrepareOutput(
        project=project,
        files=files,
        constraints=PrepareConstraints(),
    )


def write_prepare_output(output: PrepareOutput, cg_dir: Path) -> Path:
    """Write prepare output to ``.codegraph/intermediate/enrich_input.json``.

    Returns the path to the written file.
    """
    intermediate_dir = cg_dir / "intermediate"
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    output_path = intermediate_dir / "enrich_input.json"
    output_path.write_text(
        output.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    return output_path


# ── helpers ──────────────────────────────────────────────────────────


def _norm_path(p: str) -> str:
    return p.replace("\\", "/")


def _node_file(store: GraphStore, node_id: str) -> str | None:
    node = store.get_node(node_id)
    if node is None:
        return None
    fp = getattr(node, "file_path", "")
    return _norm_path(fp) if fp else None


def _node_name(store: GraphStore, node_id: str) -> str:
    node = store.get_node(node_id)
    return getattr(node, "name", node_id) if node else node_id


def _add_to_list(
    file_map: dict, fp: str, key: str, entry: dict, max_items: int
) -> None:
    if fp in file_map:
        lst = file_map[fp].get(key)
        if isinstance(lst, list) and len(lst) < max_items:
            lst.append(entry)


def _truncate_lines(text: str | None, max_lines: int) -> str | None:
    if not text:
        return None
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines])
