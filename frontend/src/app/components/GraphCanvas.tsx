import { useMemo, useState } from "react";
import dagre from "@dagrejs/dagre";
import { Spinner } from "./Spinner";
import type { OverviewResponse } from "../../api";

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

// ── Overview graph constants ─────────────────────────────────────────

const OV_NODE_W = 184;
const OV_NODE_H = 48;

const MODULE_COLORS = [
  "#6366f1", "#a78bfa", "#34d399", "#f59e0b",
  "#f87171", "#06b6d4", "#f472b6", "#fb923c",
];

function getModuleColor(module: string, map: Record<string, string>): string {
  if (map[module]) return map[module];
  const idx = Object.keys(map).length % MODULE_COLORS.length;
  map[module] = MODULE_COLORS[idx];
  return map[module];
}

function shortLabel(path: string, label: string): string {
  if (label === "__init__.py") {
    const parts = path.replace(/\\/g, "/").split("/");
    return parts[parts.length - 2] || label;
  }
  return label.replace(/\.py$/, "");
}

function parentDir(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/");
  return parts.slice(0, -1).join("/");
}

export interface EdgeIdentity {
  source: string;
  target: string;
  type: string;
}

interface Props {
  state: CanvasState;
  onSelectNode?: (nodeId: string) => void;
  onSelectFile?: (filePath: string) => void;
  onSelectEdge?: (edge: EdgeIdentity) => void;
  nodes?: GraphNodeData[];
  edges?: GraphEdgeData[];
  overviewData?: OverviewResponse | null;
}

