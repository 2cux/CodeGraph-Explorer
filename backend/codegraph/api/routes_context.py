"""Context Pack API routes — Evidence Pack output.

POST /api/context-pack — returns structured code evidence only.
No reading plans, agent instructions, or action directives.
"""
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from codegraph.api.deps import get_store
from codegraph.context.pack_builder import build_context_pack
from codegraph.graph.store import GraphStore

router = APIRouter(prefix="/api", tags=["context"])


# ── Request models ───────────────────────────────────────────────


class ContextPackRequest(BaseModel):
    task: str
    query: str = ""
    target_symbols: list[str] = []
    max_tokens: int = 6000
    include_tests: bool = True
    depth: int = 2
    debug_plan: bool = False


# ── Response models ──────────────────────────────────────────────


class TaskSchema(BaseModel):
    raw_request: str = ""
    intent: str = "understand_code"
    keywords: list[str] = []
    target_symbols: list[str] = []
    constraints: dict = {}


class EntryPointItem(BaseModel):
    symbol_id: str
    type: str
    name: str
    file_path: str
    location: dict | None = None
    signature: str | None = None
    reason: str = ""
    score: float = 0.0
    match_sources: list[str] = []


class RelatedSymbolItem(BaseModel):
    symbol_id: str
    relation: str = "related"
    distance: int = 1
    direction: str = "outgoing"
    reason: str = ""
    importance: str = "medium"
    confidence: float = 0.0
    confidence_level: str = "unknown"


class CallGraphNode(BaseModel):
    id: str
    label: str
    type: str


class CallGraphEdge(BaseModel):
    source: str
    target: str
    type: str = "calls"
    confidence: float = 0.0
    resolution: str = ""
    confidence_level: str = "unknown"


class CallGraphSchema(BaseModel):
    center: str = ""
    depth: int = 1
    nodes: list[CallGraphNode] = []
    edges: list[CallGraphEdge] = []


class AffectedSymbolItem(BaseModel):
    symbol_id: str
    reason: str = ""
    impact_type: str = "unknown"
    distance: int = 1
    confidence: float = 0.0
    confidence_level: str = "unknown"


class AffectedFileItem(BaseModel):
    file_path: str
    reason: str = ""
    priority: str = "medium"


class RiskSchema(BaseModel):
    level: str = "low"
    reasons: list[str] = []


class ImpactSchema(BaseModel):
    changed_symbol: str = ""
    affected_symbols: list[AffectedSymbolItem] = []
    affected_files: list[AffectedFileItem] = []
    risk: RiskSchema = RiskSchema()


class SelectedContextItem(BaseModel):
    context_id: str = ""
    type: str = "code_snippet"
    symbol_id: str = ""
    file_path: str = ""
    line_start: int = 0
    line_end: int = 0
    priority: str = "medium"
    relation: str = ""
    selection_reason: str = ""
    content: str = ""
    estimated_tokens: int = 0
    content_mode: str = "full_source"
    confidence: float = 0.0
    confidence_level: str = "unknown"
    resolution: str = ""
    evidence: str = ""


class RelatedTestItem(BaseModel):
    source: str = "existing"
    test_file: str
    test_name: str = ""
    reason: str = ""
    confidence: float = 0.0
    confidence_level: str = "unknown"


class TestsSectionSchema(BaseModel):
    existing_tests: list[RelatedTestItem] = []
    suggested_tests: list[RelatedTestItem] = []


class IndexStatusSchema(BaseModel):
    symbol_count: int = 0
    edge_count: int = 0
    index_format: str = "codegraph/v1"
    language: str = "python"


class PackNoteSchema(BaseModel):
    type: str
    message: str
    details: dict = {}


class ExportsInfo(BaseModel):
    markdown_path: str = ""
    json_path: str = ""


class ContextPackResponse(BaseModel):
    schema_version: str = "1.0.0"
    pack_id: str = ""
    created_at: str = ""
    task: TaskSchema = TaskSchema()
    repo: dict = {}
    index_status: IndexStatusSchema = IndexStatusSchema()
    entry_points: list[EntryPointItem] = []
    related_symbols: list[RelatedSymbolItem] = []
    call_graph: CallGraphSchema = CallGraphSchema()
    impact: ImpactSchema = ImpactSchema()
    tests: TestsSectionSchema = TestsSectionSchema()
    selected_context: list[SelectedContextItem] = []
    warnings: list[str] = []
    pack_notes: list[PackNoteSchema] = []
    token_budget: dict = {}
    exports: ExportsInfo = ExportsInfo()


# ── Routes ───────────────────────────────────────────────────────


