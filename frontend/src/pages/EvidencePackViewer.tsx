import { useState } from "react";
import { api, type ContextPackResponse } from "../api";
import { Spinner } from "../app/components/Spinner";

export default function EvidencePackViewer() {
  const [task, setTask] = useState("");
  const [maxTokens, setMaxTokens] = useState(6000);
  const [depth, setDepth] = useState(2);
  const [includeTests, setIncludeTests] = useState(true);
  const [result, setResult] = useState<ContextPackResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"overview" | "entry_points" | "selected_context" | "call_graph" | "impact" | "tests" | "warnings">("overview");

  async function generate() {
    if (!task.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.context.generate(task, maxTokens, includeTests, depth);
      setResult(r);
      setView("overview");
    } catch {
      setError("Failed to generate evidence pack.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Input bar */}
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid var(--cg-border)",
        background: "var(--cg-bg-panel)", display: "flex", flexDirection: "column", gap: 8,
      }}>
        <div className="flex items-center" style={{ gap: 8 }}>
          <input
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="Describe a task (e.g. 'Add MFA to login flow')"
            onKeyDown={(e) => e.key === "Enter" && generate()}
            style={{
              flex: 1, minWidth: 0, height: 30, padding: "0 10px",
              background: "var(--cg-bg-subtle)", border: "1px solid var(--cg-border)", borderRadius: 4,
              color: "var(--cg-text-primary)", fontSize: 12, fontFamily: "inherit", outline: "none",
            }}
          />
          <button
            onClick={generate}
            disabled={loading}
            style={{
              height: 30, padding: "0 14px", border: "none", borderRadius: 4, cursor: "pointer",
              background: "var(--cg-accent)", color: "#fff", fontSize: 11, fontFamily: "inherit",
              opacity: loading ? 0.6 : 1,
            }}
          >
            Generate
          </button>
        </div>
        <div className="flex items-center" style={{ gap: 12, flexWrap: "wrap" }}>
          <label style={{ fontSize: 10, color: "var(--cg-text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
            Tokens
            <input type="number" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))}
              style={{
                width: 60, height: 22, padding: "0 6px", fontSize: 10, fontFamily: "inherit",
                background: "var(--cg-bg-subtle)", border: "1px solid var(--cg-border)", borderRadius: 3, color: "var(--cg-text-primary)",
              }} />
          </label>
          <label style={{ fontSize: 10, color: "var(--cg-text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
            Depth
            <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}
              style={{
                height: 22, padding: "0 4px", fontSize: 10, fontFamily: "inherit",
                background: "var(--cg-bg-subtle)", border: "1px solid var(--cg-border)", borderRadius: 3, color: "var(--cg-text-primary)",
              }}>
              {[1, 2, 3].map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <label style={{ fontSize: 10, color: "var(--cg-text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
            <input type="checkbox" checked={includeTests} onChange={(e) => setIncludeTests(e.target.checked)} />
            Include tests
          </label>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {loading && (
          <div className="flex items-center" style={{ padding: 24, gap: 10, color: "var(--cg-text-muted)" }}>
            <Spinner size={16} />
            <span style={{ fontSize: 12 }}>Generating evidence pack...</span>
          </div>
        )}
        {error && <div style={{ padding: 16, color: "var(--cg-error)", fontSize: 12 }}>{error}</div>}

        {result && (
          <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
            {/* Sub-tabs */}
            <div style={{
              display: "flex", gap: 0, borderBottom: "1px solid var(--cg-border)",
              background: "var(--cg-bg-panel)", padding: "0 8px", flexShrink: 0,
            }}>
              {([
                ["overview", "Overview"],
                ["entry_points", `Entry Points (${result.entry_points.length})`],
                ["selected_context", `Selected Context (${result.selected_context.length})`],
                ["call_graph", "Call Graph"],
                ["impact", "Impact"],
                ["tests", "Tests"],
                ["warnings", `Warnings (${result.warnings.length})`],
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setView(key)}
                  style={{
                    height: 28, padding: "0 10px", border: "none", borderBottom: view === key ? "2px solid var(--cg-accent)" : "2px solid transparent",
                    background: "transparent", color: view === key ? "var(--cg-text-primary)" : "var(--cg-text-muted)",
                    fontSize: 10, fontFamily: "inherit", cursor: "pointer", whiteSpace: "nowrap",
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div style={{ flex: 1, overflow: "auto", padding: "12px 16px" }}>
              {view === "overview" && <PackOverview pack={result} />}
              {view === "entry_points" && <EntryPointsView pack={result} />}
              {view === "selected_context" && <SelectedContextView pack={result} />}
              {view === "call_graph" && <CallGraphView pack={result} />}
              {view === "impact" && <PackImpactView pack={result} />}
              {view === "tests" && <TestsView pack={result} />}
              {view === "warnings" && <WarningsView pack={result} />}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PackOverview({ pack }: { pack: ContextPackResponse }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", letterSpacing: 0.5, marginBottom: 4 }}>TASK</div>
        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--cg-text-primary)" }}>{pack.task.raw_request}</div>
        <div className="cg-mono" style={{ fontSize: 10, color: "var(--cg-accent)", marginTop: 2 }}>{pack.task.intent}</div>
      </div>

      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", letterSpacing: 0.5, marginBottom: 4 }}>PACK INFO</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px" }}>
          <KV label="Pack ID" value={pack.pack_id} mono />
          <KV label="Schema" value={pack.schema_version} mono />
          <KV label="Entry points" value={String(pack.entry_points.length)} />
          <KV label="Related symbols" value={String(pack.related_symbols.length)} />
          <KV label="Selected context" value={String(pack.selected_context.length)} />
          <KV label="Warnings" value={String(pack.warnings.length)} />
        </div>
      </div>

      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", letterSpacing: 0.5, marginBottom: 4 }}>TOKEN BUDGET</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px" }}>
          {Object.entries(pack.token_budget).map(([k, v]) => (
            <KV key={k} label={k} value={String(v)} />
          ))}
        </div>
      </div>

      {pack.exports?.json_path && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", letterSpacing: 0.5, marginBottom: 4 }}>EXPORTS</div>
          <div className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>JSON: {pack.exports.json_path}</div>
          <div className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>MD: {pack.exports.markdown_path}</div>
        </div>
      )}

      {pack.pack_notes.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", letterSpacing: 0.5, marginBottom: 4 }}>PACK NOTES</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {pack.pack_notes.map((n, i) => (
              <div key={i} style={{ display: "flex", gap: 8, fontSize: 10, padding: "4px 6px", background: "var(--cg-bg-subtle)", borderRadius: 3 }}>
                <span className="cg-mono" style={{ color: "var(--cg-accent)", flexShrink: 0 }}>{n.type}</span>
                <span style={{ color: "var(--cg-text-secondary)" }}>{n.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function KV({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
      <span style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>{label}:</span>
      <span className={mono ? "cg-mono" : ""} style={{ fontSize: 10, color: "var(--cg-text-primary)" }}>{value}</span>
    </div>
  );
}

function EntryPointsView({ pack }: { pack: ContextPackResponse }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <p style={{ margin: 0, fontSize: 11, color: "var(--cg-text-secondary)", lineHeight: 1.5 }}>
        Entry point candidates identified from the task description. Each includes a match reason describing the evidence basis — not a suggested reading order.
      </p>
      {pack.entry_points.map((ep) => (
        <div key={ep.symbol_id} style={{
          padding: "8px 10px", border: "1px solid var(--cg-border)", borderRadius: 4,
          background: "var(--cg-bg-subtle)", display: "flex", flexDirection: "column", gap: 4,
        }}>
          <div className="flex items-center" style={{ gap: 8 }}>
            <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-accent)", flexShrink: 0 }}>{ep.type}</span>
            <span className="cg-mono" style={{ fontSize: 12, fontWeight: 500, color: "var(--cg-text-primary)" }}>{ep.name}</span>
            <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)", marginLeft: "auto" }}>
              score: {ep.score.toFixed(2)}
            </span>
          </div>
          <div className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>{ep.file_path}</div>
          <div style={{ fontSize: 10, color: "var(--cg-text-secondary)", lineHeight: 1.4 }}>{ep.reason}</div>
          {ep.match_sources.length > 0 && (
            <div style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>
              Match: {ep.match_sources.join(", ")}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function SelectedContextView({ pack }: { pack: ContextPackResponse }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{
        padding: "8px 10px", fontSize: 11, lineHeight: 1.5,
        color: "var(--cg-text-secondary)", background: "var(--cg-bg-subtle)",
        border: "1px solid color-mix(in srgb, var(--cg-accent) 20%, transparent)", borderRadius: 4,
      }}>
        Selected context materials under token budget. This is not a reading or execution order.
      </div>
      {pack.selected_context.map((sc) => (
        <div key={sc.context_id} style={{
          padding: "8px 10px", border: "1px solid var(--cg-border)", borderRadius: 4,
          display: "flex", flexDirection: "column", gap: 4,
        }}>
          <div className="flex items-center" style={{ gap: 8 }}>
            <span className="cg-mono" style={{ fontSize: 10, color: kindColor(sc.type) }}>{sc.type}</span>
            <span className="cg-mono" style={{ fontSize: 11, fontWeight: 500, color: "var(--cg-text-primary)" }}>{sc.symbol_id}</span>
          </div>
          <div className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>
            {sc.file_path}:{sc.line_start}-{sc.line_end}
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 10 }}>
            <span style={{ color: "var(--cg-text-muted)" }}>relation: {sc.relation}</span>
            <span style={{ color: confColor(sc.confidence) }}>confidence: {sc.confidence.toFixed(2)} ({sc.confidence_level})</span>
            <span style={{ color: "var(--cg-text-muted)" }}>resolution: {sc.resolution}</span>
            <span style={{ color: "var(--cg-text-muted)" }}>tokens: {sc.estimated_tokens}</span>
          </div>
          <div style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>{sc.selection_reason}</div>
          {sc.evidence && <div className="cg-mono" style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>Evidence: {sc.evidence}</div>}
          {sc.content && (
            <pre style={{
              margin: 0, padding: 8, background: "var(--cg-bg-canvas)", borderRadius: 3, fontSize: 10,
              color: "var(--cg-text-primary)", maxHeight: 200, overflow: "auto", whiteSpace: "pre-wrap",
            }}>
              {sc.content}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

function CallGraphView({ pack }: { pack: ContextPackResponse }) {
  const cg = pack.call_graph;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="flex items-center" style={{ gap: 12, fontSize: 11, color: "var(--cg-text-secondary)" }}>
        <span>Center: <span className="cg-mono" style={{ color: "var(--cg-text-primary)" }}>{cg.center}</span></span>
        <span>Depth: {cg.depth}</span>
        <span>Nodes: {cg.nodes.length}</span>
        <span>Edges: {cg.edges.length}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {cg.edges.map((e, i) => (
          <div key={i} className="flex items-center" style={{
            gap: 8, padding: "4px 8px", background: "var(--cg-bg-subtle)", borderRadius: 3, fontSize: 10,
          }}>
            <span className="cg-mono" style={{ color: "var(--cg-text-primary)" }}>{e.source}</span>
            <span style={{ color: "var(--cg-text-muted)" }}>→</span>
            <span className="cg-mono" style={{ color: "var(--cg-text-primary)" }}>{e.target}</span>
            <span className="cg-mono" style={{ color: "var(--cg-text-muted)", marginLeft: "auto" }}>{e.type}</span>
            <span className="cg-mono" style={{ color: confColor(e.confidence) }}>{(e.confidence * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PackImpactView({ pack }: { pack: ContextPackResponse }) {
  const imp = pack.impact;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>
        Changed symbol: <span className="cg-mono" style={{ color: "var(--cg-text-primary)" }}>{imp.changed_symbol}</span>
      </div>
      {imp.risk && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", marginBottom: 4 }}>RISK: {imp.risk.level.toUpperCase()}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {imp.risk.reasons.map((r, i) => (
              <div key={i} className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>{r}</div>
            ))}
          </div>
        </div>
      )}
      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", marginBottom: 4 }}>
          AFFECTED SYMBOLS ({imp.affected_symbols.length})
        </div>
        {imp.affected_symbols.map((s, i) => (
          <div key={i} className="flex items-center" style={{ gap: 8, padding: "3px 6px", fontSize: 10 }}>
            <span className="cg-mono" style={{ color: "var(--cg-text-primary)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.symbol_id}</span>
            <span style={{ color: "var(--cg-text-muted)", flexShrink: 0 }}>{s.impact_type}</span>
            <span className="cg-mono" style={{ color: confColor(s.confidence), flexShrink: 0 }}>{(s.confidence * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TestsView({ pack }: { pack: ContextPackResponse }) {
  const t = pack.tests;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", marginBottom: 4 }}>
          EXISTING TESTS ({t.existing_tests.length})
        </div>
        {t.existing_tests.map((tt, i) => (
          <div key={i} className="flex items-center" style={{ gap: 8, padding: "3px 6px", fontSize: 10 }}>
            <span className="cg-mono" style={{ color: "var(--cg-text-primary)" }}>{tt.test_file}</span>
            <span style={{ color: "var(--cg-text-muted)" }}>{tt.test_name}</span>
            <span className="cg-mono" style={{ color: confColor(tt.confidence), marginLeft: "auto" }}>{(tt.confidence * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", marginBottom: 4 }}>
          SUGGESTED TESTS ({t.suggested_tests.length})
        </div>
        {t.suggested_tests.map((tt, i) => (
          <div key={i} className="flex items-center" style={{ gap: 8, padding: "3px 6px", fontSize: 10 }}>
            <span className="cg-mono" style={{ color: "var(--cg-text-primary)" }}>{tt.test_file}</span>
            <span style={{ color: "var(--cg-text-muted)" }}>{tt.test_name}</span>
            <span style={{ color: "var(--cg-text-secondary)", marginLeft: "auto", fontSize: 9 }}>{tt.reason}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function WarningsView({ pack }: { pack: ContextPackResponse }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {pack.warnings.length === 0 ? (
        <span style={{ fontSize: 11, color: "var(--cg-text-muted)" }}>No warnings.</span>
      ) : (
        pack.warnings.map((w, i) => (
          <div key={i} style={{
            padding: "8px 10px", fontSize: 10, color: "var(--cg-warning)",
            background: "color-mix(in srgb, var(--cg-warning) 8%, transparent)",
            border: "1px solid color-mix(in srgb, var(--cg-warning) 20%, transparent)",
            borderRadius: 4, lineHeight: 1.4,
          }}>
            {w}
          </div>
        ))
      )}
      {pack.pack_notes.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", marginBottom: 4 }}>PACK NOTES</div>
          {pack.pack_notes.map((n, i) => (
            <div key={i} style={{ display: "flex", gap: 8, padding: "4px 6px", fontSize: 10 }}>
              <span className="cg-mono" style={{ color: "var(--cg-accent)", flexShrink: 0 }}>{n.type}</span>
              <span style={{ color: "var(--cg-text-secondary)" }}>{n.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function kindColor(type: string): string {
  const t = type.toLowerCase();
  if (t.includes("code") || t.includes("snippet")) return "var(--cg-accent)";
  if (t.includes("summary")) return "var(--cg-text-secondary)";
  if (t.includes("warning")) return "var(--cg-warning)";
  return "var(--cg-text-muted)";
}

function confColor(c: number): string {
  if (c >= 0.85) return "var(--cg-success)";
  if (c >= 0.7) return "var(--cg-text-secondary)";
  if (c > 0) return "var(--cg-warning)";
  return "var(--cg-text-muted)";
}
