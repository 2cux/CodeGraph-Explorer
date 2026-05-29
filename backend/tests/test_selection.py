"""Tests for context scoring, content mode selection, and ContextSelector."""

import pytest

from codegraph.context.models import (
    ContextType,
    EntryPoint,
    SelectedContext,
    RelatedSymbol,
    Importance,
)
from codegraph.context.selection import (
    ContextSelector,
    score_context_item,
    select_content_mode,
    _build_summary_content,
    _build_reference_content,
    _compute_impact_score,
)
from codegraph.context.token_budget import TokenBudget
from codegraph.graph.models import GraphNode, NodeType, Location, EdgeType
from codegraph.graph.store import GraphStore


# ── Helpers ──────────────────────────────────────────────────────────────────


def _node(
    id: str,
    name: str = "",
    type: NodeType = NodeType.function,
    file_path: str = "app/module.py",
    signature: str = "",
    docstring: str = "",
    code_preview: str = "",
    tags: list[str] | None = None,
) -> GraphNode:
    return GraphNode(
        id=id,
        name=name or id.split("::")[-1],
        type=type,
        file_path=file_path,
        location=Location(line_start=1, line_end=10),
        signature=signature,
        docstring=docstring,
        code_preview=code_preview,
        tags=tags or [],
    )


def _ep(symbol_id: str, name: str = "", score: float = 1.0, file_path: str = "app/module.py") -> EntryPoint:
    return EntryPoint(
        symbol_id=symbol_id,
        type="function",
        name=name or symbol_id.split("::")[-1],
        file_path=file_path,
        reason="Test entry point",
        score=score,
    )


# ── ScoreContextItem ─────────────────────────────────────────────────────────


class TestScoreContextItem:
    def test_entry_point_scores_higest(self):
        """Entry point with name match scores higher than a callee."""
        ep_node = _node("app/auth.py::login", name="login",
                        code_preview="def login(u, p): return 'token'")
        callee_node = _node("app/store.py::save_token", name="save_token")

        ep_score = score_context_item(ep_node, "login flow", "entry_point", "critical", 0.95, 0)
        callee_score = score_context_item(callee_node, "login flow", "callee", "high", 0.85, 1)

        assert ep_score > callee_score, f"ep={ep_score}, callee={callee_score}"

    def test_distance_penalty(self):
        """Same node at distance=3 scores lower than distance=1."""
        node = _node("app/auth.py::login", name="login")
        s1 = score_context_item(node, "login", "callee", "high", 0.9, 1)
        s3 = score_context_item(node, "login", "callee", "high", 0.9, 3)
        assert s3 < s1, f"dist=1={s1}, dist=3={s3}"

    def test_token_cost_penalty(self):
        """Node with large code_preview scores lower than small one."""
        small = _node("app/a.py::f1", name="f1", code_preview="x" * 100)
        large = _node("app/a.py::f2", name="f2", code_preview="x" * 4000)
        s_small = score_context_item(small, "test", "callee", "high", 0.9, 1)
        s_large = score_context_item(large, "test", "callee", "high", 0.9, 1)
        assert s_large < s_small, f"small={s_small}, large={s_large}"

    def test_test_node_gets_test_boost(self):
        """Test nodes get a small boost from the test_score factor."""
        node = _node("tests/test_auth.py::test_login", name="test_login",
                     type=NodeType.test, file_path="tests/test_auth.py")
        score = score_context_item(node, "login", "test", "high", 0.85, 1)
        assert 0.0 <= score <= 1.0

    def test_confidence_affects_score(self):
        """Higher confidence → higher score, all else equal."""
        node = _node("app/auth.py::login", name="login")
        s_high = score_context_item(node, "login", "callee", "high", 0.95, 1)
        s_low = score_context_item(node, "login", "callee", "high", 0.50, 1)
        assert s_high > s_low, f"high_conf={s_high}, low_conf={s_low}"

    def test_result_clamped(self):
        """Score never goes negative even with maximum penalties."""
        node = _node("app/unrelated.py::helper", name="helper",
                     code_preview="x" * 10000)  # max token cost penalty
        score = score_context_item(node, "completely different topic", "caller", "low", 0.1, 5)
        assert score >= 0.0

    def test_empty_task_description(self):
        node = _node("app/auth.py::login", name="login")
        score = score_context_item(node, "", "entry_point", "critical", 1.0, 0)
        assert 0.0 <= score <= 1.0


# ── ComputeImpactScore ───────────────────────────────────────────────────────


