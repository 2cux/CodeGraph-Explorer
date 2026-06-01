import { useState, useCallback, useRef, useEffect } from "react";
import { api, type SearchResult } from "../../api";
import { IconSearch } from "./icons";

interface SearchBarProps {
  onSelectResult: (symbolId: string) => void;
  /** Optional placeholder text */
  placeholder?: string;
}

export default function SearchBar({
  onSelectResult,
  placeholder = "Search symbols...",
}: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const abortRef = useRef<AbortController>();

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      setOpen(false);
      setError(null);
      return;
    }

    // Abort previous request
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();

    setLoading(true);
    setError(null);
    try {
      const res = await api.symbols.search(q, undefined, undefined, 5, 0);
      setResults(res.results.slice(0, 5));
      setOpen(res.results.length > 0);
      setHighlightIndex(-1);
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") return;
      setError("Search failed");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleInput = useCallback(
    (value: string) => {
      setQuery(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => doSearch(value), 250);
    },
    [doSearch],
  );

  const handleSelect = useCallback(
    (result: SearchResult) => {
      setQuery("");
      setOpen(false);
      setResults([]);
      inputRef.current?.blur();
      onSelectResult(result.symbol_id);
    },
    [onSelectResult],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!open) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlightIndex((prev) =>
          prev < results.length - 1 ? prev + 1 : 0,
        );
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlightIndex((prev) =>
          prev > 0 ? prev - 1 : results.length - 1,
        );
      } else if (e.key === "Enter" && highlightIndex >= 0) {
        e.preventDefault();
        handleSelect(results[highlightIndex]);
      } else if (e.key === "Escape") {
        setOpen(false);
        inputRef.current?.blur();
      }
    },
    [open, results, highlightIndex, handleSelect],
  );

  const kindColor = (type: string) => {
    const t = type.toLowerCase();
    if (t === "function" || t === "method") return "var(--cg-accent)";
    if (t === "class") return "var(--cg-success)";
    if (t === "test") return "#4ADE80";
    return "var(--cg-text-muted)";
  };

  return (
    <div ref={containerRef} style={{ position: "relative", width: 280 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          height: 30,
          padding: "0 10px",
          borderRadius: 6,
          background: "var(--cg-bg-panel)",
          border: `1px solid ${open ? "var(--cg-accent)" : "var(--cg-border)"}`,
          transition: "border-color 120ms ease",
        }}
      >
        <IconSearch size={12} color="var(--cg-text-muted)" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (results.length > 0) setOpen(true);
          }}
          placeholder={placeholder}
          className="cg-mono"
          style={{
            flex: 1,
            minWidth: 0,
            border: "none",
            outline: "none",
            background: "transparent",
            fontSize: 12,
            color: "var(--cg-text-primary)",
            fontFamily: "inherit",
          }}
        />
        {loading && (
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              border: "2px solid var(--cg-border)",
              borderTopColor: "var(--cg-accent)",
              animation: "spin 0.6s linear infinite",
            }}
          />
        )}
      </div>

      {/* Dropdown */}
      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            marginTop: 4,
            borderRadius: 6,
            background: "var(--cg-bg-panel)",
            border: "1px solid var(--cg-border)",
            overflow: "hidden",
            zIndex: 100,
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
          }}
        >
          {error ? (
            <div
              style={{
                padding: "8px 12px",
                fontSize: 11,
                color: "var(--cg-error)",
              }}
            >
              {error}
            </div>
          ) : results.length === 0 ? (
            <div
              style={{
                padding: "8px 12px",
                fontSize: 11,
                color: "var(--cg-text-muted)",
              }}
            >
              No results found.
            </div>
          ) : (
            results.map((r, i) => (
              <button
                key={r.symbol_id}
                onClick={() => handleSelect(r)}
                onMouseEnter={() => setHighlightIndex(i)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  width: "100%",
                  padding: "6px 10px",
                  border: "none",
                  borderBottom:
                    i < results.length - 1
                      ? "1px solid var(--cg-border)"
                      : "none",
                  background:
                    i === highlightIndex
                      ? "var(--cg-bg-subtle)"
                      : "transparent",
                  cursor: "pointer",
                  textAlign: "left",
                  fontFamily: "inherit",
                  transition: "background 80ms ease",
                }}
              >
                <span
                  className="cg-mono"
                  style={{
                    fontSize: 9,
                    fontWeight: 600,
                    color: kindColor(r.type),
                    letterSpacing: 0.5,
                    padding: "1px 4px",
                    borderRadius: 2,
                    background: `color-mix(in srgb, ${kindColor(r.type)} 14%, transparent)`,
                    flexShrink: 0,
                  }}
                >
                  {r.type?.toUpperCase().slice(0, 4) || "???"}
                </span>
                <div
                  style={{
                    flex: 1,
                    minWidth: 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: 1,
                  }}
                >
                  <span
                    className="cg-mono"
                    style={{
                      fontSize: 11,
                      fontWeight: 500,
                      color: "var(--cg-text-primary)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {r.name}
                  </span>
                  <span
                    className="cg-mono"
                    style={{
                      fontSize: 9,
                      color: "var(--cg-text-muted)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {r.file_path}
                  </span>
                </div>
              </button>
            ))
          )}
          <div
            style={{
              padding: "3px 8px",
              fontSize: 9,
              color: "var(--cg-text-muted)",
              textAlign: "right",
              borderTop: "1px solid var(--cg-border)",
            }}
          >
            ↑↓ navigate · ↵ select · esc close
          </div>
        </div>
      )}
    </div>
  );
}
