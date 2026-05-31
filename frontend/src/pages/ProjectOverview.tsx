import { useEffect, useState } from "react";
import { api, type OverviewResponse, type DashboardStats } from "../api";
import { Spinner } from "../app/components/Spinner";

interface Props {
  onSelectFile: (filePath: string) => void;
}

export default function ProjectOverview({ onSelectFile }: Props) {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [s, ov] = await Promise.all([api.dashboard.stats(), api.graph.overview()]);
        setStats(s);
        setOverview(ov);
      } catch {
        setError("Failed to load project overview.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center" style={{ height: "100%", gap: 10, color: "var(--cg-text-muted)" }}>
        <Spinner size={18} />
        <span style={{ fontSize: 12 }}>Loading project overview...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center" style={{ height: "100%", gap: 8, color: "var(--cg-text-muted)" }}>
        <span style={{ fontSize: 12, color: "var(--cg-error)" }}>{error}</span>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "auto" }}>
      {/* Stats bar */}
      <div style={{
        display: "flex", gap: 16, padding: "10px 16px", flexWrap: "wrap",
        borderBottom: "1px solid var(--cg-border)", background: "var(--cg-bg-panel)",
      }}>
        <Stat label="Files" value={stats?.file_count ?? overview?.nodes.length ?? 0} />
        <Stat label="Symbols" value={stats?.symbol_count ?? 0} />
        <Stat label="Functions" value={stats?.function_count ?? 0} />
        <Stat label="Classes" value={stats?.class_count ?? 0} />
        <Stat label="Edges" value={stats?.edge_count ?? 0} />
        <Stat label="Low-conf ratio" value={`${((stats?.low_confidence_ratio ?? 0) * 100).toFixed(1)}%`} />
      </div>

      {/* File listing */}
      <div style={{ flex: 1, overflow: "auto", padding: "8px 0" }}>
        <div style={{ padding: "0 16px 8px", fontSize: 10, color: "var(--cg-text-muted)", letterSpacing: 0.5 }}>
          FILES ({overview?.nodes.length ?? 0})
        </div>
        {overview?.nodes.map((n) => (
          <div
            key={n.id}
            className="flex items-center"
            style={{
              gap: 10, padding: "6px 16px", cursor: "pointer", fontSize: 12,
              borderBottom: "1px solid color-mix(in srgb, var(--cg-border) 50%, transparent)",
            }}
            onClick={() => onSelectFile(n.id)}
            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--cg-bg-subtle)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          >
            <span style={{ color: "var(--cg-text-muted)", width: 18, textAlign: "right", fontSize: 10 }}>
              {n.symbol_count}
            </span>
            <span className="cg-mono" style={{ color: "var(--cg-text-primary)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {n.path}
            </span>
            <span style={{
              fontSize: 9, color: "var(--cg-text-muted)", flexShrink: 0,
              padding: "1px 5px", borderRadius: 3, background: "var(--cg-bg-subtle)",
            }}>
              {n.module}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
      <span className="cg-mono" style={{ fontSize: 12, fontWeight: 600, color: "var(--cg-text-primary)" }}>
        {value}
      </span>
      <span style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>{label}</span>
    </div>
  );
}