class TestComputeImpactScore:
    def test_entry_point_max(self):
        node = _node("x::f", name="f")
        assert _compute_impact_score(node, "entry_point") == 1.0

    def test_callee_high(self):
        node = _node("x::f", name="f")
        assert _compute_impact_score(node, "callee") == 0.80

    def test_caller_medium(self):
        node = _node("x::f", name="f")
        assert _compute_impact_score(node, "caller") == 0.60

    def test_route_boost(self):
        node = _node("x::f", name="f", tags=["route"])
        score = _compute_impact_score(node, "callee")
        assert score == 0.90  # 0.80 + 0.10

    def test_route_boost_capped(self):
        node = _node("x::f", name="f", tags=["route"])
        score = _compute_impact_score(node, "entry_point")
        assert score == 1.0  # already 1.0, capped


# ── SelectContentMode ────────────────────────────────────────────────────────


class TestSelectContentMode:
    def test_entry_point_always_full_source(self):
        node = _node("app/auth.py::login", name="login",
                     code_preview="def login(): pass")
        budget = TokenBudget(10)  # tiny budget
        mode, content, ctx_type = select_content_mode(node, "critical", "entry_point", 0.95, budget)
        assert mode == "full_source"
        assert ctx_type == ContextType.code_snippet

    def test_model_always_summary(self):
        node = _node("app/models/user.py::User", name="User",
                     type=NodeType.class_,
                     code_preview="class User:\n    id: str\n    name: str")
        budget = TokenBudget(6000)
        mode, content, ctx_type = select_content_mode(node, "high", "model", 0.95, budget)
        assert mode == "summary"
        assert ctx_type == ContextType.model_summary
        assert "User" in content

    def test_config_always_summary(self):
        node = _node("app/config.py::Settings", name="Settings",
                     type=NodeType.class_,
                     code_preview="class Settings:\n    DEBUG = True")
        budget = TokenBudget(6000)
        mode, content, ctx_type = select_content_mode(node, "high", "config", 0.95, budget)
        assert mode == "summary"
        assert ctx_type == ContextType.config_summary

    def test_store_always_summary(self):
        node = _node("app/store.py::TokenStore", name="TokenStore",
                     type=NodeType.class_,
                     code_preview="class TokenStore:\n    def save(self): pass")
        budget = TokenBudget(6000)
        mode, content, ctx_type = select_content_mode(node, "medium", "store", 0.90, budget)
        assert mode == "summary"

    def test_test_high_confidence_full_source(self):
        node = _node("tests/test_auth.py::test_login", name="test_login",
                     type=NodeType.test, file_path="tests/test_auth.py",
                     code_preview="def test_login(): assert True")
        budget = TokenBudget(6000)
        mode, content, ctx_type = select_content_mode(node, "high", "test", 0.90, budget)
        assert mode == "full_source"
        assert ctx_type == ContextType.test_reference

    def test_test_medium_confidence_summary(self):
        node = _node("tests/test_auth.py::test_login", name="test_login",
                     type=NodeType.test, file_path="tests/test_auth.py",
                     code_preview="def test_login(): assert True")
        budget = TokenBudget(6000)
        mode, content, ctx_type = select_content_mode(node, "high", "test", 0.65, budget)
        assert mode == "summary"

    def test_test_low_confidence_warning(self):
        node = _node("tests/test_auth.py::test_login", name="test_login",
                     type=NodeType.test, file_path="tests/test_auth.py")
        budget = TokenBudget(6000)
        mode, content, ctx_type = select_content_mode(node, "high", "test", 0.40, budget)
        assert mode == "reference"
        assert ctx_type == ContextType.warning

    def test_low_confidence_reference(self):
        node = _node("app/unknown.py::helper", name="helper")
        budget = TokenBudget(6000)
        mode, content, ctx_type = select_content_mode(node, "medium", "callee", 0.45, budget)
        assert mode == "reference"
        assert ctx_type == ContextType.warning

    def test_over_budget_degrades_to_summary(self):
        node = _node("app/auth.py::helper", name="helper",
                     code_preview="def helper(): pass\n" * 50)  # reasonably large
        budget = TokenBudget(10)  # tiny budget
        mode, content, ctx_type = select_content_mode(node, "medium", "callee", 0.85, budget)
        assert mode == "summary"


# ── BuildSummaryContent ──────────────────────────────────────────────────────


