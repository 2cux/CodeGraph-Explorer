import { useEffect, useState, useCallback } from "react";
import { api, type SearchResult } from "../api";

type ViewMode = "initial" | "loading" | "results" | "empty" | "error";

interface ViewState {
  mode: ViewMode;
  results: SearchResult[];
  total: number;
  error: string;
}

const PAGE_SIZE = 30;

export default function SymbolSearch() {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [types, setTypes] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState<ViewState>({
    mode: "initial",
    results: [],
    total: 0,
    error: "",
  });

  // Fetch available types on mount
  useEffect(() => {
    api.symbols
      .types()
      .then((res) => setTypes(res.types))
      .catch(() => {});
  }, []);

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const doSearch = useCallback(
    async (q: string, off: number) => {
      if (!q.trim()) {
        setState({ mode: "initial", results: [], total: 0, error: "" });
        return;
      }
      setState((s) => ({ ...s, mode: "loading" }));
      try {
        const resp = await api.symbols.search(
          q,
          typeFilter || undefined,
          undefined,
          PAGE_SIZE,
          off,
        );
        if (resp.results.length === 0) {
          setState({ mode: "empty", results: [], total: 0, error: "" });
        } else {
          setState({
            mode: "results",
            results: resp.results,
            total: resp.total,
            error: "",
          });
        }
      } catch (e: unknown) {
        setState({
          mode: "error",
          results: [],
          total: 0,
          error: e instanceof Error ? e.message : "Search failed",
        });
      }
    },
    [typeFilter],
  );

  // Trigger search when debounced query or filters change
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
      case "initial":
        return <InitialState />;
      case "loading":
        return <LoadingState />;
      case "empty":
        return <EmptyResults query={debouncedQuery} />;
      case "error":
        return <ErrorState message={state.error} />;
      case "results":
        return (
          <ResultsList
            results={state.results}
            total={state.total}
            currentPage={currentPage}
            totalPages={totalPages}
            onPageChange={goToPage}
          />
        );
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Symbol Search</h1>
        <p className="text-gray-500 text-sm mt-1">
          Search for functions, classes, methods and other symbols in the code graph.
        </p>
      </div>

      {/* Search bar + filter */}
      <div className="flex gap-3">
        <div className="flex-1 relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">⌕</span>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name, file path, or docstring..."
            className="w-full pl-9 pr-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
            autoFocus
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-3 py-2 border rounded-lg bg-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All types</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {renderContent()}
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────── */

function InitialState() {
  return (
    <div className="text-center py-16 border-2 border-dashed border-gray-300 rounded-xl">
      <div className="text-5xl text-gray-300 mb-4">⌕</div>
      <h2 className="text-lg font-semibold text-gray-500">
        Enter a query to search
      </h2>
      <p className="text-sm text-gray-400 mt-1">
        Search by symbol name, file path, or keywords in docstrings.
      </p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-3 animate-pulse">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="h-20 bg-gray-100 rounded-lg" />
      ))}
    </div>
  );
}

function EmptyResults({ query }: { query: string }) {
  return (
    <div className="text-center py-16 border rounded-xl">
      <p className="text-gray-500">
        No results found for <strong>"{query}"</strong>
      </p>
      <p className="text-sm text-gray-400 mt-1">
        Try a different search term or remove filters.
      </p>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
      {message}
    </div>
  );
}

const TYPE_COLORS: Record<string, string> = {
  function: "bg-emerald-100 text-emerald-700",
  method: "bg-blue-100 text-blue-700",
  class: "bg-violet-100 text-violet-700",
  module: "bg-gray-100 text-gray-700",
  variable: "bg-amber-100 text-amber-700",
  constant: "bg-rose-100 text-rose-700",
};

function TypeBadge({ type }: { type: string }) {
  const colors = TYPE_COLORS[type] || "bg-gray-100 text-gray-600";
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors}`}>
      {type}
    </span>
  );
}

function ResultsList({
  results,
  total,
  currentPage,
  totalPages,
  onPageChange,
}: {
  results: SearchResult[];
  total: number;
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-500">
        {total} result{total !== 1 ? "s" : ""}
      </p>
      <div className="space-y-2">
        {results.map((r) => (
          <a
            key={r.symbol_id}
            href={`/symbol/${encodeURIComponent(r.symbol_id)}`}
            className="block p-3 bg-white border rounded-lg hover:border-blue-300 hover:shadow-sm transition-all"
          >
            <div className="flex items-center gap-2 mb-1">
              <TypeBadge type={r.type} />
              <span className="font-mono text-sm font-medium text-gray-800">
                {r.name}
              </span>
              <span className="text-xs text-gray-400 ml-auto">
                score {r.score.toFixed(2)}
              </span>
            </div>
            <div className="text-xs text-gray-500 font-mono">
              {r.file_path}
            </div>
            <div className="flex gap-2 mt-1 text-xs text-gray-400">
              <code className="text-[10px] bg-gray-50 px-1 rounded">{r.symbol_id}</code>
              {r.match_sources.length > 0 && (
                <span>matched: {r.match_sources.join(", ")}</span>
              )}
            </div>
          </a>
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <PageButton
            disabled={currentPage <= 1}
            onClick={() => onPageChange(currentPage - 1)}
          >
            Prev
          </PageButton>
          <span className="text-sm text-gray-500">
            Page {currentPage} of {totalPages}
          </span>
          <PageButton
            disabled={currentPage >= totalPages}
            onClick={() => onPageChange(currentPage + 1)}
          >
            Next
          </PageButton>
        </div>
      )}
    </div>
  );
}

function PageButton({
  disabled,
  onClick,
  children,
}: {
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className="px-3 py-1.5 text-sm border rounded-lg disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50 transition-colors"
    >
      {children}
    </button>
  );
}
