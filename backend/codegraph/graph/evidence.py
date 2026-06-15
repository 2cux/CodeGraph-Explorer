"""Sufficiency evidence models for MCP tool responses.

These types define the enriched response-layer evidence blocks that
upgrade CodeGraph MCP tools from "returning pointers" to "returning
enough evidence to continue working without immediate Read/Grep."

They are NOT part of the canonical graph storage schema (models.py) —
they live at the MCP response layer and are used by tool handlers in
mcp_server.py to enrich responses before sending.
"""

from enum import Enum
from pydantic import BaseModel, Field
from typing import Any


# ── Evidence item types ────────────────────────────────────────────────


class EvidenceItemType(str, Enum):
    """Typed evidence categories for MCP response enrichment.

    Each evidence item describes ONE piece of supporting evidence
    for a conclusion (risk assessment, symbol match, test coverage, etc.).
    """

    # ── Call-graph evidence ───────────────────────────────────────────
    caller = "caller"               # upstream caller symbol
    callee = "callee"               # downstream callee symbol
    test = "test"                   # test that covers or calls this symbol
    edge = "edge"                   # generic graph edge (resolution + confidence)
    sibling = "sibling"             # same-file sibling function/method

    # ── Dependency evidence ───────────────────────────────────────────
    import_dep = "import_dep"       # imported module/class
    model_dep = "model_dep"         # data model dependency
    config_dep = "config_dep"       # configuration dependency
    route = "route"                 # HTTP route handler

    # ── Metadata evidence ─────────────────────────────────────────────
    name_match = "name_match"       # symbol name matched query
    symbol_metadata = "symbol_metadata"  # type, signature, tags
    docstring = "docstring"         # docstring-derived evidence
    signature = "signature"         # function/method signature
    snippet = "snippet"             # source code snippet

    # ── External / unresolved ─────────────────────────────────────────
    external = "external"           # external library call
    unresolved = "unresolved"       # unresolved reference


class EvidenceItem(BaseModel):
    """A single typed piece of evidence backing a conclusion.

    Mirrors the evidence array schema from the sufficiency requirements
    (Req 3.1): typed items with symbol, file, line, confidence, and
    resolution provenance.
    """

    type: EvidenceItemType
    symbol: str | None = None
    symbol_id: str | None = None
    file: str | None = None
    line: int | None = None
    confidence: str | None = None       # "high" | "medium" | "low" | "heuristic"
    resolution: str | None = None       # resolution strategy (from Resolution enum)
    reason: str | None = None
    provenance: str | None = None       # "ast" | "heuristic" | "import_resolver" | ...


class EvidenceBlock(BaseModel):
    """Evidence array attached to a reason or conclusion.

    Used in risk assessments, symbol matches, and impact analyses
    to show WHY a conclusion was reached (Req 3.1).
    """

    reason: str
    evidence: list[EvidenceItem] = Field(default_factory=list)


# ── Source declaration ─────────────────────────────────────────────────


class SourceDeclaration(BaseModel):
    """Provenance metadata for a source code snippet (Req 3.5).

    Every snippet returned by CodeGraph MUST declare:
    - It was read from current disk (not stale cache, not summary)
    - Its line range
    - Whether the source file has been modified since indexing
    - That it is equivalent to one Read tool call
    """

    provenance: str = "live_disk_read"
    """Always 'live_disk_read' — file was read from current disk state."""

    file: str
    """Relative file path within project root."""

    line_start: int
    line_end: int
    lines: int
    truncated: bool = False

    is_stale_cache: bool = False
    """True if the file has been modified since the last index."""

    is_summary: bool = False
    """Always False for source snippets — summaries are not source."""

    equivalent_to: str = "one Read tool call"
    """Tells the agent this snippet is as good as reading the file."""


# ── File freshness ─────────────────────────────────────────────────────


