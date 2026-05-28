import { useState, useRef, useEffect, useCallback } from "react";
import {
  IconLogo,
  IconRepo,
  IconBranch,
  IconCommit,
  IconSearch,
  IconCommand,
  IconSun,
  IconMoon,
  IconMonitor,
  IconMenu,
  IconClose,
  IconWarning,
  IconRefresh,
  IconSettings,
  IconHelp,
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

/* ─── Hook: close on outside click ─── */
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

/* ─── Topbar root ─── */
export function Topbar({
  theme,
  setTheme,
  onOpenLibrary,
  indexStatus = "indexed",
}: {
  theme: Theme;
  setTheme: (t: Theme) => void;
  onOpenLibrary?: () => void;
  indexStatus?: IndexStatus;
}) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [indexPopoverOpen, setIndexPopoverOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  function openSearch() {
    setSearchOpen(true);
    setCommandOpen(false);
    setMenuOpen(false);
  }
  function openCommand() {
    setCommandOpen(true);
    setSearchOpen(false);
    setMenuOpen(false);
  }

  return (
    <div
      style={{
        height: 36,
        flex: "0 0 36px",
        display: "flex",
        alignItems: "center",
        padding: "0 8px",
        gap: 0,
        borderBottom: "1px solid var(--cg-border)",
        background: "var(--cg-bg-panel)",
        userSelect: "none",
        position: "relative",
        zIndex: 20,
        overflow: "visible",
      }}
    >
      {/* Left: project context */}
      <LeftSection
        indexStatus={indexStatus}
        indexPopoverOpen={indexPopoverOpen}
        setIndexPopoverOpen={(v) => {
          setIndexPopoverOpen(v);
          if (v) { setMenuOpen(false); setSearchOpen(false); setCommandOpen(false); }
        }}
      />

      <div style={{ flex: 1 }} />

      {/* Right: actions */}
      <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
        <SearchInput
          open={searchOpen}
          onOpen={openSearch}
          onClose={() => setSearchOpen(false)}
        />
        <div style={{ width: 4 }} />
        <CommandInput
          open={commandOpen}
          onOpen={openCommand}
          onClose={() => setCommandOpen(false)}
        />
        <Divider />
        <ThemeSwitcher theme={theme} setTheme={setTheme} />
        <Divider />
        <MenuButton
          open={menuOpen}
          setOpen={(v) => {
            setMenuOpen(v);
            if (v) { setSearchOpen(false); setCommandOpen(false); setIndexPopoverOpen(false); }
          }}
          onOpenLibrary={onOpenLibrary}
        />
      </div>
    </div>
  );
}

/* ─── Left section ─── */
function LeftSection({
  indexStatus,
  indexPopoverOpen,
  setIndexPopoverOpen,
}: {
  indexStatus: IndexStatus;
  indexPopoverOpen: boolean;
  setIndexPopoverOpen: (v: boolean) => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 0, overflow: "hidden" }}>
      {/* Logo + name */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "0 6px", flexShrink: 0 }}>
        <span style={{ color: "var(--cg-accent)", display: "flex", alignItems: "center" }}>
          <IconLogo size={14} />
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "var(--cg-text-primary)",
            letterSpacing: 0.1,
            whiteSpace: "nowrap",
          }}
        >
          CodeGraph Explorer
        </span>
      </div>

      <Divider />

      {/* Repo */}
      <ContextChip icon={<IconRepo size={11} />}>
        <span style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>my-app</span>
      </ContextChip>

      <Divider />

      {/* Branch */}
      <ContextChip icon={<IconBranch size={11} />}>
        <span
          className="cg-mono"
          style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}
        >
          main
        </span>
      </ContextChip>

      <Divider />

      {/* Commit */}
      <ContextChip icon={<IconCommit size={11} />}>
        <span
          className="cg-mono"
          style={{ fontSize: 11, color: "var(--cg-text-muted)" }}
        >
          a1b2c3d
        </span>
      </ContextChip>

      <Divider />

      {/* Index status */}
      <IndexStatusChip
        status={indexStatus}
        popoverOpen={indexPopoverOpen}
        onTogglePopover={() => setIndexPopoverOpen(!indexPopoverOpen)}
        onClosePopover={() => setIndexPopoverOpen(false)}
      />
    </div>
  );
}

