import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type DashboardStats } from "../api";

type ViewMode = "stats" | "error" | "empty" | "loading";

interface ViewState {
  mode: ViewMode;
  data: DashboardStats | null;
  error: string;
}

export default function ProjectOverview() {
  const navigate = useNavigate();
  const [state, setState] = useState<ViewState>({ mode: "loading", data: null, error: "" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setState((s) => ({ ...s, mode: "loading" }));
      try {
        const stats = await api.dashboard.stats();
        if (cancelled) return;
        if (stats.symbol_count === 0 && stats.file_count === 0) {
          setState({ mode: "empty", data: stats, error: "" });
        } else {
          setState({ mode: "stats", data: stats, error: "" });
        }
      } catch (e: unknown) {
        if (cancelled) return;
        setState({
          mode: "error",
          data: null,
          error: e instanceof Error ? e.message : "Failed to load stats",
        });
      }
    })();
    return () => { cancelled = true; };
  }, [navigate]);

  const renderContent = () => {
    switch (state.mode) {
      case "loading": return <LoadingSkeleton />;
      case "error": return <ErrorBanner message={state.error} />;
      case "empty": return <EmptyState />;
      case "stats": return <StatsDashboard data={state.data!} onNavigate={navigate} />;
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h1 style={{ fontSize: 18, fontWeight: 500, color: "var(--cg-text-primary)", margin: 0 }}>
          Project Overview
        </h1>
        <p style={{ fontSize: 12, color: "var(--cg-text-secondary)", margin: "4px 0 0" }}>
          Repository summary and code graph statistics
        </p>
      </div>
      {renderContent()}
    </div>
  );
}

/* ── States ──────────────────────────────────────────────────── */

function LoadingSkeleton() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
      {[...Array(8)].map((_, i) => (
        <div key={i} className="cg-skeleton" style={{ height: 80, borderRadius: 6, animationDelay: `${i * 0.05}s` }} />
      ))}
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      style={{
        padding: "10px 12px",
        background: "var(--cg-error-alpha)",
        border: "1px solid color-mix(in srgb, var(--cg-error) 30%, transparent)",
        borderRadius: 6,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div className="flex items-center" style={{ gap: 6, color: "var(--cg-error)", fontWeight: 500, fontSize: 12 }}>
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="8" cy="8" r="5.5" /><path d="M8 4.5v4M8 11.2v.1" />
        </svg>
        <span>Failed to load dashboard</span>
      </div>
      <p style={{ margin: 0, fontSize: 11, color: "var(--cg-text-secondary)" }}>{message}</p>
      <button
        onClick={() => window.location.reload()}
        style={{
          height: 24, padding: "0 10px", border: "1px solid var(--cg-border)",
          borderRadius: 4, background: "transparent", color: "var(--cg-text-primary)",
          fontSize: 11, cursor: "pointer", fontFamily: "inherit", alignSelf: "flex-start",
        }}
      >
        Retry
      </button>
    </div>
  );
}

function EmptyState() {
  return (
    <div
      style={{
        textAlign: "center", padding: "40px 20px",
        border: "1px dashed var(--cg-border)", borderRadius: 8,
      }}
    >
      <div style={{ fontSize: 32, color: "var(--cg-text-muted)", marginBottom: 12 }}>◉</div>
      <h2 style={{ fontSize: 14, fontWeight: 500, color: "var(--cg-text-secondary)", margin: "0 0 4px" }}>
        No Repository Indexed
      </h2>
      <p style={{ fontSize: 11, color: "var(--cg-text-muted)", margin: "0 0 16px", maxWidth: 400, marginLeft: "auto", marginRight: "auto" }}>
        Run <code className="cg-mono" style={{ background: "var(--cg-bg-subtle)", padding: "1px 5px", borderRadius: 2, fontSize: 10 }}>codegraph index</code> from the CLI to scan your codebase and build the code graph.
      </p>
      <div className="cg-mono" style={{ display: "inline-block", padding: "8px 12px", background: "var(--cg-bg-subtle)", borderRadius: 4, fontSize: 11, color: "var(--cg-text-secondary)", border: "1px solid var(--cg-border)" }}>
        $ codegraph index ./my-project
      </div>
    </div>
  );
}

/* ── Stats dashboard ─────────────────────────────────────────── */