export function GraphCanvas({ state, onSelectNode, onSelectFile, onSelectEdge, nodes: propNodes, edges: propEdges, overviewData }: Props) {
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);

  if (state === "loading") return <CanvasWrapper><LoadingState /></CanvasWrapper>;
  if (state === "error") return <CanvasWrapper><ErrorState /></CanvasWrapper>;
  if (state === "empty") return <CanvasWrapper><EmptyState /></CanvasWrapper>;

  if (state === "overview") {
    return (
      <CanvasWrapper>
        {overviewData ? <OverviewGraph data={overviewData} onSelectFile={onSelectFile} /> : <LoadingState />}
      </CanvasWrapper>
    );
  }

  // focused state — require real data, no mock fallback
  const nodes = propNodes;
  const edges = propEdges;

  if (!nodes || nodes.length === 0) {
    return <CanvasWrapper><EmptyState /></CanvasWrapper>;
  }

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
        {edges?.map((e) => {
          const from = getNode(e.from);
          const to = getNode(e.to);
          if (!from || !to) return null;
          return (
            <g
              key={edgeKey(e)}
              className="cg-edge-group"
              onClick={() => onSelectEdge?.({ source: e.from, target: e.to, type: e.label })}
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
        {hoveredNode && edges?.filter((e) => e.from === hoveredNode || e.to === hoveredNode).map((e) => {
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

function OverviewGraph({ data, onSelectFile }: { data: OverviewResponse; onSelectFile?: (fp: string) => void }) {
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const { layout, moduleColorMap } = useMemo(() => {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "LR", nodesep: 20, ranksep: 64, marginx: 40, marginy: 40 });
    g.setDefaultEdgeLabel(() => ({}));

    const colorMap: Record<string, string> = {};
    for (const n of data.nodes) {
      getModuleColor(n.module, colorMap);
      g.setNode(n.id, { width: OV_NODE_W, height: OV_NODE_H });
    }

    // Cap edges: keep top 200 most significant
    const topEdges = [...data.edges]
      .sort((a, b) => b.edge_count - a.edge_count)
      .slice(0, 200);
    for (const e of topEdges) {
      g.setEdge(e.source, e.target, { weight: e.edge_count });
    }

    dagre.layout(g);
    return { layout: g, moduleColorMap: colorMap };
  }, [data]);

  const gw = layout.graph().width ?? 800;
  const gh = layout.graph().height ?? 600;
  const pad = 60;
  const vw = gw + pad * 2;
  const vh = gh + pad * 2;

  return (
    <>
      {/* Stats bar */}
      <div
        style={{
          position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)",
          display: "flex", gap: 16, zIndex: 5,
          padding: "5px 14px", borderRadius: 6,
          background: "var(--cg-bg-panel)", border: "1px solid var(--cg-border)",
          fontSize: 10, color: "var(--cg-text-muted)",
        }}
      >
        <span style={{ color: "var(--cg-text-primary)", fontWeight: 600, fontSize: 11 }}>Overview</span>
        <span>{data.nodes.length} files</span>
        <span>{data.edges.length} dependencies</span>
        <span>{data.nodes.reduce((s, n) => s + n.symbol_count, 0)} symbols</span>
      </div>

      <svg width="100%" height="100%" viewBox={`0 0 ${vw} ${vh}`} style={{ display: "block", overflow: "visible" }}>
        <defs>
          <pattern id="grid-ov" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--cg-grid)" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width={vw} height={vh} fill="url(#grid-ov)" />

        {/* Edges */}
        {layout.edges().map((e: { v: string; w: string }) => {
          const edgeData = layout.edge(e.v, e.w);
          const pts = edgeData?.points || [];
          if (pts.length < 2) return null;
          const sx = pts[0].x + pad;
          const sy = pts[0].y + pad;
          const tx = pts[pts.length - 1].x + pad;
          const ty = pts[pts.length - 1].y + pad;
          return (
            <g key={`${e.v}→${e.w}`}>
              <line
                x1={sx} y1={sy} x2={tx} y2={ty}
                stroke="var(--cg-border-hover)" strokeWidth={Math.min(edgeData.weight || 1, 5)}
                opacity={0.4}
                markerEnd="url(#arrow-ov)"
              />
            </g>
          );
        })}

        {/* Arrow marker */}
        <defs>
          <marker id="arrow-ov" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto">
            <path d="M0,0 L6,3 L0,6 z" fill="var(--cg-border-hover)" />
          </marker>
        </defs>

        {/* Nodes */}
        {data.nodes.map((n) => {
          const pt = layout.node(n.id);
          if (!pt) return null;
          const x = pt.x - OV_NODE_W / 2 + pad;
          const y = pt.y - OV_NODE_H / 2 + pad;
          const modColor = moduleColorMap[n.module] || "var(--cg-text-muted)";
          const label = shortLabel(n.path, n.label);
          const dir = parentDir(n.path);
          const isHovered = hoveredNode === n.id;
          return (
            <foreignObject
              key={n.id}
              x={x} y={y} width={OV_NODE_W} height={OV_NODE_H}
              onMouseEnter={() => setHoveredNode(n.id)}
              onMouseLeave={() => setHoveredNode(null)}
              onClick={() => onSelectFile?.(n.id)}
              style={{ cursor: "pointer" }}
            >
              <div
                style={{
                  width: "100%", height: "100%",
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "0 8px",
                  background: isHovered ? "var(--cg-bg-subtle)" : "var(--cg-bg-panel)",
                  border: `1px solid ${isHovered ? modColor : "var(--cg-border)"}`,
                  borderLeft: `3px solid ${modColor}`,
                  borderRadius: 6, overflow: "hidden",
                  transition: "border-color 120ms ease, background 120ms ease",
                }}
              >
                <span style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: modColor, flexShrink: 0,
                }} />
                <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 0 }}>
                  <span
                    className="cg-mono"
                    style={{
                      fontSize: 11, fontWeight: 600,
                      color: "var(--cg-text-primary)",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}
                  >
                    {label}
                  </span>
                  <span
                    className="cg-mono"
                    style={{
                      fontSize: 9,
                      color: "var(--cg-text-muted)",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}
                  >
                    {dir}
                  </span>
                </div>
                <span
                  className="cg-mono"
                  style={{
                    fontSize: 9, fontWeight: 500,
                    color: "var(--cg-text-muted)", flexShrink: 0,
                    padding: "1px 4px", borderRadius: 2,
                    background: "var(--cg-bg-subtle)",
                  }}
                >
                  {n.symbol_count}
                </span>
              </div>
            </foreignObject>
          );
        })}
      </svg>
    </>
  );
}
