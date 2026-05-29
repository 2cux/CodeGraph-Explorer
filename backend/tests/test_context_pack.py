"""Tests for Context Pack generation — ranking, reading plan, markdown, and pack builder."""

import pytest
from codegraph.graph.models import GraphNode, NodeType, EdgeType, Location, GraphEdge
from codegraph.graph.store import GraphStore
from codegraph.context.models import (
    ContextPack, Task, TaskIntent, TaskConstraints,
    EntryPoint, RelatedSymbol, CallGraph, CallGraphNode, CallGraphEdge,
    Impact, AffectedSymbol, AffectedFile, Risk, RiskLevel,
    RecommendedContext, ContextType, ReadingStep, AgentInstructions,
    Importance, ImpactType,
)
from codegraph.context.ranking import tokenize, score_relevance, rank_entry_points, get_match_sources, build_reason
from codegraph.context.reading_plan import build_reading_plan
from codegraph.context.markdown_exporter import export_to_markdown, save_markdown
from codegraph.context.pack_builder import build_context_pack


# ══════════════════════════════════════════════════════════════════════════
# Ranking tests
# ══════════════════════════════════════════════════════════════════════════


class TestTokenize:
    def test_basic(self):
        tokens = tokenize("add MFA to login flow")
        assert "add" in tokens
        assert "login" in tokens
        assert "flow" in tokens
        assert "to" not in tokens  # stopword

    def test_stopwords_removed(self):
        tokens = tokenize("the quick brown fox jumps over the lazy dog")
        meaningful = [t for t in tokens if t not in ("the", "over")]
        assert len(meaningful) <= len(tokens)

    def test_empty_string(self):
        assert tokenize("") == []

    def test_short_tokens_removed(self):
        tokens = tokenize("a an the is go to")
        assert tokens == []


class TestScoreRelevance:
    def test_exact_name_match(self):
        node = GraphNode(id="auth.py::login", type=NodeType.function, name="login",
                         file_path="auth.py")
        score = score_relevance(node, "login")
        assert score > 0.9

    def test_file_path_match(self):
        node = GraphNode(id="auth.py", type=NodeType.file, name="auth.py",
                         file_path="auth.py", module="auth")
        score = score_relevance(node, "auth")
        assert score > 0.0

    def test_no_match(self):
        node = GraphNode(id="x.py::foo", type=NodeType.function, name="foo",
                         file_path="x.py")
        score = score_relevance(node, "something_completely_different")
        assert score == 0.0

    def test_empty_task(self):
        node = GraphNode(id="x.py::foo", type=NodeType.function, name="foo",
                         file_path="x.py")
        score = score_relevance(node, "")
        assert score == 0.5  # default when no description


class TestRankEntryPoints:
    def test_ranks_by_relevance(self):
        nodes = [
            GraphNode(id="auth.py::login", type=NodeType.function, name="login",
                      file_path="auth.py"),
            GraphNode(id="user.py::User", type=NodeType.class_, name="User",
                      file_path="user.py"),
        ]
        ranked = rank_entry_points("login", nodes)
        assert len(ranked) == 2
        # login should rank higher than User for "login" query
        assert ranked[0][0].name == "login"
        assert ranked[0][1] >= ranked[1][1]

    def test_empty_candidates(self):
        assert rank_entry_points("test", []) == []

    def test_filters_zero_score(self):
        nodes = [
            GraphNode(id="x.py::foo", type=NodeType.function, name="foo",
                      file_path="x.py"),
        ]
        ranked = rank_entry_points("something_completely_different", nodes)
        assert ranked == []


class TestGetMatchSources:
    def test_name_match(self):
        node = GraphNode(id="auth.py::login", type=NodeType.function, name="login",
                         file_path="auth.py")
        sources = get_match_sources(node, ["login"])
        assert "symbol_name" in sources

    def test_file_path_match(self):
        node = GraphNode(id="auth.py", type=NodeType.file, name="auth.py",
                         file_path="auth.py", module="auth")
        sources = get_match_sources(node, ["auth"])
        assert "file_path" in sources or "module_name" in sources


class TestBuildReason:
    def test_contains_name(self):
        node = GraphNode(id="auth.py::login", type=NodeType.function, name="login",
                         file_path="auth.py")
        reason = build_reason(node, ["login"])
        assert "login" in reason


