// ── Response types ─────────────────────────────────────────────────────

export interface RepoSummary {
  name: string;
  root_path: string;
  file_count: number;
  symbol_count: number;
  function_count: number;
  class_count: number;
  edge_count: number;
  indexed_at: string | null;
  commit_hash: string | null;
  failed_files: number;
  low_confidence_ratio: number;
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
  affected_symbols: ImpactSymbol[];
  affected_files: ImpactFile[];
  risk: { level: string; reasons: string[] } | null;
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

export interface TypesResponse {
  types: string[];
  total: number;
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

export const api = {
  repo: {
    summary: () => fetchJSON<RepoSummary>(`${BASE}/repo/summary`),
    index: () => fetchJSON<{ status: string; message: string }>(`${BASE}/repo/index`, {}),
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
      fetchJSON<{ symbol_id: string; callers: unknown[]; total: number }>(
        `${BASE}/symbols/${encodeURIComponent(nodeId)}/callers`,
      ),
    callees: (nodeId: string) =>
      fetchJSON<{ symbol_id: string; callees: unknown[]; total: number }>(
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
  },

  dashboard: {
    stats: () => fetchJSON<DashboardStats>(`${BASE}/dashboard/stats`),
  },

  context: {
    generate: (task: string, maxTokens = 6000) =>
      postJSON<unknown>(`${BASE}/context-pack`, {
        task,
        max_tokens: maxTokens,
        include_tests: true,
        depth: 2,
      }),
  },
};
