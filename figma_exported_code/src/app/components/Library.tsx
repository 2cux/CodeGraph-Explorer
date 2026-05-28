import { GraphNodeView, type NodeKind, type NodeState } from "./GraphCanvas";
import { OutlineButton, Section, CodeBlock } from "./RightInspector";
import { Spinner } from "./Spinner";
import { IconClose, IconPlus, IconArrow } from "./icons";

export function Library({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="cg-scroll"
      style={{
        position: "absolute", inset: 0, zIndex: 30,
        background: "var(--cg-bg-canvas)",
        overflowY: "auto",
      }}
    >
      <div
        className="flex items-center justify-between"
        style={{
          position: "sticky", top: 0, zIndex: 1,
          height: 32, padding: "0 14px",
          background: "var(--cg-bg-panel)",
          borderBottom: "1px solid var(--cg-border)",
        }}
      >
        <div className="flex items-center" style={{ gap: 8, fontSize: 11, color: "var(--cg-text-secondary)" }}>
          <span>Component Library</span>
          <span style={{ color: "var(--cg-text-muted)" }}>·</span>
          <span className="cg-mono" style={{ color: "var(--cg-text-muted)" }}>v0.1</span>
        </div>
        <button
          onClick={onClose}
          style={{
            width: 22, height: 22, borderRadius: 4, border: "1px solid var(--cg-border)",
            background: "transparent", color: "var(--cg-text-secondary)", cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
        >
          <IconClose size={11} />
        </button>
      </div>

      <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 24, maxWidth: 980, margin: "0 auto" }}>
        <Group title="Design Tokens">
          <TokenGrid />
        </Group>

        <Group title="Graph Node — kinds × states">
          <NodeMatrix />
        </Group>

        <Group title="Graph Edge — states">
          <EdgeMatrix />
        </Group>

        <Group title="Buttons & Inputs">
          <Row>
            <OutlineButton label="Default" full={false} />
            <OutlineButton label="With Icon" icon={<IconPlus size={11} />} full={false} />
            <OutlineButton label="View Source" icon={<IconArrow size={11} />} full={false} />
          </Row>
          <Row>
            <FakeInput placeholder="Search symbols, files…" kbd="⌘K" width={220} />
            <FakeInput placeholder="Run task…" kbd="⌘P" width={160} />
          </Row>
        </Group>

        <Group title="Section & Code Block">
          <div style={{ maxWidth: 360, background: "var(--cg-bg-panel)", padding: 12, border: "1px solid var(--cg-border)", borderRadius: 4 }}>
            <Section title="Signature">
              <CodeBlock lines={["def authenticate(", "  username: str,", ") -> Session:"]} />
            </Section>
          </div>
        </Group>

        <Group title="Spinner">
          <Row>
            <Spinner size={12} />
            <Spinner size={14} />
            <Spinner size={18} />
          </Row>
        </Group>
      </div>
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div
        className="flex items-center"
        style={{
          gap: 6, fontSize: 10, letterSpacing: 0.6, textTransform: "uppercase",
          color: "var(--cg-text-muted)",
        }}
      >
        <span>──</span>
        <span>{title}</span>
        <span style={{ flex: 1, height: 1, background: "var(--cg-border)" }} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>{children}</div>
    </section>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex items-center" style={{ gap: 12, flexWrap: "wrap" }}>{children}</div>;
}

function TokenGrid() {
  const tokens = [
    "bg-canvas", "bg-panel", "bg-subtle", "bg-elevated",
    "border", "border-hover",
    "text-primary", "text-secondary", "text-muted",
    "accent", "accent-alpha",
    "success", "warning", "error",
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
      {tokens.map((t) => (
        <div
          key={t}
          className="flex items-center"
          style={{
            gap: 8, padding: 8,
            border: "1px solid var(--cg-border)", borderRadius: 4,
            background: "var(--cg-bg-panel)",
          }}
        >
          <div
            style={{
              width: 22, height: 22, borderRadius: 3,
              background: `var(--cg-${t})`,
              border: "1px solid var(--cg-border)",
            }}
          />
          <div className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>
            --cg-{t}
          </div>
        </div>
      ))}
    </div>
  );
}

function NodeMatrix() {
  const kinds: NodeKind[] = ["function", "method", "class", "file", "test", "external_symbol"];
  const states: NodeState[] = ["normal", "active", "related", "dimmed"];
  return (
    <div style={{ display: "grid", gridTemplateColumns: `120px repeat(${states.length}, 1fr)`, gap: 8, alignItems: "center" }}>
      <div />
      {states.map((s) => (
        <div key={s} className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>{s}</div>
      ))}
      {kinds.map((k) => (
        <Cells key={k} kind={k} states={states} />
      ))}
    </div>
  );
}

function Cells({ kind, states }: { kind: NodeKind; states: NodeState[] }) {
  return (
    <>
      <div className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>{kind}</div>
      {states.map((s) => (
        <div key={s} style={{ padding: 6, position: "relative", minHeight: 64 }}>
          <GraphNodeView
            standalone
            node={{
              id: `${kind}-${s}`,
              x: 0, y: 0,
              kind,
              name: sampleName(kind),
              path: samplePath(kind),
              confidence: 0.84,
              state: s,
            }}
          />
        </div>
      ))}
    </>
  );
}

function sampleName(k: NodeKind) {
  if (k === "function") return "authenticate";
  if (k === "method") return "Session.create";
  if (k === "class") return "MFAForm";
  if (k === "file") return "auth.py";
  if (k === "test") return "test_auth_mfa";
  return "jwt.decode";
}
function samplePath(k: NodeKind) {
  if (k === "function") return "src/auth.py:42";
  if (k === "method") return "src/session.py:67";
  if (k === "class") return "src/ui/mfa.tsx:18";
  if (k === "file") return "src/auth.py";
  if (k === "test") return "tests/test_auth.py:31";
  return "pyjwt";
}

function EdgeMatrix() {
  const labels = ["calls", "imports", "contains", "tested_by", "references"];
  const states = ["default", "active_flow", "dimmed", "low_confidence"];
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `120px repeat(${labels.length}, 1fr)`,
        gap: 8, alignItems: "center",
      }}
    >
      <div />
      {labels.map((l) => (
        <div key={l} className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>{l}</div>
      ))}
      {states.map((s) => (
        <RowEdge key={s} state={s} labels={labels} />
      ))}
    </div>
  );
}

