"""Context item scoring and selection for Evidence Pack generation.

Selects the most relevant context items under a token budget. Every
selected item carries its relation, confidence, resolution, and evidence
so the consumer can assess reliability independently.

Round 2: ContextSelector accepts a ContextStrategy to adjust relation
priorities based on task intent.
Round 4 (Evidence Pack): SelectedContext replaces RecommendedContext.
Context items carry evidence fields, not reading-order hints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codegraph.context.models import (
    ConfidenceLevel,
    ContentMode,
    ContextType,
    EntryPoint,
    PriorityLevel,
    SelectedContext,
    RelatedSymbol,
)
from codegraph.graph.confidence import get_confidence_level
from codegraph.context.ranking import score_relevance
from codegraph.context.token_budget import TokenBudget, estimate_tokens
from codegraph.graph.confidence import is_low_confidence
from codegraph.graph.models import GraphNode, NodeType
from codegraph.graph.store import GraphStore

if TYPE_CHECKING:
    from codegraph.context.strategies import ContextStrategy


def _compute_impact_score(node: GraphNode, relation: str) -> float:
    """Score based on structural role — how impactful/central this symbol is."""
    if relation == "entry_point":
        score = 1.0
    elif relation == "callee":
        score = 0.80
    elif relation == "caller":
        score = 0.60
    elif relation == "test":
        score = 0.40
    elif relation in ("model", "config"):
        score = 0.70
    elif relation in ("store",):
        score = 0.60
    else:
        score = 0.50

    if "route" in node.tags:
        score = min(score + 0.10, 1.0)

    return score


def score_context_item(
    node: GraphNode,
    task_description: str,
    relation: str,
    importance: str,
    confidence: float,
    distance: int,
) -> float:
    """Compute a unified context score for a candidate item.

    Uses a weighted formula:

        relevance * 0.35 + importance * 0.20 + confidence * 0.15
        + impact * 0.15 + test * 0.05
        - distance_penalty * 0.05 - token_cost_penalty * 0.05

    Returns a float clamped to [0, 1].
    """
    # 1. Relevance (0-1)
    relevance = score_relevance(node, task_description)

    # 2. Importance (map string → 0-1)
    importance_map = {"critical": 1.0, "high": 0.85, "medium": 0.60, "low": 0.30}
    importance_val = importance_map.get(importance, 0.50)

    # 3. Confidence (already 0-1)
    confidence_val = confidence

    # 4. Impact score
    impact_val = _compute_impact_score(node, relation)

    # 5. Test score
    test_val = 1.0 if node.type == NodeType.test else 0.0

    # 6. Distance penalty
    distance_penalty = min(distance / 5.0, 1.0)

    # 7. Token cost penalty
    content_len = len(node.code_preview or "")
    token_cost_penalty = min(content_len / 2000.0, 1.0)

    score = (
        relevance * 0.35
        + importance_val * 0.20
        + confidence_val * 0.15
        + impact_val * 0.15
        + test_val * 0.05
        - distance_penalty * 0.05
        - token_cost_penalty * 0.05
    )

    return round(max(0.0, min(score, 1.0)), 4)


def _build_summary_content(node: GraphNode, relation: str) -> "tuple[str, ContextType]":
    """Build a summary representation of a node."""
    if relation == "model":
        ctx_type = ContextType.model_summary
        lines = [
            f"[Model: {node.name}]",
            f"File: {node.file_path or 'unknown'}",
        ]
        if node.signature:
            lines.append(f"Definition: {node.signature}")
        if node.code_preview:
            lines.append(f"Preview: {node.code_preview[:400]}")
        return ("\n".join(lines), ctx_type)

    if relation == "config":
        ctx_type = ContextType.config_summary
        lines = [
            f"[Config: {node.name}]",
            f"File: {node.file_path or 'unknown'}",
        ]
        if node.code_preview:
            lines.append(f"Preview: {node.code_preview[:400]}")
        return ("\n".join(lines), ctx_type)

    if relation == "store":
        ctx_type = ContextType.symbol_summary
        lines = [
            f"Symbol: {node.name}",
            f"Type: {node.type.value}",
            f"File: {node.file_path}",
            f"Signature: {node.signature or 'N/A'}",
        ]
        if node.docstring:
            lines.append(f"Doc: {node.docstring[:200]}")
        return ("\n".join(lines), ctx_type)

    # Default: generic symbol summary
    ctx_type = ContextType.symbol_summary
    lines = [
        f"Symbol: {node.name}",
        f"Type: {node.type.value}",
        f"File: {node.file_path}",
        f"Signature: {node.signature or 'N/A'}",
    ]
    if node.docstring:
        lines.append(f"Doc: {node.docstring[:200]}")
    return ("\n".join(lines), ctx_type)


def _build_reference_content(node: GraphNode) -> str:
    """Minimal reference content for low-confidence / warning items."""
    lines = [
        f"[Low confidence reference]",
        f"Symbol: {node.name}",
        f"File: {node.file_path}",
        f"Type: {node.type.value}",
        f"Verify manually before relying on this item.",
    ]
    return "\n".join(lines)


def _build_evidence(node: GraphNode, relation: str) -> str:
    """Describe the evidence source for this context item's relationship."""
    if relation in ("callee", "caller"):
        return f"Static call graph edge from AST analysis (node: {node.id})"
    if relation == "test":
        return f"Test node matched via name or call graph (node: {node.id})"
    if relation in ("model", "config", "store"):
        return f"Import-based dependency from AST analysis (node: {node.id})"
    return f"Graph node indexed from source (node: {node.id})"