@router.post("/context-pack", response_model=ContextPackResponse)
async def generate_context_pack(
    req: ContextPackRequest,
    store: GraphStore = Depends(get_store),
):
    """Generate an Evidence Pack for a natural language task description.

    Returns structured code evidence: entry point candidates, related
    symbols, call graph, impact signals, selected context, tests,
    warnings, and pack notes. No reading plans, execution orders, or
    agent instructions are included.
    """
    output_dir = str(Path.cwd() / ".codegraph" / "context_packs")
    pack = build_context_pack(
        store=store,
        task_description=req.task,
        query=req.query,
        target_symbols=req.target_symbols or None,
        max_tokens=req.max_tokens,
        include_tests=req.include_tests,
        depth=req.depth,
        output_dir=output_dir,
        debug_plan=req.debug_plan,
    )

    response = ContextPackResponse(
        schema_version="1.0.0",
        pack_id=pack.pack_id or f"ctx_{id(pack):x}",
        created_at=pack.created_at,
        task=TaskSchema(
            raw_request=pack.task.raw_request or req.task,
            intent=pack.task.intent.value if pack.task.intent else "understand_code",
            keywords=pack.task.keywords or req.task.split(),
            target_symbols=pack.task.target_symbols or req.target_symbols,
            constraints={
                "max_tokens": pack.task.constraints.max_tokens if pack.task.constraints else req.max_tokens,
                "depth": req.depth,
                "include_tests": pack.task.constraints.include_tests if pack.task.constraints else req.include_tests,
            },
        ),
        index_status=IndexStatusSchema(
            symbol_count=pack.index_status.symbol_count,
            edge_count=pack.index_status.edge_count,
            index_format=pack.index_status.index_format,
            language=pack.index_status.language,
        ),
        entry_points=[
            EntryPointItem(
                symbol_id=ep.symbol_id,
                type=ep.type,
                name=ep.name,
                file_path=ep.file_path,
                location=ep.location,
                signature=ep.signature,
                reason=ep.reason,
                score=ep.score,
                match_sources=ep.match_sources,
            )
            for ep in pack.entry_points
        ],
        related_symbols=[
            RelatedSymbolItem(
                symbol_id=rs.symbol_id,
                relation=rs.relation.value if hasattr(rs.relation, "value") else rs.relation,
                distance=rs.distance,
                direction=rs.direction.value if hasattr(rs.direction, "value") else rs.direction,
                reason=rs.reason,
                importance=rs.importance.value if hasattr(rs.importance, "value") else rs.importance,
                confidence=rs.confidence,
                confidence_level=rs.confidence_level.value if hasattr(rs.confidence_level, "value") else rs.confidence_level,
            )
            for rs in pack.related_symbols
        ],
        call_graph=CallGraphSchema(
            center=pack.call_graph.center,
            depth=pack.call_graph.depth,
            nodes=[CallGraphNode(id=n.id, label=n.label, type=n.type) for n in pack.call_graph.nodes],
            edges=[CallGraphEdge(
                source=e.source, target=e.target, type=e.type,
                confidence=e.confidence,
                resolution=e.resolution,
                confidence_level=e.confidence_level.value if hasattr(e.confidence_level, "value") else e.confidence_level,
            ) for e in pack.call_graph.edges],
        ),
        impact=ImpactSchema(
            changed_symbol=pack.impact.changed_symbol,
            affected_symbols=[
                AffectedSymbolItem(
                    symbol_id=sym.symbol_id,
                    reason=sym.reason,
                    impact_type=sym.impact_type.value if hasattr(sym.impact_type, "value") else sym.impact_type,
                    distance=sym.distance,
                    confidence=sym.confidence,
                    confidence_level=sym.confidence_level.value if hasattr(sym.confidence_level, "value") else sym.confidence_level,
                )
                for sym in pack.impact.affected_symbols
            ],
            affected_files=[
                AffectedFileItem(
                    file_path=f.file_path,
                    reason=f.reason,
                    priority=f.priority,
                )
                for f in pack.impact.affected_files
            ],
            risk=RiskSchema(
                level=pack.impact.risk.level.value if hasattr(pack.impact.risk.level, "value") else pack.impact.risk.level,
                reasons=pack.impact.risk.reasons,
            ),
        ),
        tests=TestsSectionSchema(
            existing_tests=[
                RelatedTestItem(
                    source=rt.source.value if hasattr(rt.source, "value") else rt.source,
                    test_file=rt.test_file,
                    test_name=rt.test_name,
                    reason=rt.reason,
                    confidence=rt.confidence,
                    confidence_level=rt.confidence_level.value if hasattr(rt.confidence_level, "value") else rt.confidence_level,
                )
                for rt in pack.tests.existing_tests
            ],
            suggested_tests=[
                RelatedTestItem(
                    source=st.source.value if hasattr(st.source, "value") else st.source,
                    test_file=st.test_file,
                    test_name=st.test_name,
                    reason=st.reason,
                    confidence=st.confidence,
                    confidence_level=st.confidence_level.value if hasattr(st.confidence_level, "value") else st.confidence_level,
                )
                for st in pack.tests.suggested_tests
            ],
        ),
        selected_context=[
            SelectedContextItem(
                context_id=sc.context_id,
                type=sc.type.value if hasattr(sc.type, "value") else sc.type,
                symbol_id=sc.symbol_id,
                file_path=sc.file_path,
                line_start=sc.line_start,
                line_end=sc.line_end,
                priority=sc.priority,
                relation=sc.relation,
                selection_reason=sc.selection_reason,
                content=sc.content,
                estimated_tokens=sc.estimated_tokens,
                content_mode=sc.content_mode,
                confidence=sc.confidence,
                confidence_level=sc.confidence_level.value if hasattr(sc.confidence_level, "value") else sc.confidence_level,
                resolution=sc.resolution,
                evidence=sc.evidence,
            )
            for sc in pack.selected_context
        ],
        warnings=pack.warnings,
        pack_notes=[
            PackNoteSchema(
                type=note.type.value if hasattr(note.type, "value") else note.type,
                message=note.message,
                details=note.details,
            )
            for note in pack.pack_notes
        ],
        exports=ExportsInfo(
            markdown_path=pack.exports.markdown_path,
            json_path=pack.exports.json_path,
        ),
        token_budget=pack.token_budget,
    )

    return response
