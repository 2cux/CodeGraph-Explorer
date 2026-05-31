// ── Response types ─────────────────────────────────────────────────────

export interface CallerCalleeItem {
  node_id: string;
  name: string;
  type: string;
  file_path: string;
  edge_type: string;
}

export interface CallerCalleeResponse {
  symbol_id: string;
  callers?: CallerCalleeItem[];
  callees?: CallerCalleeItem[];
  total: number;
}

export interface SearchResult {
  symbol_id: string;
  name: string;
  type: string;
  file_path: string;
  score: number;
  match_sources: string[];
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  query: string;
  limit: number;
  offset: number;
}

export interface SymbolDetail {
  id: string;
  name: string;
  type: string;
  file_path: string;
  module: string | null;
  qualified_name: string | null;
  display_name: string | null;
  position: { line_start: number; line_end: number; column_start?: number; column_end?: number } | null;
  signature: string | null;
  docstring: string | null;
  code_preview: string | null;
  visibility: string | null;
  tags: string[];
}

export interface NeighborItem {
  node_id: string;
  name: string;
  type: string;
  file_path: string;
  edge_type: string;
  confidence: string;
}

export interface NeighborsResponse {
  center_node_id: string;
  neighbors: NeighborItem[];
  total: number;
}

export interface ImpactSymbol {
  symbol_id: string;
  name?: string;
  type?: string;
  file_path?: string;
  reason: string;
  impact_type: string;
  distance: number;
  confidence: number;
}

export interface ImpactFile {
  file_path: string;
  reason: string;
  priority: string;
}

export interface ImpactResponse {
  changed_symbol: string;
  changed_symbol_type: string;
  affected_symbols: ImpactSymbol[];
  affected_files: ImpactFile[];
  risk: { level: string; reasons: string[] } | null;
  recommendations: { step: number; message: string }[];
  warnings: string[];
}

export interface GraphNodeItem {
  id: string;
  label: string;
  type: string;
  file_path: string | null;
}

export interface GraphEdgeItem {
  source: string;
  target: string;
  type: string;
  confidence: number | null;
}

export interface SubgraphResponse {
  center_node_id: string;
  depth: number;
  nodes: GraphNodeItem[];
  edges: GraphEdgeItem[];
  layout_hints: {
    group_by: string;
    max_nodes: number;
    suggested_view: string;
  };
}

export interface GraphStats {
  symbol_count: number;
  file_count: number;
  edge_count: number;
  function_count: number;
  method_count: number;
  class_count: number;
  module_count: number;
  test_count: number;
  import_count: number;
  low_confidence_edges: number;
  low_confidence_ratio: number;
}

export interface OverviewNodeItem {
  id: string;
  path: string;
  label: string;
  module: string;
  symbol_count: number;
  function_count: number;
  class_count: number;
  test_count: number;
}

export interface OverviewEdgeItem {
  source: string;
  target: string;
  edge_count: number;
  types: string[];
}

export interface OverviewResponse {
  nodes: OverviewNodeItem[];
  edges: OverviewEdgeItem[];
}

export interface TypesResponse {
  types: string[];
  total: number;
}

export interface ContextPackResponse {
  schema_version: string;
  pack_id: string;
  task: {
    raw_request: string;
    intent: string;
    keywords: string[];
    target_symbols: string[];
    constraints: Record<string, unknown>;
  };
  repo: Record<string, unknown>;
  entry_points: {
    symbol_id: string;
    type: string;
    name: string;
    file_path: string;
    location: { line_start?: number; line_end?: number } | null;
    signature: string | null;
    reason: string;
    score: number;
    match_sources: string[];
  }[];
  related_symbols: {
    symbol_id: string;
    relation: string;
    distance: number;
    direction: string;
    reason: string;
    importance: string;
    confidence: number;
  }[];
  call_graph: {
    center: string;
    depth: number;
    nodes: { id: string; label: string; type: string }[];
    edges: { source: string; target: string; type: string; confidence: number }[];
  };
  impact: {
    changed_symbol: string;
    affected_symbols: { symbol_id: string; reason: string; impact_type: string; distance: number; confidence: number }[];
    affected_files: { file_path: string; reason: string; priority: string }[];
    risk: { level: string; reasons: string[] };
  };
  selected_context: {
    context_id: string;
    type: string;
    symbol_id: string;
    file_path: string;
    line_start: number;
    line_end: number;
    priority: string;
    relation: string;
    selection_reason: string;
    content: string;
    estimated_tokens: number;
    content_mode: string;
    confidence: number;
    confidence_level: string;
    resolution: string;
    evidence: string;
  }[];
  tests: {
    existing_tests: { source: string; test_file: string; test_name: string; reason: string; confidence: number }[];
    suggested_tests: { source: string; test_file: string; test_name: string; reason: string; confidence: number }[];
  };
  warnings: string[];
  pack_notes: { type: string; message: string; details: Record<string, unknown> }[];
  token_budget: Record<string, number>;
  exports: {
    markdown_path: string;
    json_path: string;
  };
}

