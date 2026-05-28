import { useState } from "react";
import { Spinner } from "./Spinner";

export type NodeKind = "function" | "method" | "class" | "file" | "test" | "external_symbol";
export type NodeState = "normal" | "active" | "related" | "dimmed";
export type EdgeState = "default" | "active_flow" | "dimmed" | "low_confidence";
export type CanvasState = "overview" | "focused" | "empty" | "loading" | "error";

export interface GraphNodeData {
  id: string;
  x: number;
  y: number;
  kind: NodeKind;
  name: string;
  path: string;
  confidence: number;
  state: NodeState;
}

export interface GraphEdgeData {
  from: string;
  to: string;
  label: "calls" | "imports" | "contains" | "tested_by" | "references";
  state: EdgeState;
}

const KIND_LABEL: Record<NodeKind, string> = {
  function: "FUNC",
  method: "METH",
  class: "CLASS",
  file: "FILE",
  test: "TEST",
  external_symbol: "EXT",
};

const KIND_COLOR: Record<NodeKind, string> = {
  function: "var(--cg-accent)",
  method: "#A78BFA",
  class: "var(--cg-success)",
  file: "var(--cg-text-secondary)",
  test: "#4ADE80",
  external_symbol: "var(--cg-warning)",
};

export const NODE_W = 168;
export const NODE_H = 46;

const CANVAS_W = 1300;
const CANVAS_H = 780;

const focusedNodes: Omit<GraphNodeData, "state">[] = [
  { id: "auth",      x: 360, y: 360, kind: "function",        name: "authenticate",    path: "src/auth.py:42",        confidence: 0.95 },
  { id: "login",     x: 180, y: 170, kind: "method",          name: "login",           path: "src/api/login.py:24",   confidence: 0.92 },
  { id: "test_auth", x: 180, y: 540, kind: "test",            name: "test_authenticate",path: "tests/test_auth.py:31", confidence: 0.90 },
  { id: "token",     x: 570, y: 190, kind: "function",        name: "verify_token",    path: "src/auth.py:104",       confidence: 0.78 },
  { id: "mfa",       x: 570, y: 340, kind: "class",           name: "MFAForm",         path: "src/ui/mfa.tsx:18",    confidence: 0.70 },
  { id: "session",   x: 570, y: 500, kind: "method",          name: "Session.create",   path: "src/session.py:67",    confidence: 0.62 },
  { id: "db",        x: 360, y: 140, kind: "file",            name: "database.py",     path: "src/db.py",            confidence: 0.85 },
  { id: "jwt",       x: 200, y: 370, kind: "external_symbol", name: "pyjwt.decode",    path: "pyjwt",                confidence: 0.55 },
];

const focusedEdges: GraphEdgeData[] = [
  { from: "login",  to: "auth",    label: "calls",      state: "active_flow" },
  { from: "auth",   to: "token",   label: "calls",      state: "default" },
  { from: "auth",   to: "jwt",     label: "calls",      state: "low_confidence" },
  { from: "auth",   to: "session", label: "calls",      state: "default" },
  { from: "auth",   to: "mfa",     label: "references", state: "default" },
  { from: "db",     to: "auth",    label: "contains",   state: "dimmed" },
  { from: "test_auth", to: "auth", label: "tested_by",  state: "default" },
  { from: "login",  to: "session", label: "calls",      state: "default" },
];

interface DashboardStatsData {
  project_name?: string;
  symbol_count?: number;
  file_count?: number;
  function_count?: number;
  class_count?: number;
  edge_count?: number;
  test_count?: number;
  module_count?: number;
  low_confidence_ratio?: number;
  last_indexed_at?: string | null;
}

interface GraphStatsData {
  symbol_count?: number;
  file_count?: number;
  edge_count?: number;
  function_count?: number;
  method_count?: number;
  class_count?: number;
  test_count?: number;
  module_count?: number;
  import_count?: number;
  low_confidence_edges?: number;
  low_confidence_ratio?: number;
}

interface Props {
  state: CanvasState;
  onSelectNode?: (nodeId: string) => void;
  onSelectEdge?: () => void;
  nodes?: GraphNodeData[];
  edges?: GraphEdgeData[];
  dashStats?: DashboardStatsData;
  graphStats?: GraphStatsData;
}

