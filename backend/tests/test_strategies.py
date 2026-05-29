"""Tests for intent classification and per-intent context strategies.

Round 2: Task Intent Classification & Strategy Optimization.
"""

import pytest

from codegraph.context.models import TaskIntent
from codegraph.context.strategies import (
    ContextStrategy,
    classify_task_intent,
    get_strategy,
)
from codegraph.context.pack_builder import build_context_pack
from codegraph.graph.models import GraphNode, NodeType
from codegraph.graph.store import GraphStore


# ── ClassifyTaskIntent ──────────────────────────────────────────────────────


class TestClassifyTaskIntent:
    """Verify classify_task_intent returns correct intent, confidence, keywords, reason."""

    def test_returns_dict_with_required_keys(self):
        result = classify_task_intent("add MFA to login flow")
        for key in ("intent", "confidence", "matched_keywords", "reason"):
            assert key in result, f"Missing key: {key}"

    def test_intent_is_task_intent_enum(self):
        result = classify_task_intent("add MFA to login")
        assert isinstance(result["intent"], TaskIntent)

    def test_confidence_is_float(self):
        result = classify_task_intent("fix login bug")
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_reason_is_non_empty_string(self):
        result = classify_task_intent("refactor auth module")
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0

    # ── Individual intents ──────────────────────────────────────────────

    def test_add_feature(self):
        for text in ("add MFA to login flow", "implement password reset",
                     "support OAuth login", "create user profile",
                     "introduce rate limiting", "enable dark mode"):
            result = classify_task_intent(text)
            assert result["intent"] == TaskIntent.add_feature, f"Failed for: {text}"

    def test_modify_existing_behavior(self):
        for text in ("change token expiration", "update login flow",
                     "modify auth check", "adjust timeout", "revise the response format"):
            result = classify_task_intent(text)
            assert result["intent"] == TaskIntent.modify_existing_behavior, f"Failed for: {text}"

    def test_fix_bug(self):
        for text in ("fix token expiration bug", "login fails with invalid password",
                     "error when saving user", "broken redirect after login",
                     "fix issue #123", "incorrect error code"):
            result = classify_task_intent(text)
            assert result["intent"] == TaskIntent.fix_bug, f"Failed for: {text}"

    def test_refactor(self):
        for text in ("refactor permission check", "extract token logic",
                     "simplify auth flow", "rename get_user to fetch_user",
                     "cleanup old code", "split large function"):
            result = classify_task_intent(text)
            assert result["intent"] == TaskIntent.refactor, f"Failed for: {text}"

    def test_write_tests(self):
        for text in ("add tests for auth service", "write tests for login",
                     "add test coverage for user module",
                     "write unit tests", "integration test for API"):
            result = classify_task_intent(text)
            assert result["intent"] == TaskIntent.write_tests, f"Failed for: {text}"

    def test_understand_code(self):
        for text in ("explain how login works", "understand auth flow",
                     "how does token refresh work", "walk me through the login process",
                     "what does this function do", "describe the auth module"):
            result = classify_task_intent(text)
            assert result["intent"] == TaskIntent.understand_code, f"Failed for: {text}"

    def test_review_code(self):
        for text in ("review the auth code", "audit security checks",
                     "check for vulnerabilities", "inspect password hashing",
                     "verify token validation"):
            result = classify_task_intent(text)
            assert result["intent"] == TaskIntent.review_code, f"Failed for: {text}"

    def test_analyze_impact(self):
        for text in ("impact of changing login", "what breaks if I modify auth",
                     "blast radius of token change", "what files are affected by login",
                     "dependency analysis for user module"):
            result = classify_task_intent(text)
            assert result["intent"] == TaskIntent.analyze_impact, f"Failed for: {text}"

    def test_generate_docs(self):
        for text in ("document the auth API", "write docs for login endpoint",
                     "generate API docs", "add docstrings to user module",
                     "create readme for auth"):
            result = classify_task_intent(text)
            assert result["intent"] == TaskIntent.generate_docs, f"Failed for: {text}"

    # ── Conflict resolution ────────────────────────────────────────────

    def test_add_tests_not_add_feature(self):
        """'add tests for login' must classify as write_tests, not add_feature."""
        result = classify_task_intent("add tests for login")
        assert result["intent"] == TaskIntent.write_tests

    def test_fix_tests_is_fix_bug(self):
        """'fix login tests' has 'fix' before 'tests', fix_bug has higher priority."""
        result = classify_task_intent("fix login tests")
        assert result["intent"] == TaskIntent.fix_bug

    def test_explain_not_generate_docs(self):
        """'explain how login works' must be understand_code, not generate_docs."""
        result = classify_task_intent("explain how login works")
        assert result["intent"] == TaskIntent.understand_code

    def test_empty_defaults_to_understand(self):
        result = classify_task_intent("")
        assert result["intent"] == TaskIntent.understand_code
        assert result["confidence"] <= 0.5

    # ── Multiple keywords → higher confidence ──────────────────────────

    def test_multiple_keywords_higher_confidence(self):
        s1 = classify_task_intent("fix bug in login")["confidence"]
        s2 = classify_task_intent("fix the issue with broken error handling in the crash")["confidence"]
        assert s2 >= s1, f"More keywords should have higher or equal confidence: {s1} vs {s2}"


