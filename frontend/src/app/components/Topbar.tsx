import { useState, useRef, useEffect, useCallback } from "react";
import {
  IconLogo,
  IconSearch,
  IconSun,
  IconMoon,
  IconMonitor,
  IconMenu,
} from "./icons";
import { Spinner } from "./Spinner";

export type IndexStatus = "indexed" | "indexing" | "failed" | "not-indexed";
type Theme = "system" | "light" | "dark";

const MOCK_SYMBOLS = [
  { name: "authenticate", kind: "fn", path: "src/auth.py:42" },
  { name: "verify_token", kind: "fn", path: "src/auth.py:104" },
  { name: "MFAForm", kind: "class", path: "src/ui/mfa.tsx:18" },
  { name: "LoginService", kind: "class", path: "src/services/auth.ts:12" },
  { name: "useSession", kind: "hook", path: "src/hooks/session.ts:8" },
  { name: "tokenize", kind: "fn", path: "src/utils/token.ts:23" },
  { name: "AuthProvider", kind: "comp", path: "src/providers/auth.tsx:5" },
  { name: "MFAConfig", kind: "type", path: "src/types/auth.ts:15" },
];

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

export function Topbar({
  theme,
  setTheme,
  onOpenLibrary,
  indexStatus = "indexed",
  onSearch,
}: {
  theme: Theme;
  setTheme: (t: Theme) => void;
  onOpenLibrary?: () => void;
  indexStatus?: IndexStatus;
  onSearch?: (query: string) => Promise<{ name: string; symbol_id: string; type: string; file_path: string }[]>;
}) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [indexPopoverOpen, setIndexPopoverOpen] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const commandRef = useRef<HTMLDivElement>(null);
  const indexRef = useRef<HTMLDivElement>(null);

  useClickOutside(searchRef, () => { setSearchOpen(false); setQuery(""); setResults([]); }, searchOpen);
  useClickOutside(commandRef, () => setCommandOpen(false), commandOpen);
  useClickOutside(indexRef, () => setIndexPopoverOpen(false), indexPopoverOpen);

  const SEARCH_QUERY = "";
  const [query, setQuery] = useState(SEARCH_QUERY);
  const [results, setResults] = useState<typeof MOCK_SYMBOLS>([]);
  const searchTimer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (!searchOpen) { setQuery(""); setResults([]); return; }
    const q = query.trim().toLowerCase();
    if (!q) { setResults([]); return; }

    if (onSearch) {
      if (searchTimer.current) clearTimeout(searchTimer.current);
      searchTimer.current = setTimeout(async () => {
        const res = await onSearch(query);
        setResults(res.map((r) => ({
          name: r.name || r.symbol_id.split("::").pop() || r.symbol_id,
          kind: r.type?.toLowerCase().slice(0, 4) || "fn",
          path: r.file_path || r.symbol_id,
        })));
      }, 150);
      return;
    }

    // Fallback mock search
    setResults(MOCK_SYMBOLS.filter((s) => s.name.includes(q) || s.path.includes(q)).slice(0, 6));
  }, [query, searchOpen, onSearch]);

  const handleSearchSelect = useCallback((name: string) => {
    setQuery(name);
    setSearchOpen(false);
  }, []);

  const themeIcon = theme === "dark" ? IconMoon : theme === "light" ? IconSun : IconMonitor;
  const nextTheme: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };

  const indexLabel: Record<IndexStatus, string> = {
    indexed: "Indexed",
    indexing: "Indexing",
    failed: "Failed",
    "not-indexed": "Not indexed",
  };
  const indexColor: Record<IndexStatus, string> = {
    indexed: "var(--cg-success)",
    indexing: "var(--cg-accent)",
    failed: "var(--cg-error)",
    "not-indexed": "var(--cg-text-muted)",
  };

  return (
    <div
      style={{
        height: 36,
        display: "flex",
        alignItems: "center",
        padding: "0 8px 0 10px",
        gap: 6,
        background: "var(--cg-bg-panel)",
        borderBottom: "1px solid var(--cg-border)",
        flexShrink: 0,
      }}
    >
      {/* Logo */}
      <div
        className="flex items-center"
        style={{ gap: 6, cursor: "pointer", flexShrink: 0 }}
        onClick={() => window.location.reload()}
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

      <span style={{ width: 1, height: 20, background: "var(--cg-border)", flexShrink: 0 }} />

      {/* Search */}
      <div
        ref={searchRef}
        style={{ position: "relative", flexShrink: 0 }}
      >
        <div
          className="flex items-center"
          style={{
            gap: 4,
            height: 26,
            padding: "0 8px",
            background: searchOpen ? "var(--cg-bg-elevated)" : "var(--cg-bg-subtle)",
            border: `1px solid ${searchOpen ? "var(--cg-accent)" : "transparent"}`,
            borderRadius: 4,
            color: "var(--cg-text-muted)",
            cursor: "text",
            minWidth: 180,
            transition: "border-color 120ms ease, background 120ms ease",
          }}
          onMouseEnter={() => {}}
          onMouseLeave={() => {}}
          onClick={() => setSearchOpen(true)}
        >
          <span style={{ display: "flex", alignItems: "center" }}>
            <IconSearch size={11} />
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search symbols, files…"
            style={{
              flex: 1,
              minWidth: 0,
              background: "transparent",
              border: "none",
              outline: "none",
              color: "var(--cg-text-primary)",
              fontSize: 11,
              fontFamily: "inherit",
              padding: 0,
            }}
          />
          {!searchOpen && (
            <span className="cg-mono" style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>
              ⌘K
            </span>
          )}
          {searchOpen && query && results.length === 0 && (
            <span style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>No results</span>
          )}
        </div>

        {/* Search results dropdown */}
        {searchOpen && results.length > 0 && (
          <div
            style={{
              position: "absolute",
              top: "100%",
              left: 0,
              right: 0,
              marginTop: 4,
              background: "var(--cg-bg-elevated)",
              border: "1px solid var(--cg-border)",
              borderRadius: 4,
              boxShadow: "0 4px 12px -4px rgba(0,0,0,0.25)",
              zIndex: 50,
              overflow: "hidden",
            }}
          >
            <div style={{ padding: "4px 0" }}>
              {results.map((r) => (
                <div
                  key={`${r.path}-${r.name}`}
                  className="flex items-center"
                  style={{
                    gap: 8,
                    padding: "5px 10px",
                    cursor: "pointer",
                    fontSize: 11,
                  }}
                  onClick={() => handleSearchSelect(r.name)}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--cg-bg-subtle)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  <span
                    className="cg-mono"
                    style={{
                      fontSize: 9,
                      color: kindColor(r.kind),
                      width: 28,
                      flexShrink: 0,
                    }}
                  >
                    {r.kind.toUpperCase()}
                  </span>
                  <span style={{ color: "var(--cg-text-primary)", flex: 1, minWidth: 0 }}>
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
                      maxWidth: 140,
                    }}
                  >
                    {r.path}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Index status */}
      <div
        ref={indexRef}
        style={{ position: "relative", flexShrink: 0 }}
      >
        <button
          className="flex items-center"
          onClick={() => setIndexPopoverOpen((v) => !v)}
          style={{
            gap: 5,
            height: 26,
            padding: "0 8px",
            background: "transparent",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
            color: "var(--cg-text-muted)",
            fontSize: 10,
            fontFamily: "inherit",
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: indexColor[indexStatus],
            }}
          />
          {indexStatus === "indexing" && <Spinner size={10} />}
          <span
            className="cg-mono"
            style={{
              color: indexColor[indexStatus],
              fontSize: 10,
            }}
          >
            {indexLabel[indexStatus]}
          </span>
        </button>
        {indexPopoverOpen && (
          <div
            style={{
              position: "absolute",
              top: "100%",
              left: 0,
              marginTop: 4,
              padding: "8px 10px",
              background: "var(--cg-bg-elevated)",
              border: "1px solid var(--cg-border)",
              borderRadius: 4,
              boxShadow: "0 4px 12px -4px rgba(0,0,0,0.25)",
              zIndex: 50,
              whiteSpace: "nowrap",
              fontSize: 11,
              color: "var(--cg-text-secondary)",
            }}
          >
            {indexStatus === "indexed" && "Repository indexed. All symbols available."}
            {indexStatus === "indexing" && "Indexing in progress…"}
            {indexStatus === "failed" && "Indexing failed. Check the log for details."}
            {indexStatus === "not-indexed" && "Run codegraph index to index this repository."}
          </div>
        )}
      </div>

      <div style={{ flex: 1 }} />

      {/* Library button */}
      {onOpenLibrary && (
        <button
          onClick={onOpenLibrary}
          style={{
            height: 26,
            padding: "0 8px",
            background: "transparent",
            border: "none",
            borderRadius: 4,
            color: "var(--cg-text-muted)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 4,
            fontSize: 10,
            fontFamily: "inherit",
          }}
        >
          <IconMenu size={11} />
          <span>Library</span>
        </button>
      )}

      {/* Theme toggle */}
      <button
        className="flex items-center"
        onClick={() => setTheme(nextTheme[theme])}
        style={{
          width: 26,
          height: 26,
          borderRadius: 4,
          border: "none",
          background: "transparent",
          color: "var(--cg-text-muted)",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
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

function kindColor(kind: string) {
  if (kind === "fn" || kind === "FUNC") return "var(--cg-accent)";
  if (kind === "class" || kind === "CLASS") return "var(--cg-success)";
  if (kind === "hook") return "#A78BFA";
  if (kind === "method" || kind === "METH") return "#A78BFA";
  if (kind === "comp") return "var(--cg-text-secondary)";
  if (kind === "type") return "var(--cg-warning)";
  return "var(--cg-text-secondary)";
}