def select_content_mode(
    node: GraphNode,
    priority: str,
    relation: str,
    confidence: float,
    budget: TokenBudget,
) -> "tuple[str, str, ContextType]":
    """Determine content_mode, content string, and context type for a node.

    Selection rules (in priority order):

    1. Entry points → always ``"full_source"``
    2. Model/config/store → always ``"summary"`` (field-level)
    3. Tests degrade by confidence:
       - >= 0.75 → ``"full_source"``
       - 0.60–0.75 → ``"summary"``
       - < 0.60 → ``"reference"`` / warning
    4. Low confidence overall → ``"reference"`` / warning
    5. Over budget (non-critical/high) → ``"summary"``
    6. Default → ``"full_source"``
    """
    content = node.code_preview or ""

    if priority == "critical" or relation == "entry_point":
        return (ContentMode.full_source, content, ContextType.code_snippet)

    if relation in ("model", "config", "store"):
        summary, ctx_type = _build_summary_content(node, relation)
        return (ContentMode.summary, summary, ctx_type)

    if relation == "test":
        if confidence >= 0.75:
            return (ContentMode.full_source, content, ContextType.test_reference)
        if confidence >= 0.60:
            summary, ctx_type = _build_summary_content(node, "test")
            return (ContentMode.summary, summary, ctx_type)
        ref = _build_reference_content(node)
        return (ContentMode.reference, ref, ContextType.warning)

    if is_low_confidence(confidence):
        ref = _build_reference_content(node)
        return (ContentMode.reference, ref, ContextType.warning)

    estimated = estimate_tokens(content)
    if budget.remaining < estimated and priority not in ("critical", "high"):
        summary, ctx_type = _build_summary_content(node, relation)
        return (ContentMode.summary, summary, ctx_type)

    return (ContentMode.full_source, content, ContextType.code_snippet)


# ── Tier constants for classification ────────────────────────────────

_TIER_CRITICAL = 0
_TIER_HIGH_CALLEE = 1
_TIER_TEST = 2
_TIER_MODEL_CONFIG = 3
_TIER_CALLER = 4
_TIER_LOW_CONFIDENCE = 5

_RELATION_MAP: dict[str, str] = {
    "callee": "callee",
    "caller": "caller",
    "test": "test",
    "model_dependency": "model",
    "config_dependency": "config",
    "persistence_dependency": "store",
    "schema_dependency": "model",
}