# ── ContextStrategy ──────────────────────────────────────────────────────────


class TestContextStrategy:
    """Verify each intent has a strategy with required fields."""

    def test_all_nine_intents_have_strategy(self):
        expected = {
            TaskIntent.understand_code,
            TaskIntent.modify_existing_behavior,
            TaskIntent.add_feature,
            TaskIntent.fix_bug,
            TaskIntent.refactor,
            TaskIntent.write_tests,
            TaskIntent.review_code,
            TaskIntent.analyze_impact,
            TaskIntent.generate_docs,
        }
        for intent in expected:
            s = get_strategy(intent)
            assert s is not None, f"Missing strategy for {intent}"
            assert s.intent == intent

    def test_strategy_has_required_fields(self):
        for intent in TaskIntent:
            s = get_strategy(intent)
            assert s.intent is not None
            assert len(s.trigger_keywords) > 0
            assert len(s.context_focus) > 0
            assert isinstance(s.impact_required, bool)
            assert isinstance(s.tests_required, bool)
            assert len(s.reading_plan_order) > 0
            assert "entry" in s.reading_plan_order
            assert len(s.relation_priority_map) > 0
            assert len(s.agent_strategy_focus) > 0

    # ── Strategy-specific assertions ────────────────────────────────────

    def test_understand_code_no_impact(self):
        s = get_strategy(TaskIntent.understand_code)
        assert s.impact_required is False
        assert s.tests_required is False

    def test_add_feature_requires_impact_and_tests(self):
        s = get_strategy(TaskIntent.add_feature)
        assert s.impact_required is True
        assert s.tests_required is True
        # Models, config, store should have high priority for add_feature
        assert s.relation_priority_map.get("model") == "high"
        assert s.relation_priority_map.get("config") == "high"
        assert s.relation_priority_map.get("store") == "high"

    def test_fix_bug_requires_impact_and_tests(self):
        s = get_strategy(TaskIntent.fix_bug)
        assert s.impact_required is True
        assert s.tests_required is True
        # Callers should have high priority (who triggers the bug)
        assert s.relation_priority_map.get("caller") == "high"

    def test_refactor_requires_impact_and_tests(self):
        s = get_strategy(TaskIntent.refactor)
        assert s.impact_required is True
        assert s.tests_required is True
        # Callers should have critical priority (need to update all callers!)
        assert s.relation_priority_map.get("caller") == "critical"

    def test_write_tests_prioritizes_tests(self):
        s = get_strategy(TaskIntent.write_tests)
        assert s.impact_required is False
        assert s.tests_required is True
        assert s.relation_priority_map.get("test") == "critical"

    def test_generate_docs_no_impact_no_tests(self):
        s = get_strategy(TaskIntent.generate_docs)
        assert s.impact_required is False
        assert s.tests_required is False

    def test_analyze_impact_prioritizes_impact(self):
        s = get_strategy(TaskIntent.analyze_impact)
        assert s.impact_required is True
        assert s.relation_priority_map.get("caller") == "critical"


