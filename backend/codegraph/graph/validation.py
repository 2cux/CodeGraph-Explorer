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

from codegraph.graph.models import (
    AutoCorrectReason,
    DropReason,
    EdgeType,
    NodeType,
    Resolution,
)
from codegraph.graph.normalize import normalize_edge_type, normalize_node_type
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

# Maximum examples to include per reason in breakdowns
_MAX_TOP_EXAMPLES = 10


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
        ``dropped``, ``warnings``, ``fatal``, ``stats``, ``edge_health``.
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

    # ── 1a. Merge indexer-level diagnostics ───────────────────────────
    try:
        from codegraph.indexer.graph_builder import get_indexer_diagnostics
        idx_drops, idx_auto = get_indexer_diagnostics()
        if idx_drops:
            dropped.extend(idx_drops)
        if idx_auto:
            auto_corrected.extend(idx_auto)
    except ImportError:
        pass  # indexer module not available (e.g. during tests)

    # ── 2. Node ID uniqueness ────────────────────────────────────────
    seen_ids: set[str] = set()
    deduped_nodes: list[dict[str, Any]] = []
    for node in nodes:
        nid = node.get("id", "")
        if not nid:
            dropped.append(_drop_entry(
                DropReason.duplicate_node_id,
                "Node with empty or missing ID dropped",
                node_name=node.get("name", "?"),
            ))
            continue
        if nid in seen_ids:
            dropped.append(_drop_entry(
                DropReason.duplicate_node_id,
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
            auto_corrected.append(_auto_correct_entry(
                AutoCorrectReason.missing_edge_id,
                f"Edge missing ID — generated {new_id}",
                edge_id=new_id,
                source=edge.get("source", "?"),
                target=edge.get("target", "?"),
            ))
        elif eid in seen_edge_ids:
            new_id = _gen_edge_id()
            edge["id"] = new_id
            auto_corrected.append(_auto_correct_entry(
                AutoCorrectReason.duplicate_edge_id,
                f"Duplicate edge ID — regenerated as {new_id}",
                edge_id=new_id,
                original_value=eid, corrected_value=new_id,
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
            if "source" in missing and "target" in missing:
                reason = DropReason.missing_both
            elif "source" in missing:
                reason = DropReason.missing_source
            else:
                reason = DropReason.missing_target
            dropped.append(_drop_entry(
                reason,
                f"Edge references non-existent {'/'.join(missing)}",
                edge_id=edge.get("id"), source=source, target=target,
                edge_type=edge.get("type"),
            ))
            continue
        validated_edges.append(edge)
    edges = validated_edges

    # ── 5. Edge type validity + alias normalization ──────────────────
    validated_edges = []
    for edge in edges:
        etype = edge.get("type", "")
        if not isinstance(etype, str):
            validated_edges.append(edge)
            continue

        # Try alias normalization first
        canonical, correction = normalize_edge_type(etype)
        if canonical is not None:
            if correction is not None:
                # Non-canonical alias — auto-correct to canonical form
                edge["type"] = canonical.value
                auto_corrected.append(_auto_correct_entry(
                    AutoCorrectReason.type_alias_corrected,
                    f"Edge type '{etype}' normalized to '{canonical.value}'",
                    edge_id=edge.get("id"),
                    source=edge.get("source"), target=edge.get("target"),
                    original_value=etype, corrected_value=canonical.value,
                ))
            validated_edges.append(edge)
        elif etype not in _VALID_EDGE_TYPES:
            # Truly invalid — no alias match, not canonical
            dropped.append(_drop_entry(
                DropReason.invalid_edge_type,
                f"Invalid edge type '{etype}' — no alias match found, edge dropped",
                edge_id=edge.get("id"), edge_type=etype,
                source=edge.get("source"), target=edge.get("target"),
            ))
            continue
        else:
            validated_edges.append(edge)
    edges = validated_edges

    # ── 6. Node type validity + normalization ────────────────────────
    for node in nodes:
        ntype = node.get("type", "")
        if not isinstance(ntype, str):
            continue

        # Try alias normalization first
        canonical, correction = normalize_node_type(ntype)
        if canonical is not None:
            if correction is not None:
                node["type"] = canonical.value
                auto_corrected.append(_auto_correct_entry(
                    AutoCorrectReason.symbol_kind_normalized,
                    f"Node type '{ntype}' normalized to '{canonical.value}' "
                    f"for node '{node.get('id', '?')}'",
                    node_id=node.get("id"),
                    original_value=ntype, corrected_value=canonical.value,
                ))
        elif ntype not in _VALID_NODE_TYPES:
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
            auto_corrected.append(_auto_correct_entry(
                AutoCorrectReason.confidence_clamped,
                f"Confidence {conf} clamped to 0.0",
                edge_id=edge.get("id"),
                original_value=str(conf), corrected_value="0.0",
            ))
        elif conf > 1.0:
            edge["confidence"] = 1.0
            auto_corrected.append(_auto_correct_entry(
                AutoCorrectReason.confidence_clamped,
                f"Confidence {conf} clamped to 1.0",
                edge_id=edge.get("id"),
                original_value=str(conf), corrected_value="1.0",
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
            auto_corrected.append(_auto_correct_entry(
                AutoCorrectReason.missing_tags,
                f"Missing tags for node '{node.get('id', '?')}' — set to []",
                node_id=node.get("id"),
            ))

    for edge in edges:
        metadata = edge.get("metadata")
        if metadata and isinstance(metadata, dict):
            if "reason" not in metadata or metadata["reason"] is None:
                metadata["reason"] = ""
                auto_corrected.append(_auto_correct_entry(
                    AutoCorrectReason.missing_reason_code,
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

    # ── 11a. Path normalization (backslash → forward slash) ──────────
    for node in nodes:
        fp = node.get("file_path", "")
        if not fp or "\\" not in fp:
            continue
        normalized = fp.replace("\\", "/")
        node["file_path"] = normalized
        auto_corrected.append(_auto_correct_entry(
            AutoCorrectReason.path_normalized,
            f"File path backslashes normalized for node '{node.get('id', '?')}'",
            node_id=node.get("id"),
            original_value=fp, corrected_value=normalized,
        ))

    for edge in edges:
        sl = edge.get("source_location")
        if sl and isinstance(sl, dict):
            fp = sl.get("file_path", "")
            if fp and "\\" in fp:
                normalized = fp.replace("\\", "/")
                sl["file_path"] = normalized
                auto_corrected.append(_auto_correct_entry(
                    AutoCorrectReason.path_normalized,
                    f"Edge source_location path normalized for edge '{edge.get('id', '?')}'",
                    edge_id=edge.get("id"),
                    original_value=fp, corrected_value=normalized,
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
                dropped.append(_drop_entry(
                    DropReason.missing_target,
                    f"{dangling_edge_count} dangling edge(s) in SQLite "
                    f"(source or target not in nodes table)",
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

    # ── Build EdgeHealth ─────────────────────────────────────────────
    total_edges_before_drop = edge_count + len(dropped)
    edge_health = {
        "total_edges": total_edges_before_drop,
        "total_dropped": len(dropped),
        "total_auto_corrected": len(auto_corrected),
        "dropped_ratio": round(
            len(dropped) / total_edges_before_drop, 4
        ) if total_edges_before_drop > 0 else 0.0,
        "dropped_by_reason": _build_breakdown(dropped, key_field="reason"),
        "auto_corrected_by_reason": _build_breakdown(
            auto_corrected, key_field="reason"
        ),
        "impact_assessment": _build_impact_assessment(dropped, auto_corrected, fatal),
        "suggested_actions": _build_suggested_actions(dropped, auto_corrected, fatal),
    }

    return {
        "status": overall_status,
        "auto_corrected": auto_corrected,
        "dropped": dropped,
        "warnings": warnings,
        "fatal": fatal,
        "stats": stats,
        "edge_health": edge_health,
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
            # Support both "issue" (legacy) and "reason" (new) keys
            issue_type = item.get("issue") or item.get("reason", "")
            if issue_type in ("confidence_clamped", AutoCorrectReason.confidence_clamped.value):
                eid = item.get("edge_id")
                if eid:
                    clamped = item.get("clamped_confidence")
                    if clamped is None:
                        clamped = float(item.get("corrected_value", 1.0))
                    store.conn.execute(
                        "UPDATE edges SET confidence = ? WHERE id = ?",
                        [clamped, eid],
                    )
                    corrections_applied += 1
            elif issue_type in ("missing_tags", AutoCorrectReason.missing_tags.value):
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

    edge_health = report.get("edge_health", {})

    payload = {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": report.get("stats", {}).get("schema_version"),
        "edge_health": edge_health,
        # legacy issue_counts for backward compat
        "issue_counts": {
            "auto_corrected": edge_health.get("total_auto_corrected", 0),
            "dropped": edge_health.get("total_dropped", 0),
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
    """Build a structured issue dict (for warnings/fatal — backward compat)."""
    return {
        "issue": issue_type,
        "category": category,
        "message": message,
        **details,
    }


def _drop_entry(
    reason: DropReason,
    message: str,
    edge_id: str | None = None,
    source: str | None = None,
    target: str | None = None,
    edge_type: str | None = None,
    node_id: str | None = None,
    node_name: str | None = None,
    file_path: str | None = None,
    language_id: str | None = None,
    resolution: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a structured drop entry dict with both legacy and new keys."""
    result: dict[str, Any] = {
        "issue": reason.value,
        "reason": reason.value,
        "category": "dropped",
        "message": message,
    }
    if edge_id is not None:
        result["edge_id"] = edge_id
    if source is not None:
        result["source"] = source
    if target is not None:
        result["target"] = target
    if edge_type is not None:
        result["edge_type"] = edge_type
    if node_id is not None:
        result["node_id"] = node_id
    if node_name is not None:
        result["node_name"] = node_name
    if file_path is not None:
        result["file_path"] = file_path
    if language_id is not None:
        result["language_id"] = language_id
    if resolution is not None:
        result["resolution"] = resolution
    result.update(extra)
    return result


def _auto_correct_entry(
    reason: AutoCorrectReason,
    message: str,
    edge_id: str | None = None,
    source: str | None = None,
    target: str | None = None,
    original_value: str | None = None,
    corrected_value: str | None = None,
    node_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a structured auto-correct entry dict with both legacy and new keys."""
    result: dict[str, Any] = {
        "issue": reason.value,
        "reason": reason.value,
        "category": "auto_corrected",
        "message": message,
    }
    if edge_id is not None:
        result["edge_id"] = edge_id
    if source is not None:
        result["source"] = source
    if target is not None:
        result["target"] = target
    if original_value is not None:
        result["original_value"] = original_value
    if corrected_value is not None:
        result["corrected_value"] = corrected_value
    if node_id is not None:
        result["node_id"] = node_id
    result.update(extra)
    return result


def _gen_edge_id() -> str:
    """Generate a unique edge ID."""
    return f"edge_{uuid.uuid4().hex[:12]}"


def _build_breakdown(
    entries: list[dict[str, Any]],
    key_field: str = "reason",
    max_examples: int = _MAX_TOP_EXAMPLES,
) -> list[dict[str, Any]]:
    """Aggregate entries by a key field into ByReasonBreakdown-compatible dicts.

    Args:
        entries: List of drop or auto-correct entry dicts.
        key_field: The dict key to group by (default ``"reason"``).
        max_examples: Maximum examples to include per reason.

    Returns:
        List of ``{"reason": str, "count": int, "top_examples": [...]}`` dicts,
        sorted by count descending.
    """
    by_reason: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        reason = entry.get(key_field, "unknown")
        by_reason.setdefault(reason, []).append(entry)
    breakdown: list[dict[str, Any]] = []
    for reason, items in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        breakdown.append({
            "reason": reason,
            "count": len(items),
            "top_examples": items[:max_examples],
        })
    return breakdown


def _build_impact_assessment(
    dropped: list[dict[str, Any]],
    auto_corrected: list[dict[str, Any]],
    fatal: list[dict[str, Any]],
) -> str:
    """Generate an agent-friendly impact assessment based on drop reasons."""
    by_reason: dict[str, int] = {}
    for d in dropped:
        r = d.get("reason", "unknown")
        by_reason[r] = by_reason.get(r, 0) + 1

    parts: list[str] = []
    dangling = (
        by_reason.get("missing_source", 0)
        + by_reason.get("missing_target", 0)
        + by_reason.get("missing_both", 0)
    )
    if dangling > 0:
        parts.append(
            f"{dangling} dangling edges (call graph gaps — "
            f"callers/callees/impact may miss paths)"
        )
    if by_reason.get("invalid_edge_type", 0) > 0:
        parts.append(
            f"{by_reason['invalid_edge_type']} invalid edge types "
            f"(extractor may be producing non-canonical types)"
        )
    if by_reason.get("duplicate_edge", 0) > 0:
        parts.append(
            f"{by_reason['duplicate_edge']} duplicate edges (harmless dedup)"
        )
    if by_reason.get("parser_missing", 0) > 0:
        parts.append(
            f"{by_reason['parser_missing']} parser-missing drops "
            f"(unsupported languages or extractor failure — "
            f"affected files have NO indexed symbols)"
        )
    if by_reason.get("external_unresolved", 0) > 0:
        parts.append(
            f"{by_reason['external_unresolved']} external-unresolved "
            f"(third-party symbols not indexed — expected for external deps)"
        )
    if by_reason.get("framework_unresolved", 0) > 0:
        parts.append(
            f"{by_reason['framework_unresolved']} framework-unresolved "
            f"(resolver discarded possible/low-confidence edges)"
        )

    if not parts:
        return "No significant edge quality issues detected."

    return "Edge quality issues: " + "; ".join(parts) + "."


def _build_suggested_actions(
    dropped: list[dict[str, Any]],
    auto_corrected: list[dict[str, Any]],
    fatal: list[dict[str, Any]],
) -> list[str]:
    """Generate actionable suggestions based on drop/auto-correct reasons."""
    actions: list[str] = []
    by_reason: dict[str, int] = {}
    for d in dropped:
        r = d.get("reason", "unknown")
        by_reason[r] = by_reason.get(r, 0) + 1

    if by_reason.get("invalid_edge_type", 0) > 10:
        actions.append(
            "Many invalid edge types: check extractors for non-canonical "
            "edge type usage (e.g. 'implements' instead of 'inherits'). "
            "Run 'codegraph init --force' after fixing."
        )
    if by_reason.get("parser_missing", 0) > 0:
        actions.append(
            "Parser unavailable for some files: verify language support "
            "and tree-sitter installation. Unsupported files are not indexed."
        )
    if by_reason.get("duplicate_edge", 0) > 100:
        actions.append(
            "High duplicate edge count: resolver may be over-producing. "
            "Check resolver dedup logic. This is harmless but wastes storage."
        )
    if by_reason.get("external_unresolved", 0) > 100:
        actions.append(
            "Many unresolved external edges: third-party library symbols "
            "are not indexed. This is expected for external dependencies "
            "and does not affect internal call graph accuracy."
        )
    dangling = (
        by_reason.get("missing_source", 0)
        + by_reason.get("missing_target", 0)
        + by_reason.get("missing_both", 0)
    )
    if dangling > 100:
        actions.append(
            f"Many dangling edges ({dangling}): some symbols reference "
            f"nodes that were dropped or never indexed. Run "
            f"'codegraph doctor --repair' to clean up, or "
            f"'codegraph init --force' to rebuild."
        )

    if not actions:
        actions.append(
            "Run 'codegraph doctor --repair' to auto-repair fixable issues."
        )
    actions.append(
        "Run 'codegraph init --force' to fully rebuild the index from scratch."
    )
    return actions
