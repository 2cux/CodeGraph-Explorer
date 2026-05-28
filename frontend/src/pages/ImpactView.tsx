import { useState } from "react";
import { api, type ImpactResponse } from "../api";
import { Spinner } from "../components/Spinner";
import { IconWarning } from "../components/icons";

const RISK_COLORS: Record<string, string> = {
  critical: "var(--cg-error)",
  high: "var(--cg-warning)",
  medium: "var(--cg-accent)",
  low: "var(--cg-success)",
  unknown: "var(--cg-text-muted)",
};

const RISK_BG: Record<string, string> = {
  critical: "var(--cg-error-alpha)",
  high: "var(--cg-warning-alpha)",
  medium: "var(--cg-accent-alpha)",
  low: "var(--cg-success-alpha)",
  unknown: "color-mix(in srgb, var(--cg-text-muted) 14%, transparent)",
};

const IMPACT_TYPE_COLORS: Record<string, string> = {
  direct_definition: "var(--cg-accent)",
  upstream_caller: "var(--cg-warning)",
  downstream_call: "var(--cg-success)",
  test_coverage: "#A78BFA",
};

const IMPACT_TYPE_BG: Record<string, string> = {
  direct_definition: "var(--cg-accent-alpha)",
  upstream_caller: "var(--cg-warning-alpha)",
  downstream_call: "var(--cg-success-alpha)",
  test_coverage: "color-mix(in srgb, #A78BFA 14%, transparent)",
};

const PRIORITY_COLORS: Record<string, string> = {
  high: "var(--cg-error)",
  medium: "var(--cg-warning)",
  low: "var(--cg-text-secondary)",
};

const PRIORITY_BG: Record<string, string> = {
  high: "var(--cg-error-alpha)",
  medium: "var(--cg-warning-alpha)",
  low: "color-mix(in srgb, var(--cg-text-secondary) 14%, transparent)",
};

export default function ImpactView() {
  const [symbolId, setSymbolId] = useState("");
  const [depth, setDepth] = useState(2);
  const [result, setResult] = useState<ImpactResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function analyzeImpact() {
    if (!symbolId.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await api.symbols.impact(symbolId, depth);
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 18, fontWeight: 500, color: "var(--cg-text-primary)", margin: 0 }}>
          Impact View
        </h1>
        <p style={{ fontSize: 12, color: "var(--cg-text-secondary)", margin: "4px 0 0" }}>
          Analyze what is affected when modifying a code symbol.
        </p>
      </div>

      {/* Search form */}
      <div className="flex items-end" style={{ gap: 8 }}>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 10, color: "var(--cg-text-muted)", marginBottom: 4, display: "block" }}>
            Symbol ID
          </label>
          <input
            type="text"
            value={symbolId}
            onChange={(e) => setSymbolId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && analyzeImpact()}
            placeholder="e.g. src/app/api/auth.py::login"
            style={{
              width: "100%", height: 30, padding: "0 8px",
              border: "1px solid var(--cg-border)", borderRadius: 4,
              background: "var(--cg-bg-panel)", color: "var(--cg-text-primary)",
              fontSize: 12, fontFamily: "inherit", outline: "none",
            }}
            onFocus={(e) => e.currentTarget.style.borderColor = "var(--cg-accent)"}
            onBlur={(e) => e.currentTarget.style.borderColor = "var(--cg-border)"}
          />
        </div>
        <div>
          <label style={{ fontSize: 10, color: "var(--cg-text-muted)", marginBottom: 4, display: "block" }}>
            Depth
          </label>
          <select
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            style={{
              height: 30, padding: "0 8px",
              border: "1px solid var(--cg-border)", borderRadius: 4,
              background: "var(--cg-bg-panel)", color: "var(--cg-text-primary)",
              fontSize: 11, fontFamily: "inherit", outline: "none",
            }}
          >
            {[1, 2, 3, 4, 5].map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <button
          onClick={analyzeImpact}
          disabled={loading || !symbolId.trim()}
          style={{
            height: 30, padding: "0 14px",
            background: "var(--cg-accent)", color: "#fff",
            border: "none", borderRadius: 4,
            fontSize: 11, fontWeight: 500, cursor: loading ? "default" : "pointer",
            fontFamily: "inherit", opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? "Analyzing..." : "Analyze"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          padding: "8px 10px",
          background: "var(--cg-error-alpha)",
          border: "1px solid color-mix(in srgb, var(--cg-error) 30%, transparent)",
          borderRadius: 4, fontSize: 11, color: "var(--cg-text-secondary)",
        }}>
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center" style={{ gap: 8, padding: "12px 0", fontSize: 11, color: "var(--cg-text-muted)" }}>
          <Spinner size={12} />
          <span>Loading impact analysis...</span>
        </div>
      )}

      {/* Results */}
      {result && <ImpactResult result={result} />}
    </div>
  );
}

