import { IconClose } from "./icons";
import { Spinner } from "./Spinner";

export type InspectorTarget = "node" | "edge";
export type InspectorMode = "node" | "edge" | "loading" | "error";

export interface NodeInspectorData {
  symbol_id: string;
  name: string;
  type: string;
  file_path: string;
  line_start?: number;
  line_end?: number;
  signature?: string | null;
  docstring?: string | null;
  code_preview?: string | null;
  tags?: string[];
  visibility?: string | null;
  metadata?: Record<string, unknown>;
  callers_count?: number;
  callees_count?: number;
  tests_count?: number;
  impact_files_count?: number;
  /** Count of edges incident to this node */
  edge_count?: number;
  /** Count of distinct neighbor nodes */
  neighbor_count?: number;
  /** True if this is a synthetic group parent node */
  is_group_parent?: boolean;
  /** For group parents: count of child symbols */
  child_count?: number;
  /** For group parents: kind breakdown string */
  child_kind_summary?: string;
}

export interface EdgeInspectorData {
  source: string;
  target: string;
  type: string;
  confidence: number;
  confidence_level: string;
  resolution: string;
  reason_codes?: string[];
  reason?: string;
  evidence?: string | Record<string, unknown>;
  source_location?: { file_path: string; line_start: number; line_end?: number } | null;
}

interface Props {
  target?: InspectorTarget;
  mode?: InspectorMode;
  onClose: () => void;
  onSwitch?: (t: InspectorTarget) => void;
  onRetry?: () => void;
  nodeData?: NodeInspectorData | null;
  edgeData?: EdgeInspectorData | null;
  /** Called when user clicks "Re-center" to navigate to this symbol */
  onSelectSymbol?: (symbolId: string) => void;
  /** Called when user clicks expand/collapse on a group parent node */
  onToggleGroup?: (groupId: string) => void;
}

export function RightInspector({
  target = "node",
  mode,
  onClose,
  onSwitch,
  onRetry,
  nodeData,
  edgeData,
  onSelectSymbol,
  onToggleGroup,
}: Props) {
  const effective: InspectorMode = mode ?? target;
  return (
    <aside
      className="cg-scroll"
      style={{
        width: 360, flex: "0 0 360px",
        background: "var(--cg-bg-panel)",
        borderLeft: "1px solid var(--cg-border)",
        height: "100%", overflowY: "auto",
        display: "flex", flexDirection: "column",
      }}
    >
      <InspectorHeader target={target} onClose={onClose} onSwitch={onSwitch} />
      {effective === "node" && <NodeInspector data={nodeData} onSelectSymbol={onSelectSymbol} onToggleGroup={onToggleGroup} />}
      {effective === "edge" && <EdgeInspector data={edgeData} />}
      {effective === "loading" && <LoadingBody />}
      {effective === "error" && <ErrorBody onRetry={onRetry} />}
    </aside>
  );
}

function InspectorHeader({
  target, onClose, onSwitch,
}: { target: InspectorTarget; onClose: () => void; onSwitch?: (t: InspectorTarget) => void }) {
  return (
    <div
      className="flex items-center justify-between"
      style={{
        height: 30, padding: "0 10px 0 14px",
        borderBottom: "1px solid var(--cg-border)", flexShrink: 0,
      }}
    >
      <div className="flex items-center" style={{ gap: 8, fontSize: 11, color: "var(--cg-text-secondary)" }}>
        <span style={{ color: "var(--cg-text-muted)" }}>Inspector</span>
        <span style={{ color: "var(--cg-text-muted)" }}>·</span>
        <Tab label="Node" active={target === "node"} onClick={() => onSwitch?.("node")} />
        <Tab label="Edge" active={target === "edge"} onClick={() => onSwitch?.("edge")} />
      </div>
      <button
        onClick={onClose}
        aria-label="Close inspector"
        style={{
          width: 20, height: 20, borderRadius: 4, border: "none",
          background: "transparent", color: "var(--cg-text-muted)", cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        <IconClose size={11} />
      </button>
    </div>
  );
}

function Tab({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: "transparent", border: "none", padding: 0, cursor: "pointer",
        color: active ? "var(--cg-text-primary)" : "var(--cg-text-muted)",
        fontSize: 11,
      }}
    >
      {label}
    </button>
  );
}

