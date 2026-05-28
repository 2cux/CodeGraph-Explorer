import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type ContextPackResponse } from "../api";
import { Spinner } from "../components/Spinner";

type ViewMode = "initial" | "loading" | "pack" | "error";

interface ViewState {
  mode: ViewMode;
  pack: ContextPackResponse | null;
  error: string;
}

const RISK_COLORS: Record<string, string> = {
  critical: "var(--cg-error)", high: "var(--cg-warning)",
  medium: "var(--cg-accent)", low: "var(--cg-success)", unknown: "var(--cg-text-muted)",
};
const RISK_BG: Record<string, string> = {
  critical: "var(--cg-error-alpha)", high: "var(--cg-warning-alpha)",
  medium: "var(--cg-accent-alpha)", low: "var(--cg-success-alpha)",
  unknown: "color-mix(in srgb, var(--cg-text-muted) 14%, transparent)",
};

const PRIORITY_COLORS: Record<string, string> = {
  critical: "var(--cg-error)", high: "var(--cg-warning)",
  medium: "var(--cg-accent)", low: "var(--cg-text-secondary)",
};
const PRIORITY_BG: Record<string, string> = {
  critical: "var(--cg-error-alpha)", high: "var(--cg-warning-alpha)",
  medium: "var(--cg-accent-alpha)", low: "color-mix(in srgb, var(--cg-text-secondary) 14%, transparent)",
};

export default function ContextPackViewer() {
  const navigate = useNavigate();
  const [task, setTask] = useState("");
  const [maxTokens, setMaxTokens] = useState(6000);
  const [includeTests, setIncludeTests] = useState(true);
  const [depth, setDepth] = useState(2);
  const [state, setState] = useState<ViewState>({ mode: "initial", pack: null, error: "" });

  async function generate() {
    if (!task.trim()) return;
    setState({ mode: "loading", pack: null, error: "" });
    try {
      const data = await api.context.generate(task, maxTokens, includeTests, depth);
      setState({ mode: "pack", pack: data, error: "" });
    } catch (e: unknown) {
      setState({ mode: "error", pack: null, error: e instanceof Error ? e.message : "Generation failed" });
    }
  }

  const renderContent = () => {
    switch (state.mode) {
      case "initial": return <InitialState />;
      case "loading": return <LoadingState task={task} />;
      case "error": return <ErrorState message={state.error} />;
      case "pack": return <PackContent pack={state.pack!} onNavigate={(id) => navigate(`/symbol/${encodeURIComponent(id)}`)} />;
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 18, fontWeight: 500, color: "var(--cg-text-primary)", margin: 0 }}>
          Context Pack Viewer
        </h1>
        <p style={{ fontSize: 12, color: "var(--cg-text-secondary)", margin: "4px 0 0" }}>
          Generate a task-aware code context pack for AI coding agents.
        </p>
      </div>

      {/* Form */}
      <div style={{
        padding: 14,
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 6,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}>
        <div>
          <label style={{ fontSize: 10, color: "var(--cg-text-muted)", marginBottom: 4, display: "block" }}>
            Task Description
          </label>
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="e.g. Add MFA support to the login flow"
            rows={3}
            style={{
              width: "100%", padding: "8px",
              border: "1px solid var(--cg-border)", borderRadius: 4,
              background: "var(--cg-bg-canvas)", color: "var(--cg-text-primary)",
              fontSize: 12, fontFamily: "inherit", outline: "none", resize: "vertical",
            }}
            onFocus={(e) => e.currentTarget.style.borderColor = "var(--cg-accent)"}
            onBlur={(e) => e.currentTarget.style.borderColor = "var(--cg-border)"}
          />
        </div>
        <div className="flex items-center" style={{ gap: 10, flexWrap: "wrap" }}>
          <div>
            <label style={{ fontSize: 10, color: "var(--cg-text-muted)", marginBottom: 4, display: "block" }}>Max Tokens</label>
            <select
              value={maxTokens}
              onChange={(e) => setMaxTokens(Number(e.target.value))}
              style={{
                height: 28, padding: "0 8px",
                border: "1px solid var(--cg-border)", borderRadius: 4,
                background: "var(--cg-bg-panel)", color: "var(--cg-text-primary)",
                fontSize: 11, fontFamily: "inherit", outline: "none",
              }}
            >
              <option value={3000}>3,000</option>
              <option value={6000}>6,000</option>
              <option value={12000}>12,000</option>
              <option value={24000}>24,000</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 10, color: "var(--cg-text-muted)", marginBottom: 4, display: "block" }}>Depth</label>
            <select
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              style={{
                height: 28, padding: "0 8px",
                border: "1px solid var(--cg-border)", borderRadius: 4,
                background: "var(--cg-bg-panel)", color: "var(--cg-text-primary)",
                fontSize: 11, fontFamily: "inherit", outline: "none",
              }}
            >
              {[1, 2, 3].map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <label className="flex items-center" style={{ gap: 6, fontSize: 11, color: "var(--cg-text-secondary)", cursor: "pointer" }}>
            <input type="checkbox" checked={includeTests} onChange={(e) => setIncludeTests(e.target.checked)} style={{ accentColor: "var(--cg-accent)" }} />
            Include tests
          </label>
          <button
            onClick={generate}
            disabled={state.mode === "loading" || !task.trim()}
            style={{
              height: 28, padding: "0 14px",
              background: "var(--cg-accent)", color: "#fff",
              border: "none", borderRadius: 4,
              fontSize: 11, fontWeight: 500, cursor: state.mode === "loading" ? "default" : "pointer",
              fontFamily: "inherit", opacity: state.mode === "loading" || !task.trim() ? 0.6 : 1,
            }}
          >
            {state.mode === "loading" ? "Generating..." : "Generate"}
          </button>
        </div>
      </div>

      {renderContent()}
    </div>
  );
}

