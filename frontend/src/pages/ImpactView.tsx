import { useState, useEffect, useRef } from "react";
import { api, type ImpactResponse } from "../api";
import { Spinner } from "../app/components/Spinner";

interface Props {
  onSelectSymbol: (symbolId: string) => void;
  initialSymbolId?: string;
  onSelectFile?: (filePath: string) => void;
}

export default function ImpactView({ onSelectSymbol, initialSymbolId, onSelectFile }: Props) {
  const [symbolId, setSymbolId] = useState("");
  const [depth, setDepth] = useState(2);
  const [includeTests, setIncludeTests] = useState(true);
  const [includePossible, setIncludePossible] = useState(true);
  const [result, setResult] = useState<ImpactResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasAutoAnalyzed = useRef(false);

  const depthRef = useRef(depth);
  depthRef.current = depth;

  // Auto-analyze when initialSymbolId is provided
  useEffect(() => {
    if (initialSymbolId && !hasAutoAnalyzed.current) {
      hasAutoAnalyzed.current = true;
      setSymbolId(initialSymbolId);
      // Use setTimeout to avoid setState during render
      setTimeout(() => {
        analyzeWithId(initialSymbolId, depthRef.current);
      }, 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSymbolId]);

  async function analyze() {
    if (!symbolId.trim()) return;
    analyzeWithId(symbolId, depth);
  }

  async function analyzeWithId(id: string, d: number) {
    setLoading(true);
    setError(null);
    try {
      const r = await api.symbols.impact(id, d);
      setResult(r);
    } catch {
      setError("Impact analysis failed.");
    } finally {
      setLoading(false);
    }
  }

  const confirmed = result?.affected_symbols.filter((s) => s.confidence >= 0.6 && !s.impact_type?.toLowerCase().includes("test")) ?? [];
  const possible = includePossible ? (result?.affected_symbols.filter((s) => s.confidence < 0.6 && s.confidence >= 0.3 && !s.impact_type?.toLowerCase().includes("test")) ?? []) : [];
  const relatedTests = includeTests ? (result?.affected_symbols.filter((s) => s.impact_type?.toLowerCase().includes("test")) ?? []) : [];
  const unresolved = includePossible ? (result?.affected_symbols.filter((s) => s.confidence < 0.3) ?? []) : [];

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Input bar */}
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid var(--cg-border)",
        background: "var(--cg-bg-panel)", display: "flex", flexDirection: "column", gap: 8,
      }}>
        <div className="flex items-center" style={{ gap: 8 }}>
          <input
            value={symbolId}
            onChange={(e) => setSymbolId(e.target.value)}
            placeholder="Enter symbol_id (e.g. src/auth.py::login)"
            onKeyDown={(e) => e.key === "Enter" && analyze()}
            style={{
              flex: 1, minWidth: 0, height: 30, padding: "0 10px",
              background: "var(--cg-bg-subtle)", border: "1px solid var(--cg-border)", borderRadius: 4,
              color: "var(--cg-text-primary)", fontSize: 12, fontFamily: "'JetBrains Mono', monospace",
              outline: "none",
            }}
          />
          <button
            onClick={analyze}
            disabled={loading}
            style={{
              height: 30, padding: "0 14px", border: "none", borderRadius: 4, cursor: "pointer",
              background: "var(--cg-accent)", color: "#fff", fontSize: 11, fontFamily: "inherit",
              opacity: loading ? 0.6 : 1,
            }}
          >
            Analyze
          </button>
        </div>
        <div className="flex items-center" style={{ gap: 12, flexWrap: "wrap" }}>
          <label style={{ fontSize: 10, color: "var(--cg-text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
            Depth
            <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}
              style={{
                height: 22, padding: "0 4px", fontSize: 10, fontFamily: "inherit",
                background: "var(--cg-bg-subtle)", border: "1px solid var(--cg-border)", borderRadius: 3, color: "var(--cg-text-primary)",
              }}>
              {[1, 2, 3, 4, 5].map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <label style={{ fontSize: 10, color: "var(--cg-text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
            <input type="checkbox" checked={includeTests} onChange={(e) => setIncludeTests(e.target.checked)} />
            Tests
          </label>
          <label style={{ fontSize: 10, color: "var(--cg-text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
            <input type="checkbox" checked={includePossible} onChange={(e) => setIncludePossible(e.target.checked)} />
            Possible
          </label>
        </div>
      </div>

      {/* Results */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {loading && (
          <div className="flex items-center" style={{ padding: 24, gap: 10, color: "var(--cg-text-muted)" }}>
            <Spinner size={16} />
            <span style={{ fontSize: 12 }}>Analyzing impact...</span>
          </div>
        )}
        {error && <div style={{ padding: 16, color: "var(--cg-error)", fontSize: 12 }}>{error}</div>}

        {result && (
          <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 14 }}>
            {/* Target */}
            <Section title="Target">
              <div className="cg-mono" style={{ fontSize: 12, color: "var(--cg-text-primary)" }}>
                {result.changed_symbol}
              </div>
              <div style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                Type: {result.changed_symbol_type || "unknown"}
              </div>
            </Section>

            {/* Risk */}
            {result.risk && (
              <Section title="Risk">
                <RiskBadge level={result.risk.level} />
                {result.risk.reasons.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 4 }}>
                    {result.risk.reasons.map((r, i) => (
                      <div key={i} className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>
                        {r}
                      </div>
                    ))}
                  </div>
                )}
              </Section>
            )}

            {/* Confirmed Impact */}
            <Section title={`Confirmed Impact (${confirmed.length})`}>
              {confirmed.length === 0 ? (
                <span style={{ fontSize: 11, color: "var(--cg-text-muted)" }}>None</span>
              ) : (
                confirmed.map((s) => (
                  <ImpactRow key={s.symbol_id} item={s} onClick={() => onSelectSymbol(s.symbol_id)} />
                ))
              )}
            </Section>

            {/* Possible Impact */}
            {includePossible && (
              <Section title={`Possible Impact (${possible.length})`}>
                {possible.length === 0 ? (
                  <span style={{ fontSize: 11, color: "var(--cg-text-muted)" }}>No possible impact detected.</span>
                ) : (
                  possible.map((s) => (
                    <ImpactRow key={s.symbol_id} item={s} weak onClick={() => onSelectSymbol(s.symbol_id)} />
                  ))
                )}
              </Section>
            )}

            {/* Related Tests */}
            {includeTests && relatedTests.length > 0 && (
              <Section title={`Related Tests (${relatedTests.length})`}>
                {relatedTests.map((s) => (
                  <ImpactRow key={s.symbol_id} item={s} test onClick={() => onSelectSymbol(s.symbol_id)} />
                ))}
              </Section>
            )}

            {/* Unresolved / External Calls */}
            {includePossible && unresolved.length > 0 && (
              <Section title={`Unresolved / External Calls (${unresolved.length})`}>
                <div style={{ marginBottom: 4 }}>
                  <span style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                    Low-confidence or unresolved connections.
                  </span>
                </div>
                {unresolved.map((s) => (
                  <ImpactRow key={s.symbol_id} item={s} unresolved onClick={() => onSelectSymbol(s.symbol_id)} />
                ))}
              </Section>
            )}

            {/* Affected Files */}
            {result.affected_files && result.affected_files.length > 0 && (
              <Section title={`Affected Files (${result.affected_files.length})`}>
                {result.affected_files.map((f, i) => (
                  <div
                    key={i}
                    onClick={() => onSelectFile?.(f.file_path)}
                    style={{
                      display: "flex", flexDirection: "column", gap: 2,
                      cursor: onSelectFile ? "pointer" : "default",
                      padding: "3px 6px", borderRadius: 3,
                    }}
                    onMouseEnter={(e) => { if (onSelectFile) e.currentTarget.style.background = "var(--cg-bg-subtle)"; }}
                    onMouseLeave={(e) => { if (onSelectFile) e.currentTarget.style.background = "transparent"; }}
                  >
                    <div className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-primary)" }}>
                      {f.file_path}
                    </div>
                    <div style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                      {f.reason} · Priority: {f.priority}
                    </div>
                  </div>
                ))}
              </Section>
            )}

            {/* No affected files */}
            {(!result.affected_files || result.affected_files.length === 0) && confirmed.length === 0 && possible.length === 0 && relatedTests.length === 0 && unresolved.length === 0 && (
              <Section title="Impact">
                <span style={{ fontSize: 11, color: "var(--cg-text-muted)" }}>
                  No affected symbols detected. The impact of this change may be limited in scope.
                </span>
              </Section>
            )}

            {/* Warnings */}
            {result.warnings && result.warnings.length > 0 && (
              <Section title={`Warnings (${result.warnings.length})`}>
                {result.warnings.map((w, i) => (
                  <div key={i} style={{
                    padding: "6px 8px", fontSize: 10, color: "var(--cg-warning)",
                    background: "color-mix(in srgb, var(--cg-warning) 8%, transparent)",
                    border: "1px solid color-mix(in srgb, var(--cg-warning) 20%, transparent)",
                    borderRadius: 4,
                  }}>
                    {w}
                  </div>
                ))}
              </Section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ width: 12, height: 1, background: "var(--cg-border)", flexShrink: 0 }} />
        <span style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-secondary)", letterSpacing: 0.5 }}>
          {title}
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingLeft: 18 }}>
        {children}
      </div>
    </div>
  );
}

