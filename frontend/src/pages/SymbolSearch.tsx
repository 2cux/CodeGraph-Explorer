import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api, type SearchResult } from "../api";
import { IconSearch } from "../components/icons";

type ViewMode = "initial" | "loading" | "results" | "empty" | "error";

interface ViewState {
  mode: ViewMode;
  results: SearchResult[];
  total: number;
  error: string;
}

const PAGE_SIZE = 30;

const TYPE_COLORS: Record<string, string> = {
  function: "var(--cg-accent)",
  method: "#A78BFA",
  class: "var(--cg-success)",
  module: "var(--cg-text-secondary)",
  variable: "var(--cg-warning)",
  constant: "var(--cg-error)",
  test: "#4ADE80",
};

const TYPE_BG_COLORS: Record<string, string> = {
  function: "var(--cg-accent-alpha)",
  method: "color-mix(in srgb, #A78BFA 14%, transparent)",
  class: "var(--cg-success-alpha)",
  module: "color-mix(in srgb, var(--cg-text-secondary) 14%, transparent)",
  variable: "var(--cg-warning-alpha)",
  constant: "var(--cg-error-alpha)",
  test: "color-mix(in srgb, #4ADE80 14%, transparent)",
};

export default function SymbolSearch() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [types, setTypes] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState<ViewState>({ mode: "initial", results: [], total: 0, error: "" });

  useEffect(() => {
    api.symbols.types().then((res) => setTypes(res.types)).catch(() => {});
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const doSearch = useCallback(async (q: string, off: number) => {
    if (!q.trim()) {
      setState({ mode: "initial", results: [], total: 0, error: "" });
      return;
    }
    setState((s) => ({ ...s, mode: "loading" }));
    try {
      const resp = await api.symbols.search(q, typeFilter || undefined, undefined, PAGE_SIZE, off);
      if (resp.results.length === 0) {
        setState({ mode: "empty", results: [], total: 0, error: "" });
      } else {
        setState({ mode: "results", results: resp.results, total: resp.total, error: "" });
      }
    } catch (e: unknown) {
      setState({ mode: "error", results: [], total: 0, error: e instanceof Error ? e.message : "Search failed" });
    }
  }, [typeFilter]);

  useEffect(() => {
    doSearch(debouncedQuery, 0);
    setOffset(0);
  }, [debouncedQuery, typeFilter, doSearch]);

  const totalPages = Math.ceil(state.total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const goToPage = (page: number) => {
    const newOffset = (page - 1) * PAGE_SIZE;
    setOffset(newOffset);
    doSearch(debouncedQuery, newOffset);
  };

  const renderContent = () => {
    switch (state.mode) {
      case "initial": return <InitialState />;
      case "loading": return <LoadingState />;
      case "empty": return <EmptyResults query={debouncedQuery} />;
      case "error": return <ErrorState message={state.error} />;
      case "results": return (
        <ResultsList
          results={state.results}
          total={state.total}
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={goToPage}
          onSelect={(id) => navigate(`/symbol/${encodeURIComponent(id)}`)}
        />
      );
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 18, fontWeight: 500, color: "var(--cg-text-primary)", margin: 0 }}>
          Symbol Search
        </h1>
        <p style={{ fontSize: 12, color: "var(--cg-text-secondary)", margin: "4px 0 0" }}>
          Search for functions, classes, methods and other symbols in the code graph.
        </p>
      </div>

      {/* Search bar + filter */}
      <div className="flex items-center" style={{ gap: 8 }}>
        <div style={{ flex: 1, position: "relative" }}>
          <span style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", color: "var(--cg-text-muted)", display: "flex", alignItems: "center" }}>
            <IconSearch size={12} />
          </span>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name, file path, or docstring..."
            autoFocus
            style={{
              width: "100%", height: 30, padding: "0 8px 0 28px",
              border: "1px solid var(--cg-border)", borderRadius: 4,
              background: "var(--cg-bg-panel)", color: "var(--cg-text-primary)",
              fontSize: 12, fontFamily: "inherit", outline: "none",
            }}
            onFocus={(e) => e.currentTarget.style.borderColor = "var(--cg-accent)"}
            onBlur={(e) => e.currentTarget.style.borderColor = "var(--cg-border)"}
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          style={{
            height: 30, padding: "0 8px",
            border: "1px solid var(--cg-border)", borderRadius: 4,
            background: "var(--cg-bg-panel)", color: "var(--cg-text-primary)",
            fontSize: 11, fontFamily: "inherit", outline: "none",
          }}
        >
          <option value="">All types</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {renderContent()}
    </div>
  );
}

/* ── Sub-components ──────────────────────────────────────────── */

function InitialState() {
  return (
    <div style={{ textAlign: "center", padding: "40px 20px", border: "1px dashed var(--cg-border)", borderRadius: 8 }}>
      <div style={{ fontSize: 32, color: "var(--cg-text-muted)", marginBottom: 12 }}>⌕</div>
      <h2 style={{ fontSize: 14, fontWeight: 500, color: "var(--cg-text-secondary)", margin: "0 0 4px" }}>
        Enter a query to search
      </h2>
      <p style={{ fontSize: 11, color: "var(--cg-text-muted)", margin: 0 }}>
        Search by symbol name, file path, or keywords in docstrings.
      </p>
    </div>
  );
}

function LoadingState() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {[...Array(5)].map((_, i) => (
        <div key={i} className="cg-skeleton" style={{ height: 48, borderRadius: 4, animationDelay: `${i * 0.05}s` }} />
      ))}
    </div>
  );
}