function InspectorSection({ title, children, first = false }: { title: string; children: React.ReactNode; first?: boolean }) {
  return (
    <section style={{
      display: "flex", flexDirection: "column", gap: 8,
      paddingTop: first ? 0 : 14,
      borderTop: first ? "none" : "1px solid var(--cg-border)",
      marginTop: first ? 0 : 14,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 10, letterSpacing: 0.5, fontWeight: 600,
        color: "var(--cg-text-secondary)",
      }}>
        <span style={{ color: "var(--cg-text-muted)" }}>──</span>
        <span>{title}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {children}
      </div>
    </section>
  );
}

function NodeInspector({
  data,
  onSelectSymbol,
  onToggleGroup,
}: {
  data?: NodeInspectorData | null;
  onSelectSymbol?: (symbolId: string) => void;
  onToggleGroup?: (groupId: string) => void;
}) {
  if (!data) {
    return (
      <div style={{ padding: "14px", fontSize: 11, color: "var(--cg-text-muted)" }}>
        Select a node to inspect.
      </div>
    );
  }

  const kind = data.type?.toUpperCase() || "UNKNOWN";
  const location = data.line_start != null
    ? `${data.file_path}:${data.line_start}${data.line_end ? `-${data.line_end}` : ""}`
    : data.file_path;
  const isLowConf = (data.metadata?.confidence as number) != null && (data.metadata?.confidence as number) < 0.6;

  return (
    <div style={{ padding: "12px 14px 16px", display: "flex", flexDirection: "column" }}>
      <NodeIdentity kind={kind} name={data.name} location={location} />

      {/* Group parent summary */}
      {data.is_group_parent && (
        <InspectorSection title="Group Summary">
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <KV label="Group type" value={data.type} mono />
            {data.child_count != null && (
              <KV label="Child symbols" value={String(data.child_count)} mono />
            )}
            {data.child_kind_summary && (
              <KV label="Breakdown" value={data.child_kind_summary} />
            )}
            {onToggleGroup && (
              <div style={{ marginTop: 4 }}>
                <button
                  onClick={() => onToggleGroup(data.symbol_id)}
                  style={{
                    gap: 6, height: 26, padding: "0 10px",
                    background: "transparent", border: "1px solid var(--cg-border)", borderRadius: 4,
                    color: "var(--cg-text-primary)", fontSize: 11, cursor: "pointer",
                    justifyContent: "flex-start", width: "100%",
                    fontFamily: "inherit",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "var(--cg-bg-subtle)";
                    e.currentTarget.style.borderColor = "var(--cg-border-hover)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "transparent";
                    e.currentTarget.style.borderColor = "var(--cg-border)";
                  }}
                >
                  Expand / Collapse
                </button>
              </div>
            )}
          </div>
        </InspectorSection>
      )}

      {data.signature && (
        <InspectorSection title="Signature">
          <CodeBlock lines={data.signature.split("\n")} language="py" />
        </InspectorSection>
      )}

      {data.docstring && (
        <InspectorSection title="Summary">
          <p style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: "var(--cg-text-secondary)" }}>
            {data.docstring}
          </p>
        </InspectorSection>
      )}

      <InspectorSection title="Identity">
        <KV label="symbol_id" value={data.symbol_id} mono />
        <KV label="name" value={data.name} />
        <KV label="type" value={data.type} mono />
        <KV label="file_path" value={data.file_path} mono />
        {data.line_start != null && (
          <KV label="line" value={`${data.line_start}${data.line_end ? `-${data.line_end}` : ""}`} mono />
        )}
        {data.visibility && <KV label="visibility" value={data.visibility} mono />}
      </InspectorSection>

      {/* Quick action: neighbors */}
      {!data.is_group_parent && onSelectSymbol && (
        <InspectorSection title="Explore">
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <button
              onClick={() => onSelectSymbol(data.symbol_id)}
              style={{
                gap: 6, height: 26, padding: "0 10px",
                background: "transparent", border: "1px solid var(--cg-border)", borderRadius: 4,
                color: "var(--cg-text-primary)", fontSize: 11, cursor: "pointer",
                justifyContent: "flex-start", width: "100%",
                fontFamily: "inherit",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--cg-bg-subtle)";
                e.currentTarget.style.borderColor = "var(--cg-border-hover)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.borderColor = "var(--cg-border)";
              }}
            >
              Re-center on this symbol
            </button>
            <div style={{ display: "flex", gap: 6 }}>
              <button
                onClick={() => onSelectSymbol(data.symbol_id)}
                style={{
                  gap: 6, height: 26, padding: "0 10px", flex: 1,
                  background: "transparent", border: "1px solid var(--cg-border)", borderRadius: 4,
                  color: "var(--cg-text-primary)", fontSize: 11, cursor: "pointer",
                  fontFamily: "inherit",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--cg-bg-subtle)";
                  e.currentTarget.style.borderColor = "var(--cg-border-hover)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.borderColor = "var(--cg-border)";
                }}
              >
                View Callers
              </button>
              <button
                onClick={() => onSelectSymbol(data.symbol_id)}
                style={{
                  gap: 6, height: 26, padding: "0 10px", flex: 1,
                  background: "transparent", border: "1px solid var(--cg-border)", borderRadius: 4,
                  color: "var(--cg-text-primary)", fontSize: 11, cursor: "pointer",
                  fontFamily: "inherit",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--cg-bg-subtle)";
                  e.currentTarget.style.borderColor = "var(--cg-border-hover)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.borderColor = "var(--cg-border)";
                }}
              >
                View Callees
              </button>
            </div>
          </div>
        </InspectorSection>
      )}

      {data.tags && data.tags.length > 0 && (
        <InspectorSection title="Tags">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {data.tags.map((t) => (
              <span key={t} style={{
                fontSize: 9, padding: "1px 6px", borderRadius: 3,
                background: "var(--cg-bg-subtle)", color: "var(--cg-text-secondary)",
                border: "1px solid var(--cg-border)",
              }}>
                {t}
              </span>
            ))}
          </div>
        </InspectorSection>
      )}

      {(data.callers_count != null || data.callees_count != null || data.tests_count != null) && (
        <InspectorSection title="Relations">
          <div style={{ display: "flex", gap: 16 }}>
            {data.callers_count != null && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                <span className="cg-mono" style={{ fontSize: 14, fontWeight: 600, color: "var(--cg-text-primary)" }}>
                  {data.callers_count}
                </span>
                <span style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>callers</span>
              </div>
            )}
            {data.callees_count != null && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                <span className="cg-mono" style={{ fontSize: 14, fontWeight: 600, color: "var(--cg-text-primary)" }}>
                  {data.callees_count}
                </span>
                <span style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>callees</span>
              </div>
            )}
            {data.tests_count != null && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                <span className="cg-mono" style={{ fontSize: 14, fontWeight: 600, color: "var(--cg-text-primary)" }}>
                  {data.tests_count}
                </span>
                <span style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>tests</span>
              </div>
            )}
          </div>
        </InspectorSection>
      )}

      {data.metadata && Object.keys(data.metadata).length > 0 && (
        <InspectorSection title="Metadata">
          {Object.entries(data.metadata).map(([k, v]) => (
            <KV key={k} label={k} value={String(v)} mono />
          ))}
        </InspectorSection>
      )}

      {isLowConf && <LowConfidenceNotice />}
    </div>
  );
}