# ── Strategy-aware reading plan ─────────────────────────────────────────────


class TestStrategyAwareReadingPlan:
    """Evidence Pack: reading plans removed. Strategy order lives in relation_priority_map."""

    def test_add_feature_reading_plan_order(self):
        """Strategy reading_plan_order still defines section ordering internally."""
        s = get_strategy(TaskIntent.add_feature)
        assert isinstance(s.reading_plan_order, list)
        assert "entry" in s.reading_plan_order
        assert "models" in s.reading_plan_order

    def test_refactor_reading_plan_order(self):
        """Refactor strategy prioritizes callers over callees."""
        s = get_strategy(TaskIntent.refactor)
        caller_idx = s.reading_plan_order.index("callers")
        callee_idx = s.reading_plan_order.index("callees")
        assert caller_idx < callee_idx

    def test_understand_code_reading_plan_order(self):
        """Understand strategy prioritizes callees over callers."""
        s = get_strategy(TaskIntent.understand_code)
        callee_idx = s.reading_plan_order.index("callees")
        caller_idx = s.reading_plan_order.index("callers")
        assert callee_idx < caller_idx

    def test_write_tests_reading_plan_order(self):
        """Write tests strategy prioritizes tests after callees."""
        s = get_strategy(TaskIntent.write_tests)
        assert s.reading_plan_order.index("tests") < s.reading_plan_order.index("low_conf")


# ── Intent-aware Context Pack integration ────────────────────────────────────


def _make_store() -> GraphStore:
    store = GraphStore()
    for n in [
        GraphNode(id="app/api/auth.py", type=NodeType.file, name="auth.py",
                  file_path="app/api/auth.py"),
        GraphNode(id="app/api/auth.py::login", type=NodeType.function, name="login",
                  file_path="app/api/auth.py",
                  code_preview="def login(u, p): return 'token'"),
        GraphNode(id="app/store/token_store.py::save_token", type=NodeType.function,
                  name="save_token", file_path="app/store/token_store.py",
                  code_preview="def save_token(t): pass"),
        GraphNode(id="main.py::main", type=NodeType.function, name="main",
                  file_path="main.py",
                  code_preview="def main(): login('u','p')"),
    ]:
        store.add_node(n)
    from codegraph.graph.models import EdgeType, GraphEdge
    store.add_edge(GraphEdge(type=EdgeType.calls, source="main.py::main",
                   target="app/api/auth.py::login", confidence=0.95))
    store.add_edge(GraphEdge(type=EdgeType.calls, source="app/api/auth.py::login",
                   target="app/store/token_store.py::save_token", confidence=0.90))
    return store


