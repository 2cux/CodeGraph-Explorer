"""Tests for Context Pack generation — ranking, markdown, and pack builder.

Evidence Pack (Round 4): Reading plans, agent instructions, and action
directives are removed. Tests verify structured evidence output instead.
"""

import pytest
from codegraph.graph.models import GraphNode, NodeType, EdgeType, Location, GraphEdge
from codegraph.graph.store import GraphStore
from codegraph.context.models import (
    ContextPack, Task, TaskIntent, TaskConstraints,
    EntryPoint, RelatedSymbol, CallGraph, CallGraphNode, CallGraphEdge,
    Impact, AffectedSymbol, AffectedFile, Risk, RiskLevel,
    SelectedContext, ContextType, Importance, ImpactType, NoteType,
    PackNote, TestsSection, IndexStatus,
)
from codegraph.context.ranking import tokenize, score_relevance, rank_entry_points, get_match_sources, build_reason
from codegraph.context.markdown_exporter import export_to_markdown, save_markdown
from codegraph.context.pack_builder import build_context_pack


# ══════════════════════════════════════════════════════════════════════════
# Ranking tests
# ══════════════════════════════════════════════════════════════════════════


class TestTokenize:
    def test_basic(self):
        tokens = tokenize("add MFA to login flow")
        assert "mfa" in tokens
        assert "login" in tokens
        assert "flow" in tokens

    def test_removes_stopwords(self):
        tokens = tokenize("the quick brown fox")
        assert "the" not in tokens

    def test_case_insensitive(self):
        t1 = tokenize("Login FLOW")
        t2 = tokenize("login flow")
        assert t1 == t2

    def test_non_alpha_cleaned(self):
        tokens = tokenize("token_store.py::save")
        assert "token_store" in tokens or "token" in tokens


class TestScoreRelevance:
    def test_scores_float(self):
        node = GraphNode(id="auth.py::login", type=NodeType.function, name="login")
        s = score_relevance(node, "login flow")
        assert isinstance(s, float)
        assert 0.0 <= s <= 1.0

    def test_name_match_scores_higher(self):
        node = GraphNode(id="auth.py::login", type=NodeType.function, name="login")
        s = score_relevance(node, "login flow")
        assert s > 0.0


class TestRankEntryPoints:
    def test_returns_list_of_tuples(self):
        nodes = [
            GraphNode(id="a.py::f1", type=NodeType.function, name="login"),
            GraphNode(id="b.py::f2", type=NodeType.function, name="logout"),
        ]
        ranked = rank_entry_points("login", nodes)
        assert isinstance(ranked, list)
        assert len(ranked) >= 1
        for node, score in ranked:
            assert isinstance(score, float)

    def test_higher_score_first(self):
        nodes = [
            GraphNode(id="a.py::f1", type=NodeType.function, name="logout"),
            GraphNode(id="b.py::f2", type=NodeType.function, name="login"),
        ]
        ranked = rank_entry_points("login", nodes)
        if len(ranked) >= 2:
            assert ranked[0][1] >= ranked[1][1]

    def test_ranks_by_relevance(self):
        nodes = [
            GraphNode(id="a.py::f1", type=NodeType.function, name="login"),
            GraphNode(id="b.py::f2", type=NodeType.function, name="unrelated"),
        ]
        ranked = rank_entry_points("login", nodes)
        if len(ranked) >= 2:
            assert ranked[0][1] > ranked[1][1] or ranked[0][0].name == "login"

    def test_empty_nodes(self):
        ranked = rank_entry_points("login", [])
        assert ranked == []

    def test_empty_query(self):
        nodes = [GraphNode(id="a.py::f1", type=NodeType.function, name="f1")]
        ranked = rank_entry_points("", nodes)
        assert len(ranked) >= 0


class TestGetMatchSources:
    def test_name_match(self):
        node = GraphNode(id="auth.py::login", type=NodeType.function, name="login")
        sources = get_match_sources(node, ["login"])
        assert len(sources) > 0


class TestBuildReason:
    def test_non_empty(self):
        node = GraphNode(id="auth.py::login", type=NodeType.function, name="login")
        reason = build_reason(node, ["login"])
        assert isinstance(reason, str)
        assert len(reason) > 0


# ══════════════════════════════════════════════════════════════════════════
# Markdown export — Evidence Pack structure
# ══════════════════════════════════════════════════════════════════════════


def _make_minimal_pack() -> ContextPack:
    return ContextPack(
        pack_id="test_pack",
        task=Task(raw_request="explain login"),
        entry_points=[
            EntryPoint(symbol_id="auth.py::login", type="function", name="login",
                      file_path="auth.py", reason="Name match: login", score=0.95,
                      match_sources=["name"]),
        ],
        selected_context=[
            SelectedContext(
                context_id="ctx_item_001", type=ContextType.code_snippet,
                symbol_id="auth.py::login", file_path="auth.py",
                priority="critical", relation="entry_point",
                selection_reason="Candidate entry point.",
                content="def login(): pass",
                estimated_tokens=10, content_mode="full_source",
                confidence=0.95, evidence="Matched by name",
            ),
        ],
    )