/* ── States ──────────────────────────────────────────────────── */

function InitialState() {
  return (
    <div style={{ textAlign: "center", padding: "40px 20px", border: "1px dashed var(--cg-border)", borderRadius: 8 }}>
      <div style={{ fontSize: 32, color: "var(--cg-text-muted)", marginBottom: 12 }}>⊞</div>
      <h2 style={{ fontSize: 14, fontWeight: 500, color: "var(--cg-text-secondary)", margin: "0 0 4px" }}>
        Describe your task
      </h2>
      <p style={{ fontSize: 11, color: "var(--cg-text-muted)", margin: 0 }}>
        Enter a natural language task description to generate a Context Pack.
      </p>
    </div>
  );
}

function LoadingState({ task }: { task: string }) {
  return (
    <div style={{
      padding: 14, background: "var(--cg-bg-panel)", border: "1px solid var(--cg-border)", borderRadius: 6,
    }}>
      <div className="flex items-center" style={{ gap: 8, marginBottom: 12 }}>
        <Spinner size={12} />
        <span style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>
          Analyzing codebase for: <strong>"{task}"</strong>
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {[240, 180, 220, 160].map((w, i) => (
          <div key={i} className="cg-skeleton" style={{ height: 10, width: w, borderRadius: 2, animationDelay: `${i * 0.08}s` }} />
        ))}
      </div>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div style={{
      padding: "8px 10px",
      background: "var(--cg-error-alpha)",
      border: "1px solid color-mix(in srgb, var(--cg-error) 30%, transparent)",
      borderRadius: 4, fontSize: 11, color: "var(--cg-text-secondary)",
    }}>
      {message}
    </div>
  );
}

/* ── Pack content ────────────────────────────────────────────── */

