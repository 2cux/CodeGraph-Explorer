"""Entry point ranking and relevance scoring for Context Pack.

PRD §14.3 — Entry point ranking rules.

Scoring signals (weighted, combined):
  1. Exact symbol name match (0.95)
  2. CamelCase / snake_case decomposition match (0.82)
  3. Prefix match (0.85)
  4. Substring name match (0.80)
  5. Exact file basename match (0.85)
  6. Qualified name match (0.85)
  7. Directory component match (0.78)
  8. Arbitrary path substring (0.70)
  9. Module name match (0.70)
  10. Docstring match (0.60)
  11. Framework entry point boost (+0.10, baseline 0.72)
  12. Production file boost (+0.03)
  13. Test penalty (conditional on query intent): max 0.55 (test type) / 0.65 (test path)
"""

import re
from typing import TYPE_CHECKING

from codegraph.graph.models import NodeType
from codegraph.utils.path_utils import (
    is_test_path,
    is_production_path,
    is_test_intent_query,
    is_framework_entry_point,
    FW_ENTRY_TYPES,
)

if TYPE_CHECKING:
    from codegraph.graph.models import GraphNode

_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "can", "could",
    "shall", "should", "may", "might", "must", "to", "of", "in", "for", "on",
    "with", "at", "by", "from", "as", "into", "through", "during", "before",
    "after", "above", "below", "between", "out", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "because", "but", "and", "or",
    "if", "while", "that", "this", "these", "those", "it", "its", "add",
    "change", "update", "fix", "implement", "need", "want", "make", "get",
    "set", "use", "using", "used", "based", "also", "see", "seealso",
    "return", "returns", "param", "type", "note", "example",
})

# ── CamelCase / snake_case decomposition ────────────────────────────────

# Splits on: lower→Upper boundary, ACRONYM→Word boundary, _ and - separators
_CAMEL_SPLIT_RE = re.compile(
    r'(?<=[a-z0-9])(?=[A-Z])'
    r'|(?<=[A-Z])(?=[A-Z][a-z])'
    r'|[_\-]+'
)


def _decompose_name(name: str) -> set[str]:
    """Split a symbol name into its constituent words.

    ``"MemoryService"`` → ``{"memory", "service"}``
    ``"find_related_ccrs"`` → ``{"find", "related", "ccrs"}``
    ``"SQLQueryBuilder"`` → ``{"sql", "query", "builder"}``
    """
    if not name:
        return set()
    parts = [p.lower() for p in _CAMEL_SPLIT_RE.split(name) if len(p) > 1]
    result: set[str] = set(parts)
    # Also try splitting by number boundaries e.g. "get2fa" → ["get", "2fa"]
    for p in list(result):
        num_split = re.split(r'(?<=\D)(?=\d)|(?<=\d)(?=\D)', p)
        for ns in num_split:
            if len(ns) > 1:
                result.add(ns.lower())
    return result


def tokenize(text: str) -> list[str]:
    """Split text into lowercase meaningful tokens, removing stopwords."""
    tokens = re.split(r"[^a-zA-Z0-9_]+", text.lower())
    return [t for t in tokens if len(t) > 2 and t not in _STOPWORDS]


def score_relevance(node: "GraphNode", task_description: str) -> float:
    """Score a single node's relevance to the task description.

    Evaluates across multiple ranking signals:
      - exact name → prefix → substring name → CamelCase decomposition
      - path relevance (basename > component > substring)
      - qualified name, docstring, module name
      - framework entry point boost
      - production file boost
      - conditional test penalty

    Returns a float in [0, 1].
    """
    if not task_description:
        return 0.5

    tokens = tokenize(task_description)
    if not tokens:
        return 0.0

    score = 0.0
    matched = 0
    query_has_test_intent = is_test_intent_query(task_description)

    name_lower = node.name.lower()

    # ── 1. Symbol name match (highest weight) ─────────────────────────
    for t in tokens:
        if t == name_lower:
            matched += 2
            score = max(score, 0.95)
        elif name_lower.startswith(t) or t.startswith(name_lower):
            matched += 1
            score = max(score, 0.85)
        elif t in name_lower:
            matched += 1
            score = max(score, 0.80)

    # ── 1b. CamelCase / snake_case decomposition match ────────────────
    name_parts = _decompose_name(node.name)
    if name_parts:
        for t in tokens:
            if t in name_parts:
                matched += 1
                score = max(score, 0.82)

    # ── 2. File path match (weighted by specificity) ──────────────────
    path_lower = node.file_path.lower()
    # Exact file basename (without extension)
    file_base = path_lower.rsplit("/", 1)[-1].rsplit(".", 1)[0] if "/" in path_lower else path_lower.rsplit(".", 1)[0]
    path_parts = set(path_lower.replace("/", " ").replace(".", " ").split())
    for t in tokens:
        if t == file_base:
            matched += 2
            score = max(score, 0.85)  # exact file basename match
        elif t in path_parts:
            matched += 1
            score = max(score, 0.78)  # directory component match
        elif t in path_lower:
            matched += 1
            score = max(score, 0.70)  # arbitrary substring

    # ── 3. Qualified name match ───────────────────────────────────────
    if node.qualified_name:
        qn_lower = node.qualified_name.lower()
        for t in tokens:
            if t in qn_lower:
                matched += 1
                score = max(score, 0.85)

    # ── 4. Docstring match ────────────────────────────────────────────
    if node.docstring:
        doc_lower = node.docstring.lower()
        for t in tokens:
            if t in doc_lower:
                matched += 1
                score = max(score, 0.60)

    # ── 5. Module name match ──────────────────────────────────────────
    module_lower = (node.module or "").lower()
    for t in tokens:
        if t in module_lower:
            matched += 1
            score = max(score, 0.70)

    # ── 6. Framework entry point boost ────────────────────────────────
    if is_framework_entry_point(
        node_type=node.type.value if node.type else "",
        tags=node.tags,
        framework_id=node.framework_id,
        name=node.name,
        file_path=node.file_path or "",
    ):
        score = max(score, 0.72)
        score = min(score + 0.10, 1.0)

    # ── 7. Test function penalty — conditional on query intent ────────
    if not query_has_test_intent:
        if node.type == NodeType.test:
            score = min(score, 0.55)
        elif is_test_path(node.file_path or ""):
            score = min(score, 0.65)

    # ── 8. Production file boost ──────────────────────────────────────
    if is_production_path(node.file_path or ""):
        score = min(score + 0.03, 1.0)

    if matched == 0:
        return 0.0

    # Boost score slightly per additional token match, cap at 1.0
    return round(min(score + (matched * 0.02), 1.0), 4)