function NodeIdentity({ kind, name, location }: { kind: string; name: string; location: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div className="flex items-center" style={{ gap: 6 }}>
        <span
          className="cg-mono"
          style={{
            fontSize: 9, color: kindColor(kind),
            letterSpacing: 0.5, padding: "1px 5px",
            background: `color-mix(in srgb, ${kindColor(kind)} 14%, transparent)`,
            borderRadius: 2,
          }}
        >
          {kind}
        </span>
        <span className="cg-mono" style={{ fontSize: 13, color: "var(--cg-text-primary)", fontWeight: 500 }}>
          {name}
        </span>
      </div>
      <div className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>
        {location}
      </div>
    </div>
  );
}

function EdgeInspector({ data }: { data?: EdgeInspectorData | null }) {
  if (!data) {
    return (
      <div style={{ padding: "14px", fontSize: 11, color: "var(--cg-text-muted)" }}>
        Select an edge to inspect.
      </div>
    );
  }

  const confidence = data.confidence;
  const level = confidenceLevelLabel(confidence);
  const resolution = data.resolution;
  const isLow = confidence < 0.6;

  return (
    <div style={{ padding: "12px 14px 16px", display: "flex", flexDirection: "column" }}>
      <EdgeIdentity from={data.source} to={data.target} />

      <InspectorSection title="Properties">
        <KV label="Type" value={data.type} mono />
        <KV label="Confidence" value={`${confidence.toFixed(2)} (${level.label})`} tone={level.tone} mono />
        <KV label="Confidence Level" value={data.confidence_level} mono />
        <KV label="Resolution" value={resolutionLabel(resolution)} mono />
      </InspectorSection>

      {data.evidence ? (
        <InspectorSection title="Evidence">
          <p style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: "var(--cg-text-secondary)" }}>
            {typeof data.evidence === "string" ? data.evidence : JSON.stringify(data.evidence, null, 2)}
          </p>
        </InspectorSection>
      ) : (
        <InspectorSection title="Evidence">
          <p style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: "var(--cg-text-muted)", fontStyle: "italic" }}>
            No detailed evidence available
          </p>
        </InspectorSection>
      )}

      {data.reason && (
        <InspectorSection title="Reason">
          <p style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: "var(--cg-text-secondary)" }}>
            {data.reason}
          </p>
        </InspectorSection>
      )}

      {data.source_location && (
        <InspectorSection title="Source Location">
          <div className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>
            {data.source_location.file_path}:{data.source_location.line_start}
          </div>
        </InspectorSection>
      )}

      {data.reason_codes && data.reason_codes.length > 0 && (
        <InspectorSection title="Reason Codes">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {data.reason_codes.map((rc) => (
              <span key={rc} style={{
                fontSize: 9, padding: "1px 6px", borderRadius: 3,
                background: "var(--cg-bg-subtle)", color: "var(--cg-text-secondary)",
                border: "1px solid var(--cg-border)",
              }}>
                {rc}
              </span>
            ))}
          </div>
        </InspectorSection>
      )}

      {isLow && <LowConfidenceNotice />}
    </div>
  );
}