class FileFreshnessEntry(BaseModel):
    """Per-file staleness information (Req 3.4).

    Instead of a global "index may be stale" warning, each file
    referenced in a response gets its own freshness status.
    """

    file: str
    status: str  # "fresh" | "edited_recently" | "pending_change"
    mtime_delta_ms: int | None = None  # ms since last index (0 = fresh)

    in_this_response: bool = True
    """True if this file appears in the current response data."""


class FileFreshnessBlock(BaseModel):
    """Aggregated per-file freshness for a complete MCP response.

    Provides both per-file entries AND a human-readable summary
    for the agent to quickly assess staleness of the returned data.
    """

    files: list[FileFreshnessEntry] = Field(default_factory=list)
    summary: str = ""
    """Human-readable: 'src/server.ts was edited 342ms ago and appears
    in this response. Other files in this response are fresh. 3 unrelated
    pending files exist elsewhere.'"""

    unrelated_pending: int = 0
    """Count of files that have pending changes but are NOT referenced
    in this response."""


# ── Multi-candidate transparency ───────────────────────────────────────


class CandidateInfo(BaseModel):
    """Multi-candidate selection transparency (Req 3.2).

    When multiple symbols match a query, this block declares which one
    was selected and lists the alternatives — the agent should never
    wonder whether there were better matches that were silently dropped.
    """

    selected_symbol_id: str
    selected_reason: str = ""
    other_candidates: list[dict[str, Any]] = Field(default_factory=list)
    """List of {symbol_id, name, type, file_path} dicts for alternatives."""


# ── Container outline ──────────────────────────────────────────────────


class ContainerOutline(BaseModel):
    """Member list for large classes/interfaces (Req 3.7).

    Instead of returning thousands of lines of source for a large class,
    return a structured member list with method signatures and line numbers.
    The agent can then Read specific methods as needed.
    """

    symbol_id: str
    name: str
    type: str = "class"
    file: str = ""
    line_start: int = 0
    line_end: int = 0

    total_members: int = 0
    public_methods: list[dict[str, Any]] = Field(default_factory=list)
    """Each entry: {name, signature, line_start, line_end, visibility}"""

    other_members: list[dict[str, Any]] = Field(default_factory=list)
    """Private methods, attributes, nested classes:
    {name, type, line_start, line_end, visibility}"""

    truncated: bool = False
    """True if member list was truncated (total_members > max_members)."""


# ── Failure fallback ───────────────────────────────────────────────────


class FailureFallback(BaseModel):
    """Structured fallback context when a symbol is not found (Req 3.3).

    Instead of returning an empty error, provides whatever context
    IS available: same-file siblings, known endpoint details, likely
    dynamic dispatch breakpoints.
    """

    message: str = "No static path found."

    likely_breakpoints: list[str] = Field(default_factory=list)
    """Reasons the symbol might not be statically resolvable:
    'callback', 'framework_dispatch', 'interface_dispatch', 'dynamic_import'"""

    known_endpoint_details: dict[str, Any] | None = None
    """If the query was for a known endpoint/route pattern, details
    extracted from partial matches."""

    immediate_callers: list[dict[str, Any]] | None = None
    immediate_callees: list[dict[str, Any]] | None = None
    same_file_siblings: list[dict[str, Any]] | None = None
    """Same-file functions/methods that might be related."""


# ── Necessity / budget ─────────────────────────────────────────────────


class Necessity(str, Enum):
    """Content necessity classification for budget awareness (Req 3.6).

    'necessary' items (queried symbol, flow spine, planned edit files)
    are NEVER cut by token budget. 'incidental' items (related references,
    test suggestions) are cut first when budget is tight.
    """

    necessary = "necessary"
    incidental = "incidental"


class BudgetInfo(BaseModel):
    """Token budget tracking with necessity breakdown (Req 3.6).

    Shows how the budget was used and what was cut, so the agent
    knows whether it needs to make additional calls for full context.
    """

    max_tokens: int = 0
    estimated_used: int = 0
    necessary_items: int = 0
    incidental_items: int = 0
    incidental_cut: int = 0
    would_expand_if_budget_available: list[str] = Field(default_factory=list)
    """Symbol IDs that were cut but could be included with more budget."""
