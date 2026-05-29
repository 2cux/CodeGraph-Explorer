"""Intent classification and per-intent context generation strategies.

Round 2: Task Intent Classification & Strategy Optimization.
Round 3: Compositional strategy — TaskProfile + StrategyFlags replace fixed templates.

Each TaskIntent has a ContextStrategy that controls how the Context Pack
pipeline generates its output. The strategy can now be composed dynamically
from operation signals, domain signals, and constraints via ``compose_strategy``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from codegraph.context.models import ConstraintType, OperationSignal, TaskIntent


# ── StrategyFlags ──────────────────────────────────────────────────────────


@dataclass
class StrategyFlags:
    """Composable behaviour flags that control Context Pack generation.

    These are computed from the TaskProfile (primary intent + operation
    signals + constraints) and drive every downstream pipeline decision.
    """

    needs_impact: bool = False
    needs_tests: bool = False
    modify_allowed: bool = True
    preserve_behavior: bool = False
    focus_callers: bool = False
    focus_callees: bool = False
    focus_models: bool = False
    focus_tests: bool = False
    is_read_only: bool = False


# ── TaskProfile ────────────────────────────────────────────────────────────


@dataclass
class TaskProfile:
    """Rich task analysis result — signals, constraints, and intents.

    Replaces the flat ``classify_task_intent`` dict with structured
    multi-intent classification that supports compound tasks like
    "add MFA to login flow and update tests".
    """

    primary_intent: TaskIntent = TaskIntent.understand_code
    secondary_intents: list[TaskIntent] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    domain_signals: list[str] = field(default_factory=list)
    operation_signals: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    confidence: float = 0.5
    reason: str = ""


# ── ContextStrategy ────────────────────────────────────────────────────────


class ContextStrategy:
    """Per-intent configuration for Context Pack generation.

    Each field controls one aspect of the pipeline so that
    ``add_feature`` and ``understand_code`` produce fundamentally
    different Context Packs even from the same code graph.

    When created via ``compose_strategy(profile)``, the ``flags``
    attribute carries the computed ``StrategyFlags`` so downstream
    modules can make granular decisions beyond the pre-computed
    ``reading_plan_order`` and ``relation_priority_map``.
    """

    def __init__(
        self,
        *,
        intent: TaskIntent,
        trigger_keywords: list[str],
        context_focus: str,
        impact_required: bool,
        tests_required: bool,
        reading_plan_order: list[str],
        relation_priority_map: dict[str, str],
        agent_strategy_focus: str,
        flags: StrategyFlags | None = None,
    ) -> None:
        self.intent = intent
        self.trigger_keywords = trigger_keywords
        self.context_focus = context_focus
        self.impact_required = impact_required
        self.tests_required = tests_required
        self.reading_plan_order = reading_plan_order
        self.relation_priority_map = relation_priority_map
        self.agent_strategy_focus = agent_strategy_focus

        if flags is not None:
            self.flags = flags
        else:
            # Build default flags from strategy attributes for backward compat
            callee_pos = reading_plan_order.index("callees") if "callees" in reading_plan_order else 99
            caller_pos = reading_plan_order.index("callers") if "callers" in reading_plan_order else 99
            model_pos = reading_plan_order.index("models") if "models" in reading_plan_order else 99
            test_pos = reading_plan_order.index("tests") if "tests" in reading_plan_order else 99
            low_conf_pos = reading_plan_order.index("low_conf") if "low_conf" in reading_plan_order else 99

            self.flags = StrategyFlags(
                needs_impact=impact_required,
                needs_tests=tests_required,
                focus_callees=callee_pos < caller_pos,
                focus_callers=caller_pos < callee_pos,
                focus_models=model_pos < test_pos or model_pos < low_conf_pos,
                focus_tests=(test_pos < low_conf_pos and tests_required)
                            or relation_priority_map.get("test") in ("critical", "high"),
                is_read_only=intent in (TaskIntent.understand_code, TaskIntent.review_code,
                                       TaskIntent.analyze_impact, TaskIntent.generate_docs),
                modify_allowed=intent not in (TaskIntent.understand_code, TaskIntent.analyze_impact,
                                             TaskIntent.generate_docs),
            )


# ── Strategy definitions ────────────────────────────────────────────────────
# reading_plan_order keys:
#   "entry"   — entry points (always first)
#   "callers" — upstream callers
#   "callees" — downstream callees
#   "models"  — data models / schemas
#   "config"  — configuration / settings
#   "store"   — persistence layer
#   "tests"   — test files
#   "low_conf" — low-confidence items (always last)

# relation_priority_map: relation → priority (critical/high/medium/low)
# Overrides the default priority mapping per intent.

_STRATEGIES: dict[TaskIntent, ContextStrategy] = {}


def _register(strategy: ContextStrategy) -> ContextStrategy:
    _STRATEGIES[strategy.intent] = strategy
    return strategy


# ── 1. write_tests ─────────────────────────────────────────────────────────

_STRATEGY_WRITE_TESTS = _register(ContextStrategy(
    intent=TaskIntent.write_tests,
    trigger_keywords=["write test", "add test", "add tests", "test coverage",
                      "pytest", "unit test", "integration test", "spec"],
    context_focus="Target symbol + dependencies + existing test patterns + suggested tests",
    impact_required=False,
    tests_required=True,
    reading_plan_order=["entry", "callees", "tests", "models", "config", "store", "callers", "low_conf"],
    relation_priority_map={
        "test": "critical",
        "callee": "high",
        "model": "high",
        "caller": "medium",
        "config": "medium",
        "store": "low",
    },
    agent_strategy_focus="Prioritize test coverage. Focus on existing test patterns and suggest new tests for uncovered paths.",
))

# ── 2. fix_bug ─────────────────────────────────────────────────────────────

_STRATEGY_FIX_BUG = _register(ContextStrategy(
    intent=TaskIntent.fix_bug,
    trigger_keywords=["fix", "bug", "error", "wrong", "broken", "fails",
                      "exception", "traceback", "issue", "incorrect", "crash"],
    context_focus="Suspected target + error path + callers (who triggers) + callees + tests",
    impact_required=True,
    tests_required=True,
    reading_plan_order=["entry", "callers", "callees", "tests", "models", "config", "store", "low_conf"],
    relation_priority_map={
        "entry_point": "critical",
        "caller": "high",
        "callee": "high",
        "test": "high",
        "model": "medium",
        "config": "medium",
        "store": "low",
    },
    agent_strategy_focus="Focus on the error path. Trace callers to understand triggers, then callees to find the root cause. Verify with tests.",
))

# ── 3. refactor ────────────────────────────────────────────────────────────

_STRATEGY_REFACTOR = _register(ContextStrategy(
    intent=TaskIntent.refactor,
    trigger_keywords=["refactor", "cleanup", "simplify", "extract", "rename",
                      "move", "split", "deduplicate", "restructure", "reorganize"],
    context_focus="All callers + all callees + public API surface + tests",
    impact_required=True,
    tests_required=True,
    reading_plan_order=["entry", "callers", "callees", "models", "config", "tests", "store", "low_conf"],
    relation_priority_map={
        "entry_point": "critical",
        "caller": "critical",
        "callee": "high",
        "test": "high",
        "model": "high",
        "config": "medium",
        "store": "medium",
    },
    agent_strategy_focus="Refactoring requires full caller/callee awareness. Every upstream consumer must be checked. Tests are the safety net.",
))

# ── 4. analyze_impact ──────────────────────────────────────────────────────

_STRATEGY_ANALYZE_IMPACT = _register(ContextStrategy(
    intent=TaskIntent.analyze_impact,
    trigger_keywords=["impact", "affected", "what breaks", "blast radius",
                      "dependency", "depends on", "what depends"],
    context_focus="Callers + callees + affected files + risk assessment",
    impact_required=True,
    tests_required=False,
    reading_plan_order=["entry", "callers", "callees", "models", "config", "tests", "store", "low_conf"],
    relation_priority_map={
        "entry_point": "critical",
        "caller": "critical",
        "callee": "high",
        "model": "high",
        "config": "medium",
        "test": "medium",
        "store": "medium",
    },
    agent_strategy_focus="Map the full blast radius. Prioritize upstream callers (who breaks) and downstream callees (what breaks).",
))

# ── 5. review_code ─────────────────────────────────────────────────────────

_STRATEGY_REVIEW_CODE = _register(ContextStrategy(
    intent=TaskIntent.review_code,
    trigger_keywords=["review", "audit", "check", "inspect", "verify",
                      "security review", "code review"],
    context_focus="Sensitive paths + risks + tests + low-confidence warnings",
    impact_required=True,
    tests_required=True,
    reading_plan_order=["entry", "callers", "callees", "tests", "models", "config", "store", "low_conf"],
    relation_priority_map={
        "entry_point": "critical",
        "callee": "high",
        "caller": "high",
        "test": "high",
        "model": "high",
        "config": "high",
        "store": "medium",
    },
    agent_strategy_focus="Review with scrutiny. Highlight low-confidence edges, sensitive dependencies, and untested paths. Flag risks explicitly.",
))

# ── 6. understand_code ─────────────────────────────────────────────────────

_STRATEGY_UNDERSTAND_CODE = _register(ContextStrategy(
    intent=TaskIntent.understand_code,
    trigger_keywords=["explain", "understand", "how does", "how works",
                      "walk me through", "what does", "describe"],
    context_focus="Call flow + summaries + entry points + downstream flow",
    impact_required=False,
    tests_required=False,
    reading_plan_order=["entry", "callees", "models", "callers", "config", "store", "tests", "low_conf"],
    relation_priority_map={
        "entry_point": "critical",
        "callee": "high",
        "model": "medium",
        "caller": "medium",
        "config": "low",
        "test": "low",
        "store": "low",
    },
    agent_strategy_focus="Explain the flow clearly. Start from entry points, trace the downstream call chain. Summarize rather than dumping all source.",
))

# ── 7. generate_docs ───────────────────────────────────────────────────────

_STRATEGY_GENERATE_DOCS = _register(ContextStrategy(
    intent=TaskIntent.generate_docs,
    trigger_keywords=["document", "docs", "readme", "write documentation",
                      "generate docs", "api docs", "docstring"],
    context_focus="Public APIs + summaries + examples + type signatures",
    impact_required=False,
    tests_required=False,
    reading_plan_order=["entry", "callees", "models", "config", "callers", "store", "tests", "low_conf"],
    relation_priority_map={
        "entry_point": "critical",
        "callee": "high",
        "model": "high",
        "config": "medium",
        "caller": "low",
        "test": "low",
        "store": "low",
    },
    agent_strategy_focus="Focus on public API surface. Collect signatures, docstrings, and type information. Generate readable documentation.",
))

# ── 8. add_feature ─────────────────────────────────────────────────────────

_STRATEGY_ADD_FEATURE = _register(ContextStrategy(
    intent=TaskIntent.add_feature,
    trigger_keywords=["add", "implement", "support", "introduce", "create",
                      "enable", "new", "feature"],
    context_focus="Entry point + service + model/config + persistence + tests",
    impact_required=True,
    tests_required=True,
    reading_plan_order=["entry", "callees", "models", "config", "store", "callers", "tests", "low_conf"],
    relation_priority_map={
        "entry_point": "critical",
        "callee": "high",
        "model": "high",
        "config": "high",
        "store": "high",
        "test": "high",
        "caller": "medium",
    },
    agent_strategy_focus="Plan the feature addition. Understand the service layer, data models, config, and persistence. Check existing tests and write new ones.",
))

# ── 9. modify_existing_behavior ────────────────────────────────────────────

_STRATEGY_MODIFY = _register(ContextStrategy(
    intent=TaskIntent.modify_existing_behavior,
    trigger_keywords=["change", "modify", "update", "adjust", "revise", "edit",
                      "make", "improve", "enhance"],
    context_focus="Target behavior + callers + callees + affected tests",
    impact_required=True,
    tests_required=True,
    reading_plan_order=["entry", "callers", "callees", "tests", "models", "config", "store", "low_conf"],
    relation_priority_map={
        "entry_point": "critical",
        "caller": "high",
        "callee": "high",
        "test": "high",
        "model": "medium",
        "config": "medium",
        "store": "medium",
    },
    agent_strategy_focus="Understand existing behavior before changing it. Trace callers to assess impact and callees to understand dependencies.",
))


# ── Signal & constraint detection ─────────────────────────────────────────

# Operation signal patterns: signal_name → trigger words
_OPERATION_SIGNAL_PATTERNS: dict[str, list[str]] = {
    "create": ["add", "implement", "support", "introduce", "create", "enable", "new"],
    "modify": ["change", "modify", "update", "adjust", "revise", "edit", "improve", "enhance"],
    "delete": ["remove", "delete", "deprecate", "drop"],
    "understand": ["explain", "understand", "how does", "how works", "what does", "describe", "walk through"],
    "test": ["test", "tests", "spec", "coverage", "pytest", "unit test", "integration test"],
    "document": ["document", "docs", "readme", "docstring", "generate docs", "api docs"],
    "review": ["review", "audit", "inspect", "verify", "check"],
    "analyze": ["impact", "affected", "what breaks", "blast radius", "dependency", "depends on"],
    "fix": ["fix", "bug", "error", "wrong", "broken", "fails", "exception", "traceback", "crash", "incorrect", "issue"],
    "refactor": ["refactor", "cleanup", "simplify", "extract", "rename", "restructure", "split", "deduplicate", "reorganize"],
}

# Domain signal patterns
_DOMAIN_SIGNAL_PATTERNS: dict[str, list[str]] = {
    "auth": ["login", "auth", "token", "password", "permission", "session", "oauth", "mfa", "jwt"],
    "api": ["endpoint", "route", "api", "rest", "http", "request", "response", "handler"],
    "data": ["model", "schema", "database", "orm", "migration", "field", "entity"],
    "config": ["config", "settings", "env", "environment", "options", "flags"],
    "storage": ["store", "repository", "cache", "file", "persistence", "db"],
    "business": ["service", "logic", "workflow", "rule", "validation", "policy"],
}

# Constraint detection patterns (regex)
_CONSTRAINT_PATTERNS: list[tuple[str, str]] = [
    # (constraint_type, regex_pattern)
    ("no_modify", r"do\s+not\s+modify"),
    ("no_modify", r"don'?t\s+change"),
    ("no_modify", r"don'?t\s+modify"),
    ("no_modify", r"without\s+changing\s+(any\s+)?code"),
    ("no_modify", r"read[\s-]only"),
    ("no_modify", r"do\s+not\s+edit"),
    ("preserve_behavior", r"without\s+changing\s+behavior"),
    ("preserve_behavior", r"preserve\s+behavior"),
    ("preserve_behavior", r"keep\s+(the\s+)?(existing\s+)?behavior"),
    ("preserve_behavior", r"same\s+behavior"),
    ("preserve_behavior", r"no\s+breaking\s+changes?"),
    ("preserve_behavior", r"backward[\s-]compatible"),
    ("with_tests", r"with\s+tests?"),
    ("with_tests", r"include\s+tests?"),
    ("with_tests", r"and\s+update\s+tests?"),
    ("with_tests", r"and\s+add\s+tests?"),
    ("with_tests", r"and\s+write\s+tests?"),
    ("with_tests", r"along\s+with\s+tests?"),
    ("performance", r"performance"),
    ("performance", r"(?:make\s+it\s+)?faster"),
    ("performance", r"speed\s+(?:up|improvement)"),
    ("performance", r"optimize"),
    ("performance", r"slow"),
    ("security", r"security"),
    ("security", r"vulnerabilit(?:y|ies)"),
    ("security", r"(?:in)?secure"),
]

# Signal → TaskIntent mapping
_SIGNAL_TO_INTENT: dict[str, TaskIntent] = {
    "create": TaskIntent.add_feature,
    "modify": TaskIntent.modify_existing_behavior,
    "delete": TaskIntent.modify_existing_behavior,
    "understand": TaskIntent.understand_code,
    "test": TaskIntent.write_tests,
    "document": TaskIntent.generate_docs,
    "review": TaskIntent.review_code,
    "analyze": TaskIntent.analyze_impact,
    "fix": TaskIntent.fix_bug,
    "refactor": TaskIntent.refactor,
}


def _word_match(keyword: str, text: str) -> bool:
    """Match keyword with word boundaries for short words."""
    if len(keyword) <= 5:
        pattern = r'\b' + re.escape(keyword) + r'\b'
        return bool(re.search(pattern, text))
    return keyword in text


def _matches_keywords(keywords: list[str], text: str) -> list[str]:
    """Return list of matching keywords using word-boundary matching."""
    return [kw for kw in keywords if _word_match(kw, text)]


def _detect_operation_signals(text: str) -> list[str]:
    """Detect which operation signals are present in the task text."""
    signals: list[str] = []
    for signal_name, trigger_words in _OPERATION_SIGNAL_PATTERNS.items():
        if _matches_keywords(trigger_words, text):
            signals.append(signal_name)
    return signals


def _detect_domain_signals(text: str) -> list[str]:
    """Detect which domain signals are present in the task text."""
    domains: list[str] = []
    for domain_name, trigger_words in _DOMAIN_SIGNAL_PATTERNS.items():
        if _matches_keywords(trigger_words, text):
            domains.append(domain_name)
    return domains


def _detect_constraints(text: str) -> list[str]:
    """Detect constraints from regex patterns in the task text."""
    constraints: list[str] = []
    for constraint_type, pattern in _CONSTRAINT_PATTERNS:
        if re.search(pattern, text):
            if constraint_type not in constraints:
                constraints.append(constraint_type)
    return constraints


def _split_clauses(text: str) -> list[str]:
    """Split a compound task into clauses on ' and ' or ', '.

    Only splits when there are clear multi-clause signals (multiple
    action verbs). Returns a single-element list for simple tasks.
    """
    # Split on " and " (word-bounded)
    parts = re.split(r'\s+and\s+', text)
    if len(parts) >= 2:
        # Verify at least two parts have action verbs
        action_count = sum(1 for p in parts if _detect_operation_signals(p))
        if action_count >= 2:
            return [p.strip() for p in parts if p.strip()]
    # Split on ", " or "; "
    parts = re.split(r'[,;]\s+', text)
    if len(parts) >= 2:
        action_count = sum(1 for p in parts if _detect_operation_signals(p))
        if action_count >= 2:
            return [p.strip() for p in parts if p.strip()]
    return [text]


# ── Internal classification ───────────────────────────────────────────────


def _classify_intent_internal(text: str) -> tuple[TaskIntent, float, list[str]]:
    """Shared classification logic — returns (intent, confidence, keywords).

    Extracted so both ``classify_task_intent`` and ``analyze_task``
    share the same primary-intent detection rules.
    """
    if not text:
        return (TaskIntent.understand_code, 0.3, [])

    # Ordered list of (intent, strategy) pairs in priority order.
    checks: list[tuple[TaskIntent, ContextStrategy]] = [
        (TaskIntent.write_tests, _STRATEGY_WRITE_TESTS),
        (TaskIntent.fix_bug, _STRATEGY_FIX_BUG),
        (TaskIntent.refactor, _STRATEGY_REFACTOR),
        (TaskIntent.analyze_impact, _STRATEGY_ANALYZE_IMPACT),
        (TaskIntent.understand_code, _STRATEGY_UNDERSTAND_CODE),
        (TaskIntent.generate_docs, _STRATEGY_GENERATE_DOCS),
        (TaskIntent.modify_existing_behavior, _STRATEGY_MODIFY),
        (TaskIntent.add_feature, _STRATEGY_ADD_FEATURE),
        (TaskIntent.review_code, _STRATEGY_REVIEW_CODE),
    ]

    # Conflict: "add tests for X" must NOT match add_feature
    has_test_word = any(_word_match(w, text) for w in ("test", "tests", "spec", "coverage", "pytest"))
    has_write_word = any(_word_match(w, text) for w in ("write", "add", "create"))

    # Special case: "add tests for X" / "write tests for X"
    if has_test_word and has_write_word:
        strategy = _STRATEGY_WRITE_TESTS
        matched = _matches_keywords(strategy.trigger_keywords, text)
        return (strategy.intent, 0.85 if matched else 0.70, matched[:5])

    for intent, strategy in checks:
        matched = _matches_keywords(strategy.trigger_keywords, text)
        if matched:
            confidence = 0.90 if len(matched) >= 2 else 0.75
            return (intent, confidence, matched[:5])

    return (TaskIntent.understand_code, 0.40, [])


def _infer_secondary_intents(
    op_signals: list[str],
    primary_intent: TaskIntent,
    text: str,
) -> list[TaskIntent]:
    """Infer secondary intents from operation signals and clause analysis.

    Only includes intents that differ from the primary intent.
    """
    secondary: list[TaskIntent] = []

    # From operation signals
    for sig in op_signals:
        intent = _SIGNAL_TO_INTENT.get(sig)
        if intent and intent != primary_intent and intent not in secondary:
            secondary.append(intent)

    # From compound clauses
    clauses = _split_clauses(text)
    if len(clauses) > 1:
        for clause in clauses[1:]:
            clause_intent, _, _ = _classify_intent_internal(clause)
            if clause_intent != primary_intent and clause_intent not in secondary:
                secondary.append(clause_intent)

    return secondary


def _build_profile_reason(
    primary: TaskIntent,
    secondary: list[TaskIntent],
    op_signals: list[str],
    domain_signals: list[str],
    constraints: list[str],
) -> str:
    """Build a human-readable reason string for a TaskProfile."""
    parts = [f"Primary intent: {primary.value}"]
    if secondary:
        parts.append(f"Secondary intents: {', '.join(s.value for s in secondary)}")
    if op_signals:
        parts.append(f"Operation signals: {', '.join(op_signals)}")
    if domain_signals:
        parts.append(f"Domain signals: {', '.join(domain_signals)}")
    if constraints:
        parts.append(f"Constraints: {', '.join(constraints)}")
    return " | ".join(parts)


# ── Public API ──────────────────────────────────────────────────────────────


def get_strategy(intent: TaskIntent) -> ContextStrategy:
    """Return the ContextStrategy for a given task intent."""
    return _STRATEGIES.get(intent, _STRATEGY_UNDERSTAND_CODE)


def classify_task_intent(task_description: str) -> dict:
    """Classify a natural-language task description into a TaskIntent.

    Returns a dict with:
      - intent: TaskIntent enum value
      - confidence: float [0, 1]
      - matched_keywords: list[str]
      - reason: str

    This is a backward-compatible wrapper. New code should prefer
    ``analyze_task`` for richer multi-intent classification.
    """
    intent, confidence, keywords = _classify_intent_internal(
        task_description.lower().strip()
    )
    if not task_description.strip():
        return {
            "intent": TaskIntent.understand_code,
            "confidence": 0.3,
            "matched_keywords": [],
            "reason": "Empty task description — defaulting to understand_code.",
        }
    return {
        "intent": intent,
        "confidence": confidence,
        "matched_keywords": keywords[:5],
        "reason": (
            f"Matched keywords: {', '.join(keywords[:3])} → classified as {intent.value}."
            if keywords else
            "No strong keyword match — defaulting to understand_code."
        ),
    }


def analyze_task(task_description: str) -> TaskProfile:
    """Analyze a task description into a rich TaskProfile.

    Detects primary and secondary intents, operation signals,
    domain signals, and constraints. Handles compound tasks like
    "add MFA to login flow and update tests".

    Returns a ``TaskProfile`` with all detected signals.
    """
    text = task_description.lower().strip()
    if not text:
        return TaskProfile(
            primary_intent=TaskIntent.understand_code,
            confidence=0.3,
            reason="Empty task description — defaulting to understand_code.",
        )

    # Detect operation signals and constraints
    op_signals = _detect_operation_signals(text)
    domain_signals = _detect_domain_signals(text)
    constraints = _detect_constraints(text)

    # Primary intent from the first clause (or full text for simple tasks)
    clauses = _split_clauses(text)
    if len(clauses) > 1:
        primary_intent, confidence, keywords = _classify_intent_internal(clauses[0])
    else:
        primary_intent, confidence, keywords = _classify_intent_internal(text)

    # Secondary intents
    secondary_intents = _infer_secondary_intents(op_signals, primary_intent, text)

    # Reason
    reason = _build_profile_reason(
        primary_intent, secondary_intents, op_signals, domain_signals, constraints,
    )

    return TaskProfile(
        primary_intent=primary_intent,
        secondary_intents=secondary_intents,
        keywords=keywords,
        domain_signals=domain_signals,
        operation_signals=op_signals,
        constraints=constraints,
        confidence=confidence,
        reason=reason,
    )


def compose_strategy(profile: TaskProfile) -> ContextStrategy:
    """Build a ``ContextStrategy`` from a ``TaskProfile``.

    Unlike ``get_strategy(intent)`` which returns a fixed template,
    this composes a strategy dynamically from the profile's signals
    and constraints. The result carries ``StrategyFlags`` that
    downstream modules use for granular decisions.

    Composition rules (in order of precedence):
      1. Primary intent sets the base flags
      2. Operation signals add/override flags
      3. Secondary intents add flags
      4. Constraints override flags (highest precedence)
    """
    flags = StrategyFlags()
    intent = profile.primary_intent

    # ── 1. Base flags from primary intent ──
    if intent == TaskIntent.add_feature:
        flags.needs_impact = True
        flags.needs_tests = True
        flags.focus_callees = True
        flags.focus_models = True
    elif intent == TaskIntent.fix_bug:
        flags.needs_impact = True
        flags.needs_tests = True
        flags.focus_callers = True
        flags.focus_callees = True
    elif intent == TaskIntent.refactor:
        flags.needs_impact = True
        flags.needs_tests = True
        flags.focus_callers = True
        flags.focus_callees = True
    elif intent == TaskIntent.modify_existing_behavior:
        flags.needs_impact = True
        flags.needs_tests = True
        flags.focus_callers = True
        flags.focus_callees = True
    elif intent == TaskIntent.understand_code:
        flags.focus_callees = True
        flags.is_read_only = True
        flags.modify_allowed = False
    elif intent == TaskIntent.write_tests:
        flags.needs_tests = True
        flags.focus_tests = True
        flags.focus_callees = True
    elif intent == TaskIntent.review_code:
        flags.needs_impact = True
        flags.needs_tests = True
        flags.focus_callers = True
        flags.focus_callees = True
        flags.is_read_only = True
    elif intent == TaskIntent.analyze_impact:
        flags.needs_impact = True
        flags.focus_callers = True
        flags.focus_callees = True
        flags.is_read_only = True
        flags.modify_allowed = False
    elif intent == TaskIntent.generate_docs:
        flags.focus_callees = True
        flags.focus_models = True
        flags.is_read_only = True
        flags.modify_allowed = False

    # ── 2. Operation signals ──
    for sig in profile.operation_signals:
        if sig == "test":
            flags.needs_tests = True
            flags.focus_tests = True
        elif sig == "analyze":
            flags.needs_impact = True
            flags.focus_callers = True
        elif sig == "review":
            flags.focus_callers = True
            flags.focus_callees = True

    # ── 3. Secondary intents ──
    for sec in profile.secondary_intents:
        if sec == TaskIntent.write_tests:
            flags.needs_tests = True
            flags.focus_tests = True
        elif sec == TaskIntent.analyze_impact:
            flags.needs_impact = True
            flags.focus_callers = True
        elif sec in (TaskIntent.fix_bug, TaskIntent.refactor):
            flags.needs_impact = True
            flags.needs_tests = True

    # ── 4. Constraints (highest precedence) ──
    for constraint in profile.constraints:
        if constraint == "no_modify":
            flags.modify_allowed = False
            flags.is_read_only = True
            flags.needs_impact = False
        elif constraint == "preserve_behavior":
            flags.preserve_behavior = True
            flags.focus_callers = True
            flags.focus_tests = True
        elif constraint == "with_tests":
            flags.needs_tests = True
            flags.focus_tests = True
        elif constraint == "performance":
            flags.focus_callees = True
        elif constraint == "security":
            flags.focus_callers = True
            flags.focus_callees = True

    # ── Build reading_plan_order from flags ──
    reading_plan_order: list[str] = ["entry"]

    # Determine caller/callee ordering
    if flags.focus_callers and flags.focus_callees:
        # Both: callers first for modify-type, callees first for understand-type
        if flags.modify_allowed and not flags.is_read_only:
            reading_plan_order.extend(["callers", "callees"])
        else:
            reading_plan_order.extend(["callees", "callers"])
    elif flags.focus_callers:
        reading_plan_order.extend(["callers", "callees"])
    elif flags.focus_callees:
        reading_plan_order.extend(["callees", "callers"])
    else:
        reading_plan_order.extend(["callers", "callees"])

    # Model/config/store
    if flags.focus_models:
        reading_plan_order.extend(["models", "config", "store"])
    else:
        reading_plan_order.extend(["models", "config", "store"])

    # Tests
    if flags.focus_tests or flags.needs_tests:
        reading_plan_order.append("tests")
    else:
        reading_plan_order.append("tests")

    reading_plan_order.append("low_conf")

    # ── Build relation_priority_map from flags ──
    priority_map: dict[str, str] = {
        "entry_point": "critical",
        "callee": "high" if flags.focus_callees else "medium",
        "caller": (
            "critical" if flags.focus_callers
            else "high" if flags.modify_allowed
            else "medium"
        ),
        "test": (
            "critical" if flags.focus_tests
            else "high" if flags.needs_tests
            else "low"
        ),
        "model": "high" if flags.focus_models else "medium",
        "config": "high" if flags.focus_models else "medium",
        "store": "high" if flags.focus_models else "medium",
    }

    # ── Build agent_strategy_focus from flags ──
    focus_parts: list[str] = []

    if flags.is_read_only or not flags.modify_allowed:
        focus_parts.append(
            "IMPORTANT: This is a read-only task — do NOT modify any source code."
        )
    if flags.preserve_behavior:
        focus_parts.append(
            "IMPORTANT: Preserve existing behavior. All existing tests must continue to pass unchanged."
        )
    if flags.needs_impact:
        focus_parts.append(
            "Run impact analysis and review all affected files before making changes."
        )
    if flags.focus_callers:
        focus_parts.append(
            "Prioritize upstream callers — understand every consumer that depends on this code."
        )
    if flags.focus_callees:
        focus_parts.append(
            "Trace downstream callees to understand the full dependency chain."
        )
    if flags.focus_models:
        focus_parts.append(
            "Review data models, configuration, and persistence layers for required changes."
        )
    if flags.focus_tests:
        focus_parts.append(
            "Focus on test coverage — review existing test patterns and write comprehensive tests for uncovered paths."
        )
    elif flags.needs_tests:
        focus_parts.append(
            "Update related tests to cover the changes."
        )

    # Fall back to the base strategy's focus if flags don't produce one
    base_strategy = get_strategy(intent)
    agent_focus = " ".join(focus_parts) if focus_parts else base_strategy.agent_strategy_focus

    # Build context_focus string
    focus_areas: list[str] = []
    if flags.focus_callees:
        focus_areas.append("callees")
    if flags.focus_callers:
        focus_areas.append("callers")
    if flags.focus_models:
        focus_areas.append("models/config/store")
    if flags.focus_tests:
        focus_areas.append("tests")
    context_focus = "Entry points + " + " + ".join(focus_areas) if focus_areas else base_strategy.context_focus

    return ContextStrategy(
        intent=intent,
        trigger_keywords=base_strategy.trigger_keywords,
        context_focus=context_focus,
        impact_required=flags.needs_impact,
        tests_required=flags.needs_tests,
        reading_plan_order=reading_plan_order,
        relation_priority_map=priority_map,
        agent_strategy_focus=agent_focus,
        flags=flags,
    )