const statCardsConfig: {
  label: string;
  key: keyof DashboardStats;
  color: string;
  format?: (v: number) => string;
}[] = [
  { label: "Files", key: "file_count", color: "var(--cg-accent)" },
  { label: "Symbols", key: "symbol_count", color: "var(--cg-success)" },
  { label: "Functions", key: "function_count", color: "var(--cg-accent)" },
  { label: "Classes", key: "class_count", color: "#A78BFA" },
  { label: "Edges", key: "edge_count", color: "var(--cg-warning)" },
  { label: "Low Conf.", key: "low_confidence_ratio", color: "var(--cg-error)", format: (v: number) => `${(v * 100).toFixed(1)}%` },
];

function StatsDashboard({ data, onNavigate }: { data: DashboardStats; onNavigate: (to: string) => void }) {
  return (
    <>
      {/* Stat cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10 }}>
        {statCardsConfig.map(({ label, key, color, format }) => {
          const value = data[key];
          const display = typeof value === "number" ? (format ? format(value) : value.toLocaleString()) : value ?? "-";
          return (
            <div
              key={key}
              style={{
                padding: "12px 14px",
                background: "var(--cg-bg-panel)",
                border: "1px solid var(--cg-border)",
                borderRadius: 6,
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <span style={{ fontSize: 10, color: "var(--cg-text-muted)", letterSpacing: 0.3 }}>{label}</span>
              <span style={{ fontSize: 22, fontWeight: 500, color }}>{display}</span>
            </div>
          );
        })}
      </div>

      {/* Meta row */}
      <div
        className="flex items-center"
        style={{
          gap: 16, padding: "10px 14px", flexWrap: "wrap",
          background: "var(--cg-bg-panel)", border: "1px solid var(--cg-border)", borderRadius: 6,
          fontSize: 11, color: "var(--cg-text-secondary)",
        }}
      >
        <div><span style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>Project:</span> {data.project_name}</div>
        <div><span style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>Root:</span> <span className="cg-mono" style={{ fontSize: 10 }}>{data.root_path}</span></div>
        {data.last_indexed_at && (
          <div><span style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>Indexed:</span> {new Date(data.last_indexed_at).toLocaleString()}</div>
        )}
        {data.commit_hash && (
          <div><span style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>Commit:</span> <span className="cg-mono" style={{ fontSize: 10 }}>{data.commit_hash.slice(0, 8)}</span></div>
        )}
      </div>

      {/* Failed files warning */}
      {data.failed_files > 0 && (
        <div
          style={{
            padding: "8px 10px",
            background: "var(--cg-warning-alpha)",
            border: "1px solid color-mix(in srgb, var(--cg-warning) 30%, transparent)",
            borderRadius: 4,
            fontSize: 11,
            color: "var(--cg-text-secondary)",
          }}
        >
          <span style={{ fontWeight: 500, color: "var(--cg-warning)" }}>{data.failed_files}</span> file(s) failed during indexing. Some symbols may be missing.
        </div>
      )}

      {/* Quick actions */}
      <div style={{ padding: "14px", background: "var(--cg-bg-panel)", border: "1px solid var(--cg-border)", borderRadius: 6 }}>
        <h3 style={{ fontSize: 11, fontWeight: 600, color: "var(--cg-text-primary)", margin: "0 0 10px", letterSpacing: 0.2 }}>Quick Actions</h3>
        <div className="flex items-center" style={{ gap: 8, flexWrap: "wrap" }}>
          <QuickBtn onClick={() => onNavigate("/search")}>Search Symbols</QuickBtn>
          <QuickBtn onClick={() => onNavigate("/graph")}>Explore Graph</QuickBtn>
          <QuickBtn onClick={() => onNavigate("/impact")}>Analyze Impact</QuickBtn>
          <QuickBtn onClick={() => onNavigate("/context")}>Generate Context Pack</QuickBtn>
        </div>
      </div>
    </>
  );
}

function QuickBtn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        height: 26, padding: "0 10px",
        background: "transparent", border: "1px solid var(--cg-border)",
        borderRadius: 4, color: "var(--cg-text-primary)", fontSize: 11,
        cursor: "pointer", fontFamily: "inherit",
        transition: "background 120ms ease, border-color 120ms ease",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--cg-bg-subtle)"; e.currentTarget.style.borderColor = "var(--cg-border-hover)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.borderColor = "var(--cg-border)"; }}
    >
      {children}
    </button>
  );
}