def get_match_sources(node: "GraphNode", tokens: list[str]) -> list[str]:
    """Determine which aspects of a node matched against query tokens."""
    sources: list[str] = []
    name_lower = node.name.lower()
    path_lower = node.file_path.lower()
    module_lower = (node.module or "").lower()

    # Also check decomposition parts
    name_parts = _decompose_name(node.name)

    for t in tokens:
        if t == name_lower or t in name_lower or name_lower.startswith(t):
            if "symbol_name" not in sources:
                sources.append("symbol_name")
        if t in name_parts:
            if "name_decomposition" not in sources:
                sources.append("name_decomposition")
        if t in path_lower:
            if "file_path" not in sources:
                sources.append("file_path")
        if node.docstring and t in node.docstring.lower():
            if "docstring" not in sources:
                sources.append("docstring")
        if module_lower and t in module_lower:
            if "module_name" not in sources:
                sources.append("module_name")
        if node.qualified_name and t in node.qualified_name.lower():
            if "qualified_name" not in sources:
                sources.append("qualified_name")

    if not sources:
        sources.append("general_match")
    return sources


def build_reason(node: "GraphNode", tokens: list[str]) -> str:
    """Generate a human-readable reason explaining why a node matched."""
    parts: list[str] = []
    name_lower = node.name.lower()
    path_lower = node.file_path.lower()

    # Framework entry point — primary signal, always first
    if is_framework_entry_point(
        node_type=node.type.value if node.type else "",
        tags=node.tags,
        framework_id=node.framework_id,
        name=node.name,
        file_path=node.file_path or "",
    ):
        if node.type and node.type.value in FW_ENTRY_TYPES:
            parts.append(f"{node.type.value.capitalize()} — framework entry point")
        elif "route" in (node.tags or []):
            parts.append("Route handler — entry point for external HTTP requests")
        elif node.framework_id and node.framework_id != "unknown":
            parts.append(f"Framework entry point ({node.framework_id})")
        else:
            parts.append("Likely framework entry point (name or path pattern)")

    name_matches = [t for t in tokens if t in name_lower or name_lower.startswith(t)]
    path_matches = [t for t in tokens if t in path_lower]
    doc_matches = [t for t in tokens if node.docstring and t in node.docstring.lower()]
    module_matches = [t for t in tokens if node.module and t in node.module.lower()]
    # Decomposition matches
    name_parts = _decompose_name(node.name)
    decomp_matches = [t for t in tokens if t in name_parts]

    if name_matches:
        parts.append(f"Name matches: {', '.join(name_matches[:3])}")
    if decomp_matches:
        parts.append(f"Name parts: {', '.join(decomp_matches[:3])}")
    if path_matches:
        parts.append(f"File path contains: {', '.join(path_matches[:3])}")
    if module_matches:
        parts.append(f"Module matches: {', '.join(module_matches[:2])}")
    if doc_matches:
        parts.append(f"Docstring mentions: {', '.join(doc_matches[:2])}")

    if node.signature:
        sig_preview = node.signature[:60]
        parts.append(f"Signature: {sig_preview}")

    # Production / test classification
    if is_test_path(node.file_path or ""):
        parts.append("(test file)")
    elif is_production_path(node.file_path or ""):
        parts.append("(production file)")

    return "; ".join(parts) if parts else "General relevance to task"


def rank_entry_points(
    task_description: str,
    candidates: list["GraphNode"],
) -> list[tuple["GraphNode", float]]:
    """Rank candidate entry points by relevance to the task description.

    Returns a list of ``(node, score)`` tuples sorted by score descending.
    Only nodes with score > 0 are included.
    """
    scored: list[tuple["GraphNode", float]] = []
    for node in candidates:
        s = score_relevance(node, task_description)
        if s > 0:
            scored.append((node, s))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