function ContextChip({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 5,
        padding: "0 7px",
        height: 36,
        color: "var(--cg-text-muted)",
        flexShrink: 0,
      }}
    >
      <span style={{ display: "flex", alignItems: "center" }}>{icon}</span>
      {children}
    </div>
  );
}

/* ─── Index status chip + popover ─── */
function IndexStatusChip({
  status,
  popoverOpen,
  onTogglePopover,
  onClosePopover,
}: {
  status: IndexStatus;
  popoverOpen: boolean;
  onTogglePopover: () => void;
  onClosePopover: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useClickOutside(ref, onClosePopover, popoverOpen);

  return (
    <div ref={ref} style={{ position: "relative", flexShrink: 0 }}>
      <button
        onClick={onTogglePopover}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          height: 36,
          padding: "0 8px",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          borderRadius: 0,
          fontFamily: "inherit",
        }}
      >
        <StatusDot status={status} />
        <StatusLabel status={status} />
      </button>

      {popoverOpen && (
        <IndexPopover status={status} onClose={onClosePopover} />
      )}
    </div>
  );
}

function StatusDot({ status }: { status: IndexStatus }) {
  if (status === "indexing") return <Spinner size={10} />;

  const color =
    status === "indexed"
      ? "var(--cg-success)"
      : status === "failed"
      ? "var(--cg-error)"
      : "var(--cg-text-muted)";

  return (
    <span
      style={{
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: color,
        flexShrink: 0,
        boxShadow:
          status === "indexed"
            ? "0 0 0 2px color-mix(in srgb, var(--cg-success) 20%, transparent)"
            : "none",
      }}
    />
  );
}

function StatusLabel({ status }: { status: IndexStatus }) {
  const labels: Record<IndexStatus, string> = {
    indexed: "Indexed",
    indexing: "Indexing...",
    failed: "Failed",
    "not-indexed": "Not indexed",
  };
  const colors: Record<IndexStatus, string> = {
    indexed: "var(--cg-success)",
    indexing: "var(--cg-text-secondary)",
    failed: "var(--cg-error)",
    "not-indexed": "var(--cg-text-muted)",
  };
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 500,
        color: colors[status],
        whiteSpace: "nowrap",
      }}
    >
      {labels[status]}
    </span>
  );
}

function IndexPopover({
  status,
  onClose,
}: {
  status: IndexStatus;
  onClose: () => void;
}) {
  return (
    <div
      style={{
        position: "absolute",
        top: "calc(100% + 6px)",
        left: 0,
        width: 264,
        background: "var(--cg-bg-elevated)",
        border: "1px solid var(--cg-border)",
        borderRadius: 6,
        boxShadow: "0 8px 24px -8px rgba(0,0,0,0.3)",
        zIndex: 100,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "9px 12px 8px",
          borderBottom: "1px solid var(--cg-border)",
        }}
      >
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "var(--cg-text-primary)",
            flex: 1,
          }}
        >
          Index Status
        </span>
        <StatusDot status={status} />
        <StatusLabel status={status} />
      </div>

      {/* Body */}
      <div style={{ padding: "10px 12px 12px", display: "flex", flexDirection: "column", gap: 10 }}>
        {status === "indexed" && <IndexedBody onClose={onClose} />}
        {status === "indexing" && <IndexingBody />}
        {status === "failed" && <FailedBody onClose={onClose} />}
        {status === "not-indexed" && <NotIndexedBody onClose={onClose} />}
      </div>
    </div>
  );
}

function IndexedBody({ onClose }: { onClose: () => void }) {
  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <PopoverRow label="Completed" value="2026-05-27 10:30:42" mono />
        <PopoverRow label="Files" value="128" mono />
        <PopoverRow label="Symbols" value="1,432" mono />
        <PopoverRow label="Edges" value="3,891" mono />
        <PopoverRow label="Failed" value="2" mono tone="error" />
        <PopoverRow label="Low conf" value="47 · 1.2%" mono tone="warn" />
      </div>
      <PopoverBtn icon={<IconRefresh size={10} />} onClick={onClose}>
        Re-index
      </PopoverBtn>
    </>
  );
}

