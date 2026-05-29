import { IconClose, IconArrow, IconPlus } from "./icons";
import { Spinner } from "./Spinner";

export type InspectorTarget = "node" | "edge";
export type InspectorMode = "node" | "edge" | "loading" | "error";

interface Props {
  target?: InspectorTarget;
  mode?: InspectorMode;
  onClose: () => void;
  onSwitch?: (t: InspectorTarget) => void;
  onRetry?: () => void;
}

export function RightInspector({
  target = "node",
  mode,
  onClose,
  onSwitch,
  onRetry,
}: Props) {
  const effective: InspectorMode = mode ?? target;
  return (
    <aside
      className="cg-scroll"
      style={{
        width: 360,
        flex: "0 0 360px",
        background: "var(--cg-bg-panel)",
        borderLeft: "1px solid var(--cg-border)",
        height: "100%",
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <InspectorHeader target={target} onClose={onClose} onSwitch={onSwitch} />
      {effective === "node" && <NodeInspector />}
      {effective === "edge" && <EdgeInspector />}
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
        borderBottom: "1px solid var(--cg-border)",
        flexShrink: 0,
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

function InspectorSection({
  title, children, first = false,
}: { title: string; children: React.ReactNode; first?: boolean }) {
  return (
    <section
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        paddingTop: first ? 0 : 14,
        borderTop: first ? "none" : "1px solid var(--cg-border)",
        marginTop: first ? 0 : 14,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 10,
          letterSpacing: 0.5,
          fontWeight: 600,
          color: "var(--cg-text-secondary)",
          textTransform: "none",
        }}
      >
        <span style={{ color: "var(--cg-text-muted)" }}>──</span>
        <span>{title}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>{children}</div>
    </section>
  );
}

export function CodeBlock({ lines, language = "py" }: { lines: string[]; language?: "py" | "plain" }) {
  return (
    <pre
      className="cg-mono"
      style={{
        margin: 0,
        padding: 8,
        background: "var(--cg-bg-subtle)",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        fontSize: 11,
        lineHeight: 1.55,
        color: "var(--cg-text-primary)",
        overflowX: "auto",
        whiteSpace: "pre",
      }}
    >
      {lines.map((l, i) => (
        <div key={i}>{language === "py" ? colorize(l) : l}</div>
      ))}
    </pre>
  );
}

function colorize(line: string) {
  const tokens = line.split(/(\bdef\b|\bif\b|\bis\b|\bnot\b|\bNone\b|\breturn\b|\bstr\b|\bint\b|\bUser\b|\bSession\b|->)/);
  return tokens.map((t, i) => {
    if (["def", "if", "is", "not", "return"].includes(t))
      return <span key={i} style={{ color: "var(--cg-accent)" }}>{t}</span>;
    if (["str", "int", "None", "User", "Session"].includes(t))
      return <span key={i} style={{ color: "var(--cg-success)" }}>{t}</span>;
    if (t === "->") return <span key={i} style={{ color: "var(--cg-text-muted)" }}>{t}</span>;
    return <span key={i}>{t}</span>;
  });
}

function NodeInspector() {
  return (
    <div style={{ padding: "12px 14px 16px", display: "flex", flexDirection: "column" }}>
      <NodeIdentity kind="FUNC" name="authenticate" location="src/auth.py:42-78" />

      <InspectorSection title="Signature">
        <CodeBlock lines={[
          "def authenticate(",
          "  username: str,",
          "  password: str",
          ") -> User",
        ]} />
      </InspectorSection>

      <InspectorSection title="Summary">
        <p style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: "var(--cg-text-secondary)" }}>
          Authenticates user credentials against the database. Called at login and token refresh.
        </p>
      </InspectorSection>

      <InspectorSection title="Selection Reason">
        <ReasonLine>Entry point for login flow.</ReasonLine>
        <KV label="Match" value="name, docstring" />
        <KV label="Confidence" value="0.95 (High)" tone="success" mono />
        <KV label="Resolution" value="FastAPI route decorator" />
      </InspectorSection>

      <InspectorSection title="Relations">
        <RelationList title="Callers" rows={[
          { kind: "METH", name: "login", relation: "calls", confidence: 0.95 },
          { kind: "FUNC", name: "verify_token", relation: "calls", confidence: 0.72 },
          { kind: "FUNC", name: "handle_session", relation: "calls", confidence: 0.68 },
        ]} />
        <RelationList title="Callees" rows={[
          { kind: "FUNC", name: "hash_password", relation: "calls", confidence: 0.95 },
          { kind: "FUNC", name: "query_db", relation: "calls", confidence: 0.88 },
        ]} />
        <RelationList title="Tests" rows={[
          { kind: "TEST", name: "test_authenticate", relation: "tests", confidence: 0.9 },
        ]} />
      </InspectorSection>

      <InspectorSection title="Actions">
        <OutlineButton icon={<IconPlus size={11} />} label="Add to Context Pack" />
        <OutlineButton label="Generate Context Pack" />
        <OutlineButton label="Analyze Impact" />
        <OutlineButton label="View Source" icon={<IconArrow size={11} />} />
      </InspectorSection>
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
            fontSize: 9,
            color: kindColor(kind),
            letterSpacing: 0.5,
            padding: "1px 5px",
            background: `color-mix(in srgb, ${kindColor(kind)} 14%, transparent)`,
            borderRadius: 2,
          }}
        >
          {kind}
        </span>
        <span
          className="cg-mono"
          style={{ fontSize: 13, color: "var(--cg-text-primary)", fontWeight: 500 }}
        >
          {name}
        </span>
      </div>
      <div className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>
        {location}
      </div>
    </div>
  );
}