class TestBuildSummaryContent:
    def test_model_summary_type(self):
        node = _node("app/models/user.py::User", name="User",
                     type=NodeType.class_,
                     code_preview="class User(BaseModel):\n    id: str\n    username: str")
        content, ctx_type = _build_summary_content(node, "model")
        assert ctx_type == ContextType.model_summary
        assert "User" in content

    def test_config_summary_type(self):
        node = _node("app/config.py::Settings", name="Settings",
                     type=NodeType.class_,
                     code_preview="class Settings:\n    TOKEN_TTL = 3600")
        content, ctx_type = _build_summary_content(node, "config")
        assert ctx_type == ContextType.config_summary
        assert "Settings" in content

    def test_store_uses_symbol_summary_type(self):
        node = _node("app/store.py::TokenStore", name="TokenStore",
                     type=NodeType.class_)
        content, ctx_type = _build_summary_content(node, "store")
        assert ctx_type == ContextType.symbol_summary

    def test_generic_symbol_summary(self):
        node = _node("app/lib.py::helper", name="helper",
                     signature="def helper(x: int) -> str")
        content, ctx_type = _build_summary_content(node, "callee")
        assert ctx_type == ContextType.symbol_summary
        assert "helper" in content


# ── BuildReferenceContent ────────────────────────────────────────────────────


class TestBuildReferenceContent:
    def test_contains_warning(self):
        node = _node("app/unknown.py::foo", name="foo")
        content = _build_reference_content(node)
        assert "Low confidence" in content
        assert "foo" in content
        assert "Verify manually" in content


# ── ContextSelector ──────────────────────────────────────────────────────────


def _make_store_for_selection() -> GraphStore:
    """Build a minimal store for testing the ContextSelector.

    Creates: entry point ``login``, callee ``save_token``,
    caller ``main``, model ``User``, test ``test_login``.
    """
    store = GraphStore()

    login = _node("app/api/auth.py::login", name="login",
                  code_preview="def login(u, p): return 'token'")
    save = _node("app/store.py::save_token", name="save_token",
                 code_preview="def save_token(t): pass")
    main = _node("main.py::main", name="main",
                 code_preview="def main(): login('u','p')")
    user_model = _node("app/models/user.py::User", name="User",
                       type=NodeType.class_,
                       code_preview="class User:\n    id: str\n    name: str")
    test_login = _node("tests/test_auth.py::test_login", name="test_login",
                       type=NodeType.test, file_path="tests/test_auth.py",
                       code_preview="def test_login(): assert login('u','p') == 'token'")
    settings = _node("app/config.py::Settings", name="Settings",
                     type=NodeType.class_,
                     code_preview="class Settings:\n    DEBUG = True")

    for n in [login, save, main, user_model, test_login, settings]:
        store.add_node(n)

    return store


