"""Edge type and node type normalization — deterministic alias mapping.

Maps non-canonical type strings (from language extractors/resolvers)
to canonical :class:`EdgeType` and :class:`NodeType` values before
validation. No LLM, no heuristics — pure dictionary lookup.

This module is the defense-in-depth layer: even if a language extractor
produces a non-canonical edge type (e.g. Java's ``implements``),
it is normalized here rather than silently dropped.
"""

from __future__ import annotations

from codegraph.graph.models import (
    AutoCorrectReason,
    EdgeType,
    NodeType,
)

# ── Edge type aliases ─────────────────────────────────────────────────

EDGE_TYPE_ALIASES: dict[str, EdgeType] = {
    # === Common aliases (from various language extractors) ===
    "implements": EdgeType.inherits,       # Java implements → inherits
    "extends":    EdgeType.inherits,       # Java/TS extends → inherits
    "uses":       EdgeType.depends_on,     # generic uses → depends_on
    "tested":     EdgeType.tested_by,      # shortened form → tested_by
    "routes":     EdgeType.routes_to,      # shortened form → routes_to
    "import":     EdgeType.imports,        # singular form → imports
    "call":       EdgeType.calls,          # singular form → calls
    "inherit":    EdgeType.inherits,       # singular form → inherits
    "reference":  EdgeType.references,     # singular form → references
    "contain":    EdgeType.contains,       # singular form → contains
    "define_in":  EdgeType.defined_in,     # alternate spelling
    "depend_on":  EdgeType.depends_on,     # alternate spelling
    "route_to":   EdgeType.routes_to,      # alternate spelling
    "test_by":    EdgeType.tested_by,      # alternate spelling

    # === Canonical self-mappings (always accept canonical names) ===
    "contains":    EdgeType.contains,
    "defined_in":  EdgeType.defined_in,
    "imports":     EdgeType.imports,
    "calls":       EdgeType.calls,
    "inherits":    EdgeType.inherits,
    "references":  EdgeType.references,
    "tested_by":   EdgeType.tested_by,
    "routes_to":   EdgeType.routes_to,
    "depends_on":  EdgeType.depends_on,
}

# ── Node type aliases ─────────────────────────────────────────────────

NODE_TYPE_ALIASES: dict[str, NodeType] = {
    # === Language-specific aliases ===
    "func":         NodeType.function,     # Python/Go shorthand
    "cls":          NodeType.class_,       # Python shorthand
    "iface":        NodeType.class_,       # Java interface → class
    "interface":    NodeType.class_,       # Java/TS interface → class
    "enum":         NodeType.class_,       # Java enum → class
    "struct":       NodeType.class_,       # Go struct → class
    "var":          NodeType.function,     # Go/C# variable (best fit)
    "const":        NodeType.function,     # Go const (best fit)
    "typedef":      NodeType.class_,       # C#/TS type alias → class

    # === Canonical self-mappings ===
    "repository":      NodeType.repository,
    "file":            NodeType.file,
    "module":          NodeType.module,
    "class":           NodeType.class_,
    "function":        NodeType.function,
    "method":          NodeType.method,
    "import":          NodeType.import_,
    "external_symbol": NodeType.external_symbol,
    "test":            NodeType.test,
    "route":           NodeType.route,
    "controller":      NodeType.controller,
    "service":         NodeType.service,
    "component":       NodeType.component,
}

# ── Public API ────────────────────────────────────────────────────────


def normalize_edge_type(
    raw: str,
) -> tuple[EdgeType | None, AutoCorrectReason | None]:
    """Normalize a raw edge type string to canonical :class:`EdgeType`.

    Args:
        raw: Raw edge type string from an extractor or resolver.

    Returns:
        ``(canonical_type, correction_reason)`` where ``correction_reason``
        is ``None`` if the type was already canonical, and ``canonical_type``
        is ``None`` if no alias match was found.
    """
    if not isinstance(raw, str):
        return None, None
    key = raw.lower().strip()
    canonical = EDGE_TYPE_ALIASES.get(key)
    if canonical is None:
        return None, None
    if canonical.value == key:
        return canonical, None  # already canonical
    return canonical, AutoCorrectReason.type_alias_corrected


def normalize_node_type(
    raw: str,
) -> tuple[NodeType | None, AutoCorrectReason | None]:
    """Normalize a raw node type string to canonical :class:`NodeType`.

    Args:
        raw: Raw node type string from an extractor.

    Returns:
        ``(canonical_type, correction_reason)`` where ``correction_reason``
        is ``None`` if the type was already canonical, and ``canonical_type``
        is ``None`` if no alias match was found.
    """
    if not isinstance(raw, str):
        return None, None
    key = raw.lower().strip()
    canonical = NODE_TYPE_ALIASES.get(key)
    if canonical is None:
        return None, None
    if canonical.value == key:
        return canonical, None  # already canonical
    return canonical, AutoCorrectReason.symbol_kind_normalized