function EdgeIdentity({ from, to }: { from: string; to: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div className="flex items-center" style={{ gap: 6 }}>
        <span
          className="cg-mono"
          style={{
            fontSize: 9, color: "var(--cg-accent)",
            letterSpacing: 0.5, padding: "1px 5px",
            background: "var(--cg-accent-alpha)", borderRadius: 2,
          }}
        >
          EDGE
        </span>
      </div>
      <div className="cg-mono" style={{ fontSize: 13, color: "var(--cg-text-primary)", fontWeight: 500 }}>
        <span>{from}</span>
        <span style={{ color: "var(--cg-text-muted)", margin: "0 6px" }}>→</span>
        <span>{to}</span>
      </div>
    </div>
  );
}

export function OutlineButton({ label, icon, full = true }: { label: string; icon?: React.ReactNode; full?: boolean }) {
  return (
    <button className="flex items-center" style={{
      gap: 6, height: 26, padding: "0 10px",
      background: "transparent", border: "1px solid var(--cg-border)", borderRadius: 4,
      color: "var(--cg-text-primary)", fontSize: 11, cursor: "pointer",
      justifyContent: "flex-start", width: full ? "100%" : undefined,
      fontFamily: "inherit",
    }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "var(--cg-bg-subtle)";
        e.currentTarget.style.borderColor = "var(--cg-border-hover)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
        e.currentTarget.style.borderColor = "var(--cg-border)";
      }}
    >
      {icon && <span style={{ color: "var(--cg-text-secondary)" }}>{icon}</span>}
      <span>{label}</span>
    </button>
  );
}

export const Section = InspectorSection;