# ══════════════════════════════════════════════════════════════════════════
# Reading Plan tests
# ══════════════════════════════════════════════════════════════════════════


class TestBuildReadingPlan:
    def test_entry_points_first(self):
        plan = build_reading_plan(
            entry_point_ids=["auth.py::login"],
            callee_ids=["store.py::save"],
            caller_ids=["main.py::main"],
            test_ids=["test_auth.py"],
        )
        assert len(plan) == 4
        assert plan[0].target == "auth.py::login"
        assert plan[0].step == 1

    def test_callees_second(self):
        plan = build_reading_plan(
            entry_point_ids=["auth.py::login"],
            callee_ids=["store.py::save"],
            caller_ids=[],
            test_ids=[],
        )
        assert plan[1].target == "store.py::save"
        assert plan[1].step == 2

    def test_callers_after_callees(self):
        plan = build_reading_plan(
            entry_point_ids=["auth.py::login"],
            callee_ids=["store.py::save"],
            caller_ids=["main.py::main"],
            test_ids=[],
        )
        assert plan[2].target == "main.py::main"

    def test_tests_last(self):
        plan = build_reading_plan(
            entry_point_ids=["auth.py::login"],
            callee_ids=["store.py::save"],
            caller_ids=["main.py::main"],
            test_ids=["test_auth.py::test_login"],
        )
        assert plan[-1].target == "test_auth.py::test_login"

    def test_max_steps(self):
        plan = build_reading_plan(
            entry_point_ids=["a", "b", "c", "d", "e", "f"],
            callee_ids=[],
            caller_ids=[],
            test_ids=[],
            max_steps=3,
        )
        assert len(plan) == 3

    def test_empty(self):
        plan = build_reading_plan(
            entry_point_ids=[], callee_ids=[], caller_ids=[], test_ids=[],
        )
        assert plan == []

    def test_step_numbers_sequential(self):
        plan = build_reading_plan(
            entry_point_ids=["a", "b"],
            callee_ids=["c"],
            caller_ids=["d"],
            test_ids=["e"],
        )
        for i, step in enumerate(plan, 1):
            assert step.step == i

    def test_reason_not_empty(self):
        plan = build_reading_plan(
            entry_point_ids=["auth.py::login"],
            callee_ids=[],
            caller_ids=[],
            test_ids=[],
        )
        assert plan[0].reason != ""


# ══════════════════════════════════════════════════════════════════════════
# Markdown Exporter tests
# ══════════════════════════════════════════════════════════════════════════


class TestExportToMarkdown:
    def test_basic_structure(self):
        pack = ContextPack(
            pack_id="ctx_test_001",
            task=Task(raw_request="test task", intent=TaskIntent.understand_code),
            repo={"name": "test_repo"},
        )
        md = export_to_markdown(pack)
        assert "# CodeGraph Context Pack" in md
        assert "ctx_test_001" in md
        assert "test task" in md

    def test_entry_points_included(self):
        pack = ContextPack(
            pack_id="ctx_test",
            task=Task(raw_request="test"),
            entry_points=[
                EntryPoint(symbol_id="auth.py::login", type="function",
                           name="login", file_path="auth.py",
                           reason="Name matches", score=0.95),
            ],
        )
        md = export_to_markdown(pack)
        assert "auth.py::login" in md
        assert "Name matches" in md
        assert "0.95" in md

    def test_reading_plan(self):
        pack = ContextPack(
            pack_id="ctx_test",
            task=Task(raw_request="test"),
            reading_plan=[
                ReadingStep(step=1, action="read_symbol", target="auth.py::login",
                            reason="Entry point"),
            ],
        )
        md = export_to_markdown(pack)
        assert "Recommended Reading Order" in md
        assert "1." in md
        assert "auth.py::login" in md

    def test_impact(self):
        pack = ContextPack(
            pack_id="ctx_test",
            task=Task(raw_request="test"),
            impact=Impact(
                changed_symbol="auth.py::login",
                affected_files=[AffectedFile(file_path="auth.py", reason="definition", priority="high")],
                risk=Risk(level=RiskLevel.medium, reasons=["Some callers"]),
            ),
        )
        md = export_to_markdown(pack)
        assert "Impact Summary" in md
        assert "medium" in md
        assert "auth.py" in md

    def test_agent_instructions(self):
        pack = ContextPack(
            pack_id="ctx_test",
            task=Task(raw_request="test"),
            agent_instructions=AgentInstructions(
                summary="Test summary",
                recommended_strategy=["Read entry point", "Check tests"],
                warnings=["Low confidence edges"],
            ),
        )
        md = export_to_markdown(pack)
        assert "Agent Instructions" in md
        assert "Test summary" in md
        assert "Check tests" in md
        assert "Low confidence edges" in md

    def test_recommended_context(self):
        pack = ContextPack(
            pack_id="ctx_test",
            task=Task(raw_request="test"),
            recommended_context=[
                RecommendedContext(
                    context_id="ctx_001", type=ContextType.code_snippet,
                    symbol_id="auth.py::login", file_path="auth.py",
                    line_start=1, line_end=10, priority="critical",
                    reason="Entry point", content="def login(): pass",
                ),
            ],
        )
        md = export_to_markdown(pack)
        assert "Relevant Code" in md
        assert "def login(): pass" in md
        assert "```python" in md

    def test_export_to_file(self, tmp_path):
        pack = ContextPack(
            pack_id="ctx_test",
            task=Task(raw_request="test"),
        )
        out = tmp_path / "test_export.md"
        save_markdown(pack, str(out))
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "CodeGraph Context Pack" in content