function IndexingBody() {
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
        <Spinner size={11} />
        <span style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>
          Scanning files...
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <PopoverRow label="Files" value="48 / 128" mono />
        <PopoverRow label="Symbols" value="320" mono />
        <PopoverRow label="Edges" value="840" mono />
      </div>
      {/* Progress bar */}
      <div
        style={{
          height: 2,
          background: "var(--cg-bg-subtle)",
          borderRadius: 1,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: "38%",
            background: "var(--cg-accent)",
            borderRadius: 1,
            transition: "width 400ms ease",
          }}
        />
      </div>
    </>
  );
}

function FailedBody({ onClose }: { onClose: () => void }) {
  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <div style={{ fontSize: 11, color: "var(--cg-text-secondary)", lineHeight: 1.5 }}>
          Indexing failed. Parser error in{" "}
          <span className="cg-mono" style={{ color: "var(--cg-text-primary)", fontSize: 10 }}>
            src/auth.py:312
          </span>
          .
        </div>
        <div
          className="cg-mono"
          style={{
            fontSize: 10,
            color: "var(--cg-text-muted)",
            background: "var(--cg-bg-subtle)",
            border: "1px solid var(--cg-border)",
            borderRadius: 3,
            padding: "4px 7px",
          }}
        >
          PARSE_ERROR · unexpected token
        </div>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <PopoverBtn icon={<IconRefresh size={10} />} onClick={onClose}>
          Retry index
        </PopoverBtn>
        <PopoverBtn onClick={onClose} muted>
          View log
        </PopoverBtn>
      </div>
    </>
  );
}

function NotIndexedBody({ onClose }: { onClose: () => void }) {
  return (
    <>
      <div style={{ fontSize: 11, color: "var(--cg-text-secondary)", lineHeight: 1.5 }}>
        No index found for this repository.
        <br />
        Run{" "}
        <code
          className="cg-mono"
          style={{
            fontSize: 10,
            color: "var(--cg-accent)",
            background: "var(--cg-accent-alpha)",
            padding: "0 4px",
            borderRadius: 2,
          }}
        >
          codegraph index
        </code>{" "}
        to start.
      </div>
      <PopoverBtn icon={<IconRefresh size={10} />} onClick={onClose}>
        Start indexing
      </PopoverBtn>
    </>
  );
}

function PopoverBtn({
  children,
  icon,
  onClick,
  muted,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
  onClick?: () => void;
  muted?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 5,
        height: 24,
        padding: "0 8px",
        background: "transparent",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        color: muted ? "var(--cg-text-muted)" : "var(--cg-text-secondary)",
        fontSize: 11,
        cursor: "pointer",
        fontFamily: "inherit",
        flexShrink: 0,
      }}
    >
      {icon && (
        <span style={{ display: "flex", alignItems: "center" }}>{icon}</span>
      )}
      {children}
    </button>
  );
}

function PopoverRow({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: "error" | "warn";
}) {
  const valueColor =
    tone === "error"
      ? "var(--cg-error)"
      : tone === "warn"
      ? "var(--cg-warning)"
      : "var(--cg-text-primary)";
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
      <span
        style={{
          fontSize: 10,
          color: "var(--cg-text-secondary)",
          width: 56,
          flexShrink: 0,
        }}
      >
        {label}
      </span>
      <span
        className={mono ? "cg-mono" : ""}
        style={{ fontSize: 10, color: valueColor }}
      >
        {value}
      </span>
    </div>
  );
}

/* ─── Search input ─── */
const SEARCH_SHORTCUT = "⌘K";

type SearchState = "idle" | "results" | "empty" | "error";

