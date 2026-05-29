"""Entry point ranking and relevance scoring for Context Pack.

PRD §14.3 — Entry point ranking rules.
"""

import re

from codegraph.graph.models import GraphNode, NodeType

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


def tokenize(text: str) -> list[str]:
    """Split text into lowercase meaningful tokens, removing stopwords."""
    tokens = re.split(r"[^a-zA-Z0-9_]+", text.lower())
    return [t for t in tokens if len(t) > 2 and t not in _STOPWORDS]


def score_relevance(node: GraphNode, task_description: str) -> float:
    """Score a single node's relevance to the task description.

    Evaluates match across: symbol name, file path, qualified name,
    docstring, and module name. Returns a float in [0, 1].
    """
    if not task_description:
        return 0.5

    tokens = tokenize(task_description)
    if not tokens:
        return 0.0

    score = 0.0
    matched = 0

    # 1. Symbol name match (highest weight)
    name_lower = node.name.lower()
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

    # 2. File path match
    path_lower = node.file_path.lower()
    for t in tokens:
        if t in path_lower:
            matched += 1
            score = max(score, 0.75)

    # 3. Qualified name match
    if node.qualified_name:
        qn_lower = node.qualified_name.lower()
        for t in tokens:
            if t in qn_lower:
                matched += 1
                score = max(score, 0.85)

    # 4. Docstring match
    if node.docstring:
        doc_lower = node.docstring.lower()
        for t in tokens:
            if t in doc_lower:
                matched += 1
                score = max(score, 0.60)

    # 5. Module name match
    module_lower = (node.module or "").lower()
    for t in tokens:
        if t in module_lower:
            matched += 1
            score = max(score, 0.70)

    # 6. Route handler boost — route handlers are strong entry points
    if "route" in node.tags:
        score = max(score, 0.70)
        score = min(score + 0.05, 1.0)

    # 7. Test function penalty — tests should not outrank real logic
    if node.type == NodeType.test:
        score = min(score, 0.60)

    if matched == 0:
        return 0.0

    # Boost score slightly per additional token match, cap at 1.0
    return round(min(score + (matched * 0.02), 1.0), 4)


def get_match_sources(node: GraphNode, tokens: list[str]) -> list[str]:
    """Determine which aspects of a node matched against query tokens."""
    sources: list[str] = []
    name_lower = node.name.lower()
    path_lower = node.file_path.lower()
    module_lower = (node.module or "").lower()

    for t in tokens:
        if t == name_lower or t in name_lower or name_lower.startswith(t):
            if "symbol_name" not in sources:
                sources.append("symbol_name")
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


def build_reason(node: GraphNode, tokens: list[str]) -> str:
    """Generate a human-readable reason explaining why a node matched."""
    parts: list[str] = []
    name_lower = node.name.lower()
    path_lower = node.file_path.lower()

    # Route handler — primary signal, always first
    route = node.metadata.get("route")
    if route:
        framework = route.get("framework", "")
        method = route.get("method", "")
        path = route.get("path", "")
        parts.append(f"HTTP route handler ({framework} {method} {path}) — entry point for external requests")

    name_matches = [t for t in tokens if t in name_lower or name_lower.startswith(t)]
    path_matches = [t for t in tokens if t in path_lower]
    doc_matches = [t for t in tokens if node.docstring and t in node.docstring.lower()]
    module_matches = [t for t in tokens if node.module and t in node.module.lower()]

    if name_matches:
        parts.append(f"Name matches: {', '.join(name_matches[:3])}")
    if path_matches:
        parts.append(f"File path contains: {', '.join(path_matches[:3])}")
    if module_matches:
        parts.append(f"Module matches: {', '.join(module_matches[:2])}")
    if doc_matches:
        parts.append(f"Docstring mentions: {', '.join(doc_matches[:2])}")

    if node.signature:
        sig_preview = node.signature[:60]
        parts.append(f"Signature: {sig_preview}")

    return "; ".join(parts) if parts else "General relevance to task"


def rank_entry_points(
    task_description: str,
    candidates: list[GraphNode],
) -> list[tuple[GraphNode, float]]:
    """Rank candidate entry points by relevance to the task description.

    Returns a list of ``(node, score)`` tuples sorted by score descending.
    Only nodes with score > 0 are included.
    """
    scored: list[tuple[GraphNode, float]] = []
    for node in candidates:
        s = score_relevance(node, task_description)
        if s > 0:
            scored.append((node, s))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