# ══════════════════════════════════════════════════════════════════════════
# Pack Builder tests
# ══════════════════════════════════════════════════════════════════════════


def _make_store_for_context() -> GraphStore:
    store = GraphStore()
    for n in [
        GraphNode(id="app/api/auth.py", type=NodeType.file, name="auth.py",
                  file_path="app/api/auth.py", module="app.api.auth"),
        GraphNode(id="app/api/auth.py::login", type=NodeType.function, name="login",
                  file_path="app/api/auth.py", module="app.api.auth",
                  qualified_name="app.api.auth.login",
                  location=Location(line_start=6, line_end=9),
                  signature="(username: str, password: str) -> str",
                  code_preview="def login(username, password):\n    token = ...\n    return token"),
        GraphNode(id="app/api/auth.py::logout", type=NodeType.function, name="logout",
                  file_path="app/api/auth.py", module="app.api.auth",
                  qualified_name="app.api.auth.logout",
                  code_preview="def logout(token):\n    revoke_token(token)"),
        GraphNode(id="app/store/token_store.py", type=NodeType.file, name="token_store.py",
                  file_path="app/store/token_store.py", module="app.store.token_store"),
        GraphNode(id="app/store/token_store.py::save_token", type=NodeType.function,
                  name="save_token", file_path="app/store/token_store.py",
                  module="app.store.token_store", qualified_name="app.store.token_store.save_token",
                  code_preview="def save_token(token):\n    _tokens[token] = True"),
        GraphNode(id="app/store/token_store.py::revoke_token", type=NodeType.function,
                  name="revoke_token", file_path="app/store/token_store.py",
                  module="app.store.token_store",
                  code_preview="def revoke_token(token):\n    _tokens.pop(token, None)"),
        GraphNode(id="main.py", type=NodeType.file, name="main.py",
                  file_path="main.py", module="main"),
        GraphNode(id="main.py::main", type=NodeType.function, name="main",
                  file_path="main.py", module="main",
                  code_preview="def main():\n    users = get_users()\n    ..."),
    ]:
        store.add_node(n)
    for e in [
        GraphEdge(type=EdgeType.calls, source="main.py::main",
                  target="app/api/auth.py::login", confidence=0.95),
        GraphEdge(type=EdgeType.calls, source="main.py::main",
                  target="app/api/auth.py::logout", confidence=0.95),
        GraphEdge(type=EdgeType.calls, source="app/api/auth.py::login",
                  target="app/store/token_store.py::save_token", confidence=0.9),
        GraphEdge(type=EdgeType.calls, source="app/api/auth.py::logout",
                  target="app/store/token_store.py::revoke_token", confidence=0.9),
    ]:
        store.add_edge(e)
    return store