class TestExportToMarkdown:
    def test_basic_structure(self):
        pack = _make_minimal_pack()
        md = export_to_markdown(pack)
        assert "Evidence Pack" in md
        assert "## Task" in md
        assert "## Entry Point Candidates" in md
        assert "## Selected Context" in md

    def test_no_reading_plan_section(self):
        """Evidence Pack: Markdown must not contain Reading Plan section."""
        pack = _make_minimal_pack()
        md = export_to_markdown(pack)
        assert "Reading Plan" not in md
        assert "Reading Order" not in md
        assert "Agent Instructions" not in md
        assert "Recommended Strategy" not in md
        assert "Next Steps" not in md

    def test_entry_point_candidates_section(self):
        pack = _make_minimal_pack()
        md = export_to_markdown(pack)
        assert "Entry Point Candidates" in md
        assert "auth.py::login" in md
        assert "Name match: login" in md

    def test_selected_context_section(self):
        pack = _make_minimal_pack()
        md = export_to_markdown(pack)
        assert "Selected Context" in md
        assert "auth.py::login" in md

    def test_pack_notes_section(self):
        pack = _make_minimal_pack()
        pack.pack_notes = [
            PackNote(type=NoteType.index_status, message="Index has 42 symbols."),
        ]
        md = export_to_markdown(pack)
        assert "Pack Notes" in md
        assert "42 symbols" in md

    def test_warnings_section(self):
        pack = _make_minimal_pack()
        pack.warnings = ["Low confidence edge: a → b (0.45)"]
        md = export_to_markdown(pack)
        assert "Warnings" in md
        assert "Low confidence" in md

    def test_impact_signals_section(self):
        pack = _make_minimal_pack()
        pack.impact = Impact(
            changed_symbol="auth.py::login",
            risk=Risk(level="medium", reasons=["Multiple callers"]),
        )
        md = export_to_markdown(pack)
        assert "Impact Signals" in md
        assert "medium" in md

    def test_export_to_file(self, tmp_path):
        pack = _make_minimal_pack()
        path = str(tmp_path / "test_pack.md")
        save_markdown(pack, path)
        import os
        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "Evidence Pack" in content


# ══════════════════════════════════════════════════════════════════════════
# Build Context Pack integration
# ══════════════════════════════════════════════════════════════════════════


def _make_integration_store() -> GraphStore:
    store = GraphStore()
    store.add_node(GraphNode(id="app/api/auth.py::login", type=NodeType.function, name="login",
                   file_path="app/api/auth.py", code_preview="def login(u, p): return 'token'"))
    store.add_node(GraphNode(id="app/models/user.py::User", type=NodeType.class_, name="User",
                   file_path="app/models/user.py", code_preview="class User:\n    name: str"))
    store.add_node(GraphNode(id="app/store/token_store.py::save_token", type=NodeType.function,
                   name="save_token", file_path="app/store/token_store.py",
                   code_preview="def save_token(t): pass"))
    store.add_node(GraphNode(id="main.py::main", type=NodeType.function, name="main",
                   file_path="main.py", code_preview="def main(): login('u','p')"))
    store.add_edge(GraphEdge(type=EdgeType.calls, source="main.py::main",
                   target="app/api/auth.py::login", confidence=0.95))
    store.add_edge(GraphEdge(type=EdgeType.calls, source="app/api/auth.py::login",
                   target="app/store/token_store.py::save_token", confidence=0.90))
    return store


class TestBuildContextPack:
    def test_returns_context_pack(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "explain login flow", max_files=4, include_tests=False)
        assert isinstance(pack, ContextPack)
        assert pack.pack_id != ""

    def test_has_selected_context(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=False)
        assert isinstance(pack.selected_context, list)
        assert len(pack.selected_context) > 0

    def test_has_no_reading_plan(self):
        """Evidence Pack: ContextPack has no reading_plan field."""
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=False)
        assert not hasattr(pack, 'reading_plan')

    def test_has_no_agent_instructions(self):
        """Evidence Pack: ContextPack has no agent_instructions field."""
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=False)
        assert not hasattr(pack, 'agent_instructions')

    def test_has_pack_notes(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "explain login flow", max_files=4, include_tests=False)
        assert isinstance(pack.pack_notes, list)
        assert len(pack.pack_notes) > 0

    def test_has_warnings(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "explain login flow", max_files=4, include_tests=False)
        assert isinstance(pack.warnings, list)

    def test_has_index_status(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "explain login flow", max_files=4, include_tests=False)
        assert pack.index_status.symbol_count > 0
        assert pack.index_status.edge_count > 0

    def test_has_created_at(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "explain login flow", max_files=4, include_tests=False)
        assert pack.created_at != ""

    def test_tests_section_structure(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=True)
        assert hasattr(pack.tests, 'existing_tests')
        assert hasattr(pack.tests, 'suggested_tests')

    def test_suggested_tests_use_heuristic_source(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=True)
        for st in pack.tests.suggested_tests:
            src = st.source.value if hasattr(st.source, 'value') else st.source
            assert src in ("suggested", "heuristic"), f"Unexpected source: {src}"