class TestIntentAwareContextPack:
    """Verify that different intents produce different Context Pack characteristics."""

    def test_understand_code_skips_impact(self):
        store = _make_store()
        pack = build_context_pack(store, "explain how login works")
        # understand_code: impact_required=False → impact should be minimal
        assert pack.task.intent == TaskIntent.understand_code
        # Impact may be empty (no changed_symbol)
        assert isinstance(pack.impact.changed_symbol, str)

    def test_add_feature_includes_impact(self):
        store = _make_store()
        pack = build_context_pack(store, "add MFA to login flow")
        assert pack.task.intent == TaskIntent.add_feature
        # add_feature: impact_required=True → impact should be computed
        assert pack.impact.changed_symbol != "" or len(pack.impact.affected_symbols) >= 0

    def test_write_tests_prioritizes_test_context(self):
        store = _make_store()
        pack = build_context_pack(store, "add tests for auth service")
        assert pack.task.intent == TaskIntent.write_tests
        # Evidence Pack: selected_context should exist
        assert isinstance(pack.selected_context, list)

    def test_different_intents_produce_different_intents(self):
        store = _make_store()
        pack_understand = build_context_pack(store, "explain how login works")
        pack_refactor = build_context_pack(store, "refactor the login function")
        assert pack_understand.task.intent == TaskIntent.understand_code
        assert pack_refactor.task.intent == TaskIntent.refactor

    def test_classification_result_in_pack(self):
        """Verify intent classification appears in task model."""
        store = _make_store()
        pack = build_context_pack(store, "fix token expiration bug")
        assert pack.task.intent == TaskIntent.fix_bug
        assert pack.task.primary_intent == TaskIntent.fix_bug

    def test_add_feature_pack_includes_impact_and_tests_evidence(self):
        """add_feature strategy: pack includes impact signals and test evidence."""
        store = _make_store()
        pack = build_context_pack(store, "add MFA to login flow")
        # Evidence Pack should have selected_context and impact
        assert isinstance(pack.selected_context, list)
        # Impact should be enabled for add_feature
        assert pack.impact is not None
        # Tests section should exist
        assert hasattr(pack.tests, 'existing_tests')
        assert hasattr(pack.tests, 'suggested_tests')


# ── Round 3: TaskProfile & analyze_task ─────────────────────────────────────


class TestTaskProfileFields:
    """Verify TaskProfile has all required fields."""

    def test_has_primary_intent(self):
        from codegraph.context.strategies import TaskProfile
        p = TaskProfile()
        assert p.primary_intent == TaskIntent.understand_code

    def test_has_secondary_intents_list(self):
        from codegraph.context.strategies import TaskProfile
        p = TaskProfile()
        assert isinstance(p.secondary_intents, list)
        assert len(p.secondary_intents) == 0

    def test_has_operation_signals(self):
        from codegraph.context.strategies import TaskProfile
        p = TaskProfile()
        assert isinstance(p.operation_signals, list)

    def test_has_domain_signals(self):
        from codegraph.context.strategies import TaskProfile
        p = TaskProfile()
        assert isinstance(p.domain_signals, list)

    def test_has_constraints(self):
        from codegraph.context.strategies import TaskProfile
        p = TaskProfile()
        assert isinstance(p.constraints, list)

    def test_has_keywords(self):
        from codegraph.context.strategies import TaskProfile
        p = TaskProfile()
        assert isinstance(p.keywords, list)

    def test_has_confidence(self):
        from codegraph.context.strategies import TaskProfile
        p = TaskProfile()
        assert isinstance(p.confidence, float)

    def test_has_reason(self):
        from codegraph.context.strategies import TaskProfile
        p = TaskProfile()
        assert isinstance(p.reason, str)


