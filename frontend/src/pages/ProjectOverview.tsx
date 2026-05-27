import { useEffect, useState } from "react";
import { api, type DashboardStats } from "../api";

type ViewMode = "stats" | "error" | "empty" | "loading";

interface ViewState {
  mode: ViewMode;
  data: DashboardStats | null;
  error: string;
}

export default function ProjectOverview() {
  const [state, setState] = useState<ViewState>({
    mode: "loading",
    data: null,
    error: "",
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setState((s) => ({ ...s, mode: "loading" }));
      try {
        const stats = await api.dashboard.stats();
        if (cancelled) return;
        if (
          stats.symbol_count === 0 &&
          stats.file_count === 0
        ) {
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
    return () => {
      cancelled = true;
    };
  }, []);

  const renderContent = () => {
    switch (state.mode) {
      case "loading":
        return <LoadingSkeleton />;
      case "error":
        return <ErrorBanner message={state.error} onRetry={() => setState((s) => ({ ...s, mode: "loading" }))} />;
      case "empty":
        return <EmptyState />;
      case "stats":
        return <StatsDashboard data={state.data!} />;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Project Overview</h1>
          <p className="text-gray-500 text-sm mt-1">
            Repository summary and code graph statistics
          </p>
        </div>
      </div>
      {renderContent()}
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────── */

function LoadingSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 animate-pulse">
      {[...Array(8)].map((_, i) => (
        <div key={i} className="h-28 bg-gray-200 rounded-xl" />
      ))}
    </div>
  );
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
      <div className="flex items-center gap-2 text-red-700 font-medium mb-1">
        <span className="text-lg">!</span>
        <span>Failed to load dashboard</span>
      </div>
      <p className="text-sm text-red-600 mb-3">{message}</p>
      <button
        onClick={onRetry}
        className="px-3 py-1.5 text-sm bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
      >
        Retry
      </button>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="text-center py-16 border-2 border-dashed border-gray-300 rounded-xl">
      <div className="text-5xl text-gray-300 mb-4">◉</div>
      <h2 className="text-xl font-semibold text-gray-600 mb-2">
        No Repository Indexed
      </h2>
      <p className="text-gray-500 mb-6 max-w-md mx-auto">
        Run <code className="bg-gray-100 px-2 py-0.5 rounded text-sm font-mono">codegraph index</code>
        {" "}from the CLI to scan your codebase and build the code graph.
      </p>
      <div className="text-left inline-block bg-gray-50 p-4 rounded-lg border text-sm text-gray-600 font-mono">
        $ codegraph index ./my-project
      </div>
    </div>
  );
}

/* ── Stats dashboard ──────────────────────────────────────────── */

const statCardsConfig: {
  label: string;
  key: keyof DashboardStats;
  color: string;
  format?: (v: number) => string;
}[] = [
  { label: "Files", key: "file_count", color: "bg-blue-50 text-blue-700 border-blue-200" },
  { label: "Symbols", key: "symbol_count", color: "bg-indigo-50 text-indigo-700 border-indigo-200" },
  { label: "Functions", key: "function_count", color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  { label: "Classes", key: "class_count", color: "bg-violet-50 text-violet-700 border-violet-200" },
  { label: "Edges", key: "edge_count", color: "bg-amber-50 text-amber-700 border-amber-200" },
  {
    label: "Low Conf. Ratio",
    key: "low_confidence_ratio",
    color: "bg-rose-50 text-rose-700 border-rose-200",
    format: (v: number) => `${(v * 100).toFixed(1)}%`,
  },
];

function StatsDashboard({ data }: { data: DashboardStats }) {
  return (
    <>
      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCardsConfig.map(({ label, key, color, format }) => {
          const value = data[key];
          const display =
            typeof value === "number"
              ? format
                ? format(value)
                : value.toLocaleString()
              : value ?? "-";
          return (
            <div
              key={key}
              className={`p-4 rounded-xl border ${color} flex flex-col justify-between`}
            >
              <span className="text-sm font-medium opacity-80">{label}</span>
              <span className="text-3xl font-bold mt-1">{display}</span>
            </div>
          );
        })}
      </div>

      {/* Meta row */}
      <div className="flex flex-wrap gap-4 text-sm text-gray-500 bg-white p-4 rounded-xl border">
        <div>
          <span className="font-medium text-gray-700">Project:</span>{" "}
          {data.project_name}
        </div>
        <div>
          <span className="font-medium text-gray-700">Root:</span>{" "}
          <code className="text-xs">{data.root_path}</code>
        </div>
        {data.last_indexed_at && (
          <div>
            <span className="font-medium text-gray-700">Indexed:</span>{" "}
            {new Date(data.last_indexed_at).toLocaleString()}
          </div>
        )}
        {data.commit_hash && (
          <div>
            <span className="font-medium text-gray-700">Commit:</span>{" "}
            <code className="text-xs">{data.commit_hash.slice(0, 8)}</code>
          </div>
        )}
      </div>

      {/* Failed files warning */}
      {data.failed_files > 0 && (
        <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800">
          <strong>{data.failed_files}</strong> file(s) failed during indexing.
          Some symbols may be missing from the graph.
        </div>
      )}

      {/* Quick actions */}
      <div className="bg-white p-4 rounded-xl border">
        <h2 className="font-semibold text-gray-800 mb-3">Quick Actions</h2>
        <div className="flex flex-wrap gap-3">
          <QuickActionLink to="/search" label="Search Symbols" />
          <QuickActionLink to="/graph" label="Explore Graph" />
          <QuickActionLink to="/impact" label="Analyze Impact" />
          <QuickActionLink to="/context" label="Generate Context Pack" />
        </div>
      </div>
    </>
  );
}

function QuickActionLink({ to, label }: { to: string; label: string }) {
  return (
    <a
      href={to}
      className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-blue-50 hover:text-blue-700 hover:border-blue-200 border border-transparent transition-colors"
    >
      {label}
    </a>
  );
}
