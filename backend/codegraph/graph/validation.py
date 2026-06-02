"""Graph validation — structural, referential, and semantic checks.

Validates both in-memory node/edge lists and SQLite-stored graph data.
Produces a ValidationReport with auto-corrected items, dropped items,
warnings, and fatal errors. Supports lightweight repair operations.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codegraph.graph.models import EdgeType, NodeType, Resolution
from codegraph.storage.sqlite_store import SUPPORTED_SCHEMA_VERSION, SqliteStore

# ── Thresholds ──────────────────────────────────────────────────────────

ORPHAN_RATIO_WARNING_THRESHOLD = 0.5
EXTERNAL_RATIO_WARNING_THRESHOLD = 0.3
LOW_CONFIDENCE_RATIO_WARNING_THRESHOLD = 0.5
LOW_CONFIDENCE_THRESHOLD = 0.6

# Valid enum member values for fast lookup
_VALID_NODE_TYPES: set[str] = {m.value for m in NodeType}
_VALID_EDGE_TYPES: set[str] = {m.value for m in EdgeType}
_VALID_RESOLUTIONS: set[str] = {m.value for m in Resolution}


# ── Public API ──────────────────────────────────────────────────────────


def validate_graph(
    cg_dir: Path,
    project_root: Path,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    store: SqliteStore | None = None,
) -> dict[str, Any]:
    """Validate graph nodes and edges for structural and referential integrity.

    Three modes:
    1. **Store-only**: loads from SQLite, runs all checks including
       schema_version, FTS, dangling edges.
    2. **Nodes+edges only**: in-memory validation (used pre-write).
    3. **Both**: cross-validates in-memory against SQLite.

    Args:
        cg_dir: ``.codegraph`` directory path.
        project_root: Project root for path safety checks.
        nodes: Optional in-memory node dicts.
        edges: Optional in-memory edge dicts.
        store: Optional ``SqliteStore`` for SQLite-side checks.

    Returns:
        ValidationReport dict with keys: ``status``, ``auto_corrected``,
        ``dropped``, ``warnings``, ``fatal``, ``stats``.
    """
    auto_corrected: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    fatal: list[dict[str, Any]] = []

    # ── 1. Load data ─────────────────────────────────────────────────
    if store is not None:
        if nodes is None:
            nodes = store.load_all_nodes()
        if edges is None:
            edges = store.load_all_edges()

    if nodes is None or edges is None:
        raise ValueError(
            "At least one of (nodes+edges) or store must be provided"
        )

    # Work on copies to avoid mutating caller data
    nodes = list(nodes)
    edges = list(edges)

    # ── 2. Node ID uniqueness ────────────────────────────────────────
    seen_ids: set[str] = set()
    deduped_nodes: list[dict[str, Any]] = []
    for node in nodes:
        nid = node.get("id", "")
        if not nid:
            dropped.append(_issue(
                "duplicate_node_id", "dropped",
                "Node with empty or missing ID dropped",
                node_name=node.get("name", "?"),
            ))
            continue
        if nid in seen_ids:
            dropped.append(_issue(
                "duplicate_node_id", "dropped",
                f"Duplicate node ID '{nid}' — keeping first occurrence",
                node_id=nid, node_name=node.get("name", "?"),
            ))
            continue
        seen_ids.add(nid)
        deduped_nodes.append(node)
    nodes = deduped_nodes

    # ── 3. Edge ID uniqueness + missing ID regeneration ──────────────
    seen_edge_ids: set[str] = set()
    deduped_edges: list[dict[str, Any]] = []
    for edge in edges:
        eid = edge.get("id", "")
        if not eid:
            new_id = _gen_edge_id()
            edge["id"] = new_id
            auto_corrected.append(_issue(
                "missing_edge_id", "auto_corrected",
                f"Edge missing ID — generated {new_id}",
                edge_id=new_id,
                source=edge.get("source", "?"),
                target=edge.get("target", "?"),
            ))
        elif eid in seen_edge_ids:
            new_id = _gen_edge_id()
            edge["id"] = new_id
            auto_corrected.append(_issue(
                "duplicate_edge_id", "auto_corrected",
                f"Duplicate edge ID — regenerated as {new_id}",
                old_edge_id=eid, new_edge_id=new_id,
            ))
        seen_edge_ids.add(edge["id"])
        deduped_edges.append(edge)
    edges = deduped_edges

    # Build valid node ID set (for edge referential checks)
    valid_node_ids: set[str] = {n["id"] for n in nodes}

    # ── 4. Edge source/target existence ──────────────────────────────
    validated_edges: list[dict[str, Any]] = []
    for edge in edges:
        source = edge.get("source", "")
        target = edge.get("target", "")
        missing = []
        if source and source not in valid_node_ids:
            missing.append("source")
        if target and target not in valid_node_ids:
            missing.append("target")
        if missing:
            dropped.append(_issue(
                "dangling_edge", "dropped",
                f"Edge references non-existent {'/'.join(missing)}",
                edge_id=edge.get("id"), source=source, target=target,
                missing_endpoints=missing,
            ))
            continue
        validated_edges.append(edge)
    edges = validated_edges

    # ── 5. Edge type validity ────────────────────────────────────────
    validated_edges = []
    for edge in edges:
        etype = edge.get("type", "")
        if isinstance(etype, str) and etype not in _VALID_EDGE_TYPES:
            dropped.append(_issue(
                "invalid_edge_type", "dropped",
                f"Invalid edge type '{etype}' — edge dropped",
                edge_id=edge.get("id"), edge_type=etype,
            ))
            continue
        validated_edges.append(edge)
    edges = validated_edges

    # ── 6. Node type validity ────────────────────────────────────────
    for node in nodes:
        ntype = node.get("type", "")
        if isinstance(ntype, str) and ntype not in _VALID_NODE_TYPES:
            warnings.append(_issue(
                "invalid_node_type", "warning",
                f"Invalid node type '{ntype}' for node '{node.get('id', '?')}'",
                node_id=node.get("id"), node_type=ntype,
            ))

    # ── 7. Confidence clamping ───────────────────────────────────────
    for edge in edges:
        conf = edge.get("confidence", 1.0)
        if not isinstance(conf, (int, float)):
            continue
        if conf < 0.0:
            edge["confidence"] = 0.0
            auto_corrected.append(_issue(
                "confidence_clamped", "auto_corrected",
                f"Confidence {conf} clamped to 0.0",
                edge_id=edge.get("id"),
                original_confidence=conf, clamped_confidence=0.0,
            ))
        elif conf > 1.0:
            edge["confidence"] = 1.0
            auto_corrected.append(_issue(
                "confidence_clamped", "auto_corrected",
                f"Confidence {conf} clamped to 1.0",
                edge_id=edge.get("id"),
                original_confidence=conf, clamped_confidence=1.0,
            ))

    # ── 8. Resolution validity ───────────────────────────────────────
    for edge in edges:
        metadata = edge.get("metadata")
        if not metadata or not isinstance(metadata, dict):
            continue
        resolution = metadata.get("resolution", "")
        if isinstance(resolution, str) and resolution not in _VALID_RESOLUTIONS:
            warnings.append(_issue(
                "invalid_resolution", "warning",
                f"Invalid resolution '{resolution}' for edge '{edge.get('id', '?')}'",
                edge_id=edge.get("id"), resolution=resolution,
            ))

    # ── 9. Metadata JSON serializability ─────────────────────────────
    for node in nodes:
        meta = node.get("metadata")
        if meta is not None:
            try:
                json.dumps(meta)
            except (TypeError, ValueError) as e:
                warnings.append(_issue(
                    "metadata_not_serializable", "warning",
                    f"Node metadata not JSON-serializable: {e}",
                    node_id=node.get("id"),
                ))

    for edge in edges:
        meta = edge.get("metadata")
        if meta is not None:
            try:
                json.dumps(meta)
            except (TypeError, ValueError) as e:
                warnings.append(_issue(
                    "metadata_not_serializable", "warning",
                    f"Edge metadata not JSON-serializable: {e}",
                    edge_id=edge.get("id"),
                ))

    # ── 10. Missing tags / reason_codes fixup ────────────────────────
    for node in nodes:
        if "tags" not in node or node["tags"] is None:
            node["tags"] = []
            auto_corrected.append(_issue(
                "missing_tags", "auto_corrected",
                f"Missing tags for node '{node.get('id', '?')}' — set to []",
                node_id=node.get("id"),
            ))

    for edge in edges:
        metadata = edge.get("metadata")
        if metadata and isinstance(metadata, dict):
            if "reason" not in metadata or metadata["reason"] is None:
                metadata["reason"] = ""
                auto_corrected.append(_issue(
                    "missing_reason_code", "auto_corrected",
                    f"Missing reason_code for edge '{edge.get('id', '?')}'",
                    edge_id=edge.get("id"),
                ))

    # ── 11. File path safety ─────────────────────────────────────────
    resolved_root = project_root.resolve()
    for node in nodes:
        fp = node.get("file_path", "")
        if not fp:
            continue
        try:
            node_path = (resolved_root / fp).resolve()
            if not str(node_path).startswith(str(resolved_root) + os.sep) \
               and node_path != resolved_root:
                warnings.append(_issue(
                    "path_outside_root", "warning",
                    f"File path '{fp}' resolves outside project root",
                    node_id=node.get("id"), file_path=fp,
                ))
        except (ValueError, OSError):
            warnings.append(_issue(
                "path_resolution_error", "warning",
                f"Cannot resolve file path '{fp}'",
                node_id=node.get("id"), file_path=fp,
            ))

    # ── 12. Schema version check ─────────────────────────────────────
    schema_version: str | None = None
    if store is not None:
        sv_status, sv_msg = store.schema_version_status()
        schema_version = store.get_meta("schema_version")
        if sv_status == "error":
            fatal.append(_issue(
                "schema_version_incompatible", "fatal",
                sv_msg,
                schema_version=schema_version,
                supported=SUPPORTED_SCHEMA_VERSION,
            ))
        elif sv_status == "warning":
            warnings.append(_issue(
                "schema_version_missing", "warning",
                sv_msg,
                schema_version=schema_version,
            ))

    # ── 13. Node/edge counts ─────────────────────────────────────────
    node_count = len(nodes)
    edge_count = len(edges)

    if node_count == 0:
        fatal.append(_issue(
            "empty_nodes", "fatal",
            "No valid nodes — graph is empty. Run: codegraph init --force",
            node_count=node_count,
        ))

    if store is not None:
        try:
            sqlite_node_count = store.node_count()
            sqlite_edge_count = store.edge_count()
            if sqlite_node_count != node_count:
                warnings.append(_issue(
                    "sqlite_node_count_mismatch", "warning",
                    f"SQLite node count ({sqlite_node_count}) != "
                    f"in-memory node count ({node_count})",
                    sqlite_count=sqlite_node_count, memory_count=node_count,
                ))
            if sqlite_edge_count != edge_count:
                warnings.append(_issue(
                    "sqlite_edge_count_mismatch", "warning",
                    f"SQLite edge count ({sqlite_edge_count}) != "
                    f"in-memory edge count ({edge_count})",
                    sqlite_count=sqlite_edge_count, memory_count=edge_count,
                ))
        except Exception as exc:
            fatal.append(_issue(
                "sqlite_unreadable", "fatal",
                f"SQLite database unreadable: {exc}. Run: codegraph init --force",
                error=str(exc),
            ))

    # ── 14. FTS count match ──────────────────────────────────────────
    fts_count: int | None = None
    if store is not None:
        if store.has_fts_table():
            fts_count = store.fts_count()
            if fts_count is not None and fts_count != node_count:
                warnings.append(_issue(
                    "fts_count_mismatch", "warning",
                    f"FTS symbol count ({fts_count}) != node count ({node_count})",
                    fts_count=fts_count, node_count=node_count,
                ))

    # ── 15. Orphan node ratio ────────────────────────────────────────
    # A node is orphan if it has zero incoming AND zero outgoing edges
    nodes_with_incoming: set[str] = set()
    nodes_with_outgoing: set[str] = set()
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src:
            nodes_with_outgoing.add(src)
        if tgt:
            nodes_with_incoming.add(tgt)

    orphan_count = 0
    for node in nodes:
        nid = node.get("id", "")
        if nid not in nodes_with_incoming and nid not in nodes_with_outgoing:
            orphan_count += 1

    orphan_ratio = orphan_count / node_count if node_count > 0 else 0.0
    if orphan_ratio > ORPHAN_RATIO_WARNING_THRESHOLD:
        warnings.append(_issue(
            "high_orphan_ratio", "warning",
            f"Orphan node ratio {orphan_ratio:.1%} exceeds "
            f"threshold {ORPHAN_RATIO_WARNING_THRESHOLD:.0%}",
            orphan_count=orphan_count, orphan_ratio=round(orphan_ratio, 4),
            node_count=node_count,
        ))

    # ── 16. External/unresolved symbol ratio ─────────────────────────
    external_count = sum(
        1 for n in nodes
        if n.get("type") in ("external_symbol", NodeType.external_symbol.value)
    )
    external_ratio = external_count / node_count if node_count > 0 else 0.0
    if external_ratio > EXTERNAL_RATIO_WARNING_THRESHOLD:
        warnings.append(_issue(
            "high_external_ratio", "warning",
            f"External symbol ratio {external_ratio:.1%} exceeds "
            f"threshold {EXTERNAL_RATIO_WARNING_THRESHOLD:.0%}",
            external_count=external_count, external_ratio=round(external_ratio, 4),
            node_count=node_count,
        ))

    # ── 17. Low-confidence edge ratio ────────────────────────────────
    low_conf_count = sum(
        1 for e in edges
        if isinstance(e.get("confidence"), (int, float))
        and e["confidence"] < LOW_CONFIDENCE_THRESHOLD
    )
    low_conf_ratio = low_conf_count / edge_count if edge_count > 0 else 0.0
    if low_conf_ratio > LOW_CONFIDENCE_RATIO_WARNING_THRESHOLD:
        warnings.append(_issue(
            "high_low_confidence_ratio", "warning",
            f"Low-confidence edge ratio {low_conf_ratio:.1%} exceeds "
            f"threshold {LOW_CONFIDENCE_RATIO_WARNING_THRESHOLD:.0%}",
            low_confidence_count=low_conf_count,
            low_confidence_ratio=round(low_conf_ratio, 4),
            edge_count=edge_count,
        ))

    # ── 18. Determine overall status ─────────────────────────────────
    if fatal:
        overall_status = "error"
    elif warnings:
        overall_status = "warning"
    else:
        overall_status = "ok"

    # ── 19. Dangling edges (SQLite-side) ─────────────────────────────
    dangling_edge_count = 0
    if store is not None:
        try:
            dangling_edge_count = store.dangling_edge_count()
            if dangling_edge_count > 0:
                dropped.append(_issue(
                    "sqlite_dangling_edges", "dropped",
                    f"{dangling_edge_count} dangling edge(s) in SQLite",
                    dangling_edge_count=dangling_edge_count,
                ))
        except Exception:
            pass

    # ── Build stats ──────────────────────────────────────────────────
    stats = {
        "node_count": node_count,
        "edge_count": edge_count,
        "orphan_count": orphan_count,
        "orphan_ratio": round(orphan_ratio, 4),
        "external_count": external_count,
        "external_ratio": round(external_ratio, 4),
        "low_confidence_count": low_conf_count,
        "low_confidence_ratio": round(low_conf_ratio, 4),
        "schema_version": schema_version,
        "fts_count": fts_count,
        "dangling_edge_count": dangling_edge_count,
    }

    return {
        "status": overall_status,
        "auto_corrected": auto_corrected,
        "dropped": dropped,
        "warnings": warnings,
        "fatal": fatal,
        "stats": stats,
    }


def repair_graph(
    cg_dir: Path,
    report: dict[str, Any],
    store: SqliteStore | None = None,
) -> dict[str, Any]:
    """Apply lightweight, safe repairs based on a validation report.

    Safe repairs (always applied):
    - Confidence clamping (UPDATE edges SET confidence)
    - Missing tags (UPDATE nodes SET tags='[]')
    - Dangling edges (DELETE FROM edges WHERE source/target NOT IN nodes)
    - Duplicate edge IDs (DELETE duplicates)
    - FTS rebuild (rebuild_fts)
    - JSON re-export (export_json_from_sqlite)

    NEVER auto-repairs: SQLite corruption, schema version mismatch,
    mass node loss, path traversal. These raise ValueError with
    "codegraph init --force" suggestion.

    Args:
        cg_dir: ``.codegraph`` directory path.
        report: Validation report from ``validate_graph()``.
        store: Optional ``SqliteStore`` (opened fresh if not provided).

    Returns:
        Updated validation report after repairs.
    """
    # Check for fatal issues that cannot be auto-repaired
    for f in report.get("fatal", []):
        issue_type = f.get("issue", "")
        if issue_type in ("schema_version_incompatible", "empty_nodes",
                          "sqlite_unreadable"):
            raise ValueError(
                f"Cannot auto-repair fatal issue '{issue_type}': "
                f"{f.get('message', '')}\nRun: codegraph init --force"
            )

    sqlite_path = cg_dir / "index.sqlite"
    own_store = False
    if store is None:
        if not sqlite_path.exists():
            raise ValueError(
                "SQLite database is missing. Cannot repair. "
                "Run: codegraph init --force"
            )
        store = SqliteStore(sqlite_path)
        store.initialize()
        own_store = True

    try:
        # ── Apply auto-corrections ─────────────────────────────────
        corrections_applied = 0

        for item in report.get("auto_corrected", []):
            issue_type = item.get("issue", "")
            if issue_type == "confidence_clamped":
                eid = item.get("edge_id")
                if eid:
                    clamped = item.get("clamped_confidence", 1.0)
                    store.conn.execute(
                        "UPDATE edges SET confidence = ? WHERE id = ?",
                        [clamped, eid],
                    )
                    corrections_applied += 1
            elif issue_type == "missing_tags":
                nid = item.get("node_id")
                if nid:
                    store.conn.execute(
                        "UPDATE nodes SET tags = ? WHERE id = ?",
                        [json.dumps([]), nid],
                    )
                    corrections_applied += 1

        # ── Drop dangling edges ────────────────────────────────────
        dangling_count = report.get("stats", {}).get("dangling_edge_count", 0)
        if dangling_count > 0:
            store.conn.execute(
                "DELETE FROM edges WHERE source NOT IN (SELECT id FROM nodes) "
                "OR target NOT IN (SELECT id FROM nodes)"
            )
            corrections_applied += store.conn.rowcount if hasattr(store.conn, 'rowcount') else dangling_count

        # ── FTS rebuild if mismatched ──────────────────────────────
        for w in report.get("warnings", []):
            if w.get("issue") == "fts_count_mismatch":
                store.rebuild_fts()
                corrections_applied += 1
                break

        store.conn.commit()

    except Exception as exc:
        try:
            store.conn.rollback()
        except Exception:
            pass
        raise ValueError(
            f"Repair failed: {exc}. Run: codegraph init --force"
        ) from exc
    finally:
        if own_store:
            store.close()

    # ── JSON re-export ──────────────────────────────────────────────
    try:
        from codegraph.storage.writer import export_json_from_sqlite
        export_json_from_sqlite(cg_dir)
    except Exception:
        pass  # non-fatal — metadata/state can be repaired separately

    # ── Re-validate and return updated report ───────────────────────
    if own_store:
        return validate_graph(cg_dir, cg_dir.parent, store=None)
    else:
        store2 = SqliteStore(sqlite_path)
        store2.initialize()
        try:
            return validate_graph(cg_dir, cg_dir.parent, store=store2)
        finally:
            store2.close()


def save_validation_report(
    cg_dir: Path,
    report: dict[str, Any],
) -> Path:
    """Persist a validation report to ``.codegraph/validation_report.json``.

    Args:
        cg_dir: ``.codegraph`` directory path.
        report: Validation report from ``validate_graph()``.

    Returns:
        Path to the written report file.
    """
    cg_dir.mkdir(parents=True, exist_ok=True)
    report_path = cg_dir / "validation_report.json"

    status = report.get("status", "unknown")
    suggested_fix = (
        "codegraph init --force"
        if status == "error"
        else "codegraph doctor --repair"
        if status == "warning"
        else None
    )

    payload = {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": report.get("stats", {}).get("schema_version"),
        "issue_counts": {
            "auto_corrected": len(report.get("auto_corrected", [])),
            "dropped": len(report.get("dropped", [])),
            "warnings": len(report.get("warnings", [])),
            "fatal": len(report.get("fatal", [])),
        },
        "stats": report.get("stats", {}),
        "suggested_fix": suggested_fix,
    }

    report_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report_path


def load_validation_report(cg_dir: Path) -> dict[str, Any] | None:
    """Load a previously persisted validation report.

    Args:
        cg_dir: ``.codegraph`` directory path.

    Returns:
        The report dict, or ``None`` if not found or unreadable.
    """
    report_path = cg_dir / "validation_report.json"
    if not report_path.exists():
        return None
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ── Internal helpers ──────────────────────────────────────────────────


def _issue(
    issue_type: str,
    category: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    """Build a structured issue dict."""
    return {
        "issue": issue_type,
        "category": category,
        "message": message,
        **details,
    }


def _gen_edge_id() -> str:
    """Generate a unique edge ID."""
    return f"edge_{uuid.uuid4().hex[:12]}"