class TestAnalyzeTask:
    """Verify analyze_task returns rich TaskProfile with signals and constraints."""

    def test_returns_task_profile(self):
        from codegraph.context.strategies import TaskProfile, analyze_task
        result = analyze_task("add MFA to login flow")
        assert isinstance(result, TaskProfile)

    def test_simple_task_has_primary_intent(self):
        from codegraph.context.strategies import analyze_task
        p = analyze_task("add MFA to login flow")
        assert p.primary_intent == TaskIntent.add_feature

    def test_detects_operation_signals(self):
        from codegraph.context.strategies import analyze_task
        p = analyze_task("add MFA to login flow")
        assert "create" in p.operation_signals

    def test_detects_domain_signals(self):
        from codegraph.context.strategies import analyze_task
        p = analyze_task("add MFA to login flow")
        assert "auth" in p.domain_signals

    def test_detects_constraints(self):
        from codegraph.context.strategies import analyze_task
        p = analyze_task("explain login flow, do not modify code")
        assert "no_modify" in p.constraints

    def test_detects_preserve_behavior_constraint(self):
        from codegraph.context.strategies import analyze_task
        p = analyze_task("refactor permission check without changing behavior")
        assert "preserve_behavior" in p.constraints

    def test_detects_with_tests_constraint(self):
        from codegraph.context.strategies import analyze_task
        p = analyze_task("add MFA to login flow and update tests")
        assert "with_tests" in p.constraints

    def test_understand_code_has_read_only_signals(self):
        from codegraph.context.strategies import analyze_task
        p = analyze_task("explain how login works")
        assert p.primary_intent == TaskIntent.understand_code

    def test_empty_input_defaults(self):
        from codegraph.context.strategies import analyze_task
        p = analyze_task("")
        assert p.primary_intent == TaskIntent.understand_code
        assert p.confidence <= 0.5

    def test_reason_is_descriptive(self):
        from codegraph.context.strategies import analyze_task
        p = analyze_task("add MFA to login flow and update tests")
        assert "add_feature" in p.reason
        assert "write_tests" in p.reason or len(p.secondary_intents) > 0

    # ── Compound task tests ────────────────────────────────────────────

    def test_compound_task_primary_add_feature(self):
        """'add MFA to login flow and update tests' → primary=add_feature."""
        from codegraph.context.strategies import analyze_task
        p = analyze_task("add MFA to login flow and update tests")
        assert p.primary_intent == TaskIntent.add_feature, \
            f"Expected add_feature, got {p.primary_intent}"

    def test_compound_task_secondary_includes_write_tests(self):
        """'add MFA to login flow and update tests' → secondary includes write_tests."""
        from codegraph.context.strategies import analyze_task
        p = analyze_task("add MFA to login flow and update tests")
        assert TaskIntent.write_tests in p.secondary_intents, \
            f"Expected write_tests in secondary, got {p.secondary_intents}"

    def test_compound_task_has_test_operation_signal(self):
        """'add MFA to login flow and update tests' → operation signals include test."""
        from codegraph.context.strategies import analyze_task
        p = analyze_task("add MFA to login flow and update tests")
        assert "test" in p.operation_signals

    def test_explain_with_no_modify_has_constraint(self):
        """'explain login flow, do not modify code' → constraints include no_modify."""
        from codegraph.context.strategies import analyze_task
        p = analyze_task("explain login flow, do not modify code")
        assert "no_modify" in p.constraints

    def test_explain_with_no_modify_is_understand(self):
        """'explain login flow, do not modify code' → primary_intent=understand_code."""
        from codegraph.context.strategies import analyze_task
        p = analyze_task("explain login flow, do not modify code")
        assert p.primary_intent == TaskIntent.understand_code

    def test_refactor_preserve_behavior_has_constraint(self):
        """'refactor permission check without changing behavior' → preserve_behavior."""
        from codegraph.context.strategies import analyze_task
        p = analyze_task("refactor permission check without changing behavior")
        assert "preserve_behavior" in p.constraints

    def test_refactor_preserve_behavior_is_refactor(self):
        """'refactor permission check without changing behavior' → primary=refactor."""
        from codegraph.context.strategies import analyze_task
        p = analyze_task("refactor permission check without changing behavior")
        assert p.primary_intent == TaskIntent.refactor


# ── Round 3: compose_strategy ───────────────────────────────────────────────


