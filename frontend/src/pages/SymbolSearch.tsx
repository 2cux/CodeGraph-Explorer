import { useState, useCallback, useRef, useEffect } from "react";
import { api, type SearchResult } from "../api";
import { IconSearch } from "../app/components/icons";

interface Props {
  onSelectSymbol: (symbolId: string) => void;
}

export default function SymbolSearch({ onSelectSymbol }: Props) {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [types, setTypes] = useState<string[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    api.symbols.types().then((r) => setTypes(r.types)).catch(() => {});
  }, []);

  const doSearch = useCallback(async (q: string, tf: string) => {
    if (!q.trim()) {
      setResults([]);
      setTotal(0);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const r = await api.symbols.search(q, tf || undefined);
      setResults(r.results);
      setTotal(r.total);
    } catch {
      setError("Search failed.");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleInput = useCallback((value: string) => {
    setQuery(value);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => doSearch(value, typeFilter), 200);
  }, [typeFilter, doSearch]);

  const handleTypeChange = useCallback((tf: string) => {
    setTypeFilter(tf);
    doSearch(query, tf);
  }, [query, doSearch]);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Search input bar */}
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid var(--cg-border)",
        background: "var(--cg-bg-panel)", display: "flex", flexDirection: "column", gap: 8,
      }}>
        <div className="flex items-center" style={{
          gap: 8, padding: "6px 10px", background: "var(--cg-bg-subtle)",
          border: "1px solid var(--cg-border)", borderRadius: 4,
        }}>
          <IconSearch size={13} />
          <input
            value={query}
            onChange={(e) => handleInput(e.target.value)}
            placeholder="Search symbols by name, file path, or docstring..."
            style={{
              flex: 1, minWidth: 0, background: "transparent", border: "none", outline: "none",
              color: "var(--cg-text-primary)", fontSize: 12, fontFamily: "inherit",
            }}
          />
        </div>
        {types.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <FilterChip active={!typeFilter} onClick={() => handleTypeChange("")}>All</FilterChip>
            {types.map((t) => (
              <FilterChip key={t} active={typeFilter === t} onClick={() => handleTypeChange(t)}>{t}</FilterChip>
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {error && (
          <div style={{ padding: 16, color: "var(--cg-error)", fontSize: 12 }}>{error}</div>
        )}
        {loading && (
          <div style={{ padding: 16, color: "var(--cg-text-muted)", fontSize: 12 }}>Searching...</div>
        )}
        {!loading && !error && results.length === 0 && query && (
          <div style={{ padding: 16, color: "var(--cg-text-muted)", fontSize: 12 }}>No results found.</div>
        )}
        {!loading && results.length > 0 && (
          <>
            <div style={{ padding: "8px 16px 4px", fontSize: 10, color: "var(--cg-text-muted)" }}>
              {total} result{total !== 1 ? "s" : ""}
            </div>
            {results.map((r) => (
              <div
                key={r.symbol_id}
                className="flex items-center"
                style={{
                  gap: 10, padding: "8px 16px", cursor: "pointer",
                  borderBottom: "1px solid color-mix(in srgb, var(--cg-border) 40%, transparent)",
                }}
                onClick={() => onSelectSymbol(r.symbol_id)}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--cg-bg-subtle)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <span className="cg-mono" style={{
                  fontSize: 9, color: kindColor(r.type), width: 44, flexShrink: 0,
                  padding: "1px 4px", borderRadius: 2,
                  background: `color-mix(in srgb, ${kindColor(r.type)} 14%, transparent)`,
                }}>
                  {r.type.toUpperCase()}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="cg-mono" style={{ fontSize: 12, fontWeight: 500, color: "var(--cg-text-primary)" }}>
                    {r.name}
                  </div>
                  <div className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                    {r.file_path}
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2, flexShrink: 0 }}>
                  <span className="cg-mono" style={{ fontSize: 10, color: confColor(r.score) }}>
                    {r.score.toFixed(2)}
                  </span>
                  <span style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>
                    {r.match_sources?.join(", ")}
                  </span>
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        height: 22, padding: "0 8px", border: "1px solid var(--cg-border)", borderRadius: 4,
        background: active ? "var(--cg-accent)" : "transparent",
        color: active ? "#fff" : "var(--cg-text-secondary)",
        fontSize: 10, cursor: "pointer", fontFamily: "inherit",
      }}
    >
      {children}
    </button>
  );
}

function kindColor(type: string): string {
  const t = type.toLowerCase();
  if (t === "function") return "var(--cg-accent)";
  if (t === "method") return "#A78BFA";
  if (t === "class") return "var(--cg-success)";
  if (t === "test") return "#4ADE80";
  if (t === "module") return "var(--cg-text-secondary)";
  return "var(--cg-text-muted)";
}

function confColor(c: number): string {
  if (c >= 0.85) return "var(--cg-success)";
  if (c >= 0.7) return "var(--cg-text-secondary)";
  return "var(--cg-warning)";
}