function SearchInput({
  open,
  onOpen,
  onClose,
}: {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [searchState, setSearchState] = useState<SearchState>("idle");
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useClickOutside(containerRef, () => { onClose(); setQuery(""); setSearchState("idle"); }, open);

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
    } else {
      setQuery("");
      setSearchState("idle");
    }
  }, [open]);

  function handleQueryChange(q: string) {
    setQuery(q);
    if (!q.trim()) { setSearchState("idle"); return; }
    const hits = MOCK_SYMBOLS.filter(
      (s) =>
        s.name.toLowerCase().includes(q.toLowerCase()) ||
        s.path.toLowerCase().includes(q.toLowerCase())
    );
    setSearchState(hits.length > 0 ? "results" : "empty");
  }

  const results = query.trim()
    ? MOCK_SYMBOLS.filter(
        (s) =>
          s.name.toLowerCase().includes(query.toLowerCase()) ||
          s.path.toLowerCase().includes(query.toLowerCase())
      )
    : MOCK_SYMBOLS;

  const showDropdown = open && (query.trim() ? true : searchState === "idle");

  if (!open) {
    return (
      <ChipBtn onClick={onOpen} title={`Search symbols ${SEARCH_SHORTCUT}`}>
        <IconSearch size={12} />
        <span style={{ fontSize: 11 }}>Search</span>
        <KbdHint>{SEARCH_SHORTCUT}</KbdHint>
      </ChipBtn>
    );
  }

  return (
    <div ref={containerRef} style={{ position: "relative" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          height: 26,
          width: 240,
          padding: "0 8px",
          border: "1px solid var(--cg-border)",
          borderRadius: 4,
          background: "var(--cg-bg-subtle)",
        }}
      >
        <span
          style={{
            color: "var(--cg-text-muted)",
            display: "flex",
            alignItems: "center",
            flexShrink: 0,
          }}
        >
          <IconSearch size={12} />
        </span>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => handleQueryChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") { onClose(); setQuery(""); setSearchState("idle"); }
          }}
          placeholder="Search symbols..."
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            fontSize: 12,
            color: "var(--cg-text-primary)",
            fontFamily: "inherit",
            minWidth: 0,
          }}
        />
        {query && (
          <button
            onClick={() => { setQuery(""); setSearchState("idle"); }}
            style={{
              display: "flex",
              alignItems: "center",
              background: "transparent",
              border: "none",
              padding: 0,
              cursor: "pointer",
              color: "var(--cg-text-muted)",
            }}
          >
            <IconClose size={10} />
          </button>
        )}
      </div>

      {/* Results dropdown */}
      {showDropdown && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            width: 300,
            maxHeight: 280,
            overflowY: "auto",
            background: "var(--cg-bg-elevated)",
            border: "1px solid var(--cg-border)",
            borderRadius: 6,
            boxShadow: "0 8px 24px -8px rgba(0,0,0,0.3)",
            zIndex: 100,
          }}
          className="cg-scroll"
        >
          {searchState === "empty" ? (
            <div
              style={{
                padding: "10px 12px",
                fontSize: 11,
                color: "var(--cg-text-muted)",
              }}
            >
              No symbols found for "{query}"
            </div>
          ) : searchState === "error" ? (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "10px 12px",
              }}
            >
              <span style={{ color: "var(--cg-error)", display: "flex", alignItems: "center" }}>
                <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
                  <circle cx="8" cy="8" r="5.5" /><path d="M8 4.5v4M8 11.2v.1" />
                </svg>
              </span>
              <span style={{ fontSize: 11, color: "var(--cg-text-secondary)", flex: 1 }}>
                Search failed.
              </span>
              <button
                onClick={() => setSearchState("results")}
                style={{
                  height: 20,
                  padding: "0 7px",
                  background: "transparent",
                  border: "1px solid var(--cg-border)",
                  borderRadius: 3,
                  fontSize: 10,
                  color: "var(--cg-text-secondary)",
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                Retry
              </button>
            </div>
          ) : (
            <ul style={{ margin: 0, padding: "4px 0", listStyle: "none" }}>
              {results.map((s, i) => (
                <SearchResultItem key={i} symbol={s} query={query} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

const KIND_COLOR: Record<string, string> = {
  fn: "var(--cg-accent)",
  class: "var(--cg-success)",
  hook: "var(--cg-warning)",
  comp: "var(--cg-text-secondary)",
  type: "var(--cg-text-muted)",
};

function SearchResultItem({
  symbol,
  query,
}: {
  symbol: (typeof MOCK_SYMBOLS)[number];
  query: string;
}) {
  const [hovered, setHovered] = useState(false);

  return (
    <li
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 12px",
        cursor: "pointer",
        background: hovered ? "var(--cg-bg-subtle)" : "transparent",
      }}
    >
      <span
        className="cg-mono"
        style={{
          fontSize: 9,
          fontWeight: 500,
          color: KIND_COLOR[symbol.kind] ?? "var(--cg-text-muted)",
          background: "var(--cg-bg-subtle)",
          padding: "1px 4px",
          borderRadius: 2,
          flexShrink: 0,
          minWidth: 28,
          textAlign: "center",
        }}
      >
        {symbol.kind}
      </span>
      <span
        className="cg-mono"
        style={{
          fontSize: 11,
          fontWeight: 500,
          color: "var(--cg-text-primary)",
          flex: 1,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {highlight(symbol.name, query)}
      </span>
      <span
        className="cg-mono"
        style={{
          fontSize: 10,
          color: "var(--cg-text-muted)",
          flexShrink: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          maxWidth: 120,
        }}
      >
        {symbol.path}
      </span>
    </li>
  );
}

function highlight(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark
        style={{
          background: "color-mix(in srgb, var(--cg-accent) 25%, transparent)",
          color: "inherit",
          borderRadius: 1,
        }}
      >
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  );
}

/* ─── Command / Task input ─── */
const CMD_SHORTCUT = "⌘P";

function CommandInput({
  open,
  onOpen,
  onClose,
}: {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useClickOutside(containerRef, () => { onClose(); setText(""); }, open);

  useEffect(() => {
    if (open) inputRef.current?.focus();
    else setText("");
  }, [open]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") { onClose(); setText(""); }
    if (e.key === "Enter" && text.trim()) {
      // Submit task: in a real app, would trigger context pack generation
      onClose();
      setText("");
    }
  }

  if (!open) {
    return (
      <ChipBtn onClick={onOpen} title={`Run task ${CMD_SHORTCUT}`}>
        <IconCommand size={12} />
        <span style={{ fontSize: 11 }}>Task</span>
        <KbdHint>{CMD_SHORTCUT}</KbdHint>
      </ChipBtn>
    );
  }

  return (
    <div ref={containerRef} style={{ position: "relative" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          height: 26,
          width: 260,
          padding: "0 8px",
          border: "1px solid var(--cg-border)",
          borderRadius: 4,
          background: "var(--cg-bg-subtle)",
        }}
      >
        <span
          style={{
            color: "var(--cg-text-muted)",
            display: "flex",
            alignItems: "center",
            flexShrink: 0,
          }}
        >
          <IconCommand size={12} />
        </span>
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="e.g. Add MFA to login flow"
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            fontSize: 12,
            color: "var(--cg-text-primary)",
            fontFamily: "inherit",
            minWidth: 0,
          }}
        />
        {text && (
          <KbdHint muted={false} style={{ flexShrink: 0 }}>↵</KbdHint>
        )}
      </div>
    </div>
  );
}

/* ─── Theme switcher ─── */
function ThemeSwitcher({
  theme,
  setTheme,
}: {
  theme: Theme;
  setTheme: (t: Theme) => void;
}) {
  const opts: { value: Theme; icon: React.ReactNode; label: string }[] = [
    { value: "system", icon: <IconMonitor size={11} />, label: "System" },
    { value: "light", icon: <IconSun size={11} />, label: "Light" },
    { value: "dark", icon: <IconMoon size={11} />, label: "Dark" },
  ];

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        background: "var(--cg-bg-subtle)",
        border: "1px solid var(--cg-border)",
        borderRadius: 5,
        padding: 2,
        gap: 1,
        margin: "0 4px",
      }}
    >
      {opts.map((o) => {
        const active = theme === o.value;
        return (
          <button
            key={o.value}
            onClick={() => setTheme(o.value)}
            title={o.label}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              height: 22,
              padding: "0 7px",
              borderRadius: 3,
              border: "none",
              cursor: "pointer",
              background: active
                ? "var(--cg-bg-panel)"
                : "transparent",
              color: active
                ? "var(--cg-text-primary)"
                : "var(--cg-text-muted)",
              fontFamily: "inherit",
              fontSize: 10,
              fontWeight: active ? 500 : 400,
              transition: "background 80ms ease, color 80ms ease",
              boxShadow: active
                ? "0 1px 2px rgba(0,0,0,0.12)"
                : "none",
            }}
          >
            <span style={{ display: "flex", alignItems: "center" }}>
              {o.icon}
            </span>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/* ─── Menu button + dropdown ─── */
function MenuButton({
  open,
  setOpen,
  onOpenLibrary,
}: {
  open: boolean;
  setOpen: (v: boolean) => void;
  onOpenLibrary?: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useClickOutside(ref, () => setOpen(false), open);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <GhostBtn
        active={open}
        onClick={() => setOpen(!open)}
        aria-label="Menu"
      >
        <IconMenu size={13} />
      </GhostBtn>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            width: 180,
            background: "var(--cg-bg-elevated)",
            border: "1px solid var(--cg-border)",
            borderRadius: 6,
            boxShadow: "0 8px 24px -8px rgba(0,0,0,0.3)",
            zIndex: 100,
            padding: "4px 0",
          }}
        >
          <MenuItem
            icon={<IconSettings size={12} />}
            label="Settings"
            hint="⌘,"
            onClick={() => setOpen(false)}
          />
          <MenuItem
            icon={<IconHelp size={12} />}
            label="Export"
            onClick={() => setOpen(false)}
          />
          <MenuItem
            icon={<IconHelp size={12} />}
            label="Help"
            onClick={() => setOpen(false)}
          />
          <MenuDivider />
          <MenuItem
            icon={<IconMenu size={12} />}
            label="Component Library"
            onClick={() => {
              setOpen(false);
              onOpenLibrary?.();
            }}
          />
        </div>
      )}
    </div>
  );
}