function ImpactRow({ item, weak, test, unresolved, onClick }: { item: { symbol_id: string; reason: string; impact_type: string; distance: number; confidence: number }; weak?: boolean; test?: boolean; unresolved?: boolean; onClick?: () => void }) {
  const dotColor = unresolved ? "var(--cg-text-muted)" : test ? "#4ADE80" : weak ? "var(--cg-warning)" : "var(--cg-success)";
  const rowOpacity = unresolved ? 0.5 : weak ? 0.6 : test ? 0.85 : 1;
  return (
    <div
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 8, padding: "4px 6px", borderRadius: 3, cursor: onClick ? "pointer" : "default",
        opacity: rowOpacity,
      }}
      onMouseEnter={(e) => { if (onClick) e.currentTarget.style.background = "var(--cg-bg-subtle)"; }}
      onMouseLeave={(e) => { if (onClick) e.currentTarget.style.background = "transparent"; }}
    >
      <span style={{
        width: 4, height: 4, borderRadius: "50%", flexShrink: 0,
        background: dotColor,
      }} />
      <span className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-primary)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {item.symbol_id}
      </span>
      <span className="cg-mono" style={{ fontSize: 10, color: confColor(item.confidence), flexShrink: 0 }}>
        {(item.confidence * 100).toFixed(0)}%
      </span>
      <span style={{ fontSize: 9, color: "var(--cg-text-muted)", flexShrink: 0 }}>
        {item.impact_type} · d={item.distance}
      </span>
    </div>
  );
}

function RiskBadge({ level }: { level: string }) {
  const color =
    level === "critical" ? "var(--cg-error)" :
    level === "high" ? "#DC2626" :
    level === "medium" ? "var(--cg-warning)" :
    level === "low" ? "var(--cg-success)" : "var(--cg-text-muted)";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 3,
      background: `color-mix(in srgb, ${color} 14%, transparent)`,
      color, fontSize: 11, fontWeight: 500,
    }}>
      {level.toUpperCase()}
    </span>
  );
}

function confColor(c: number): string {
  if (c >= 0.85) return "var(--cg-success)";
  if (c >= 0.7) return "var(--cg-text-secondary)";
  if (c > 0) return "var(--cg-warning)";
  return "var(--cg-text-muted)";
}
