import { useState, useCallback, useRef, useEffect } from "react";
import { api, type SearchResult } from "../api";
import { IconSearch } from "../app/components/icons";

interface Props {
  onSelectSymbol: (symbolId: string) => void;
}

const HISTORY_KEY = "codegraph_search_history";
const MAX_HISTORY = 5;

interface HistoryEntry {
  symbol_id: string;
  name: string;
  type: string;
  file_path: string;
}

function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveHistory(entry: HistoryEntry): HistoryEntry[] {
  const prev = loadHistory();
  const filtered = prev.filter((h) => h.symbol_id !== entry.symbol_id);
  const next = [entry, ...filtered].slice(0, MAX_HISTORY);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  return next;
}

export default function SymbolSearch({ onSelectSymbol }: Props) {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [filteredResults, setFilteredResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [types, setTypes] = useState<string[]>([]);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const [searchHistory, setSearchHistory] = useState<HistoryEntry[]>(loadHistory);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.symbols.types().then((r) => setTypes(r.types)).catch(() => {});
  }, []);

  // Client-side tag filtering
  useEffect(() => {
    if (!tagFilter.trim()) {
      setFilteredResults(results);
      return;
    }
    const tags = tagFilter.toLowerCase().split(/\s+/).filter(Boolean);
    setFilteredResults(
      results.filter((r) => {
        const sources = (r.match_sources || []).map((s) => s.toLowerCase());
        return tags.some((t) => sources.some((s) => s.includes(t)));
      }),
    );
  }, [results, tagFilter]);

  const doSearch = useCallback(async (q: string, tf: string) => {
    if (!q.trim()) {
      setResults([]);
      setFilteredResults([]);
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
    setHighlightIndex(-1);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => doSearch(value, typeFilter), 200);
  }, [typeFilter, doSearch]);

  const handleTypeChange = useCallback((tf: string) => {
    setTypeFilter(tf);
    setHighlightIndex(-1);
    doSearch(query, tf);
  }, [query, doSearch]);

  const handleSelect = useCallback((r: SearchResult) => {
    setQuery("");
    setResults([]);
    setFilteredResults([]);
    setHighlightIndex(-1);
    setSearchHistory(saveHistory({
      symbol_id: r.symbol_id,
      name: r.name,
      type: r.type,
      file_path: r.file_path,
    }));
    onSelectSymbol(r.symbol_id);
  }, [onSelectSymbol]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    const list = filteredResults.length > 0 ? filteredResults : results;
    if (list.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIndex((prev) => (prev < list.length - 1 ? prev + 1 : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIndex((prev) => (prev > 0 ? prev - 1 : list.length - 1));
    } else if (e.key === "Enter" && highlightIndex >= 0) {
      e.preventDefault();
      handleSelect(list[highlightIndex]);
    } else if (e.key === "Escape") {
      setQuery("");
      setResults([]);
      setFilteredResults([]);
      setHighlightIndex(-1);
      inputRef.current?.blur();
    }
  }, [filteredResults, results, highlightIndex, handleSelect]);

  const displayResults = filteredResults.length > 0 || tagFilter ? filteredResults : results;
  const showHistory = !query && searchHistory.length > 0;

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
            ref={inputRef}
            value={query}
            onChange={(e) => handleInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search symbols by name, file path, or docstring..."
            style={{
              flex: 1, minWidth: 0, background: "transparent", border: "none", outline: "none",
              color: "var(--cg-text-primary)", fontSize: 12, fontFamily: "inherit",
            }}
          />
        </div>
        {/* Type filter chips */}
        {types.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <FilterChip active={!typeFilter} onClick={() => handleTypeChange("")}>All</FilterChip>
            {types.map((t) => (
              <FilterChip key={t} active={typeFilter === t} onClick={() => handleTypeChange(t)}>{t}</FilterChip>
            ))}
          </div>
        )}
        {/* Tag filter input */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 10, color: "var(--cg-text-muted)", flexShrink: 0 }}>Tags:</span>
          <input
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
            placeholder="Space-separated tags (e.g. auth route)..."
            style={{
              flex: 1, minWidth: 0, height: 22, padding: "0 6px",
              background: "var(--cg-bg-subtle)", border: "1px solid var(--cg-border)", borderRadius: 3,
              color: "var(--cg-text-primary)", fontSize: 10, fontFamily: "inherit", outline: "none",
            }}
          />
        </div>
      </div>

      {/* Results */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {error && (
          <div style={{ padding: 16, color: "var(--cg-error)", fontSize: 12 }}>{error}</div>
        )}
        {loading && (
          <div style={{ padding: 16, color: "var(--cg-text-muted)", fontSize: 12 }}>Searching...</div>
        )}

        {/* Search history — shown when query is empty */}
        {!loading && !error && showHistory && (
          <div style={{ padding: "8px 16px" }}>
            <div style={{ padding: "4px 0 6px", fontSize: 10, color: "var(--cg-text-muted)" }}>
              Recent searches
            </div>
            {searchHistory.map((h) => (
              <div
                key={h.symbol_id}
                className="flex items-center"
                style={{
                  gap: 8, padding: "6px 8px", cursor: "pointer", borderRadius: 3,
                }}
                onClick={() => onSelectSymbol(h.symbol_id)}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--cg-bg-subtle)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <span className="cg-mono" style={{
                  fontSize: 9, color: kindColor(h.type), width: 36, flexShrink: 0,
                  padding: "1px 4px", borderRadius: 2,
                  background: `color-mix(in srgb, ${kindColor(h.type)} 14%, transparent)`,
                }}>
                  {h.type.slice(0, 4).toUpperCase()}
                </span>
                <span className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-primary)" }}>
                  {h.name}
                </span>
                <span className="cg-mono" style={{ fontSize: 9, color: "var(--cg-text-muted)", flex: 1, textAlign: "right", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {h.file_path}
                </span>
              </div>
            ))}
          </div>
        )}

        {!loading && !error && !showHistory && results.length === 0 && query && (
          <div style={{ padding: "24px 16px", textAlign: "center" }}>
            <div style={{ fontSize: 12, color: "var(--cg-text-secondary)", marginBottom: 6 }}>
              No symbols matched your query.
            </div>
            <div style={{ fontSize: 11, color: "var(--cg-text-muted)" }}>
              Check the spelling or adjust filter settings.
            </div>
          </div>
        )}

        {!loading && displayResults.length > 0 && (
          <>
            <div style={{ padding: "8px 16px 4px", fontSize: 10, color: "var(--cg-text-muted)" }}>
              {tagFilter ? `${displayResults.length} of ` : ""}{total} result{total !== 1 ? "s" : ""}
              {tagFilter && <span> (tag filter active)</span>}
            </div>
            {displayResults.map((r, i) => (
              <div
                key={r.symbol_id}
                className="flex items-center"
                style={{
                  gap: 10, padding: "8px 16px", cursor: "pointer",
                  borderBottom: "1px solid color-mix(in srgb, var(--cg-border) 40%, transparent)",
                  background: i === highlightIndex ? "var(--cg-bg-subtle)" : "transparent",
                }}
                onClick={() => handleSelect(r)}
                onMouseEnter={(e) => {
                  setHighlightIndex(i);
                  if (i !== highlightIndex) e.currentTarget.style.background = "var(--cg-bg-subtle)";
                }}
                onMouseLeave={(e) => {
                  if (i !== highlightIndex) e.currentTarget.style.background = "transparent";
                }}
              >
                <span className="cg-mono" style={{
                  fontSize: 9, color: kindColor(r.type), minWidth: 44, flexShrink: 0,
                  padding: "1px 4px", borderRadius: 2, textAlign: "center",
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
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3, flexShrink: 0 }}>
                  <span className="cg-mono" style={{ fontSize: 11, fontWeight: 500, color: confColor(r.score) }}>
                    {(r.score * 100).toFixed(0)}%
                  </span>
                  <div style={{ display: "flex", gap: 3, flexWrap: "wrap", justifyContent: "flex-end", maxWidth: 140 }}>
                    {r.match_sources?.slice(0, 3).map((s) => (
                      <span key={s} style={{
                        fontSize: 8, padding: "1px 4px", borderRadius: 2,
                        background: "var(--cg-bg-subtle)", color: "var(--cg-text-muted)",
                        border: "1px solid var(--cg-border)",
                      }}>
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </>
        )}

        {!loading && !error && !showHistory && query && displayResults.length === 0 && (
          <div style={{ padding: "24px 16px", textAlign: "center" }}>
            <div style={{ fontSize: 12, color: "var(--cg-text-secondary)", marginBottom: 6 }}>
              No symbols matched your query.
            </div>
            <div style={{ fontSize: 11, color: "var(--cg-text-muted)" }}>
              Check the spelling or adjust filter settings.
            </div>
          </div>
        )}

        {/* Keyboard nav hint */}
        {displayResults.length > 0 && (
          <div style={{
            padding: "6px 16px", fontSize: 9, color: "var(--cg-text-muted)",
            textAlign: "center", borderTop: "1px solid var(--cg-border)",
          }}>
            ↑↓ navigate · ↵ select · esc clear
          </div>
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