export function GraphCanvas({ state, onSelectNode, onSelectEdge, nodes: propNodes, edges: propEdges, dashStats, graphStats }: Props) {
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);

  if (state === "loading") return <CanvasWrapper><LoadingState /></CanvasWrapper>;
  if (state === "error") return <CanvasWrapper><ErrorState /></CanvasWrapper>;
  if (state === "empty") return <CanvasWrapper><EmptyState /></CanvasWrapper>;

  if (state === "overview") {
    return (
      <CanvasWrapper>
        <OverviewContent dashStats={dashStats} graphStats={graphStats} />
      </CanvasWrapper>
    );
  }

  // focused state
  const nodes = propNodes ?? focusedNodes.map((n) => ({ ...n, state: "normal" as NodeState }));
  const edges = propEdges ?? focusedEdges;

  const getNode = (id: string) => nodes.find((n) => n.id === id);
  const edgeKey = (e: GraphEdgeData) => `${e.from}→${e.to}`;

  return (
    <CanvasWrapper>
      <svg width="100%" height="100%" viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`} style={{ display: "block", overflow: "visible" }}>
        {/* Grid */}
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--cg-grid)" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width={CANVAS_W} height={CANVAS_H} fill="url(#grid)" />

        {/* Edges */}
        {edges.map((e) => {
          const from = getNode(e.from);
          const to = getNode(e.to);
          if (!from || !to) return null;
          return (
            <g
              key={edgeKey(e)}
              className="cg-edge-group"
              onClick={onSelectEdge}
              onMouseEnter={() => setHoveredEdge(edgeKey(e))}
              onMouseLeave={() => setHoveredEdge(null)}
            >
              {/* Hit area */}
              <line
                x1={from.x + NODE_W / 2} y1={from.y + NODE_H / 2}
                x2={to.x + NODE_W / 2} y2={to.y + NODE_H / 2}
                className="cg-edge-hit"
              />
              {/* Visible line */}
              <line
                x1={from.x + NODE_W / 2} y1={from.y + NODE_H / 2}
                x2={to.x + NODE_W / 2} y2={to.y + NODE_H / 2}
                className="cg-edge-line"
                stroke={edgeStrokeColor(e.state)}
                strokeWidth={hoveredEdge === edgeKey(e) ? 1.5 : 1}
                markerEnd={`url(#arrow-${e.state})`}
              />
              {/* Label */}
              <g
                className="cg-edge-label"
                opacity={hoveredEdge === edgeKey(e) ? 1 : 0.6}
                transform={`translate(${(from.x + to.x) / 2 + NODE_W / 2},${(from.y + to.y) / 2 + NODE_H / 2})`}
              >
                <rect x={-getLW(e.label) / 2} y={-6.5} width={getLW(e.label)} height={13} rx={2}
                  fill="var(--cg-bg-canvas)" stroke="var(--cg-border)" />
                <text x={0} y={3} textAnchor="middle" fontSize={8}
                  fontFamily="'JetBrains Mono', monospace" fill={edgeStrokeColor(e.state)}>
                  {e.label}
                </text>
              </g>
            </g>
          );
        })}

        {/* Edge markers */}
        <defs>
          {(["default", "active_flow", "dimmed", "low_confidence"] as EdgeState[]).map((s) => (
            <marker key={s} id={`arrow-${s}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" fill={edgeStrokeColor(s)} />
            </marker>
          ))}
        </defs>

        {/* Nodes */}
        {nodes.map((n) => (
          <foreignObject
            key={n.id}
            x={n.x}
            y={n.y}
            width={NODE_W}
            height={NODE_H}
            onMouseEnter={() => setHoveredNode(n.id)}
            onMouseLeave={() => setHoveredNode(null)}
            onClick={() => onSelectNode?.(n.id)}
            style={{ cursor: "pointer" }}
          >
            <GraphNodeView node={n} />
          </foreignObject>
        ))}

        {/* Halo on hovered node's edges */}
        {hoveredNode && edges.filter((e) => e.from === hoveredNode || e.to === hoveredNode).map((e) => {
          const from = getNode(e.from);
          const to = getNode(e.to);
          if (!from || !to) return null;
          return (
            <circle
              key={`halo-${edgeKey(e)}`}
              className="cg-halo"
              cx={(from.x + to.x) / 2 + NODE_W / 2}
              cy={(from.y + to.y) / 2 + NODE_H / 2}
              r={4}
              fill={edgeStrokeColor(e.state)}
            />
          );
        })}
      </svg>
    </CanvasWrapper>
  );
}

export function GraphNodeView({ node, standalone: _standalone }: { node: GraphNodeData; standalone?: boolean }) {
  const isDimmed = node.state === "dimmed";
  const isActive = node.state === "active";
  const isRelated = node.state === "related";

  const borderColor = isActive
    ? KIND_COLOR[node.kind]
    : isRelated
    ? "var(--cg-accent)"
    : "var(--cg-border)";

  const bgColor = isActive
    ? "color-mix(in srgb, var(--cg-accent) 6%, transparent)"
    : "var(--cg-bg-panel)";

  return (
    <div
      className="cg-node flex items-center"
      style={{
        width: "100%",
        height: "100%",
        padding: "0 10px",
        gap: 8,
        background: bgColor,
        border: `1px solid ${borderColor}`,
        borderRadius: 6,
        opacity: isDimmed ? 0.4 : 1,
        overflow: "hidden",
      }}
    >
      <span
        className="cg-mono"
        style={{
          fontSize: 9,
          color: KIND_COLOR[node.kind],
          letterSpacing: 0.5,
          flexShrink: 0,
          width: 32,
          fontWeight: 500,
        }}
      >
        {KIND_LABEL[node.kind]}
      </span>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
        <span
          className="cg-mono"
          style={{
            fontSize: 11,
            color: "var(--cg-text-primary)",
            fontWeight: 500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {node.name}
        </span>
        <span
          className="cg-mono"
          style={{
            fontSize: 9,
            color: "var(--cg-text-muted)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {node.path}
        </span>
      </div>
      {node.confidence < 0.8 && (
        <span
          style={{
            fontSize: 9,
            color: node.confidence < 0.6 ? "var(--cg-warning)" : "var(--cg-text-muted)",
            flexShrink: 0,
          }}
        >
          {node.confidence.toFixed(2)}
        </span>
      )}
    </div>
  );
}

function edgeStrokeColor(state: EdgeState) {
  if (state === "active_flow") return "var(--cg-accent)";
  if (state === "low_confidence") return "var(--cg-warning)";
  if (state === "dimmed") return "var(--cg-border-hover)";
  return "var(--cg-text-muted)";
}

function getLW(label: string) { return Math.max(34, label.length * 6 + 8); }

function CanvasWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        overflow: "hidden",
        background: "var(--cg-bg-canvas)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {children}
    </div>
  );
}

function LoadingState() {
  return (
    <div
      className="flex items-center"
      style={{ gap: 10, color: "var(--cg-text-muted)" }}
    >
      <Spinner size={18} />
      <span style={{ fontSize: 12 }}>Loading graph...</span>
    </div>
  );
}

function ErrorState() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
        color: "var(--cg-text-muted)",
      }}
    >
      <svg width="24" height="24" viewBox="0 0 16 16" fill="none" stroke="var(--cg-error)" strokeWidth="1.4" strokeLinecap="round">
        <circle cx="8" cy="8" r="5.5" />
        <path d="M8 4.5v4M8 11.2v.1" />
      </svg>
      <span style={{ fontSize: 12, color: "var(--cg-text-secondary)" }}>
        Failed to load graph data.
      </span>
    </div>
  );
}

function EmptyState() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
        color: "var(--cg-text-muted)",
      }}
    >
      <svg width="24" height="24" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
        <circle cx="8" cy="8" r="5.5" />
        <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" />
      </svg>
      <span style={{ fontSize: 12, color: "var(--cg-text-secondary)" }}>
        No graph data available.
      </span>
      <span style={{ fontSize: 10 }}>Index a project to get started.</span>
    </div>
  );
}

function OverviewContent({ dashStats, graphStats }: { dashStats?: DashboardStatsData; graphStats?: GraphStatsData }) {
  const s = graphStats || dashStats || {} as Record<string, unknown>;

  function stat(label: string, value: unknown, fallback: number | string) {
    return { label, value: String(value ?? fallback) };
  }

  const stats = [
    stat("symbols", s.symbol_count, 1284),
    stat("files", s.file_count, 147),
    stat("edges", s.edge_count, 4392),
    stat("functions", s.function_count, 612),
    stat("classes", s.class_count, 89),
    stat("tests", s.test_count, 203),
    stat("modules", s.module_count, 24),
    stat("confidence", s.low_confidence_ratio != null ? (1 - Number(s.low_confidence_ratio)).toFixed(2) : null, "0.87"),
  ];

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 24,
        padding: 40,
      }}
    >
      <div
        style={{
          fontSize: 11,
          color: "var(--cg-text-muted)",
          letterSpacing: 0.5,
          textTransform: "uppercase",
        }}
      >
        Project Overview
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
          width: "100%",
          maxWidth: 640,
        }}
      >
        {stats.map((s) => (
          <div
            key={s.label}
            style={{
              padding: "14px 16px",
              background: "var(--cg-bg-panel)",
              border: "1px solid var(--cg-border)",
              borderRadius: 6,
              textAlign: "center",
            }}
          >
            <div
              className="cg-mono"
              style={{ fontSize: 18, fontWeight: 600, color: "var(--cg-text-primary)" }}
            >
              {s.value}
            </div>
            <div style={{ fontSize: 10, color: "var(--cg-text-muted)", marginTop: 2 }}>
              {s.label}
            </div>
          </div>
        ))}
      </div>
      <div
        className="flex items-center"
        style={{ gap: 12, fontSize: 10, color: "var(--cg-text-muted)" }}
      >
        <span style={{ color: "var(--cg-success)" }}>●</span>
        <span>Last indexed 2 minutes ago</span>
        <span>·</span>
        <span style={{ color: "var(--cg-warning)" }}>47 low-confidence edges</span>
      </div>
    </div>
  );
}
