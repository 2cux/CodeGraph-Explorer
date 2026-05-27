"""Context Pack API routes.

PRD §16.1 — POST /api/context-pack
PRD §16.2 — request / response schema
"""
from fastapi import APIRouter, Depends, HTTPException
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


# ── Response models ──────────────────────────────────────────────


class TaskSchema(BaseModel):
    raw_request: str
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


class CallGraphNode(BaseModel):
    id: str
    label: str
    type: str


class CallGraphEdge(BaseModel):
    source: str
    target: str
    type: str = "calls"
    confidence: float = 0.0


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


class RecommendedContextItem(BaseModel):
    context_id: str = ""
    type: str = "code_snippet"
    symbol_id: str = ""
    file_path: str = ""
    priority: str = "medium"
    reason: str = ""
    estimated_tokens: int = 0


class ReadingStepItem(BaseModel):
    step: int
    action: str = "read_symbol"
    target: str
    reason: str = ""


class AgentInstructionsSchema(BaseModel):
    summary: str = ""
    recommended_strategy: list[str] = []
    warnings: list[str] = []


class ExportsInfo(BaseModel):
    markdown_path: str = ""
    json_path: str = ""


class ContextPackResponse(BaseModel):
    schema_version: str = "1.0.0"
    pack_id: str = ""
    task: TaskSchema = TaskSchema()
    repo: dict = {}
    entry_points: list[EntryPointItem] = []
    related_symbols: list[RelatedSymbolItem] = []
    call_graph: CallGraphSchema = CallGraphSchema()
    impact: ImpactSchema = ImpactSchema()
    recommended_context: list[RecommendedContextItem] = []
    reading_plan: list[ReadingStepItem] = []
    agent_instructions: AgentInstructionsSchema = AgentInstructionsSchema()
    exports: ExportsInfo = ExportsInfo()


# ── Routes ───────────────────────────────────────────────────────


@router.post("/context-pack", response_model=ContextPackResponse)
async def generate_context_pack(
    req: ContextPackRequest,
    store: GraphStore = Depends(get_store),
):
    """Generate a Context Pack for a natural language task description."""
    try:
        pack = build_context_pack(
            store=store,
            task_description=req.task,
            max_tokens=req.max_tokens,
        )
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="Context Pack generation is not yet implemented. "
            "Phase 3 development required.",
        )

    response = ContextPackResponse(
        schema_version="1.0.0",
        pack_id=pack.pack_id or f"ctx_{id(pack):x}",
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
                relation=rs.relation,
                distance=rs.distance,
                direction=rs.direction,
                reason=rs.reason,
                importance=rs.importance.value if hasattr(rs.importance, "value") else rs.importance,
                confidence=rs.confidence,
            )
            for rs in pack.related_symbols
        ],
        call_graph=CallGraphSchema(
            center=pack.call_graph.center,
            depth=pack.call_graph.depth,
            nodes=[CallGraphNode(id=n.id, label=n.label, type=n.type) for n in pack.call_graph.nodes],
            edges=[CallGraphEdge(source=e.source, target=e.target, type=e.type, confidence=e.confidence) for e in pack.call_graph.edges],
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
        recommended_context=[
            RecommendedContextItem(
                context_id=rc.context_id,
                type=rc.type.value if hasattr(rc.type, "value") else rc.type,
                symbol_id=rc.symbol_id,
                file_path=rc.file_path,
                priority=rc.priority,
                reason=rc.reason,
                estimated_tokens=rc.estimated_tokens,
            )
            for rc in pack.recommended_context
        ],
        reading_plan=[
            ReadingStepItem(
                step=rp.step,
                action=rp.action,
                target=rp.target,
                reason=rp.reason,
            )
            for rp in pack.reading_plan
        ],
        agent_instructions=AgentInstructionsSchema(
            summary=pack.agent_instructions.summary,
            recommended_strategy=pack.agent_instructions.recommended_strategy,
            warnings=pack.agent_instructions.warnings,
        ),
        exports=ExportsInfo(
            markdown_path=pack.exports.markdown_path,
            json_path=pack.exports.json_path,
        ),
    )

    return response