function PackContent({ pack, onNavigate }: { pack: ContextPackResponse; onNavigate: (id: string) => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Pack header */}
      <div style={{
        padding: "12px 14px",
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 6,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <div>
          <div className="flex items-center" style={{ gap: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 500, color: "var(--cg-text-primary)" }}>Context Pack</span>
            <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>{pack.pack_id}</span>
          </div>
          <p style={{ fontSize: 11, color: "var(--cg-text-secondary)", margin: "4px 0 0" }}>
            Intent: {pack.task.intent} · Keywords: {pack.task.keywords.join(", ")}
          </p>
        </div>
      </div>

      {/* Agent Instructions */}
      <CardSection title="Agent Instructions">
        <p style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: "var(--cg-text-secondary)" }}>
          {pack.agent_instructions.summary}
        </p>
        {pack.agent_instructions.recommended_strategy.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", marginBottom: 4 }}>Recommended Strategy</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {pack.agent_instructions.recommended_strategy.map((s, i) => (
                <div key={i} className="flex items-start" style={{ gap: 6, fontSize: 11, color: "var(--cg-text-secondary)" }}>
                  <span className="cg-mono" style={{ color: "var(--cg-accent)", flexShrink: 0 }}>{i + 1}.</span>
                  <span>{s}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {pack.agent_instructions.warnings.length > 0 && (
          <div style={{
            marginTop: 8, padding: "6px 8px",
            background: "var(--cg-warning-alpha)",
            border: "1px solid color-mix(in srgb, var(--cg-warning) 30%, transparent)",
            borderRadius: 4,
          }}>
            {pack.agent_instructions.warnings.map((w, i) => (
              <p key={i} style={{ margin: 0, fontSize: 10, color: "var(--cg-text-secondary)" }}>{w}</p>
            ))}
          </div>
        )}
      </CardSection>

      {/* Entry Points */}
      <CardSection title={`Entry Points (${pack.entry_points.length})`}>
        {pack.entry_points.length === 0 ? (
          <EmptyText />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {pack.entry_points.map((ep, i) => (
              <div key={i} style={{
                padding: "8px 10px", cursor: "pointer",
                background: "var(--cg-bg-panel)", border: "1px solid var(--cg-border)",
                borderRadius: 4, fontSize: 11,
                transition: "border-color 120ms ease, background 120ms ease",
              }}
                onClick={() => onNavigate(ep.symbol_id)}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--cg-border-hover)"; e.currentTarget.style.background = "var(--cg-bg-elevated)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--cg-border)"; e.currentTarget.style.background = "var(--cg-bg-panel)"; }}
              >
                <div className="flex items-center" style={{ gap: 6, marginBottom: 2 }}>
                  <span className="cg-mono" style={{ fontSize: 9, padding: "1px 4px", background: "var(--cg-bg-subtle)", color: "var(--cg-text-muted)", borderRadius: 2 }}>
                    {ep.type}
                  </span>
                  <span className="cg-mono" style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>
                    {ep.name}
                  </span>
                  <span style={{ flex: 1 }} />
                  <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                    {ep.score.toFixed(2)}
                  </span>
                </div>
                <p style={{ margin: 0, fontSize: 10, color: "var(--cg-text-secondary)" }}>{ep.reason}</p>
              </div>
            ))}
          </div>
        )}
      </CardSection>

      {/* Related Symbols */}
      <CardSection title={`Related Symbols (${pack.related_symbols.length})`}>
        {pack.related_symbols.length === 0 ? (
          <EmptyText />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {pack.related_symbols.map((rs, i) => {
              const impColor = rs.importance === "critical" ? "var(--cg-error)" : rs.importance === "high" ? "var(--cg-warning)" : "var(--cg-text-secondary)";
              const impBg = rs.importance === "critical" ? "var(--cg-error-alpha)" : rs.importance === "high" ? "var(--cg-warning-alpha)" : "color-mix(in srgb, var(--cg-text-secondary) 14%, transparent)";
              return (
                <div key={i} style={{ padding: "6px 8px", borderBottom: "1px solid var(--cg-border)", fontSize: 11 }}>
                  <div className="flex items-center" style={{ gap: 6 }}>
                    <span style={{ fontSize: 9, padding: "1px 4px", borderRadius: 2, color: impColor, background: impBg, letterSpacing: 0.3 }}>
                      {rs.importance}
                    </span>
                    <span className="cg-mono" style={{ color: "var(--cg-text-primary)" }}>{rs.symbol_id}</span>
                    <span style={{ color: "var(--cg-text-muted)", fontSize: 10 }}>D{rs.distance} {rs.direction}</span>
                    <span style={{ flex: 1 }} />
                    <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                      conf={rs.confidence.toFixed(2)}
                    </span>
                  </div>
                  <p style={{ margin: "2px 0 0", fontSize: 10, color: "var(--cg-text-secondary)" }}>{rs.reason}</p>
                </div>
              );
            })}
          </div>
        )}
      </CardSection>

      {/* Call Graph */}
      <CardSection title="Call Graph">
        {pack.call_graph.nodes.length === 0 ? (
          <EmptyText />
        ) : (
          <div style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>
            <p style={{ margin: "0 0 8px" }}>
              Center: <span className="cg-mono" style={{ background: "var(--cg-bg-subtle)", padding: "1px 4px", borderRadius: 2 }}>{pack.call_graph.center}</span>
              {" · "}Depth: {pack.call_graph.depth}
              {" · "}{pack.call_graph.nodes.length} nodes, {pack.call_graph.edges.length} edges
            </p>
            {pack.call_graph.edges.length > 0 && (
              <div style={{ maxHeight: 160, overflowY: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
                {pack.call_graph.edges.map((e, i) => (
                  <div key={i} className="flex items-center" style={{ gap: 4, fontSize: 10 }}>
                    <span className="cg-mono" style={{ color: "var(--cg-text-primary)" }}>{e.source}</span>
                    <span style={{ color: "var(--cg-text-muted)" }}>→</span>
                    <span className="cg-mono" style={{ color: "var(--cg-text-primary)" }}>{e.target}</span>
                    <span style={{ color: "var(--cg-text-muted)", fontSize: 9 }}>
                      ({e.type}, conf={e.confidence.toFixed(2)})
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardSection>

      {/* Impact */}
      <CardSection title="Impact Analysis">
        {!pack.impact.changed_symbol ? (
          <EmptyText />
        ) : (
          <div style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>
            <div className="flex items-center" style={{ gap: 6, marginBottom: 6 }}>
              <span style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>Changing:</span>
              <span className="cg-mono" style={{ background: "var(--cg-bg-subtle)", padding: "1px 4px", borderRadius: 2 }}>{pack.impact.changed_symbol}</span>
            </div>
            <div className="flex items-center" style={{ gap: 8, marginBottom: 6 }}>
              <span style={{
                fontSize: 9, fontWeight: 500, padding: "2px 6px", borderRadius: 2,
                color: RISK_COLORS[pack.impact.risk?.level || "unknown"],
                background: RISK_BG[pack.impact.risk?.level || "unknown"],
                letterSpacing: 0.5,
              }}>
                {pack.impact.risk?.level?.toUpperCase()}
              </span>
              <span>{pack.impact.affected_symbols.length} symbols, {pack.impact.affected_files.length} files</span>
            </div>
            {pack.impact.risk?.reasons?.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {pack.impact.risk.reasons.map((r, i) => (
                  <div key={i} className="flex items-start" style={{ gap: 4, fontSize: 10 }}>
                    <span style={{ color: "var(--cg-accent)" }}>•</span>
                    <span>{r}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardSection>

      {/* Reading Plan */}
      <CardSection title="Reading Plan">
        {pack.reading_plan.length === 0 ? (
          <EmptyText />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {pack.reading_plan.map((step) => (
              <div key={step.step} className="flex items-start" style={{ gap: 8, padding: "6px 0", borderBottom: "1px solid var(--cg-border)", fontSize: 11 }}>
                <span className="cg-mono" style={{ color: "var(--cg-accent)", fontWeight: 500, flexShrink: 0, width: 20 }}>{step.step}.</span>
                <div>
                  <div className="flex items-center" style={{ gap: 6 }}>
                    <span className="cg-mono" style={{
                      fontSize: 9, padding: "1px 5px", borderRadius: 2,
                      color: "var(--cg-success)", background: "var(--cg-success-alpha)",
                    }}>
                      {step.action}
                    </span>
                    <span className="cg-mono" style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>
                      {step.target}
                    </span>
                  </div>
                  {step.reason && (
                    <p style={{ margin: "2px 0 0", fontSize: 10, color: "var(--cg-text-secondary)" }}>{step.reason}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardSection>

      {/* Recommended Context */}
      {pack.recommended_context.length > 0 && (
        <CardSection title={`Recommended Context (${pack.recommended_context.length})`}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 320, overflowY: "auto" }}>
            {pack.recommended_context.map((rc, i) => {
              const priColor = PRIORITY_COLORS[rc.priority] || "var(--cg-text-muted)";
              const priBg = PRIORITY_BG[rc.priority] || "color-mix(in srgb, var(--cg-text-muted) 14%, transparent)";
              return (
                <div key={i} style={{
                  padding: "8px 10px",
                  background: "var(--cg-bg-panel)",
                  border: "1px solid var(--cg-border)",
                  borderRadius: 4,
                  fontSize: 11,
                  cursor: "pointer",
                  transition: "border-color 120ms ease",
                }}
                  onClick={() => onNavigate(rc.symbol_id)}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--cg-border-hover)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--cg-border)"; }}
                >
                  <div className="flex items-center" style={{ gap: 6, marginBottom: 2 }}>
                    <span style={{ fontSize: 9, padding: "1px 4px", borderRadius: 2, color: priColor, background: priBg, letterSpacing: 0.3 }}>
                      {rc.priority}
                    </span>
                    <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                      {rc.file_path}:{rc.line_start}–{rc.line_end}
                    </span>
                    <span style={{ flex: 1 }} />
                    <span className="cg-mono" style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>
                      ~{rc.estimated_tokens}tok
                    </span>
                  </div>
                  <p style={{ margin: 0, fontSize: 10, color: "var(--cg-text-secondary)" }}>{rc.reason}</p>
                </div>
              );
            })}
          </div>
        </CardSection>
      )}
    </div>
  );
}

function CardSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      padding: 14,
      background: "var(--cg-bg-panel)",
      border: "1px solid var(--cg-border)",
      borderRadius: 6,
      display: "flex",
      flexDirection: "column",
    }}>
      <div className="flex items-center" style={{ gap: 6, fontSize: 10, letterSpacing: 0.5, fontWeight: 600, color: "var(--cg-text-secondary)", marginBottom: 10 }}>
        <span style={{ color: "var(--cg-text-muted)" }}>──</span>
        <span>{title}</span>
      </div>
      {children}
    </div>
  );
}

function EmptyText() {
  return <p style={{ fontSize: 11, color: "var(--cg-text-muted)", margin: 0, fontStyle: "italic" }}>None</p>;
}