export interface DashboardStats {
  project_name: string;
  root_path: string;
  commit_hash: string | null;
  file_count: number;
  symbol_count: number;
  function_count: number;
  class_count: number;
  edge_count: number;
  last_indexed_at: string | null;
  failed_files: number;
  low_confidence_ratio: number;
}

// ── API client ─────────────────────────────────────────────────────────

const BASE = "/api";

async function fetchJSON<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(path, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)));
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`);
  return res.json();
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`);
  return res.json();
}

export interface StatusResponse {
  status: string;  // "fresh" | "stale" | "missing"
  indexed_at: string | null;
  changed_files: string[];
  added_files: string[];
  deleted_files: string[];
  recommendation: string;
}

export const api = {
  repo: {
    status: () => fetchJSON<StatusResponse>(`${BASE}/repo/status`),
    index: (mode: "force" | "incremental" = "force") =>
      postJSON<{ status: string; message: string; file_count?: number; symbol_count?: number; edge_count?: number }>(
        `${BASE}/repo/index`, { mode }
      ),
  },

  symbols: {
    search: (query: string, typeFilter?: string, fileFilter?: string, limit = 50, offset = 0) =>
      fetchJSON<SearchResponse>(`${BASE}/symbols/search`, {
        query,
        ...(typeFilter && { type: typeFilter }),
        ...(fileFilter && { file: fileFilter }),
        limit,
        offset,
      }),
    detail: (nodeId: string) =>
      fetchJSON<SymbolDetail>(`${BASE}/symbols/${encodeURIComponent(nodeId)}`),
    callers: (nodeId: string) =>
      fetchJSON<CallerCalleeResponse>(
        `${BASE}/symbols/${encodeURIComponent(nodeId)}/callers`,
      ),
    callees: (nodeId: string) =>
      fetchJSON<CallerCalleeResponse>(
        `${BASE}/symbols/${encodeURIComponent(nodeId)}/callees`,
      ),
    neighbors: (nodeId: string, depth = 1) =>
      fetchJSON<NeighborsResponse>(
        `${BASE}/symbols/${encodeURIComponent(nodeId)}/neighbors`,
        { depth },
      ),
    impact: (nodeId: string, depth = 2) =>
      fetchJSON<ImpactResponse>(
        `${BASE}/symbols/${encodeURIComponent(nodeId)}/impact`,
        { depth },
      ),
    types: () => fetchJSON<TypesResponse>(`${BASE}/symbols/types`),
  },

  graph: {
    subgraph: (symbolId: string, depth = 1) =>
      fetchJSON<SubgraphResponse>(`${BASE}/graph/subgraph`, { symbol_id: symbolId, depth }),
    stats: () => fetchJSON<GraphStats>(`${BASE}/graph/stats`),
    overview: () => fetchJSON<OverviewResponse>(`${BASE}/graph/overview`),
  },

  dashboard: {
    stats: () => fetchJSON<DashboardStats>(`${BASE}/dashboard/stats`),
  },

  context: {
    generate: (task: string, maxTokens = 6000, includeTests = true, depth = 2) =>
      postJSON<ContextPackResponse>(`${BASE}/context-pack`, {
        task,
        max_tokens: maxTokens,
        include_tests: includeTests,
        depth,
      }),
  },
};