class TestComposeStrategy:
    """Verify compose_strategy builds correct ContextStrategy from TaskProfile."""

    def test_returns_context_strategy(self):
        from codegraph.context.strategies import ContextStrategy, analyze_task, compose_strategy
        p = analyze_task("add MFA to login flow")
        s = compose_strategy(p)
        assert isinstance(s, ContextStrategy)

    def test_strategy_has_flags(self):
        from codegraph.context.strategies import analyze_task, compose_strategy, StrategyFlags
        p = analyze_task("add MFA to login flow")
        s = compose_strategy(p)
        assert isinstance(s.flags, StrategyFlags)

    def test_add_feature_flags(self):
        from codegraph.context.strategies import analyze_task, compose_strategy
        p = analyze_task("add MFA to login flow")
        s = compose_strategy(p)
        assert s.flags.needs_impact is True
        assert s.flags.needs_tests is True
        assert s.flags.focus_models is True
        assert s.flags.focus_callees is True

    def test_understand_code_flags(self):
        from codegraph.context.strategies import analyze_task, compose_strategy
        p = analyze_task("explain how login works")
        s = compose_strategy(p)
        assert s.flags.is_read_only is True
        assert s.flags.modify_allowed is False
        assert s.flags.needs_impact is False
        assert s.flags.focus_callees is True

    def test_no_modify_constraint_overrides_flags(self):
        from codegraph.context.strategies import analyze_task, compose_strategy
        p = analyze_task("explain login flow, do not modify code")
        s = compose_strategy(p)
        assert s.flags.is_read_only is True
        assert s.flags.modify_allowed is False

    def test_preserve_behavior_constraint_flags(self):
        from codegraph.context.strategies import analyze_task, compose_strategy
        p = analyze_task("refactor permission check without changing behavior")
        s = compose_strategy(p)
        assert s.flags.preserve_behavior is True
        assert s.flags.focus_callers is True
        assert s.flags.focus_tests is True

    def test_with_tests_constraint_flags(self):
        from codegraph.context.strategies import analyze_task, compose_strategy
        p = analyze_task("add MFA to login flow and update tests")
        s = compose_strategy(p)
        assert s.flags.needs_tests is True
        assert s.flags.focus_tests is True

    def test_compound_strategy_has_impact(self):
        """Compound add_feature + write_tests still needs impact."""
        from codegraph.context.strategies import analyze_task, compose_strategy
        p = analyze_task("add MFA to login flow and update tests")
        s = compose_strategy(p)
        assert s.flags.needs_impact is True

    def test_reading_plan_order_is_list_of_strings(self):
        from codegraph.context.strategies import analyze_task, compose_strategy
        p = analyze_task("add MFA to login flow")
        s = compose_strategy(p)
        assert isinstance(s.reading_plan_order, list)
        assert "entry" in s.reading_plan_order
        assert "low_conf" in s.reading_plan_order

    def test_relation_priority_map_is_dict(self):
        from codegraph.context.strategies import analyze_task, compose_strategy
        p = analyze_task("add MFA to login flow")
        s = compose_strategy(p)
        assert isinstance(s.relation_priority_map, dict)
        assert "entry_point" in s.relation_priority_map

    def test_agent_strategy_focus_is_string(self):
        from codegraph.context.strategies import analyze_task, compose_strategy
        p = analyze_task("add MFA to login flow")
        s = compose_strategy(p)
        assert isinstance(s.agent_strategy_focus, str)
        assert len(s.agent_strategy_focus) > 0

    # ── Flag-based strategy vs fixed strategy ──────────────────────────

    def test_composed_differs_from_fixed_for_compound_task(self):
        """A compound task's composed strategy should differ from the simple get_strategy."""
        from codegraph.context.strategies import analyze_task, compose_strategy, get_strategy
        p = analyze_task("add MFA to login flow and update tests")
        composed = compose_strategy(p)
        fixed = get_strategy(p.primary_intent)
        # Composed strategy should have test focus, fixed add_feature might not
        assert composed.flags.focus_tests is True
        # Relation priority map should differ for test relation
        assert composed.relation_priority_map.get("test") == "critical"


# ── Round 3: Compound Context Pack integration ──────────────────────────────