function EmptyResults({ query }: { query: string }) {
  return (
    <div style={{ textAlign: "center", padding: "40px 20px", border: "1px solid var(--cg-border)", borderRadius: 6 }}>
      <p style={{ fontSize: 12, color: "var(--cg-text-secondary)", margin: 0 }}>
        No results found for <strong>"{query}"</strong>
      </p>
      <p style={{ fontSize: 11, color: "var(--cg-text-muted)", margin: "4px 0 0" }}>
        Try a different search term or remove filters.
      </p>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div style={{
      padding: "8px 10px",
      background: "var(--cg-error-alpha)",
      border: "1px solid color-mix(in srgb, var(--cg-error) 30%, transparent)",
      borderRadius: 4, fontSize: 11, color: "var(--cg-text-secondary)",
    }}>
      {message}
    </div>
  );
}

/* ── Results ─────────────────────────────────────────────────── */

function ResultsList({
  results, total, currentPage, totalPages, onPageChange, onSelect,
}: {
  results: SearchResult[]; total: number;
  currentPage: number; totalPages: number;
  onPageChange: (page: number) => void;
  onSelect: (id: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <p style={{ fontSize: 11, color: "var(--cg-text-muted)", margin: 0 }}>
        {total} result{total !== 1 ? "s" : ""}
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {results.map((r) => {
          const color = TYPE_COLORS[r.type] || "var(--cg-text-secondary)";
          const bg = TYPE_BG_COLORS[r.type] || "color-mix(in srgb, var(--cg-text-secondary) 10%, transparent)";
          return (
            <div
              key={r.symbol_id}
              onClick={() => onSelect(r.symbol_id)}
              style={{
                padding: "8px 10px",
                background: "var(--cg-bg-panel)",
                border: "1px solid var(--cg-border)",
                borderRadius: 4,
                cursor: "pointer",
                transition: "border-color 120ms ease, background 120ms ease",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--cg-border-hover)"; e.currentTarget.style.background = "var(--cg-bg-elevated)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--cg-border)"; e.currentTarget.style.background = "var(--cg-bg-panel)"; }}
            >
              <div className="flex items-center" style={{ gap: 6, marginBottom: 4 }}>
                <span className="cg-mono" style={{ fontSize: 9, color, background: bg, padding: "1px 4px", borderRadius: 2, letterSpacing: 0.5 }}>
                  {r.type}
                </span>
                <span className="cg-mono" style={{ fontSize: 12, fontWeight: 500, color: "var(--cg-text-primary)" }}>
                  {r.name}
                </span>
                <span style={{ flex: 1 }} />
                <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                  {r.score.toFixed(2)}
                </span>
              </div>
              <div className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>
                {r.file_path}
              </div>
              <div className="flex items-center" style={{ gap: 6, marginTop: 2 }}>
                <span className="cg-mono" style={{ fontSize: 9, color: "var(--cg-text-muted)", padding: "1px 4px", background: "var(--cg-bg-subtle)", borderRadius: 2 }}>
                  {r.symbol_id}
                </span>
                {r.match_sources.length > 0 && (
                  <span style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                    matched: {r.match_sources.join(", ")}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center" style={{ justifyContent: "center", gap: 8, paddingTop: 8 }}>
          <PageBtn disabled={currentPage <= 1} onClick={() => onPageChange(currentPage - 1)}>Prev</PageBtn>
          <span style={{ fontSize: 11, color: "var(--cg-text-muted)" }}>
            Page {currentPage} of {totalPages}
          </span>
          <PageBtn disabled={currentPage >= totalPages} onClick={() => onPageChange(currentPage + 1)}>Next</PageBtn>
        </div>
      )}
    </div>
  );
}

function PageBtn({ disabled, onClick, children }: { disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      style={{
        height: 24, padding: "0 10px",
        border: "1px solid var(--cg-border)", borderRadius: 4,
        background: "transparent", color: disabled ? "var(--cg-text-muted)" : "var(--cg-text-primary)",
        fontSize: 11, cursor: disabled ? "default" : "pointer", fontFamily: "inherit",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {children}
    </button>
  );
}