class TestBuildContextPack:
    def test_basic_pack_structure(self):
        store = _make_store_for_context()
        pack = build_context_pack(
            store=store,
            task_description="add MFA to login flow",
            max_tokens=6000,
        )
        assert isinstance(pack, ContextPack)
        assert pack.pack_id.startswith("ctx_")
        assert pack.task.raw_request == "add MFA to login flow"
        assert pack.task.intent == TaskIntent.add_feature

    def test_entry_points_populated(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "login")
        assert len(pack.entry_points) > 0
        assert any("login" in ep.symbol_id for ep in pack.entry_points)

    def test_entry_points_have_reason(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "login")
        for ep in pack.entry_points:
            assert ep.reason != ""

    def test_entry_points_have_score(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "login")
        for ep in pack.entry_points:
            assert ep.score > 0

    def test_call_graph(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "login")
        assert len(pack.call_graph.nodes) > 0
        assert isinstance(pack.call_graph.center, str)

    def test_reading_plan(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "login")
        assert len(pack.reading_plan) > 0
        for step in pack.reading_plan:
            assert step.step >= 1
            assert step.target != ""

    def test_agent_instructions(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "login")
        assert pack.agent_instructions.summary != ""
        assert len(pack.agent_instructions.recommended_strategy) > 0

    def test_fix_bug_intent(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "fix bug in login flow")
        assert pack.task.intent in (
            TaskIntent.fix_bug, TaskIntent.modify_existing_behavior,
        )

    def test_understand_code_intent(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "explain how login works")
        assert pack.task.intent == TaskIntent.understand_code

    def test_refactor_intent(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "refactor the auth module")
        assert pack.task.intent == TaskIntent.refactor

    def test_impact_for_modify_intent(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "modify login to support MFA")
        if pack.impact.changed_symbol:
            assert len(pack.impact.affected_symbols) > 0

    def test_context_export(self, tmp_path):
        store = _make_store_for_context()
        pack = build_context_pack(
            store, "login", output_dir=str(tmp_path / "context_packs"),
        )
        assert pack.exports.markdown_path != ""
        assert pack.exports.json_path != ""

    def test_warnings_for_no_results(self):
        store = GraphStore()
        store.add_node(GraphNode(id="foo.py", type=NodeType.file, name="foo.py"))
        pack = build_context_pack(store, "something_completely_unrelated")
        # Should not crash, may have warnings
        assert isinstance(pack, ContextPack)


# ── Round 8: Token Budget & Selection tests ──────────────────────────────────


class TestContextPackTokenBudget:
    """Verify the new token_budget and optional_context fields on ContextPack."""

    def test_token_budget_in_pack(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "add MFA to login flow", max_tokens=6000)
        tb = pack.token_budget
        assert "max_tokens" in tb
        assert "used_tokens" in tb
        assert "remaining" in tb
        assert tb["max_tokens"] == 6000

    def test_optional_context_field_exists(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "add MFA to login flow")
        assert isinstance(pack.optional_context, list)

    def test_recommended_context_has_new_fields(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "add MFA to login flow", max_tokens=6000)
        for rc in pack.recommended_context:
            assert hasattr(rc, "content_mode"), f"Missing content_mode on {rc.context_id}"
            assert hasattr(rc, "context_score"), f"Missing context_score on {rc.context_id}"
            assert rc.content_mode in ("full_source", "summary", "reference"), \
                f"Unexpected content_mode: {rc.content_mode}"

    def test_tiny_budget_produces_degraded_items(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "add MFA to login flow", max_tokens=200)
        assert isinstance(pack, ContextPack)
        # Should have at least entry points as critical
        assert len(pack.recommended_context) > 0

    def test_large_budget_all_full_source(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "add MFA to login flow", max_tokens=50000)
        # With a huge budget, most items should be full_source
        full_source_count = sum(1 for rc in pack.recommended_context if rc.content_mode == "full_source")
        assert full_source_count > 0


class TestContextPackMarkdownNewFields:
    """Verify markdown export includes new sections."""

    def test_token_budget_in_markdown(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "add MFA to login flow", max_tokens=6000)
        md = export_to_markdown(pack)
        assert "Token Budget" in md
        assert "Max Tokens" in md

    def test_content_mode_in_markdown(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "add MFA to login flow", max_tokens=6000)
        md = export_to_markdown(pack)
        assert "Content Mode" in md

    def test_context_score_in_markdown(self):
        store = _make_store_for_context()
        pack = build_context_pack(store, "add MFA to login flow", max_tokens=6000)
        md = export_to_markdown(pack)
        assert "Context Score" in md