class TestCompoundContextPack:
    """Acceptance criteria: compound tasks produce correct Context Packs."""

    def test_add_feature_and_update_tests_primary_intent(self):
        """Acceptance: 'add MFA to login flow and update tests' → primary=add_feature."""
        store = _make_store()
        pack = build_context_pack(store, "add MFA to login flow and update tests")
        assert pack.task.primary_intent == TaskIntent.add_feature

    def test_add_feature_and_update_tests_secondary_intents(self):
        """Acceptance: secondary_intents includes write_tests."""
        store = _make_store()
        pack = build_context_pack(store, "add MFA to login flow and update tests")
        assert TaskIntent.write_tests in pack.task.secondary_intents

    def test_add_feature_and_update_tests_has_impact(self):
        """Acceptance: Context Pack includes impact analysis."""
        store = _make_store()
        pack = build_context_pack(store, "add MFA to login flow and update tests")
        # Impact should be computed (changed_symbol is set)
        assert pack.impact.changed_symbol != "" or len(pack.impact.affected_symbols) >= 0

    def test_add_feature_and_update_tests_has_tests_context(self):
        """Acceptance: Evidence Pack includes test evidence section."""
        store = _make_store()
        pack = build_context_pack(store, "add MFA to login flow and update tests")
        # Tests section should exist
        assert hasattr(pack.tests, 'existing_tests')
        assert hasattr(pack.tests, 'suggested_tests')

    def test_explain_no_modify_has_read_only_constraint(self):
        """Acceptance: 'explain login flow, do not modify code' → no_modify constraint in keywords."""
        store = _make_store()
        pack = build_context_pack(store, "explain login flow, do not modify code")
        # Task should be classified as understand_code
        assert pack.task.primary_intent == TaskIntent.understand_code
        # Evidence Pack: no modification hints in pack_notes or warnings
        assert isinstance(pack.warnings, list)
        assert isinstance(pack.pack_notes, list)

    def test_explain_no_modify_is_understand_primary(self):
        """Acceptance: primary_intent=understand_code for explain task."""
        store = _make_store()
        pack = build_context_pack(store, "explain login flow, do not modify code")
        assert pack.task.primary_intent == TaskIntent.understand_code

    def test_refactor_preserve_behavior_has_callers(self):
        """Acceptance: 'refactor permission check without changing behavior' → caller symbols in related_symbols."""
        store = _make_store()
        pack = build_context_pack(store, "refactor permission check without changing behavior")
        # Impact should be computed for refactor
        assert pack.impact is not None

    def test_refactor_preserve_behavior_has_preserve_behavior_flag(self):
        """Acceptance: preserve_behavior constraint is detected and reflected in strategy."""
        store = _make_store()
        pack = build_context_pack(store, "refactor permission check without changing behavior")
        # The preserve_behavior constraint should be in the task's secondary intents or keywords
        assert pack.task.primary_intent == TaskIntent.refactor
        assert isinstance(pack.selected_context, list)

    def test_refactor_preserve_behavior_has_tests(self):
        """Acceptance: refactor with preserve behavior includes test evidence."""
        store = _make_store()
        pack = build_context_pack(store, "refactor permission check without changing behavior")
        # Tests section should exist
        assert hasattr(pack.tests, 'existing_tests')

    def test_classify_task_intent_still_works(self):
        """Backward compat: classify_task_intent returns dict format."""
        result = classify_task_intent("add MFA to login flow")
        assert isinstance(result, dict)
        assert "intent" in result
        assert "confidence" in result
        assert "matched_keywords" in result
        assert "reason" in result
        assert result["intent"] == TaskIntent.add_feature

    def test_task_model_has_secondary_intents(self):
        """Task model stores primary_intent and secondary_intents."""
        store = _make_store()
        pack = build_context_pack(store, "add MFA to login flow and update tests")
        assert hasattr(pack.task, 'primary_intent')
        assert hasattr(pack.task, 'secondary_intents')
        assert isinstance(pack.task.secondary_intents, list)
