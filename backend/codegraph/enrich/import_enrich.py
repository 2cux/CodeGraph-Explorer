"""Import validated enrichment data into the SQLite store.

Reads validated ``AgentOutput`` JSON and writes enrichment fields
to the nodes table. Tags are merged (enrichment + existing, deduped).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codegraph.enrich.models import AgentOutput
from codegraph.graph.store import GraphStore
from codegraph.storage.sqlite_store import SqliteStore


def import_enrichment(
    output_path: Path,
    store: GraphStore,
    sqlite_store: SqliteStore,
) -> dict[str, Any]:
    """Import validated enrichment data into SQLite.

    Args:
        output_path: Path to the validated agent output JSON.
        store: The loaded graph store (for symbol lookup).
        sqlite_store: The SQLite store to write enrichment to.

    Returns:
        Dict with import statistics: file_count, symbol_count, enriched_at.
    """
    raw = output_path.read_text(encoding="utf-8")
    output = AgentOutput.model_validate(json.loads(raw))

    enriched_at = output.enriched_at or datetime.now(timezone.utc).isoformat()

    file_count = 0
    symbol_count = 0

    # Import file-level enrichment
    for fe in output.files:
        if not fe.path:
            continue
        norm_path = fe.path.replace("\\", "/")
        # Find file nodes for this path
        file_node_ids = _find_nodes_by_file(store, norm_path)
        for node_id in file_node_ids:
            # Merge tags: existing + enrichment, dedup, respect max
            existing_node = store.get_node(node_id)
            existing_tags = list(getattr(existing_node, "tags", []) or [])
            merged_tags = _dedup_tags(existing_tags + fe.tags)[:10]
            sqlite_store.update_node_enrichment(
                node_id=node_id,
                summary=fe.summary[:500],
                role=fe.role,
                responsibilities=[],  # file-level doesn't have responsibilities
                edge_cases=[],  # file-level doesn't have edge_cases
                test_relevance="",
                enrichment_confidence=fe.confidence,
                enrichment_evidence=[ev.model_dump() for ev in fe.evidence],
                enrichment_status="analyzed",
                enriched_at=enriched_at,
                commit=False,  # batch commit at end
            )
            # Also update tags on the node via a direct SQL update
            sqlite_store.conn.execute(
                "UPDATE nodes SET tags = ? WHERE id = ?",
                [json.dumps(merged_tags, ensure_ascii=False), node_id],
            )
        file_count += 1

    # Import symbol-level enrichment
    for se in output.symbols:
        if not se.symbol or not se.file:
            continue
        norm_file = se.file.replace("\\", "/")
        # Find the symbol node
        node_id = _find_symbol(store, se.symbol, norm_file)
        if node_id is None:
            continue
        existing_node = store.get_node(node_id)
        existing_tags = list(getattr(existing_node, "tags", []) or [])
        merged_tags = _dedup_tags(existing_tags)[:10]
        sqlite_store.update_node_enrichment(
            node_id=node_id,
            summary=se.summary[:500],
            role="",  # symbol-level uses responsibilities instead of role
            responsibilities=se.responsibilities,
            edge_cases=se.edge_cases,
            test_relevance=se.test_relevance,
            enrichment_confidence=se.confidence,
            enrichment_evidence=[ev.model_dump() for ev in se.evidence],
            enrichment_status="analyzed",
            enriched_at=enriched_at,
            commit=False,  # batch commit at end
        )
        sqlite_store.conn.execute(
            "UPDATE nodes SET tags = ? WHERE id = ?",
            [json.dumps(merged_tags, ensure_ascii=False), node_id],
        )
        symbol_count += 1

    # Write meta
    sqlite_store.set_meta("enrichment_last_import", enriched_at)
    sqlite_store.set_meta("enrichment_file_count", str(file_count))
    sqlite_store.set_meta("enrichment_symbol_count", str(symbol_count))
    sqlite_store.conn.commit()

    return {
        "file_count": file_count,
        "symbol_count": symbol_count,
        "enriched_at": enriched_at,
    }


# ── helpers ──────────────────────────────────────────────────────────


def _find_nodes_by_file(store: GraphStore, file_path: str) -> list[str]:
    """Find file-type node IDs belonging to a file path.

    Only returns nodes with type='file' — symbol nodes receive
    symbol-level enrichment separately via ``_find_symbol``.
    """
    node_ids: list[str] = []
    for node in store.all_nodes():
        fp = getattr(node, "file_path", "").replace("\\", "/")
        if fp != file_path:
            continue
        node_type = node.type.value if hasattr(node.type, "value") else str(node.type)
        if node_type == "file":
            node_ids.append(node.id)
    return node_ids


def _find_symbol(store: GraphStore, symbol_name: str, file_path: str) -> str | None:
    """Find a symbol node by name within a file."""
    for node in store.all_nodes():
        fp = getattr(node, "file_path", "").replace("\\", "/")
        if fp != file_path:
            continue
        if node.name == symbol_name:
            return node.id
        if getattr(node, "qualified_name", "") == symbol_name:
            return node.id
        # Fuzzy: symbol id ends with the symbol name
        if node.id.endswith(f"::{symbol_name}"):
            return node.id
    return None


def _dedup_tags(tags: list[str]) -> list[str]:
    """Deduplicate tags case-insensitively, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        lower = tag.lower()
        if lower not in seen:
            seen.add(lower)
            result.append(tag)
    return result