function ImpactResult({ result }: { result: ImpactResponse }) {
  const riskColor = RISK_COLORS[result.risk?.level || "unknown"];
  const riskBg = RISK_BG[result.risk?.level || "unknown"];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Summary card */}
      <div style={{
        padding: "12px 14px",
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 6,
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}>
        <span className="cg-mono" style={{ fontSize: 13, fontWeight: 500, color: "var(--cg-text-primary)" }}>
          {result.changed_symbol}
        </span>
        {result.changed_symbol_type && (
          <span style={{ fontSize: 10, color: "var(--cg-text-muted)", background: "var(--cg-bg-subtle)", padding: "1px 5px", borderRadius: 2 }}>
            {result.changed_symbol_type}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {result.risk && (
          <span style={{
            fontSize: 10, fontWeight: 500, padding: "2px 8px",
            borderRadius: 3, color: riskColor, background: riskBg,
            letterSpacing: 0.5,
          }}>
            {result.risk.level.toUpperCase()}
          </span>
        )}
      </div>

      {/* Stats row */}
      <div style={{
        padding: "8px 12px",
        background: "var(--cg-bg-subtle)",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        fontSize: 11,
        color: "var(--cg-text-secondary)",
      }}>
        {result.affected_symbols.length} affected symbols · {result.affected_files.length} affected files
      </div>

      {/* Risk factors */}
      {result.risk && result.risk.reasons.length > 0 && (
        <Section title="Risk Factors">
          {result.risk.reasons.map((reason, i) => (
            <div key={i} className="flex items-start" style={{ gap: 6, fontSize: 11, color: "var(--cg-text-secondary)" }}>
              <span style={{ color: riskColor }}>•</span>
              <span>{reason}</span>
            </div>
          ))}
        </Section>
      )}

      {/* Warnings */}
      {result.warnings.length > 0 && (
        <div style={{
          padding: "8px 10px",
          background: "var(--cg-warning-alpha)",
          border: "1px solid color-mix(in srgb, var(--cg-warning) 30%, transparent)",
          borderRadius: 4,
        }}>
          <div className="flex items-center" style={{ gap: 6, fontSize: 11, fontWeight: 500, color: "var(--cg-warning)", marginBottom: 4 }}>
            <IconWarning size={11} />
            <span>Warnings</span>
          </div>
          {result.warnings.map((w, i) => (
            <p key={i} style={{ fontSize: 11, color: "var(--cg-text-secondary)", margin: "2px 0" }}>{w}</p>
          ))}
        </div>
      )}

      {/* Recommendations */}
      {result.recommendations.length > 0 && (
        <Section title="Recommendations">
          {result.recommendations.map((rec) => (
            <div key={rec.step} className="flex items-start" style={{ gap: 8, fontSize: 11, color: "var(--cg-text-secondary)" }}>
              <span className="cg-mono" style={{ color: "var(--cg-accent)", fontWeight: 500, flexShrink: 0 }}>{rec.step}.</span>
              <span>{rec.message}</span>
            </div>
          ))}
        </Section>
      )}

      {/* Affected symbols */}
      {result.affected_symbols.length > 0 && (
        <Section title={`Affected Symbols (${result.affected_symbols.length})`}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {result.affected_symbols.map((sym, i) => {
              const impColor = IMPACT_TYPE_COLORS[sym.impact_type] || "var(--cg-text-muted)";
              const impBg = IMPACT_TYPE_BG[sym.impact_type] || "color-mix(in srgb, var(--cg-text-muted) 14%, transparent)";
              return (
                <div key={i} style={{
                  padding: "8px 10px",
                  background: "var(--cg-bg-panel)",
                  border: "1px solid var(--cg-border)",
                  borderRadius: 4,
                  fontSize: 11,
                }}>
                  <div className="flex items-center" style={{ gap: 6, marginBottom: 2 }}>
                    <span className="cg-mono" style={{ fontSize: 10, padding: "1px 4px", background: "var(--cg-bg-subtle)", color: "var(--cg-text-muted)", borderRadius: 2 }}>
                      D{sym.distance}
                    </span>
                    <span className="cg-mono" style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>
                      {sym.symbol_id}
                    </span>
                    {sym.type && <span style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>({sym.type})</span>}
                    <span style={{ flex: 1 }} />
                    <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                      conf={sym.confidence.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex items-center" style={{ gap: 6 }}>
                    <span style={{
                      fontSize: 9, padding: "1px 4px", borderRadius: 2,
                      color: impColor, background: impBg, letterSpacing: 0.3,
                    }}>
                      {sym.impact_type}
                    </span>
                    <span style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>{sym.reason}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* Affected files */}
      {result.affected_files.length > 0 && (
        <Section title={`Affected Files (${result.affected_files.length})`}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {result.affected_files.map((f, i) => {
              const priColor = PRIORITY_COLORS[f.priority] || "var(--cg-text-muted)";
              const priBg = PRIORITY_BG[f.priority] || "color-mix(in srgb, var(--cg-text-muted) 14%, transparent)";
              return (
                <div key={i} style={{
                  padding: "8px 10px",
                  background: "var(--cg-bg-panel)",
                  border: f.priority === "high" ? "1px solid color-mix(in srgb, var(--cg-error) 30%, transparent)" : "1px solid var(--cg-border)",
                  borderRadius: 4,
                  fontSize: 11,
                }}>
                  <div className="flex items-center" style={{ gap: 6, marginBottom: 2 }}>
                    <span style={{
                      fontSize: 9, padding: "1px 5px", borderRadius: 2,
                      color: priColor, background: priBg, letterSpacing: 0.4, fontWeight: 500,
                    }}>
                      {f.priority.toUpperCase()}
                    </span>
                    <span className="cg-mono" style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>
                      {f.file_path}
                    </span>
                  </div>
                  <p style={{ margin: 0, fontSize: 10, color: "var(--cg-text-secondary)" }}>{f.reason}</p>
                </div>
              );
            })}
          </div>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      padding: 14,
      background: "var(--cg-bg-panel)",
      border: "1px solid var(--cg-border)",
      borderRadius: 6,
      display: "flex",
      flexDirection: "column",
      gap: 8,
    }}>
      <div className="flex items-center" style={{ gap: 6, fontSize: 10, letterSpacing: 0.5, fontWeight: 600, color: "var(--cg-text-secondary)" }}>
        <span style={{ color: "var(--cg-text-muted)" }}>──</span>
        <span>{title}</span>
      </div>
      {children}
    </div>
  );
}
