const API_BASE = "/api";

async function fetchJSON<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const api = {
  repo: {
    info: () => fetchJSON<unknown>(`${API_BASE}/repo/info`),
  },
  symbols: {
    search: (query: string) => fetchJSON<unknown>(`${API_BASE}/symbols/search`, { query }),
    detail: (nodeId: string) => fetchJSON<unknown>(`${API_BASE}/symbols/${nodeId}`),
  },
  graph: {
    neighbors: (nodeId: string, depth = 1) =>
      fetchJSON<unknown>(`${API_BASE}/graph/neighbors/${nodeId}`, { depth: String(depth) }),
    callers: (nodeId: string) => fetchJSON<unknown>(`${API_BASE}/graph/callers/${nodeId}`),
    callees: (nodeId: string) => fetchJSON<unknown>(`${API_BASE}/graph/callees/${nodeId}`),
  },
  context: {
    generate: (task: string) =>
      fetchJSON<unknown>(`${API_BASE}/context/generate`, { task_description: task }),
  },
};