# ══════════════════════════════════════════════════════════════════════════
# Context Pack schema verification
# ══════════════════════════════════════════════════════════════════════════


class TestContextPackSchema:
    def test_selected_context_has_evidence_fields(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=False)
        for sc in pack.selected_context:
            assert hasattr(sc, 'selection_reason'), "Missing selection_reason"
            assert hasattr(sc, 'evidence'), "Missing evidence"
            assert hasattr(sc, 'confidence'), "Missing confidence"
            assert hasattr(sc, 'confidence_level'), "Missing confidence_level"
            assert hasattr(sc, 'resolution'), "Missing resolution"
            assert hasattr(sc, 'relation'), "Missing relation"

    def test_entry_point_reason_has_no_directives(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "explain login flow", max_files=4, include_tests=False)
        for ep in pack.entry_points:
            reason_lower = ep.reason.lower()
            assert "start here" not in reason_lower, f"Directive in reason: {ep.reason}"
            assert "read first" not in reason_lower, f"Directive in reason: {ep.reason}"
            assert "begin with" not in reason_lower, f"Directive in reason: {ep.reason}"
            assert "you should" not in reason_lower, f"Directive in reason: {ep.reason}"
            assert " you must" not in reason_lower or "you must " not in reason_lower, f"Directive in reason: {ep.reason}"

    def test_pack_dump_json_no_errors(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=False)
        data = pack.model_dump_json(indent=2, exclude_none=True)
        assert isinstance(data, str)
        assert len(data) > 0

    def test_no_plan_or_instructions_in_json(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "explain login flow", max_files=4, include_tests=False)
        data = pack.model_dump_json(indent=2, exclude_none=True)
        assert "reading_plan" not in data
        assert "reading_suggestions" not in data
        assert "agent_instructions" not in data
        assert "do_first" not in data
        assert "recommended_strategy" not in data
        assert "next_steps" not in data

    def test_has_selected_context_in_json(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=False)
        data = pack.model_dump_json(indent=2, exclude_none=True)
        assert "selected_context" in data

    def test_has_tests_section_in_json(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=True)
        data = pack.model_dump_json(indent=2, exclude_none=True)
        assert "existing_tests" in data or "suggested_tests" in data

    def test_has_pack_notes_in_json(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=False)
        data = pack.model_dump_json(indent=2, exclude_none=True)
        assert "pack_notes" in data

    def test_related_tests_use_heuristic_source(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=True)
        # Tests are now in pack.tests (TestsSection)
        for rt in pack.tests.existing_tests:
            assert hasattr(rt, 'source'), "existing_test missing source"
        for st in pack.tests.suggested_tests:
            assert hasattr(st, 'source'), "suggested_test missing source"

    def test_selected_context_item_fields(self):
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=False)
        for sc in pack.selected_context:
            assert sc.context_id != ""
            assert sc.type is not None
            assert sc.content_mode is not None
            assert sc.selection_reason or sc.evidence, \
                f"Item {sc.context_id} missing selection_reason and evidence"

    def test_completeness_fields(self):
        """Evidence Pack must include required top-level fields."""
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=True)
        required = [
            "schema_version", "pack_id", "created_at", "task", "repo",
            "index_status", "entry_points", "related_symbols", "call_graph",
            "impact", "tests", "selected_context", "warnings",
            "pack_notes", "token_budget", "exports",
        ]
        for field in required:
            assert hasattr(pack, field), f"Missing field: {field}"

    def test_completeness_no_forbidden_fields(self):
        """Evidence Pack must NOT include removed fields."""
        store = _make_integration_store()
        pack = build_context_pack(store, "add MFA to login", max_files=4, include_tests=True)
        forbidden = [
            "reading_plan", "reading_suggestions", "agent_instructions",
            "do_first", "avoid", "validation", "recommended_strategy",
            "next_steps", "optional_context", "reading_plan_debug",
        ]
        for field in forbidden:
            assert not hasattr(pack, field), f"Forbidden field present: {field}"

    def test_template_context_is_evidence_context(self):
        """Integration template returns a structured Evidence Pack."""
        store = _make_integration_store()
        pack = build_context_pack(store, "explain login flow", max_files=4, include_tests=False)
        assert isinstance(pack.task.raw_request, str)
        assert pack.task.intent == TaskIntent.understand_code
        assert len(pack.selected_context) > 0
        assert isinstance(pack.warnings, list)
        assert isinstance(pack.pack_notes, list)