function confidenceLevelLabel(c: number): { label: string; tone: "success" | "warning" | "muted" } {
  if (c >= 0.80) return { label: "High", tone: "success" };
  if (c >= 0.60) return { label: "Medium", tone: "warning" };
  if (c >= 0.40) return { label: "Low", tone: "warning" };
  return { label: "Unknown", tone: "muted" };
}

function resolutionLabel(r: string): string {
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

function EdgeInspector() {
  const confidence = 0.72;
  const level = confidenceLevelLabel(confidence);
  const resolution = "imported_function_exact";
  const isLow = confidence < 0.80;
  const evidence = {
    import_statement: "from app.services.auth_service import verify_token",
    local_name: "verify_token",
    matched_symbol_id: "app/services/auth_service.py::verify_token",
    source_location: { file_path: "app/api/auth.py", line_start: 45 },
  };

  return (
    <div style={{ padding: "12px 14px 16px", display: "flex", flexDirection: "column" }}>
      <EdgeIdentity from="authenticate" to="verify_token" />

      <InspectorSection title="Properties">
        <KV label="Type" value="calls" mono />
        <KV label="Confidence" value={`${confidence.toFixed(2)} (${level.label})`} tone={level.tone} mono />
        <KV label="Resolution" value={resolutionLabel(resolution)} mono />
      </InspectorSection>

      <InspectorSection title="Source Location">
        <div className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>
          auth.py:45
        </div>
        <CodeBlock lines={["result = verify_token(current_user.token)"]} language="py" />
      </InspectorSection>

      <InspectorSection title="Reason">
        <p style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: "var(--cg-text-secondary)" }}>
          Resolved `verify_token` via from-import.
        </p>
      </InspectorSection>

      <InspectorSection title="Evidence">
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <KV label="Import" value={evidence.import_statement} />
          <KV label="Matched" value={evidence.matched_symbol_id} />
          <KV label="Location" value={`${evidence.source_location.file_path}:${evidence.source_location.line_start}`} />
        </div>
      </InspectorSection>

      {isLow && <LowConfidenceNotice />}

      <InspectorSection title="Actions">
        <OutlineButton label="Navigate to Source" icon={<IconArrow size={11} />} />
      </InspectorSection>
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
            fontSize: 9,
            color: "var(--cg-accent)",
            letterSpacing: 0.5,
            padding: "1px 5px",
            background: "var(--cg-accent-alpha)",
            borderRadius: 2,
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

function LowConfidenceNotice() {
  return (
    <div
      style={{
        marginTop: 14,
        padding: "8px 10px",
        background: "var(--cg-warning-alpha)",
        border: "1px solid color-mix(in srgb, var(--cg-warning) 35%, transparent)",
        borderRadius: 4,
        display: "flex",
        gap: 8,
      }}
    >
      <span style={{ color: "var(--cg-warning)", flexShrink: 0, lineHeight: 1, paddingTop: 1 }}>
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round">
          <path d="M8 2.5L14 13.5H2L8 2.5zM8 7v3M8 11.6v.1" />
        </svg>
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, color: "var(--cg-warning)", fontWeight: 500 }}>Low-confidence edge</div>
        <div style={{ fontSize: 11, color: "var(--cg-text-secondary)", lineHeight: 1.5, marginTop: 2 }}>
          This edge was resolved at medium confidence. Verify manually if this is a critical code path.
        </div>
      </div>
    </div>
  );
}

export interface RelationRow {
  kind: string;
  name: string;
  relation: string;
  confidence: number;
}