def _simplify_relation(relation: str) -> str:
    return _RELATION_MAP.get(relation, relation)


_DEFAULT_PRIORITY_MAP: dict[str, str] = {
    "entry_point": "critical",
    "callee": "high",
    "model": "high",
    "config": "high",
    "test": "high",
    "store": "medium",
    "caller": "medium",
}


def _relation_priority(relation: str, strategy: "ContextStrategy | None" = None) -> str:
    """Map a relation label to a priority string.

    When a strategy is provided, uses its ``relation_priority_map``
    to adjust priorities based on task intent.
    """
    if strategy is not None:
        priority = strategy.relation_priority_map.get(relation,
                       _DEFAULT_PRIORITY_MAP.get(relation, "medium"))
        # Flag-based overrides
        flags = getattr(strategy, 'flags', None)
        if flags is not None:
            if flags.is_read_only and relation == "test" and priority in ("critical", "high"):
                return "medium"
            if flags.preserve_behavior and relation == "test":
                if priority != "critical":
                    return "high"
        return priority
    return _DEFAULT_PRIORITY_MAP.get(relation, "medium")


def _build_selection_reason(node_name: str, relation: str, importance: str, distance: int) -> str:
    """Build a fact-based selection reason — describes the relationship, not a directive."""
    dist_note = f" (distance {distance})" if distance > 1 else ""
    if relation == "callee":
        return f"Downstream dependency — `{node_name}` is called by the entry point{dist_note}."
    if relation == "caller":
        return f"Upstream consumer — `{node_name}` calls the entry point{dist_note}."
    if relation == "test":
        return f"Test coverage — `{node_name}` is related to the task{dist_note}."
    if relation == "model":
        return f"Data model — `{node_name}` defines data shapes relevant to the task{dist_note}."
    if relation == "config":
        return f"Configuration — `{node_name}` controls behavior relevant to the task{dist_note}."
    if relation == "store":
        return f"Persistence layer — `{node_name}` handles data storage relevant to the task{dist_note}."
    return f"Related symbol — `{node_name}` ({importance} importance){dist_note}."