function LowConfidenceNotice() {
  return (
    <div style={{
      marginTop: 14, padding: "8px 10px",
      background: "color-mix(in srgb, var(--cg-warning) 10%, transparent)",
      border: "1px solid color-mix(in srgb, var(--cg-warning) 35%, transparent)",
      borderRadius: 4, display: "flex", gap: 8,
    }}>
      <span style={{ color: "var(--cg-warning)", flexShrink: 0, lineHeight: 1, paddingTop: 1 }}>
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round">
          <path d="M8 2.5L14 13.5H2L8 2.5zM8 7v3M8 11.6v.1" />
        </svg>
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, color: "var(--cg-warning)", fontWeight: 500 }}>Weak signal</div>
        <div style={{ fontSize: 11, color: "var(--cg-text-secondary)", lineHeight: 1.5, marginTop: 2 }}>
          This relation has low confidence. The evidence for this connection is uncertain.
        </div>
      </div>
    </div>
  );
}

export function CodeBlock({ lines, language = "py" }: { lines: string[]; language?: "py" | "plain" }) {
  return (
    <pre className="cg-mono" style={{
      margin: 0, padding: 8,
      background: "var(--cg-bg-subtle)",
      border: "1px solid var(--cg-border)", borderRadius: 4,
      fontSize: 11, lineHeight: 1.55,
      color: "var(--cg-text-primary)",
      overflowX: "auto", whiteSpace: "pre",
    }}>
      {lines.map((l, i) => (
        <div key={i}>{language === "py" ? colorize(l) : l}</div>
      ))}
    </pre>
  );
}

function colorize(line: string) {
  const tokens = line.split(/(\bdef\b|\bif\b|\bis\b|\bnot\b|\bNone\b|\breturn\b|\bstr\b|\bint\b|->)/);
  return tokens.map((t, i) => {
    if (["def", "if", "is", "not", "return"].includes(t))
      return <span key={i} style={{ color: "var(--cg-accent)" }}>{t}</span>;
    if (["str", "int", "None"].includes(t))
      return <span key={i} style={{ color: "var(--cg-success)" }}>{t}</span>;
    if (t === "->") return <span key={i} style={{ color: "var(--cg-text-muted)" }}>{t}</span>;
    return <span key={i}>{t}</span>;
  });
}

function KV({ label, value, tone, mono }: { label: string; value: string; tone?: "success" | "warning" | "muted"; mono?: boolean }) {
  const color =
    tone === "success" ? "var(--cg-success)" :
    tone === "warning" ? "var(--cg-warning)" :
    tone === "muted" ? "var(--cg-text-muted)" :
    "var(--cg-text-primary)";
  return (
    <div className="flex items-center" style={{ gap: 8, fontSize: 11 }}>
      <span style={{ width: 100, color: "var(--cg-text-muted)", flexShrink: 0 }}>{label}</span>
      <span className={mono ? "cg-mono" : ""} style={{ color, wordBreak: "break-all" }}>{value}</span>
    </div>
  );
}

export function confidenceLevelLabel(c: number): { label: string; tone: "success" | "warning" | "muted" } {
  if (c >= 0.80) return { label: "High", tone: "success" };
  if (c >= 0.60) return { label: "Medium", tone: "warning" };
  if (c >= 0.40) return { label: "Low", tone: "warning" };
  return { label: "Unknown", tone: "muted" };
}

export function resolutionLabel(r: string): string {
  const map: Record<string, string> = {
    same_file_exact: "Same-file exact call",
    imported_function_exact: "Imported function (exact name)",
    imported_function_alias: "Imported function (aliased)",
    imported_module_attribute: "Module attribute access",
    relative_import_resolved: "Relative import resolved",
    self_method_resolved: "Self method call",
    parameter_type_hint_resolved: "Parameter type hint",
    local_instance_resolved: "Local instance resolved",
    module_instance_resolved: "Module-level instance resolved",
    constructor_call_resolved: "Constructor chain call",
    self_attribute_instance_resolved: "Self-attribute instance",
    exact_ast_match: "Exact AST match (structural)",
    direct_test_call: "Direct test call",
    test_name_heuristic: "Test name heuristic",
    test_file_heuristic: "Test file name match",
    fastapi_route_decorator: "FastAPI route decorator",
    flask_route_decorator: "Flask route decorator",
    django_view_heuristic: "Django view heuristic",
    pydantic_model_detected: "Pydantic BaseModel",
    config_class_detected: "Config class detected",
    store_name_match: "Store name match",
    unresolved: "Unresolved",
    external_symbol: "External symbol",
  };
  return map[r] || r;
}

