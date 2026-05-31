import { useState, useRef, useEffect, useCallback } from "react";
import {
  IconLogo, IconSearch, IconSun, IconMoon, IconMonitor, IconMenu,
} from "./icons";
import { Spinner } from "./Spinner";

export type IndexStatus = "fresh" | "stale" | "missing" | "indexing" | "error";
export type PageTab = "overview" | "search" | "impact" | "evidence" | "settings";
type Theme = "system" | "light" | "dark";

function useClickOutside(
  ref: React.RefObject<HTMLElement | null>,
  handler: () => void,
  enabled = true
) {
  const cb = useCallback(handler, [handler]);
  useEffect(() => {
    if (!enabled) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) cb();
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [ref, cb, enabled]);
}

interface SearchResultItem {
  name: string;
  symbol_id: string;
  type: string;
  file_path: string;
}

export function Topbar({
  theme, setTheme, onOpenLibrary,
  activeTab, setActiveTab,
  indexStatus = "missing",
  indexDetails,
  onReindex, onIncrementalIndex,
  onSearch, onSelectResult,
}: {
  theme: Theme;
  setTheme: (t: Theme) => void;
  onOpenLibrary?: () => void;
  activeTab: PageTab;
  setActiveTab: (t: PageTab) => void;
  indexStatus?: IndexStatus;
  indexDetails?: {
    status: string;
    changed_files?: string[];
    added_files?: string[];
    deleted_files?: string[];
    last_indexed_at?: string | null;
    last_error?: string | null;
    recommendation?: string;
  };
  onReindex?: () => void;
  onIncrementalIndex?: () => void;
  onSearch?: (query: string) => Promise<SearchResultItem[]>;
  onSelectResult?: (symbolId: string) => void;
}) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [indexPopoverOpen, setIndexPopoverOpen] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const indexRef = useRef<HTMLDivElement>(null);

  useClickOutside(searchRef, () => { setSearchOpen(false); setQuery(""); setResults([]); }, searchOpen);
  useClickOutside(indexRef, () => setIndexPopoverOpen(false), indexPopoverOpen);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const searchTimer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (!searchOpen) { setQuery(""); setResults([]); return; }
    const q = query.trim().toLowerCase();
    if (!q) { setResults([]); return; }
    if (onSearch) {
      if (searchTimer.current) clearTimeout(searchTimer.current);
      searchTimer.current = setTimeout(async () => {
        const res = await onSearch(query);
        setResults(res);
      }, 150);
    }
  }, [query, searchOpen, onSearch]);

  const handleSearchSelect = useCallback((item: SearchResultItem) => {
    setQuery("");
    setSearchOpen(false);
    onSelectResult?.(item.symbol_id);
  }, [onSelectResult]);

  const themeIcon = theme === "dark" ? IconMoon : theme === "light" ? IconSun : IconMonitor;
  const nextTheme: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };

  const indexLabel: Record<IndexStatus, string> = {
    fresh: "Fresh",
    stale: "Stale",
    missing: "Missing",
    indexing: "Indexing",
    error: "Error",
  };
  const indexColor: Record<IndexStatus, string> = {
    fresh: "var(--cg-success)",
    stale: "var(--cg-warning)",
    missing: "var(--cg-text-muted)",
    indexing: "var(--cg-accent)",
    error: "var(--cg-error)",
  };

  const TABS: { key: PageTab; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "search", label: "Search" },
    { key: "impact", label: "Impact" },
    { key: "evidence", label: "Evidence Pack" },
    { key: "settings", label: "Settings" },
  ];

  const changedCount = (indexDetails?.changed_files?.length ?? 0) +
    (indexDetails?.added_files?.length ?? 0) +
    (indexDetails?.deleted_files?.length ?? 0);

  return (
    <div
      style={{
        height: 36,
        display: "flex",
        alignItems: "center",
        padding: "0 8px 0 10px",
        gap: 4,
        background: "var(--cg-bg-panel)",
        borderBottom: "1px solid var(--cg-border)",
        flexShrink: 0,
      }}
    >
      {/* Logo */}
      <div
        className="flex items-center"
        style={{ gap: 6, cursor: "pointer", flexShrink: 0 }}
        onClick={() => setActiveTab("overview")}
      >
        <span style={{ color: "var(--cg-accent)", display: "flex", alignItems: "center" }}>
          <IconLogo size={16} />
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "var(--cg-text-primary)",
            letterSpacing: 0.2,
          }}
        >
          CodeGraph
        </span>
      </div>

      <span style={{ width: 1, height: 20, background: "var(--cg-border)", flexShrink: 0, marginLeft: 4 }} />

      {/* Page tabs */}
      <div style={{ display: "flex", gap: 0, marginLeft: 4 }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            style={{
              height: 36, padding: "0 10px", border: "none",
              borderBottom: activeTab === t.key ? "2px solid var(--cg-accent)" : "2px solid transparent",
              background: "transparent",
              color: activeTab === t.key ? "var(--cg-text-primary)" : "var(--cg-text-muted)",
              fontSize: 11, fontFamily: "inherit", cursor: "pointer", whiteSpace: "nowrap",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1 }} />

      {/* Quick search (always visible) */}
      <div ref={searchRef} style={{ position: "relative", flexShrink: 0 }}>
        <div
          className="flex items-center"
          style={{
            gap: 4, height: 26, padding: "0 8px",
            background: searchOpen ? "var(--cg-bg-elevated)" : "var(--cg-bg-subtle)",
            border: `1px solid ${searchOpen ? "var(--cg-accent)" : "transparent"}`,
            borderRadius: 4, color: "var(--cg-text-muted)", cursor: "text",
            minWidth: 160,
          }}
          onClick={() => setSearchOpen(true)}
        >
          <span style={{ display: "flex", alignItems: "center" }}>
            <IconSearch size={11} />
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Quick search..."
            style={{
              flex: 1, minWidth: 0, background: "transparent", border: "none", outline: "none",
              color: "var(--cg-text-primary)", fontSize: 11, fontFamily: "inherit", padding: 0,
            }}
          />
        </div>
        {searchOpen && results.length > 0 && (
          <div
            style={{
              position: "absolute", top: "100%", right: 0,
              marginTop: 4, width: 300,
              background: "var(--cg-bg-elevated)",
              border: "1px solid var(--cg-border)",
              borderRadius: 4, boxShadow: "0 4px 12px -4px rgba(0,0,0,0.25)",
              zIndex: 50, overflow: "hidden",
            }}
          >
            <div style={{ padding: "4px 0" }}>
              {results.map((r) => (
                <div
                  key={r.symbol_id}
                  className="flex items-center"
                  style={{
                    gap: 8, padding: "5px 10px", cursor: "pointer", fontSize: 11,
                  }}
                  onClick={() => handleSearchSelect(r)}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--cg-bg-subtle)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  <span className="cg-mono" style={{
                    fontSize: 9,
                    color: kindColor(r.type),
                    width: 32, flexShrink: 0,
                  }}>
                    {r.type?.toUpperCase().slice(0, 4)}
                  </span>
                  <span style={{ color: "var(--cg-text-primary)", flex: 1, minWidth: 0 }}>
                    {r.name}
                  </span>
                  <span className="cg-mono" style={{
                    fontSize: 9, color: "var(--cg-text-muted)",
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 100,
                  }}>
                    {r.file_path}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Index status */}
      <div ref={indexRef} style={{ position: "relative", flexShrink: 0 }}>
        <button
          className="flex items-center"
          onClick={() => setIndexPopoverOpen((v) => !v)}
          style={{
            gap: 5, height: 26, padding: "0 8px", background: "transparent",
            border: "none", borderRadius: 4, cursor: "pointer",
            color: "var(--cg-text-muted)", fontSize: 10, fontFamily: "inherit",
          }}
        >
          <span style={{
            width: 6, height: 6, borderRadius: "50%",
            background: indexColor[indexStatus],
          }} />
          {indexStatus === "indexing" && <Spinner size={10} />}
          <span className="cg-mono" style={{ color: indexColor[indexStatus], fontSize: 10 }}>
            {indexLabel[indexStatus]}
          </span>
          {indexStatus === "stale" && changedCount > 0 && (
            <span style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>
              {changedCount} file{changedCount !== 1 ? "s" : ""}
            </span>
          )}
        </button>
        {indexPopoverOpen && (
          <div
            style={{
              position: "absolute", top: "100%", right: 0, marginTop: 4,
              padding: "10px 12px",
              background: "var(--cg-bg-elevated)",
              border: "1px solid var(--cg-border)",
              borderRadius: 4, boxShadow: "0 4px 12px -4px rgba(0,0,0,0.25)",
              zIndex: 50, minWidth: 280, fontSize: 11,
              color: "var(--cg-text-secondary)",
              display: "flex", flexDirection: "column", gap: 6,
            }}
          >
            {indexStatus === "fresh" && (
              <>
                <span style={{ color: "var(--cg-success)", fontWeight: 500 }}>
                  Index is up to date.
                </span>
                {indexDetails?.last_indexed_at && (
                  <span style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                    Indexed {indexDetails.last_indexed_at}
                  </span>
                )}
              </>
            )}
            {indexStatus === "missing" && (
              <span>No index found. Run <code style={{ fontSize: 10 }}>codegraph index</code> to create one.</span>
            )}
            {indexStatus === "indexing" && <span>Index update in progress...</span>}
            {indexStatus === "error" && (
              <>
                <span style={{ color: "var(--cg-error)", fontWeight: 500 }}>Index error.</span>
                {indexDetails?.last_error && (
                  <code className="cg-mono" style={{ fontSize: 10, color: "var(--cg-error)" }}>
                    {indexDetails.last_error}
                  </code>
                )}
              </>
            )}
            {indexStatus === "stale" && (
              <>
                <span style={{ color: "var(--cg-warning)", fontWeight: 500 }}>
                  Index is stale — file changes detected.
                </span>
                {indexDetails?.changed_files && indexDetails.changed_files.length > 0 && (
                  <div>
                    <span style={{ fontSize: 10, fontWeight: 600 }}>
                      Changed ({indexDetails.changed_files.length}):
                    </span>
                    {indexDetails.changed_files.slice(0, 8).map((f) => (
                      <div key={f} className="cg-mono" style={{ fontSize: 9, paddingLeft: 8 }}>- {f}</div>
                    ))}
                    {indexDetails.changed_files.length > 8 && (
                      <div className="cg-mono" style={{ fontSize: 9, paddingLeft: 8 }}>
                        ... and {indexDetails.changed_files.length - 8} more
                      </div>
                    )}
                  </div>
                )}
                {indexDetails?.added_files && indexDetails.added_files.length > 0 && (
                  <div>
                    <span style={{ fontSize: 10, fontWeight: 600 }}>
                      Added ({indexDetails.added_files.length}):
                    </span>
                    {indexDetails.added_files.slice(0, 5).map((f) => (
                      <div key={f} className="cg-mono" style={{ fontSize: 9, paddingLeft: 8, color: "var(--cg-success)" }}>+ {f}</div>
                    ))}
                  </div>
                )}
                {indexDetails?.deleted_files && indexDetails.deleted_files.length > 0 && (
                  <div>
                    <span style={{ fontSize: 10, fontWeight: 600 }}>
                      Deleted ({indexDetails.deleted_files.length}):
                    </span>
                    {indexDetails.deleted_files.slice(0, 5).map((f) => (
                      <div key={f} className="cg-mono" style={{ fontSize: 9, paddingLeft: 8, color: "var(--cg-error)" }}>x {f}</div>
                    ))}
                  </div>
                )}
                {(onIncrementalIndex || onReindex) && (
                  <div style={{ display: "flex", gap: 5, marginTop: 4 }}>
                    {onIncrementalIndex && (
                      <button
                        onClick={(e) => { e.stopPropagation(); onIncrementalIndex(); }}
                        style={{
                          height: 24, padding: "0 8px", fontSize: 10, fontFamily: "inherit",
                          background: "var(--cg-accent)", color: "#fff", border: "none",
                          borderRadius: 3, cursor: "pointer",
                        }}
                      >
                        Incremental Update
                      </button>
                    )}
                    {onReindex && (
                      <button
                        onClick={(e) => { e.stopPropagation(); onReindex(); }}
                        style={{
                          height: 24, padding: "0 8px", fontSize: 10, fontFamily: "inherit",
                          background: "transparent", color: "var(--cg-text-secondary)",
                          border: "1px solid var(--cg-border)", borderRadius: 3, cursor: "pointer",
                        }}
                      >
                        Re-index
                      </button>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Library button */}
      {onOpenLibrary && (
        <button
          onClick={onOpenLibrary}
          style={{
            height: 26, padding: "0 8px", background: "transparent", border: "none",
            borderRadius: 4, color: "var(--cg-text-muted)", cursor: "pointer",
            display: "flex", alignItems: "center", gap: 4, fontSize: 10, fontFamily: "inherit",
          }}
        >
          <IconMenu size={11} />
        </button>
      )}

      {/* Theme toggle */}
      <button
        className="flex items-center"
        onClick={() => setTheme(nextTheme[theme])}
        style={{
          width: 26, height: 26, borderRadius: 4, border: "none",
          background: "transparent", color: "var(--cg-text-muted)", cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
        aria-label={`Theme: ${theme}`}
      >
        <IconComponent icon={themeIcon} size={12} />
      </button>
    </div>
  );
}

function IconComponent({ icon: Icon, size }: { icon: React.FC<{ size?: number }>; size: number }) {
  return <Icon size={size} />;
}

function kindColor(type: string) {
  const t = type?.toLowerCase() || "";
  if (t === "function") return "var(--cg-accent)";
  if (t === "method") return "#A78BFA";
  if (t === "class") return "var(--cg-success)";
  if (t === "test") return "#4ADE80";
  return "var(--cg-text-secondary)";
}