function MenuItem({
  icon,
  label,
  hint,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  hint?: string;
  onClick?: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        width: "100%",
        height: 30,
        padding: "0 10px",
        background: hovered ? "var(--cg-bg-subtle)" : "transparent",
        border: "none",
        cursor: "pointer",
        color: "var(--cg-text-secondary)",
        fontSize: 11,
        fontFamily: "inherit",
        textAlign: "left",
      }}
    >
      <span
        style={{
          color: "var(--cg-text-muted)",
          display: "flex",
          alignItems: "center",
          flexShrink: 0,
        }}
      >
        {icon}
      </span>
      <span style={{ flex: 1 }}>{label}</span>
      {hint && (
        <span
          className="cg-mono"
          style={{ fontSize: 10, color: "var(--cg-text-muted)" }}
        >
          {hint}
        </span>
      )}
    </button>
  );
}

function MenuDivider() {
  return (
    <div
      style={{
        height: 1,
        background: "var(--cg-border)",
        margin: "4px 0",
      }}
    />
  );
}

/* ─── Shared primitives ─── */
function Divider() {
  return (
    <div
      style={{
        width: 1,
        height: 14,
        background: "var(--cg-border)",
        flexShrink: 0,
        margin: "0 4px",
      }}
    />
  );
}

function ChipBtn({
  children,
  onClick,
  title,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  title?: string;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      title={title}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 5,
        height: 26,
        padding: "0 8px",
        background: hovered ? "var(--cg-bg-subtle)" : "transparent",
        border: "none",
        borderRadius: 4,
        color: "var(--cg-text-muted)",
        cursor: "pointer",
        fontFamily: "inherit",
        transition: "background 80ms ease",
      }}
    >
      {children}
    </button>
  );
}

function GhostBtn({
  children,
  onClick,
  active,
  "aria-label": ariaLabel,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  active?: boolean;
  "aria-label"?: string;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      aria-label={ariaLabel}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: 28,
        height: 28,
        background: active || hovered ? "var(--cg-bg-subtle)" : "transparent",
        border: "none",
        borderRadius: 4,
        color: active ? "var(--cg-text-primary)" : "var(--cg-text-muted)",
        cursor: "pointer",
        transition: "background 80ms ease",
      }}
    >
      {children}
    </button>
  );
}

function KbdHint({
  children,
  muted = true,
  style: extraStyle,
}: {
  children: React.ReactNode;
  muted?: boolean;
  style?: React.CSSProperties;
}) {
  return (
    <span
      className="cg-mono"
      style={{
        fontSize: 9,
        color: muted ? "var(--cg-text-muted)" : "var(--cg-text-secondary)",
        background: "var(--cg-bg-subtle)",
        border: "1px solid var(--cg-border)",
        borderRadius: 3,
        padding: "1px 4px",
        lineHeight: 1.4,
        ...extraStyle,
      }}
    >
      {children}
    </span>
  );
}
