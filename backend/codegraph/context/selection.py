"""Context item scoring, selection, and degradation for Context Pack generation.

Implements the unified scoring formula, content mode selection rules,
and the degradation cascade that keeps the most valuable context when
the token budget is tight.
"""

from codegraph.context.models import (
    ContextType,
    EntryPoint,
    RecommendedContext,
    RelatedSymbol,
)
from codegraph.context.ranking import score_relevance
from codegraph.context.token_budget import TokenBudget, estimate_tokens
from codegraph.graph.confidence import is_low_confidence
from codegraph.graph.models import GraphNode, NodeType
from codegraph.graph.store import GraphStore


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

    Uses a weighted formula (PRD §14.3 extended):

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
    """Build a summary representation of a node.

    Model/config nodes get field-level summaries. Other nodes get
    name + type + file + signature.
    """
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

    # --- entry points: always full source ---
    if priority == "critical" or relation == "entry_point":
        return ("full_source", content, ContextType.code_snippet)

    # --- model/config/store: always summarise ---
    if relation in ("model", "config", "store"):
        summary, ctx_type = _build_summary_content(node, relation)
        return ("summary", summary, ctx_type)

    # --- tests: degrade by confidence ---
    if relation == "test":
        if confidence >= 0.75:
            return ("full_source", content, ContextType.test_reference)
        if confidence >= 0.60:
            summary, ctx_type = _build_summary_content(node, "test")
            return ("summary", summary, ctx_type)
        ref = _build_reference_content(node)
        return ("reference", ref, ContextType.warning)

    # --- low confidence overall ---
    if is_low_confidence(confidence):
        ref = _build_reference_content(node)
        return ("reference", ref, ContextType.warning)

    # --- budget check: degrade to summary if over budget ---
    estimated = estimate_tokens(content)
    if budget.remaining < estimated and priority not in ("critical", "high"):
        summary, ctx_type = _build_summary_content(node, relation)
        return ("summary", summary, ctx_type)

    return ("full_source", content, ContextType.code_snippet)


# ── Tier constants for classification ──────────────────────────────────────

_TIER_CRITICAL = 0
_TIER_HIGH_CALLEE = 1
_TIER_TEST = 2
_TIER_MODEL_CONFIG = 3
_TIER_CALLER = 4
_TIER_LOW_CONFIDENCE = 5

# Map relation strings to simplified labels used by select_content_mode
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


def _relation_priority(relation: str) -> str:
    """Map a relation label to a default priority string."""
    priority_map = {
        "entry_point": "critical",
        "callee": "high",
        "model": "high",
        "config": "high",
        "test": "high",
        "store": "medium",
        "caller": "medium",
    }
    return priority_map.get(relation, "medium")


class ContextSelector:
    """Orchestrates context selection with token budgeting.

    Groups candidate symbols into priority tiers, scores each one,
    selects content modes, and applies the degradation cascade when
    the token budget is exceeded.
    """

    def __init__(
        self,
        store: GraphStore,
        task_description: str,
        max_tokens: int,
    ) -> None:
        self.store = store
        self.task_description = task_description
        self.budget = TokenBudget(max_tokens)

    def select(
        self,
        entry_points: list[EntryPoint],
        related_symbols: list[RelatedSymbol],
    ) -> "tuple[list[RecommendedContext], list[RecommendedContext]]":
        """Run the full selection pipeline.

        Returns ``(recommended_context, optional_context)``.
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

            rel = _simplify_relation(rs.relation)
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
        recommended: list[RecommendedContext] = []
        optional: list[RecommendedContext] = []
        ctx_count = 0

        for node, rel, importance, confidence, distance, score_val, tier_level in scored:
            priority = _relation_priority(rel)

            content_mode, content, ctx_type = select_content_mode(
                node, priority, rel, confidence, self.budget,
            )
            estimated = estimate_tokens(content)

            # Degradation cascade when over budget
            if not self.budget.can_fit(estimated, priority):
                if content_mode == "full_source":
                    # Degrade: full_source → summary
                    content_mode, content, ctx_type = (
                        _build_summary_content(node, rel)
                    )
                    content_mode = "summary"
                    estimated = estimate_tokens(content)

                if not self.budget.can_fit(estimated, priority) and content_mode == "summary":
                    # Degrade: summary → reference
                    content = _build_reference_content(node)
                    content_mode = "reference"
                    ctx_type = ContextType.warning
                    estimated = estimate_tokens(content)

                if not self.budget.can_fit(estimated, priority):
                    # Still can't fit → drop to optional_context
                    ctx_count += 1
                    loc = node.location
                    optional.append(RecommendedContext(
                        context_id=f"ctx_item_{ctx_count:03d}",
                        type=ctx_type,
                        symbol_id=node.id,
                        file_path=node.file_path or "",
                        line_start=loc.line_start if loc else 0,
                        line_end=loc.line_end if loc else 0,
                        priority="low",
                        reason=f"{rel} — dropped due to budget",
                        content=content,
                        estimated_tokens=estimated,
                        content_mode=content_mode,
                        context_score=score_val,
                    ))
                    continue

            self.budget.spend(estimated)
            ctx_count += 1
            loc = node.location

            rc = RecommendedContext(
                context_id=f"ctx_item_{ctx_count:03d}",
                type=ctx_type,
                symbol_id=node.id,
                file_path=node.file_path or "",
                line_start=loc.line_start if loc else 0,
                line_end=loc.line_end if loc else 0,
                priority=priority,
                reason=f"{rel} — {node.name}",
                content=content,
                estimated_tokens=estimated,
                content_mode=content_mode,
                context_score=score_val,
            )

            if is_low_confidence(confidence) or tier_level == _TIER_LOW_CONFIDENCE:
                optional.append(rc)
            else:
                recommended.append(rc)

        return recommended, optional