class TestContextSelector:
    def test_select_returns_non_empty(self):
        store = _make_store_for_selection()
        selector = ContextSelector(store, "add MFA to login", 6000)
        eps = [_ep("app/api/auth.py::login", name="login", file_path="app/api/auth.py")]

        related = [
            RelatedSymbol(symbol_id="app/store.py::save_token", relation="callee",
                          importance=Importance.high, confidence=0.90, distance=1),
            RelatedSymbol(symbol_id="main.py::main", relation="caller",
                          importance=Importance.medium, confidence=0.85, distance=1),
            RelatedSymbol(symbol_id="app/models/user.py::User", relation="model_dependency",
                          importance=Importance.high, confidence=0.85, distance=2),
            RelatedSymbol(symbol_id="tests/test_auth.py::test_login", relation="test",
                          importance=Importance.high, confidence=0.90, distance=2),
            RelatedSymbol(symbol_id="app/config.py::Settings", relation="config_dependency",
                          importance=Importance.high, confidence=0.85, distance=2),
        ]

        recommended, optional = selector.select(eps, related)
        assert len(recommended) > 0

    def test_entry_points_not_duplicated(self):
        """Entry point IDs should not appear in recommended/optional from selector."""
        store = _make_store_for_selection()
        selector = ContextSelector(store, "login flow", 6000)
        eps = [_ep("app/api/auth.py::login", name="login", file_path="app/api/auth.py")]

        related = [
            RelatedSymbol(symbol_id="app/api/auth.py::login", relation="callee",
                          importance=Importance.high, confidence=0.90, distance=0),
        ]

        recommended, optional = selector.select(eps, related)
        all_ids = {rc.symbol_id for rc in recommended} | {rc.symbol_id for rc in optional}
        assert "app/api/auth.py::login" not in all_ids

    def test_model_goes_to_recommended_not_optional(self):
        """Model dependency with high confidence goes to recommended."""
        store = _make_store_for_selection()
        selector = ContextSelector(store, "add MFA", 6000)
        eps = [_ep("app/api/auth.py::login", name="login")]

        related = [
            RelatedSymbol(symbol_id="app/models/user.py::User", relation="model_dependency",
                          importance=Importance.high, confidence=0.90, distance=2),
        ]

        recommended, optional = selector.select(eps, related)
        model_ids = {rc.symbol_id for rc in recommended}
        assert "app/models/user.py::User" in model_ids

    def test_low_confidence_goes_to_optional(self):
        store = _make_store_for_selection()
        selector = ContextSelector(store, "add MFA", 6000)
        eps = [_ep("app/api/auth.py::login", name="login")]

        related = [
            RelatedSymbol(symbol_id="app/store.py::save_token", relation="callee",
                          importance=Importance.low, confidence=0.45, distance=1),
        ]

        recommended, optional = selector.select(eps, related)
        opt_ids = {rc.symbol_id for rc in optional}
        assert "app/store.py::save_token" in opt_ids

    def test_context_scores_set(self):
        store = _make_store_for_selection()
        selector = ContextSelector(store, "add MFA", 6000)
        eps = [_ep("app/api/auth.py::login", name="login")]

        related = [
            RelatedSymbol(symbol_id="app/store.py::save_token", relation="callee",
                          importance=Importance.high, confidence=0.90, distance=1),
        ]

        recommended, optional = selector.select(eps, related)
        for rc in recommended:
            assert rc.context_score > 0, f"Expected context_score > 0 for {rc.symbol_id}"

    def test_content_modes_set(self):
        store = _make_store_for_selection()
        selector = ContextSelector(store, "add MFA", 6000)
        eps = [_ep("app/api/auth.py::login", name="login")]

        related = [
            RelatedSymbol(symbol_id="app/store.py::save_token", relation="callee",
                          importance=Importance.high, confidence=0.90, distance=1),
        ]

        recommended, optional = selector.select(eps, related)
        for rc in recommended:
            assert rc.content_mode in ("full_source", "summary", "reference"), \
                f"Unexpected content_mode: {rc.content_mode}"

    def test_model_summarized(self):
        """Model items get summary content mode."""
        store = _make_store_for_selection()
        selector = ContextSelector(store, "add MFA", 6000)
        eps = [_ep("app/api/auth.py::login", name="login")]

        related = [
            RelatedSymbol(symbol_id="app/models/user.py::User", relation="model_dependency",
                          importance=Importance.high, confidence=0.90, distance=2),
        ]

        recommended, optional = selector.select(eps, related)
        for rc in recommended:
            if rc.symbol_id == "app/models/user.py::User":
                assert rc.content_mode == "summary", \
                    f"Model should be summary, got {rc.content_mode}"
                assert rc.type == ContextType.model_summary

    def test_token_budget_tracks_usage(self):
        store = _make_store_for_selection()
        selector = ContextSelector(store, "add MFA", 6000)
        eps = [_ep("app/api/auth.py::login", name="login")]

        related = [
            RelatedSymbol(symbol_id="app/store.py::save_token", relation="callee",
                          importance=Importance.high, confidence=0.90, distance=1),
        ]

        selector.select(eps, related)
        tb = selector.budget.as_dict()
        assert tb["max_tokens"] == 6000
        assert tb["used_tokens"] > 0

    def test_tiny_budget_still_includes_items(self):
        """Even with tiny budget, the selector returns something (degraded or optional)."""
        store = _make_store_for_selection()
        selector = ContextSelector(store, "add MFA", 100)
        eps = [_ep("app/api/auth.py::login", name="login")]

        related = [
            RelatedSymbol(symbol_id="app/store.py::save_token", relation="callee",
                          importance=Importance.high, confidence=0.90, distance=1),
        ]

        recommended, optional = selector.select(eps, related)
        # Should have at least something — either recommended or optional
        total = len(recommended) + len(optional)
        assert total > 0, "Should have at least one item even with tiny budget"

    def test_empty_related_works(self):
        store = _make_store_for_selection()
        selector = ContextSelector(store, "add MFA", 6000)
        eps = [_ep("app/api/auth.py::login", name="login")]
        recommended, optional = selector.select(eps, [])
        assert isinstance(recommended, list)
        assert isinstance(optional, list)