function kindColor(kind: string) {
  const k = kind.toUpperCase();
  if (k === "FUNC" || k === "FUNCTION") return "var(--cg-accent)";
  if (k === "METH" || k === "METHOD") return "#A78BFA";
  if (k === "CLASS") return "var(--cg-success)";
  if (k === "TEST") return "#4ADE80";
  if (k === "FILE") return "var(--cg-text-secondary)";
  if (k === "EXT" || k === "EXTERNAL_SYMBOL") return "var(--cg-warning)";
  return "var(--cg-text-secondary)";
}

// ── Loading / Error states ──────────────────────────────────────────────

function LoadingBody() {
  return (
    <div style={{ padding: "12px 14px 16px", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <SkeletonLine width={36} height={16} radius={2} delay={0} />
          <SkeletonLine width={96} height={14} radius={2} delay={0.05} />
        </div>
        <SkeletonLine width={140} height={10} radius={2} delay={0.1} />
      </div>
      <SkeletonSectionHeader delay={0.12} />
      <SkeletonBlock height={72} delay={0.15} />
      <div style={{ height: 14 }} />
      <SkeletonSectionHeader delay={0.18} />
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <SkeletonLine width="90%" height={9} radius={2} delay={0.2} />
        <SkeletonLine width="75%" height={9} radius={2} delay={0.22} />
        <SkeletonLine width="60%" height={9} radius={2} delay={0.24} />
      </div>
      <div style={{
        display: "flex", alignItems: "center", gap: 6, marginTop: 20,
        paddingTop: 14, borderTop: "1px solid var(--cg-border)",
      }}>
        <Spinner size={11} />
        <span style={{ fontSize: 11, color: "var(--cg-text-muted)" }}>Loading symbol details...</span>
      </div>
    </div>
  );
}

function SkeletonLine({ width, height = 8, radius = 2, delay = 0 }: { width: number | string; height?: number; radius?: number; delay?: number }) {
  return (
    <div className="cg-skeleton" style={{ height, width, borderRadius: radius, animationDelay: `${delay}s`, flexShrink: 0 }} />
  );
}

function SkeletonBlock({ height, delay = 0 }: { height: number; delay?: number }) {
  return (
    <div className="cg-skeleton" style={{ height, borderRadius: 4, border: "1px solid var(--cg-border)", animationDelay: `${delay}s` }} />
  );
}

function SkeletonSectionHeader({ delay = 0 }: { delay?: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
      <SkeletonLine width={16} height={6} radius={1} delay={delay} />
      <SkeletonLine width={64} height={8} radius={2} delay={delay + 0.02} />
    </div>
  );
}

function ErrorBody({ onRetry }: { onRetry?: () => void }) {
  return (
    <div style={{ padding: "14px 14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <span style={{ color: "var(--cg-error)", display: "flex", alignItems: "center", flexShrink: 0, marginTop: 1 }}>
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
            <circle cx="8" cy="8" r="5.5" />
            <path d="M8 4.5v4M8 11.2v.1" />
          </svg>
        </span>
        <span style={{ fontSize: 11, fontWeight: 500, color: "var(--cg-text-primary)" }}>
          Failed to load data.
        </span>
      </div>
      <p style={{ margin: 0, fontSize: 11, color: "var(--cg-text-secondary)", lineHeight: 1.5 }}>
        The server returned an error while resolving this symbol.
      </p>
      {onRetry && (
        <div style={{ display: "flex", gap: 6 }}>
          <InlineBtn onClick={onRetry} primary>Retry</InlineBtn>
        </div>
      )}
    </div>
  );
}

function InlineBtn({ children, onClick, primary }: { children: React.ReactNode; onClick?: () => void; primary?: boolean }) {
  return (
    <button onClick={onClick} style={{
      height: 24, padding: "0 10px", borderRadius: 4,
      border: "1px solid var(--cg-border)", background: "transparent",
      color: primary ? "var(--cg-text-primary)" : "var(--cg-text-secondary)",
      fontSize: 11, cursor: "pointer", fontFamily: "inherit",
    }}>
      {children}
    </button>
  );
}
