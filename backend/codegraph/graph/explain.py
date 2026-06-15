"""Deterministic symbol/file explanation using indexed metadata and heuristics.

Produces structured, evidence-backed explanations of symbols and files
without LLMs, embeddings, or external APIs. Every explanation cites its
evidence sources (docstring, signature, callee names, snippet content).

Part of the CodeGraph MCP tool suite — used by ``codegraph_explain``.
"""

from __future__ import annotations

from typing import Any

from codegraph.graph.models import EdgeType, GraphNode, NodeType
from codegraph.graph.store import GraphStore
from codegraph.graph.test_coverage import is_test_file_path


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════


def explain_symbol(
    store: GraphStore,
    node: GraphNode,
    *,
    include_snippet: bool = True,
    include_tests: bool = True,
    include_relationships: bool = True,
    max_snippet_lines: int = 40,
    project_root: str | None = None,
    source_snippet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce a structured explanation for a single symbol.

    Args:
        store: In-memory graph store for relationship lookups.
        node: The resolved symbol node to explain.
        include_snippet: If True, include source snippet in the result.
        include_tests: If True, include test coverage signal.
        include_relationships: If True, include top callers/callees.
        max_snippet_lines: Maximum lines for the source snippet.
        project_root: Project root for resolving file paths.
        source_snippet: Pre-read source snippet dict (from ``_read_source_snippet``).
                        If None and ``include_snippet`` is True, the snippet will
                        be ``{"included": false, ...}``.
    """
    # ── Collect callee names ────────────────────────────────────────────
    callee_names: list[str] = []
    for edge in store.get_outgoing_edges(node.id):
        if edge.type == EdgeType.calls:
            callee_node = store.get_node(edge.target)
            if callee_node and callee_node.name:
                callee_names.append(callee_node.name)

    # ── Collect import target names ──────────────────────────────────────
    import_targets: list[str] = []
    for edge in store.get_outgoing_edges(node.id):
        if edge.type == EdgeType.imports:
            tgt = store.get_node(edge.target)
            if tgt and tgt.name:
                import_targets.append(tgt.name)

    # Extract snippet text for signal detection
    snippet_text: str | None = None
    if source_snippet and source_snippet.get("included") and source_snippet.get("content"):
        snippet_text = source_snippet["content"]

    # ── Generate summary ─────────────────────────────────────────────────
    summary_text, confidence, basis = _generate_summary(node, callee_names, snippet_text)

    # ── Build implementation signals ─────────────────────────────────────
    signals = _build_implementation_signals(node, callee_names, import_targets, snippet_text)

    # ── Build evidence ───────────────────────────────────────────────────
    evidence = _build_evidence(node, callee_names, basis, source_snippet)

    # ── Build target block ───────────────────────────────────────────────
    target: dict[str, Any] = {
        "kind": "symbol",
        "symbol": node.name,
        "symbol_id": node.id,
        "type": node.type.value if isinstance(node.type, NodeType) else str(node.type),
        "file": node.file_path,
    }
    if node.location:
        target["line_start"] = node.location.line_start
        target["line_end"] = node.location.line_end

    # ── Build relationships ──────────────────────────────────────────────
    relationships: dict[str, Any] = _build_relationships_section(
        store, node.id, include_relationships
    )

    # ── Build test signal ────────────────────────────────────────────────
    test_signal: dict[str, Any] = _build_test_signal_for_symbol(
        store, node.id, node.file_path, project_root, include_tests
    )

    # ── Build warnings ───────────────────────────────────────────────────
    warnings: list[dict[str, Any]] = []
    if confidence == "unknown":
        warnings.append({
            "type": "low_confidence",
            "severity": "info",
            "message": (
                "Insufficient evidence for an automated explanation. "
                "Consider reading the source directly."
            ),
        })

    # ── Source snippet (pass-through) ────────────────────────────────────
    snippet_block: dict[str, Any]
    if include_snippet and source_snippet and source_snippet.get("included"):
        snippet_block = {
            "file": node.file_path,
            "line_start": source_snippet.get("source_line_start", node.location.line_start if node.location else None),
            "line_end": source_snippet.get("source_line_end", node.location.line_end if node.location else None),
            "snippet": source_snippet.get("content", ""),
            "truncated": source_snippet.get("truncated", False),
        }
    else:
        snippet_block = {"included": False, "content": None, "truncated": False}

    # ── Enrichment block (if available) ──────────────────────────────────
    enrichment: dict[str, Any] | None = None
    if getattr(node, "enrichment_status", "") == "analyzed":
        enrichment = {}
        if getattr(node, "summary", ""):
            enrichment["summary"] = node.summary
        if getattr(node, "role", ""):
            enrichment["role"] = node.role
        if getattr(node, "responsibilities", []):
            enrichment["responsibilities"] = node.responsibilities
        if getattr(node, "edge_cases", []):
            enrichment["edge_cases"] = node.edge_cases
        if getattr(node, "test_relevance", ""):
            enrichment["test_relevance"] = node.test_relevance
        if getattr(node, "enrichment_confidence", ""):
            enrichment["confidence"] = node.enrichment_confidence
        if getattr(node, "enrichment_evidence", []):
            enrichment["evidence"] = node.enrichment_evidence

    result: dict[str, Any] = {
        "target": target,
        "explanation": {
            "summary": summary_text,
            "confidence": confidence,
            "basis": basis,
        },
        "implementation_signals": signals,
        "relationships": relationships,
        "test_signal": test_signal,
        "source_snippet": snippet_block,
        "evidence": evidence,
        "warnings": warnings,
    }
    if enrichment:
        result["enrichment"] = enrichment
    return result


def explain_file(
    store: GraphStore,
    file_path: str,
    *,
    include_tests: bool = True,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Produce a structured explanation for an entire file.

    Collects all symbols belonging to ``file_path`` and produces an
    aggregated view: primary symbols, likely role, aggregated signals,
    and test coverage overview.
    """
    normalized = file_path.replace("\\", "/")

    # ── Collect symbols in this file ────────────────────────────────────
    symbols: list[GraphNode] = []
    for n in store.all_nodes():
        node_path = (n.file_path or "").replace("\\", "/")
        if node_path == normalized or node_path.endswith("/" + normalized):
            symbols.append(n)

    if not symbols:
        return {
            "target": {"kind": "file", "file": file_path},
            "primary_symbols": [],
            "symbol_count": 0,
            "likely_role": "unknown",
            "likely_role_confidence": "unknown",
            "implementation_signals": {},
            "test_signal": _empty_test_signal(),
            "warnings": [{
                "type": "no_symbols",
                "severity": "info",
                "message": f"No indexed symbols found for file '{file_path}'.",
            }],
        }

    # ── Rank and select primary symbols ──────────────────────────────────
    primary_symbols = _rank_symbols_for_file(symbols)
    primary_count = len(primary_symbols)

    # ── Infer likely role ────────────────────────────────────────────────
    likely_role, role_confidence = _infer_file_role(file_path, symbols)

    # ── Aggregate implementation signals across symbols ──────────────────
    # For the file level, we collect all callee names and imports from
    # all symbols and detect signals from the union. We also check
    # individual symbol tags/types.
    all_callee_names: list[str] = []
    all_import_targets: list[str] = []
    has_route = False
    for sym in symbols:
        for edge in store.get_outgoing_edges(sym.id):
            if edge.type == EdgeType.calls:
                callee_node = store.get_node(edge.target)
                if callee_node and callee_node.name:
                    all_callee_names.append(callee_node.name)
            elif edge.type == EdgeType.imports:
                tgt = store.get_node(edge.target)
                if tgt and tgt.name:
                    all_import_targets.append(tgt.name)
        if sym.tags and "route" in sym.tags:
            has_route = True
        if isinstance(sym.type, NodeType) and sym.type in (NodeType.route, NodeType.controller):
            has_route = True

    # Deduplicate
    all_callee_names = list(dict.fromkeys(all_callee_names))
    all_import_targets = list(dict.fromkeys(all_import_targets))

    # Create a synthetic node for signal detection
    synthetic = GraphNode(
        id="__explain_file_synthetic__",
        type=NodeType.file,
        name=file_path,
        file_path=file_path,
        tags=["route"] if has_route else [],
    )
    aggregated_signals = _build_implementation_signals(synthetic, all_callee_names, all_import_targets, None)

    # ── Test signal per file ────────────────────────────────────────────
    test_signal: dict[str, Any] = _empty_test_signal()
    if include_tests:
        test_signal = _build_test_signal_for_file(store, symbols, project_root)

    # ── Warnings ─────────────────────────────────────────────────────────
    warnings: list[dict[str, Any]] = []
    if role_confidence == "unknown":
        warnings.append({
            "type": "low_confidence_role",
            "severity": "info",
            "message": "Could not confidently infer the file's role from path, symbols, or tags.",
        })

    return {
        "target": {"kind": "file", "file": file_path},
        "primary_symbols": [
            {
                "symbol_id": sym.id,
                "name": sym.name,
                "type": sym.type.value if isinstance(sym.type, NodeType) else str(sym.type),
                "line_start": sym.location.line_start if sym.location else None,
                "line_end": sym.location.line_end if sym.location else None,
                "tags": sym.tags,
            }
            for sym in primary_symbols
        ],
        "symbol_count": len(symbols),
        "primary_count": primary_count,
        "likely_role": likely_role,
        "likely_role_confidence": role_confidence,
        "implementation_signals": aggregated_signals,
        "test_signal": test_signal,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Summary generation
# ═══════════════════════════════════════════════════════════════════════════════


def _generate_summary(
    node: GraphNode,
    callee_names: list[str],
    snippet_text: str | None,
) -> tuple[str, str, list[str]]:
    """Generate a short summary with confidence and basis tags.

    Priority:
    1. Docstring — first sentence or first 160 chars.
    2. Symbol name + type heuristic.
    3. Callee names pattern.
    4. Fallback: insufficient evidence.

    Returns ``(summary_text, confidence, basis_tags)``.
    """
    # ── Priority 1: Docstring ────────────────────────────────────────────
    if node.docstring and node.docstring.strip():
        ds = node.docstring.strip()
        # Extract first sentence (up to ".", "\n", or 160 chars)
        first_sentence = _first_sentence(ds)
        return (first_sentence, "medium", ["docstring"])

    # ── Priority 2: Symbol name + type ───────────────────────────────────
    name_summary = _summary_from_name(node)
    if name_summary:
        return (name_summary, "low", ["symbol_name", "signature"])

    # ── Priority 3: Callee names pattern ─────────────────────────────────
    if callee_names:
        top = callee_names[:3]
        names_str = ", ".join(top)
        if len(callee_names) > 3:
            names_str += ", ..."
        summary = f"Calls {names_str}."
        return (summary, "low", ["callees"])

    # ── Priority 4: Insufficient evidence ────────────────────────────────
    return (
        "Insufficient indexed evidence to explain this symbol.",
        "unknown",
        [],
    )


def _first_sentence(text: str) -> str:
    """Extract the first sentence from a docstring (max 160 chars)."""
    # Find first sentence boundary: period followed by space/newline/end, or newline
    for i, ch in enumerate(text):
        if ch == "\n":
            candidate = text[:i].strip()
            if candidate:
                return candidate[:160]
            break
        if ch == "." and (i + 1 >= len(text) or text[i + 1] in (" ", "\n")):
            return text[:i + 1].strip()[:160]

    # No boundary found — return up to 160 chars
    return text[:160].strip()


def _summary_from_name(node: GraphNode) -> str | None:
    """Generate a summary from symbol name and type.

    Uses heuristics: verb-noun patterns, underscore-separated names,
    common prefixes (get_, set_, is_, has_, handle_, compute_, etc.).
    """
    name = node.name
    if not name or name.startswith("__"):
        return None

    node_type = node.type.value if isinstance(node.type, NodeType) else str(node.type)

    # Common verb prefixes and their meanings
    verb_meanings: dict[str, str] = {
        "get_": "Retrieves",
        "fetch_": "Fetches",
        "set_": "Sets",
        "is_": "Checks whether",
        "has_": "Checks whether",
        "handle_": "Handles",
        "process_": "Processes",
        "compute_": "Computes",
        "build_": "Builds",
        "create_": "Creates",
        "delete_": "Deletes",
        "remove_": "Removes",
        "update_": "Updates",
        "parse_": "Parses",
        "validate_": "Validates",
        "save_": "Saves",
        "load_": "Loads",
        "render_": "Renders",
        "resolve_": "Resolves",
        "format_": "Formats",
        "convert_": "Converts",
        "transform_": "Transforms",
        "find_": "Finds",
        "search_": "Searches",
        "check_": "Checks",
        "run_": "Runs",
        "start_": "Starts",
        "stop_": "Stops",
        "init_": "Initializes",
        "setup_": "Sets up",
        "teardown_": "Tears down",
        "register_": "Registers",
        "apply_": "Applies",
        "generate_": "Generates",
        "calculate_": "Calculates",
        "read_": "Reads",
        "write_": "Writes",
        "send_": "Sends",
        "receive_": "Receives",
    }

    for prefix, verb in verb_meanings.items():
        if name.startswith(prefix) and len(name) > len(prefix):
            remainder = name[len(prefix):].replace("_", " ")
            return f"{verb} {remainder}."

    # Check for camelCase verb patterns
    camel_verbs = {
        "get": "Retrieves",
        "fetch": "Fetches",
        "set": "Sets",
        "is": "Checks whether",
        "has": "Checks whether",
        "handle": "Handles",
        "process": "Processes",
        "compute": "Computes",
        "build": "Builds",
        "create": "Creates",
        "delete": "Deletes",
        "remove": "Removes",
        "update": "Updates",
        "parse": "Parses",
        "validate": "Validates",
        "save": "Saves",
        "load": "Loads",
        "render": "Renders",
        "resolve": "Resolves",
        "format": "Formats",
        "convert": "Converts",
        "transform": "Transforms",
        "find": "Finds",
        "search": "Searches",
        "check": "Checks",
        "run": "Runs",
        "start": "Starts",
        "stop": "Stops",
        "init": "Initializes",
        "register": "Registers",
        "apply": "Applies",
        "generate": "Generates",
        "calculate": "Calculates",
        "read": "Reads",
        "write": "Writes",
        "send": "Sends",
    }

    for verb, meaning in camel_verbs.items():
        if name.startswith(verb) and len(name) > len(verb) and name[len(verb)].isupper():
            remainder = name[len(verb):]
            # Split camelCase
            remainder_spaced = _camel_to_space(remainder)
            return f"{meaning} {remainder_spaced}."

    # If name contains underscores but no known prefix
    if "_" in name:
        parts = name.replace("_", " ")
        if node_type in ("function", "method"):
            return f"Function handling {parts}."
        elif node_type == "class_":
            return f"Class representing {parts}."
        return f"Symbol related to {parts}."

    return None


def _camel_to_space(text: str) -> str:
    """Convert camelCase to space-separated lowercase."""
    result: list[str] = []
    for ch in text:
        if ch.isupper() and result:
            result.append(" ")
        result.append(ch.lower())
    return "".join(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Implementation signals
# ═══════════════════════════════════════════════════════════════════════════════

# Keywords for signal detection (all lowercase, matched via substring).
# Each keyword is designed to match within callee names OR snippet text.
# Keywords ending with "(" target function-call patterns in snippet text.
# Keywords without "(" target names of callees, imports, or symbols.
_JSON_KEYWORDS = {
    "json.loads", "json.dumps", "json.load", "json.dump",
    "jsonify", "json_", "fromjson", "tojson", "json",
    "serialize", "deserialize", "marshal", "unmarshal",
}
_DB_KEYWORDS = {
    "sql", "query", "execute", "commit", "rollback",
    "cursor", "fetchone", "fetchall", "fetchmany",
    "prisma", "sqlite", "sqlalchemy", "psycopg", "mysql",
    "orm", "repository", "migrate",
}
_IO_KEYWORDS = {
    "open(", "read(", "write(", "readfile", "writefile",
    "fopen", "fclose", "mkdir", "rmdir", "listdir", "scandir",
    "readlines", "writelines",
}
_NETWORK_KEYWORDS = {
    "http", "https", "request", "fetch", "axios",
    "curl", "url", "socket", "tcp",
    "getrequest", "postrequest", "apiclient", "restclient", "httpx",
}
_ERROR_KEYWORDS = {
    "try", "except", "catch", "raise ", "throw ",
    "try:", "except ", "catch(",
}
_ASYNC_KEYWORDS = {"async", "await", "coroutine", "asyncio", "future", "promise"}


def _build_implementation_signals(
    node: GraphNode,
    callee_names: list[str],
    import_targets: list[str],
    snippet_text: str | None,
) -> dict[str, bool]:
    """Detect implementation signals from callees, imports, tags, and snippet.

    All matching is case-insensitive substring matching on lowercased strings.
    """
    callee_str = " ".join(callee_names).lower()
    import_str = " ".join(import_targets).lower()
    snippet_str = (snippet_text or "").lower()
    tags_lower = [t.lower() for t in (node.tags or [])]

    combined = f"{callee_str} {import_str} {snippet_str}"

    node_type = node.type.value if isinstance(node.type, NodeType) else str(node.type)

    return {
        "uses_json": _has_any_keyword(combined, _JSON_KEYWORDS),
        "uses_database": _has_any_keyword(combined, _DB_KEYWORDS),
        "uses_io": _has_any_keyword(combined, _IO_KEYWORDS),
        "uses_network": _has_any_keyword(combined, _NETWORK_KEYWORDS),
        "has_error_handling": _has_any_keyword(combined, _ERROR_KEYWORDS),
        "is_framework_entry": (
            node_type in ("route", "controller")
            or "route" in tags_lower
        ),
        "is_test_code": is_test_file_path(node.file_path),
        "uses_async": _has_any_keyword(combined, _ASYNC_KEYWORDS),
    }


def _has_any_keyword(text: str, keywords: set[str]) -> bool:
    """Check if any keyword from the set appears in the text (case-insensitive substring)."""
    return any(kw in text for kw in keywords)


# ═══════════════════════════════════════════════════════════════════════════════
# Evidence building
# ═══════════════════════════════════════════════════════════════════════════════


def _build_evidence(
    node: GraphNode,
    callee_names: list[str],
    basis: list[str],
    source_snippet: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build structured evidence entries from the available data sources."""
    evidence: list[dict[str, Any]] = []

    # Symbol metadata
    metadata_reasons: list[str] = []
    metadata_reasons.append(f"Symbol type is {node.type.value if isinstance(node.type, NodeType) else str(node.type)}.")
    if node.signature:
        metadata_reasons.append(f"Signature: {node.signature}")
    if node.tags:
        metadata_reasons.append(f"Tags: {', '.join(node.tags)}")
    evidence.append({
        "type": "symbol_metadata",
        "reason": " ".join(metadata_reasons),
    })

    # Docstring
    if node.docstring and node.docstring.strip():
        evidence.append({
            "type": "docstring",
            "reason": _first_sentence(node.docstring.strip()),
        })

    # Signature
    if node.signature:
        evidence.append({
            "type": "signature",
            "reason": node.signature,
        })

    # Callees
    if callee_names:
        top_callees = callee_names[:5]
        evidence.append({
            "type": "callees",
            "reason": f"Top callees: {', '.join(top_callees)}.",
            "callee_names": top_callees,
        })

    # File path
    if node.file_path:
        evidence.append({
            "type": "file_path",
            "reason": f"Defined in {node.file_path}.",
        })

    # Source snippet
    if source_snippet and source_snippet.get("included") and source_snippet.get("content"):
        excerpt = source_snippet["content"][:200]
        truncated_note = " (truncated)" if len(source_snippet["content"]) > 200 else ""
        evidence.append({
            "type": "source_snippet",
            "reason": f"Source excerpt{truncated_note}: {repr(excerpt)}",
        })

    return evidence


# ═══════════════════════════════════════════════════════════════════════════════
# Relationships
# ═══════════════════════════════════════════════════════════════════════════════


def _build_relationships_section(
    store: GraphStore,
    node_id: str,
    include_relationships: bool,
) -> dict[str, Any]:
    """Build the relationships block: counts and top callers/callees."""
    if not include_relationships:
        return {
            "callers_count": 0,
            "callees_count": 0,
            "top_callers": [],
            "top_callees": [],
        }

    # ── Collect callers ──────────────────────────────────────────────────
    callers: list[dict[str, Any]] = []
    for edge in store.get_incoming_edges(node_id):
        if edge.type == EdgeType.calls:
            caller_node = store.get_node(edge.source)
            if caller_node and caller_node.type != NodeType.test:
                callers.append({
                    "symbol_id": edge.source,
                    "name": caller_node.name,
                    "type": caller_node.type.value if isinstance(caller_node.type, NodeType) else str(caller_node.type),
                    "file_path": caller_node.file_path,
                    "confidence": edge.confidence,
                })

    # ── Collect callees ──────────────────────────────────────────────────
    callees: list[dict[str, Any]] = []
    for edge in store.get_outgoing_edges(node_id):
        if edge.type == EdgeType.calls:
            callee_node = store.get_node(edge.target)
            if callee_node:
                callees.append({
                    "symbol_id": edge.target,
                    "name": callee_node.name,
                    "type": callee_node.type.value if isinstance(callee_node.type, NodeType) else str(callee_node.type),
                    "file_path": callee_node.file_path,
                    "confidence": edge.confidence,
                })

    # Sort by confidence descending, take top 5
    callers.sort(key=lambda c: c["confidence"], reverse=True)
    callees.sort(key=lambda c: c["confidence"], reverse=True)

    return {
        "callers_count": len(callers),
        "callees_count": len(callees),
        "top_callers": callers[:5],
        "top_callees": callees[:5],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Test signal
# ═══════════════════════════════════════════════════════════════════════════════

TESTED_BY_HIGH_CONFIDENCE_THRESHOLD = 0.75


def _build_test_signal_for_symbol(
    store: GraphStore,
    node_id: str,
    node_file_path: str,
    project_root: str | None,
    include_tests: bool,
) -> dict[str, Any]:
    """Build test coverage signal focused on a single symbol.

    Checks both incoming and outgoing edges for tested_by relationships,
    since the direction convention may vary across indexers.
    """
    if not include_tests:
        return _empty_test_signal()

    related_tests: list[dict[str, Any]] = []
    high_conf = 0
    low_conf = 0

    # Check both incoming and outgoing tested_by edges
    all_edges = list(store.get_incoming_edges(node_id)) + list(store.get_outgoing_edges(node_id))
    seen_edge_ids: set[str] = set()

    for edge in all_edges:
        if edge.id and edge.id in seen_edge_ids:
            continue
        if edge.id:
            seen_edge_ids.add(edge.id)

        if edge.type == EdgeType.tested_by:
            # Determine which side is the test node
            src_node = store.get_node(edge.source)
            tgt_node = store.get_node(edge.target)
            test_node = None
            if src_node and src_node.type == NodeType.test:
                test_node = src_node
            elif tgt_node and tgt_node.type == NodeType.test:
                test_node = tgt_node

            if test_node is None:
                continue

            conf = edge.confidence
            conf_level = "high_confidence" if conf >= TESTED_BY_HIGH_CONFIDENCE_THRESHOLD else "low_confidence"
            if conf >= TESTED_BY_HIGH_CONFIDENCE_THRESHOLD:
                high_conf += 1
            else:
                low_conf += 1
            related_tests.append({
                "symbol": test_node.name,
                "symbol_id": test_node.id,
                "file": test_node.file_path,
                "confidence": conf,
                "confidence_level": conf_level,
                "reason": "Linked by tested_by edge.",
            })
        elif edge.type == EdgeType.calls:
            # Only count when a test node CALLS this production symbol
            # (i.e. incoming calls edge where source is a test).
            # Outgoing calls (production→test helper) do NOT indicate coverage.
            if edge.target == node_id:
                caller_node = store.get_node(edge.source)
                if caller_node and caller_node.type == NodeType.test:
                    conf = edge.confidence
                    conf_level = "high_confidence" if conf >= TESTED_BY_HIGH_CONFIDENCE_THRESHOLD else "low_confidence"
                    related_tests.append({
                        "symbol": caller_node.name,
                        "symbol_id": caller_node.id,
                        "file": caller_node.file_path,
                        "confidence": conf,
                        "confidence_level": conf_level,
                        "reason": "Test calls this symbol via calls edge.",
                    })

    # Deduplicate by symbol_id
    seen: set[str] = set()
    unique_tests: list[dict[str, Any]] = []
    for t in related_tests:
        if t["symbol_id"] not in seen:
            seen.add(t["symbol_id"])
            unique_tests.append(t)

    # Determine status
    if not unique_tests:
        status = "none"
    elif high_conf > 0:
        status = "high_confidence"
    elif low_conf > 0:
        status = "low_confidence"
    else:
        status = "unknown"

    return {
        "status": status,
        "tested_by_count": len(unique_tests),
        "related_tests": unique_tests[:5],
    }


def _build_test_signal_for_file(
    store: GraphStore,
    symbols: list[GraphNode],
    project_root: str | None,
) -> dict[str, Any]:
    """Aggregate test signal across all symbols in a file."""
    if not symbols:
        return _empty_test_signal()

    all_related: list[dict[str, Any]] = []
    for sym in symbols:
        sig = _build_test_signal_for_symbol(store, sym.id, sym.file_path, project_root, True)
        all_related.extend(sig.get("related_tests", []))

    # Deduplicate by symbol_id
    seen: set[str] = set()
    unique_tests: list[dict[str, Any]] = []
    high_conf = 0
    low_conf = 0
    for t in all_related:
        if t["symbol_id"] not in seen:
            seen.add(t["symbol_id"])
            unique_tests.append(t)
            if t["confidence_level"] == "high_confidence":
                high_conf += 1
            else:
                low_conf += 1

    if not unique_tests:
        status = "none"
    elif high_conf > 0:
        status = "high_confidence"
    elif low_conf > 0:
        status = "low_confidence"
    else:
        status = "unknown"

    return {
        "status": status,
        "tested_by_count": len(unique_tests),
        "related_tests": unique_tests[:5],
    }


def _empty_test_signal() -> dict[str, Any]:
    """Return an empty test signal block."""
    return {
        "status": "unknown",
        "tested_by_count": 0,
        "related_tests": [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# File-level helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _rank_symbols_for_file(symbols: list[GraphNode]) -> list[GraphNode]:
    """Rank and return top 8 primary symbols for a file.

    Excludes test symbols and dunder methods. Prefers symbols with
    docstrings, route/controller types, and public visibility.
    """
    ranked: list[tuple[int, GraphNode]] = []
    for sym in symbols:
        # Skip test symbols
        if sym.type == NodeType.test:
            continue
        # Skip dunder methods
        if sym.name.startswith("__"):
            continue
        # Skip file-type nodes (they're just containers)
        if sym.type == NodeType.file:
            continue

        score = 0
        if sym.docstring and sym.docstring.strip():
            score += 10
        sym_type = sym.type.value if isinstance(sym.type, NodeType) else str(sym.type)
        if sym_type in ("route", "controller", "service"):
            score += 8
        if sym.tags:
            score += len(sym.tags) * 2
        if sym.visibility == "public":
            score += 3
        if sym.signature:
            score += 2

        ranked.append((-score, sym))

    ranked.sort(key=lambda x: x[0])
    return [sym for _, sym in ranked[:8]]


def _infer_file_role(
    file_path: str,
    symbols: list[GraphNode],
) -> tuple[str, str]:
    """Infer a file's likely role from path, symbol types, and tags.

    Returns ``(likely_role_text, confidence)``.
    """
    normalized = file_path.replace("\\", "/").lower()
    roles: list[str] = []
    confidences: list[float] = []

    # ── Path-based inference ─────────────────────────────────────────────
    path_roles = {
        "api": ("API endpoint / route handler", 0.7),
        "routes": ("API endpoint / route handler", 0.7),
        "route": ("API endpoint / route handler", 0.7),
        "controller": ("Controller logic", 0.7),
        "models": ("Data model / schema definitions", 0.8),
        "model": ("Data model / schema definitions", 0.8),
        "entities": ("Data model / schema definitions", 0.7),
        "services": ("Service / business logic layer", 0.7),
        "service": ("Service / business logic layer", 0.7),
        "utils": ("Utility / helper functions", 0.6),
        "util": ("Utility / helper functions", 0.6),
        "helpers": ("Utility / helper functions", 0.6),
        "config": ("Configuration", 0.8),
        "settings": ("Configuration", 0.8),
        "store": ("Data persistence / storage layer", 0.7),
        "storage": ("Data persistence / storage layer", 0.7),
        "repository": ("Data access / repository layer", 0.7),
        "middleware": ("Middleware", 0.8),
        "hooks": ("Hook / lifecycle handlers", 0.7),
        "tests": ("Test code", 0.9),
        "test": ("Test code", 0.9),
        "spec": ("Test code", 0.9),
        "__tests__": ("Test code", 0.9),
        "migrations": ("Database migration", 0.8),
        ".github/workflows": ("CI / automation workflow", 0.9),
        "docker": ("Container / deployment configuration", 0.9),
        "terraform": ("Infrastructure as code", 0.9),
        "docs": ("Documentation", 0.8),
    }

    file_name_roles = {
        "dockerfile": ("Container / deployment configuration", "high"),
        "docker-compose.yml": ("Container orchestration configuration", "high"),
        "docker-compose.yaml": ("Container orchestration configuration", "high"),
        "package.json": ("JavaScript package and script configuration", "high"),
        "pyproject.toml": ("Python package and tool configuration", "high"),
        "requirements.txt": ("Python dependency manifest", "medium"),
        ".env.example": ("Environment variable configuration example", "high"),
        "tsconfig.json": ("TypeScript compiler configuration", "high"),
    }
    base_name = normalized.rsplit("/", 1)[-1]
    if normalized.startswith(".github/workflows/"):
        return ("CI / automation workflow", "high")
    if base_name in file_name_roles:
        return file_name_roles[base_name]
    if base_name.startswith("next.config."):
        return ("Next.js application configuration", "high")
    if base_name.startswith("vite.config."):
        return ("Vite build configuration", "high")
    if normalized.endswith(".graphql") or normalized.endswith(".gql"):
        return ("GraphQL schema definition", "high")
    if normalized.endswith(".tf"):
        return ("Infrastructure as code", "high")

    for path_segment, (role, conf) in path_roles.items():
        if f"/{path_segment}/" in f"/{normalized}/" or normalized.startswith(f"{path_segment}/"):
            roles.append(role)
            confidences.append(conf)
            break  # First path match wins

    # ── Symbol-based inference ───────────────────────────────────────────
    tag_roles: dict[str, str] = {}
    for sym in symbols:
        if sym.tags:
            for tag in sym.tags:
                tag_lower = tag.lower()
                if "route" in tag_lower:
                    tag_roles["route"] = "Contains route handler(s)."
                elif "model" in tag_lower:
                    tag_roles["model"] = "Contains data model(s)."
                elif "config" in tag_lower:
                    tag_roles["config"] = "Contains configuration."
                elif "store" in tag_lower or "persistence" in tag_lower:
                    tag_roles["store"] = "Contains storage/persistence logic."

        sym_type = sym.type.value if isinstance(sym.type, NodeType) else str(sym.type)
        if sym_type == "route":
            tag_roles["route"] = "Contains route handler(s)."
        elif sym_type == "controller":
            tag_roles["controller"] = "Contains controller logic."
        elif sym_type == "service":
            tag_roles["service"] = "Contains service/business logic."

    if tag_roles:
        # Symbol-based takes priority over path-based if more specific
        role_text = "; ".join(tag_roles.values())
        conf = 0.75
        return (role_text, "medium")

    if roles:
        return (roles[0], "medium" if confidences[0] >= 0.8 else "low")

    # ── Default ──────────────────────────────────────────────────────────
    # Check if it looks like a test file via heuristic
    if is_test_file_path(file_path):
        return ("Test code", "medium")

    return ("unknown", "unknown")