class ContextSelector:
    """Orchestrates context selection with token budgeting.

    Groups candidate symbols into priority tiers, scores each one,
    selects content modes, and applies the degradation cascade when
    the token budget is exceeded.

    When a ``strategy`` is provided, the relation priority mapping
    is taken from ``strategy.relation_priority_map``, making the
    selection intent-aware.
    """

    def __init__(
        self,
        store: GraphStore,
        task_description: str,
        max_tokens: int,
        strategy: "ContextStrategy | None" = None,
    ) -> None:
        self.store = store
        self.task_description = task_description
        self.budget = TokenBudget(max_tokens)
        self.strategy = strategy

    def select(
        self,
        entry_points: list[EntryPoint],
        related_symbols: list[RelatedSymbol],
    ) -> "tuple[list[SelectedContext], list[SelectedContext]]":
        """Run the full selection pipeline.

        Returns ``(selected_context, low_confidence_context)``.
        """
        entry_ids = {ep.symbol_id for ep in entry_points}

        # ---- classify related symbols into priority tiers ----
        tiers: dict[int, list[tuple[GraphNode, str, str, float, int]]] = {
            _TIER_CRITICAL: [],
            _TIER_HIGH_CALLEE: [],
            _TIER_TEST: [],
            _TIER_MODEL_CONFIG: [],
            _TIER_CALLER: [],
            _TIER_LOW_CONFIDENCE: [],
        }

        for rs in related_symbols:
            node = self.store.get_node(rs.symbol_id)
            if not node:
                continue
            if rs.symbol_id in entry_ids:
                continue

            rel = _simplify_relation(rs.relation.value if hasattr(rs.relation, 'value') else str(rs.relation))
            importance = rs.importance.value if hasattr(rs.importance, "value") else str(rs.importance)
            confidence = rs.confidence
            distance = rs.distance

            item = (node, rel, importance, confidence, distance)

            if is_low_confidence(confidence):
                tiers[_TIER_LOW_CONFIDENCE].append(item)
            elif rel == "callee" and importance in ("critical", "high") and confidence >= 0.75:
                tiers[_TIER_HIGH_CALLEE].append(item)
            elif rel == "test":
                tiers[_TIER_TEST].append(item)
            elif rel in ("model", "config", "store"):
                tiers[_TIER_MODEL_CONFIG].append(item)
            elif rel == "caller":
                tiers[_TIER_CALLER].append(item)
            else:
                tiers[_TIER_CALLER].append(item)

        # ---- score every item in every tier ----
        scored: list[tuple[GraphNode, str, str, float, int, float, int]] = []
        for tier_level in range(_TIER_LOW_CONFIDENCE + 1):
            for node, rel, importance, confidence, distance in tiers[tier_level]:
                s = score_context_item(
                    node, self.task_description, rel,
                    importance, confidence, distance,
                )
                scored.append((node, rel, importance, confidence, distance, s, tier_level))

        # Sort: tier first (lower = more important), then score desc
        scored.sort(key=lambda x: (x[6], -x[5]))

        # ---- select with budget ----
        selected: list[SelectedContext] = []
        low_conf: list[SelectedContext] = []
        ctx_count = 0

        for node, rel, importance, confidence, distance, score_val, tier_level in scored:
            priority = _relation_priority(rel, self.strategy)

            content_mode, content, ctx_type = select_content_mode(
                node, priority, rel, confidence, self.budget,
            )
            estimated = estimate_tokens(content)

            # Degradation cascade when over budget
            if not self.budget.can_fit(estimated, priority):
                if content_mode == ContentMode.full_source:
                    sm_content, sm_ctx_type = _build_summary_content(node, rel)
                    content_mode = ContentMode.summary
                    content = sm_content
                    ctx_type = sm_ctx_type
                    estimated = estimate_tokens(content)

                if not self.budget.can_fit(estimated, priority) and content_mode == ContentMode.summary:
                    content = _build_reference_content(node)
                    content_mode = ContentMode.reference
                    ctx_type = ContextType.warning
                    estimated = estimate_tokens(content)

                if not self.budget.can_fit(estimated, priority):
                    ctx_count += 1
                    loc = node.location
                    low_conf.append(SelectedContext(
                        context_id=f"ctx_item_{ctx_count:03d}",
                        type=ctx_type,
                        symbol_id=node.id,
                        file_path=node.file_path or "",
                        line_start=loc.line_start if loc else 0,
                        line_end=loc.line_end if loc else 0,
                        priority=PriorityLevel.low,
                        relation=rel,
                        selection_reason=_build_selection_reason(node.name, rel, importance, distance),
                        content=content,
                        estimated_tokens=estimated,
                        content_mode=content_mode,
                        confidence=confidence,
                        confidence_level=ConfidenceLevel(get_confidence_level(confidence)),
                        resolution="",
                        evidence=_build_evidence(node, rel),
                        context_score=score_val,
                    ))
                    continue

            self.budget.spend(estimated)
            ctx_count += 1
            loc = node.location

            sc = SelectedContext(
                context_id=f"ctx_item_{ctx_count:03d}",
                type=ctx_type,
                symbol_id=node.id,
                file_path=node.file_path or "",
                line_start=loc.line_start if loc else 0,
                line_end=loc.line_end if loc else 0,
                priority=PriorityLevel(priority),
                relation=rel,
                selection_reason=_build_selection_reason(node.name, rel, importance, distance),
                content=content,
                estimated_tokens=estimated,
                content_mode=content_mode,
                confidence=confidence,
                confidence_level=ConfidenceLevel(get_confidence_level(confidence)),
                resolution="",
                evidence=_build_evidence(node, rel),
                context_score=score_val,
            )

            if is_low_confidence(confidence) or tier_level == _TIER_LOW_CONFIDENCE:
                low_conf.append(sc)
            else:
                selected.append(sc)

        return selected, low_conf