function RowEdge({ state, labels }: { state: string; labels: string[] }) {
  return (
    <>
      <div className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>{state}</div>
      {labels.map((l) => (
        <EdgeSample key={l} label={l} state={state} />
      ))}
    </>
  );
}

function EdgeSample({ label, state }: { label: string; state: string }) {
  const color =
    state === "active_flow" ? "var(--cg-accent)" :
    state === "low_confidence" ? "var(--cg-warning)" :
    state === "dimmed" ? "var(--cg-border-hover)" : "var(--cg-text-muted)";
  return (
    <div style={{ height: 36, position: "relative" }}>
      <svg width="100%" height="36" viewBox="0 0 160 36">
        <defs>
          <marker id={`m-${state}-${label}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill={color} />
          </marker>
        </defs>
        <line
          x1="6" y1="18" x2="154" y2="18"
          stroke={color} strokeWidth={state === "active_flow" ? 1.4 : 1}
          markerEnd={`url(#m-${state}-${label})`}
          className={state === "active_flow" ? "cg-edge-active" : ""}
          opacity={state === "dimmed" ? 0.5 : 1}
        />
        <g transform="translate(80, 18)">
          <rect x={-getLW(label) / 2} y={-6.5} width={getLW(label)} height={13} rx={2}
            fill="var(--cg-bg-canvas)" stroke="var(--cg-border)" />
          <text x={0} y={3} textAnchor="middle" fontSize={9}
            fontFamily="'JetBrains Mono', monospace" fill={color}>
            {label}
          </text>
        </g>
      </svg>
    </div>
  );
}

function getLW(label: string) { return Math.max(34, label.length * 6 + 8); }

function FakeInput({ placeholder, kbd, width }: { placeholder: string; kbd: string; width: number }) {
  return (
    <div
      className="flex items-center"
      style={{
        gap: 6, height: 24, padding: "0 8px",
        border: "1px solid var(--cg-border)", borderRadius: 4,
        background: "var(--cg-bg-canvas)", width,
        color: "var(--cg-text-muted)",
      }}
    >
      <span style={{ fontSize: 11, flex: 1 }}>{placeholder}</span>
      <span className="cg-mono" style={{ fontSize: 10 }}>{kbd}</span>
    </div>
  );
}