function RelationList({ title, rows }: { title: string; rows: RelationRow[] }) {
  return (
    <div>
      <div
        className="flex items-center"
        style={{
          fontSize: 10,
          color: "var(--cg-text-muted)",
          gap: 6,
          padding: "0 2px 4px",
        }}
      >
        <span>{title}</span>
        <span className="cg-mono">({rows.length})</span>
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {rows.map((r, i) => (
          <li
            key={i}
            className="flex items-center"
            style={{
              gap: 8,
              padding: "3px 4px",
              borderRadius: 3,
              fontSize: 11,
              cursor: "pointer",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--cg-bg-subtle)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          >
            <span
              className="cg-mono"
              style={{
                fontSize: 9,
                color: kindColor(r.kind),
                letterSpacing: 0.3,
                flexShrink: 0,
                width: 32,
              }}
            >
              {r.kind}
            </span>
            <span
              className="cg-mono"
              style={{
                color: "var(--cg-text-primary)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                flex: 1,
                minWidth: 0,
              }}
            >
              {r.name}
            </span>
            <span
              className="cg-mono"
              style={{
                fontSize: 10,
                color: "var(--cg-text-muted)",
                flexShrink: 0,
              }}
            >
              {r.relation}
            </span>
            <span
              className="cg-mono"
              style={{
                fontSize: 10,
                color: confColor(r.confidence),
                width: 32,
                textAlign: "right",
                flexShrink: 0,
              }}
            >
              {r.confidence.toFixed(2)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function KV({
  label, value, tone, mono,
}: { label: string; value: string; tone?: "success" | "warning"; mono?: boolean }) {
  const color =
    tone === "success" ? "var(--cg-success)" :
    tone === "warning" ? "var(--cg-warning)" :
    "var(--cg-text-primary)";
  return (
    <div className="flex items-center" style={{ gap: 8, fontSize: 11 }}>
      <span style={{ width: 92, color: "var(--cg-text-muted)" }}>{label}</span>
      <span className={mono ? "cg-mono" : ""} style={{ color }}>{value}</span>
    </div>
  );
}

function ReasonLine({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: "var(--cg-text-primary)" }}>
      {children}
    </p>
  );
}

function kindColor(kind: string) {
  if (kind === "FUNC") return "var(--cg-accent)";
  if (kind === "METH") return "#A78BFA";
  if (kind === "CLASS") return "var(--cg-success)";
  if (kind === "TEST") return "#4ADE80";
  if (kind === "FILE") return "var(--cg-text-secondary)";
  if (kind === "EXT") return "var(--cg-warning)";
  return "var(--cg-text-secondary)";
}

function confColor(c: number) {
  if (c >= 0.85) return "var(--cg-success)";
  if (c >= 0.7) return "var(--cg-text-secondary)";
  return "var(--cg-warning)";
}

export function OutlineButton({
  label, icon, full = true,
}: { label: string; icon?: React.ReactNode; full?: boolean }) {
  return (
    <button
      className="flex items-center"
      style={{
        gap: 6,
        height: 26,
        padding: "0 10px",
        background: "transparent",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        color: "var(--cg-text-primary)",
        fontSize: 11,
        cursor: "pointer",
        justifyContent: "flex-start",
        width: full ? "100%" : undefined,
        fontFamily: "inherit",
        transition: "background 120ms ease, border-color 120ms ease",
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
      <div style={{ height: 14 }} />
      <SkeletonSectionHeader delay={0.26} />
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {[80, 95, 70].map((w, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <SkeletonLine width={28} height={9} radius={2} delay={0.28 + i * 0.04} />
            <SkeletonLine width={`${w}px`} height={9} radius={2} delay={0.3 + i * 0.04} />
          </div>
        ))}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginTop: 20,
          paddingTop: 14,
          borderTop: "1px solid var(--cg-border)",
        }}
      >
        <Spinner size={11} />
        <span style={{ fontSize: 11, color: "var(--cg-text-muted)" }}>
          Loading symbol details...
        </span>
      </div>
    </div>
  );
}

function SkeletonLine({
  width, height = 8, radius = 2, delay = 0,
}: {
  width: number | string; height?: number; radius?: number; delay?: number;
}) {
  return (
    <div
      className="cg-skeleton"
      style={{ height, width, borderRadius: radius, animationDelay: `${delay}s`, flexShrink: 0 }}
    />
  );
}

function SkeletonBlock({ height, delay = 0 }: { height: number; delay?: number }) {
  return (
    <div
      className="cg-skeleton"
      style={{ height, borderRadius: 4, border: "1px solid var(--cg-border)", animationDelay: `${delay}s` }}
    />
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
          Failed to load symbol details.
        </span>
      </div>
      <p style={{ margin: 0, fontSize: 11, color: "var(--cg-text-secondary)", lineHeight: 1.5 }}>
        The index server returned an error while resolving this symbol's relations.
      </p>
      <div
        className="cg-mono"
        style={{
          padding: "6px 8px",
          background: "var(--cg-bg-subtle)",
          border: "1px solid var(--cg-border)",
          borderRadius: 4,
          fontSize: 10,
          color: "var(--cg-text-muted)",
          lineHeight: 1.5,
        }}
      >
        IndexError: symbol_id=auth.authenticate
        <br />
        not found in cache
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <InlineBtn onClick={onRetry} primary>Retry</InlineBtn>
        <InlineBtn>View log</InlineBtn>
      </div>
    </div>
  );
}

function InlineBtn({
  children, onClick, primary,
}: { children: React.ReactNode; onClick?: () => void; primary?: boolean }) {
  return (
    <button
      onClick={onClick}
      style={{
        height: 24, padding: "0 10px", borderRadius: 4,
        border: "1px solid var(--cg-border)", background: "transparent",
        color: primary ? "var(--cg-text-primary)" : "var(--cg-text-secondary)",
        fontSize: 11, cursor: "pointer", fontFamily: "inherit",
      }}
    >
      {children}
    </button>
  );
}
