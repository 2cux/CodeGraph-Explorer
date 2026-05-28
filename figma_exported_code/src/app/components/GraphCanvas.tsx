import { useState } from "react";
import type { CSSProperties } from "react";
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

// ── Graph canvas size (shared between SVG and HTML layers) ─────────────────
const CANVAS_W = 1300;
const CANVAS_H = 780;

// ── Focused view — positions designed for the focused (detailed) layout ───
const focusedNodes: Omit<GraphNodeData, "state">[] = [
  { id: "auth",      x: 360, y: 360, kind: "function",        name: "authenticate",    path: "src/auth.py:42",        confidence: 0.95 },
  { id: "login",     x: 180, y: 170, kind: "method",          name: "login",           path: "src/api/login.py:24",   confidence: 0.92 },
  { id: "test_auth", x: 180, y: 540, kind: "test",            name: "test_authenticate",path: "tests/test_auth.py:31", confidence: 0.90 },
  { id: "verify",    x: 620, y: 220, kind: "function",        name: "verify_token",    path: "src/auth.py:104",       confidence: 0.93 },
  { id: "hash",      x: 620, y: 360, kind: "function",        name: "hash_password",   path: "src/crypto.py:8",       confidence: 0.88 },
  { id: "query",     x: 620, y: 500, kind: "function",        name: "query_db",        path: "src/db.py:55",          confidence: 0.84 },
  { id: "mfa",       x: 860, y: 320, kind: "class",           name: "MFAForm",         path: "src/ui/mfa.tsx:18",     confidence: 0.86 },
  { id: "jwt",       x: 860, y: 180, kind: "external_symbol", name: "jwt.decode",      path: "pyjwt",                 confidence: 0.78 },
  { id: "session",   x: 880, y: 540, kind: "method",          name: "Session.create",  path: "src/session.py:67",     confidence: 0.82 },
  { id: "audit",     x:1020, y: 620, kind: "function",        name: "audit_log",       path: "src/audit.py:22",       confidence: 0.55 },
  { id: "user",      x:1040, y: 420, kind: "class",           name: "UserRepo",        path: "src/user.py:12",        confidence: 0.70 },
  { id: "rate",      x:  60, y: 250, kind: "function",        name: "rate_limit",      path: "src/middleware.py:45",  confidence: 0.60 },
  { id: "mw",        x:  60, y: 380, kind: "file",            name: "middleware.py",   path: "src/middleware.py",     confidence: 0.70 },
  { id: "db",        x:1040, y:  80, kind: "file",            name: "db.py",           path: "src/db.py",             confidence: 0.65 },
  { id: "sso",       x:  60, y:  90, kind: "file",            name: "sso_callback.py", path: "src/api/sso.py",        confidence: 0.66 },
  { id: "bcrypt",    x: 860, y: 660, kind: "external_symbol", name: "bcrypt.hash",     path: "bcrypt",                confidence: 0.70 },
  { id: "logger",    x: 380, y: 680, kind: "external_symbol", name: "logger.info",     path: "logging",               confidence: 0.60 },
  { id: "errs",      x: 200, y:  60, kind: "class",           name: "AuthError",       path: "src/errors.py:8",       confidence: 0.75 },
  { id: "settings",  x:1040, y: 700, kind: "class",           name: "Settings",        path: "src/config.py:14",      confidence: 0.60 },
  { id: "cache",     x:1180, y: 300, kind: "file",            name: "cache.py",        path: "src/cache.py",          confidence: 0.55 },
];

// ── Overview — clean left-to-right hierarchical layout ────────────────────
// Columns: [peripheral] → [callers] → [core] → [callees] → [deps] → [deep]
const overviewPositions: Record<string, { x: number; y: number }> = {
  // Col 0 (x=50): background entry points
  sso:       { x:  50, y:  75 },
  mw:        { x:  50, y: 205 },
  rate:      { x:  50, y: 330 },
  // Col 1 (x=275): primary callers
  errs:      { x: 275, y:  55 },
  login:     { x: 275, y: 195 },
  // Col 2 (x=500): core hub
  test_auth: { x: 500, y:  65 },
  auth:      { x: 500, y: 285 },
  logger:    { x: 500, y: 525 },
  // Col 3 (x=740): primary callees
  verify:    { x: 740, y: 130 },
  hash:      { x: 740, y: 255 },
  query:     { x: 740, y: 385 },
  mfa:       { x: 740, y: 510 },
  // Col 4 (x=965): external / data layer
  jwt:       { x: 965, y: 105 },
  bcrypt:    { x: 965, y: 255 },
  db:        { x: 965, y: 385 },
  user:      { x: 965, y: 510 },
  // Col 5 (x=1155): deep dependencies
  cache:     { x:1155, y: 325 },
  session:   { x:1155, y: 430 },
  audit:     { x:1155, y: 555 },
  settings:  { x:1155, y: 660 },
};

// Nodes that appear at reduced opacity in overview (background context)
const overviewDimmed = new Set(["sso", "mw", "rate", "errs", "bcrypt", "logger", "session", "audit", "settings", "cache"]);

const focusedEdges: { from: string; to: string; label: GraphEdgeData["label"]; lc?: boolean }[] = [
  // Primary flow (touches auth)
  { from: "login",     to: "auth",     label: "calls"     },
  { from: "test_auth", to: "auth",     label: "tested_by" },
  { from: "auth",      to: "verify",   label: "calls"     },
  { from: "auth",      to: "hash",     label: "calls"     },
  { from: "auth",      to: "query",    label: "calls"     },
  { from: "auth",      to: "mfa",      label: "references"},
  // Related ↔ external
  { from: "verify",    to: "jwt",      label: "imports"   },
  { from: "hash",      to: "bcrypt",   label: "imports",    lc: true },
  // Background
  { from: "sso",       to: "login",    label: "calls"     },
  { from: "rate",      to: "login",    label: "calls"     },
  { from: "mw",        to: "rate",     label: "contains"  },
  { from: "query",     to: "db",       label: "imports"   },
  { from: "query",     to: "user",     label: "references"},
  { from: "session",   to: "user",     label: "references"},
  { from: "session",   to: "audit",    label: "calls"     },
  { from: "user",      to: "cache",    label: "calls"     },
  { from: "auth",      to: "logger",   label: "calls"     },
  { from: "settings",  to: "session",  label: "references"},
  { from: "errs",      to: "auth",     label: "references"},
];

// Overview: only the core structural edges, no noise
const OVERVIEW_EDGE_SET = new Set([
  "login→auth", "auth→verify", "auth→hash", "auth→query", "auth→mfa",
  "sso→login", "test_auth→auth", "verify→jwt", "query→db", "query→user",
]);
const OVERVIEW_PRIMARY = new Set(["login→auth", "auth→verify", "auth→hash", "auth→query", "auth→mfa"]);

// ── Data builder ──────────────────────────────────────────────────────────
export function getGraph(state: CanvasState): { nodes: GraphNodeData[]; edges: GraphEdgeData[] } {
  const active  = new Set(["auth"]);
  const related = new Set(["login", "verify", "hash", "query", "mfa", "test_auth", "jwt"]);

  if (state === "overview") {
    const nodes = focusedNodes.map((n) => ({
      ...n,
      x: overviewPositions[n.id]?.x ?? n.x,
      y: overviewPositions[n.id]?.y ?? n.y,
      state: overviewDimmed.has(n.id) ? "dimmed" : "normal",
    } as GraphNodeData));

    const edges = focusedEdges
      .filter((e) => OVERVIEW_EDGE_SET.has(`${e.from}→${e.to}`))
      .map((e) => ({
        from: e.from,
        to: e.to,
        label: e.label,
        state: OVERVIEW_PRIMARY.has(`${e.from}→${e.to}`) ? "default" : "dimmed",
      } as GraphEdgeData));

    return { nodes, edges };
  }

  // focused
  const nodes = focusedNodes.map((n) => ({
    ...n,
    state: active.has(n.id) ? "active" : related.has(n.id) ? "related" : "dimmed",
  } as GraphNodeData));

  const edges = focusedEdges.map((e) => {
    const fromIn      = active.has(e.from) || related.has(e.from);
    const toIn        = active.has(e.to)   || related.has(e.to);
    const touchActive = active.has(e.from) || active.has(e.to);
    let s: EdgeState;
    if (fromIn && toIn && (touchActive || (related.has(e.from) && related.has(e.to)))) s = "active_flow";
    else s = "dimmed";
    if (e.lc && fromIn && toIn) s = "low_confidence";
    return { from: e.from, to: e.to, label: e.label, state: s } as GraphEdgeData;
  });

  return { nodes, edges };
}

// ── Canvas ────────────────────────────────────────────────────────────────
interface Props {
  state: CanvasState;
  onSelectEdge?: () => void;
}

export function GraphCanvas({ state, onSelectEdge }: Props) {
  if (state === "empty")   return <EmptyState />;
  if (state === "loading") return <LoadingState />;
  if (state === "error")   return <ErrorState />;

  const isOverview = state === "overview";
  const { nodes, edges } = getGraph(state);
  const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n]));

  // z-order: dimmed first, then default/lc, active_flow on top
  const ordered = [...edges].sort((a, b) => edgeZ(a.state) - edgeZ(b.state));

  return (
    <div
      style={{
        position: "relative",
        flex: 1,
        background: "var(--cg-bg-canvas)",
        overflow: "hidden",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <GridBackground />
      <CanvasControls />
      <CanvasStatusBar state={state} />
      <CanvasLegend />

      {/*
        Fixed-size inner stage: both the SVG layer (edges) and the HTML layer (nodes)
        share the exact same 1300×780 coordinate space.
        This eliminates the SVG viewBox vs HTML pixel mismatch.
      */}
      <div
        style={{
          position: "relative",
          width: CANVAS_W,
          height: CANVAS_H,
          flexShrink: 0,
        }}
      >
        {/* Edge layer (SVG) */}
        <svg
          width={CANVAS_W}
          height={CANVAS_H}
          style={{ position: "absolute", inset: 0, overflow: "visible" }}
        >
          <defs>
            {(["default", "active_flow", "dimmed", "low_confidence"] as EdgeState[]).map((s) => (
              <marker
                key={s}
                id={`arr-${s}`}
                viewBox="0 0 7 6"
                refX="7"
                refY="3"
                markerWidth="4"
                markerHeight="3.5"
                orient="auto"
              >
                {/* Clean filled arrowhead, tip at (7, 3) */}
                <path d="M0,0 L7,3 L0,6 L1.6,3 Z" fill={edgeStroke(s)} />
              </marker>
            ))}
          </defs>

          {ordered.map((e, i) => {
            const a = nodeMap[e.from];
            const b = nodeMap[e.to];
            if (!a || !b) return null;
            return (
              <Edge
                key={`${e.from}→${e.to}-${i}`}
                a={a}
                b={b}
                edge={e}
                onClick={onSelectEdge}
                canvasMode={isOverview ? "overview" : "focused"}
                obstacles={nodes}
              />
            );
          })}
        </svg>

        {/* Node layer (HTML — same coordinate space as SVG) */}
        {nodes.map((n) => (
          <GraphNodeView key={n.id} node={n} />
        ))}
      </div>
    </div>
  );
}

function edgeZ(s: EdgeState) {
  if (s === "dimmed")          return 0;
  if (s === "default")         return 1;
  if (s === "low_confidence")  return 2;
  return 3; // active_flow
}

// ── Edge geometry ─────────────────────────────────────────────────────────

type Anchor = { x: number; y: number; side: "L" | "R" | "T" | "B" };

/**
 * Pick complementary anchor ports on each node based on relative position.
 * Prefers horizontal (left/right) ports when nodes are not vertically stacked,
 * vertical otherwise. This keeps connections leaving from a node's edge
 * rather than crossing its body.
 */
function pickAnchors(a: GraphNodeData, b: GraphNodeData): { from: Anchor; to: Anchor } {
  const acx = a.x + NODE_W / 2;
  const acy = a.y + NODE_H / 2;
  const bcx = b.x + NODE_W / 2;
  const bcy = b.y + NODE_H / 2;
  const dx = bcx - acx;
  const dy = bcy - acy;

  // Treat as vertical only when nodes overlap horizontally significantly
  const horizontalOverlap = Math.abs(dx) < NODE_W * 0.55;
  const useVertical = horizontalOverlap && Math.abs(dy) > NODE_H;

  if (useVertical) {
    if (dy >= 0) {
      return {
        from: { x: acx, y: a.y + NODE_H, side: "B" },
        to:   { x: bcx, y: b.y,           side: "T" },
      };
    } else {
      return {
        from: { x: acx, y: a.y,           side: "T" },
        to:   { x: bcx, y: b.y + NODE_H, side: "B" },
      };
    }
  }
  // Horizontal
  if (dx >= 0) {
    return {
      from: { x: a.x + NODE_W, y: acy, side: "R" },
      to:   { x: b.x,           y: bcy, side: "L" },
    };
  }
  return {
    from: { x: a.x,           y: acy, side: "L" },
    to:   { x: b.x + NODE_W, y: bcy, side: "R" },
  };
}

/** Liang–Barsky segment vs axis-aligned rect intersection test. */
function segmentHitsRect(
  x1: number, y1: number, x2: number, y2: number,
  rx1: number, ry1: number, rx2: number, ry2: number,
): boolean {
  let t0 = 0, t1 = 1;
  const dx = x2 - x1, dy = y2 - y1;
  const p = [-dx, dx, -dy, dy];
  const q = [x1 - rx1, rx2 - x1, y1 - ry1, ry2 - y1];
  for (let i = 0; i < 4; i++) {
    if (p[i] === 0) {
      if (q[i] < 0) return false;
    } else {
      const r = q[i] / p[i];
      if (p[i] < 0) { if (r > t1) return false; if (r > t0) t0 = r; }
      else          { if (r < t0) return false; if (r < t1) t1 = r; }
    }
  }
  return t0 <= t1;
}

/**
 * Detect whether the straight line from (sx,sy) to (ex,ey) would pass
 * through any non-endpoint node bbox (with padding). If so, return a
 * vertical detour Y that routes the curve around the obstacle.
 */
function findDetourY(
  sx: number, sy: number, ex: number, ey: number,
  selfA: string, selfB: string,
  obstacles: GraphNodeData[],
): number | null {
  const PAD = 10;
  let best: { detour: number; midX: number } | null = null;
  for (const n of obstacles) {
    if (n.id === selfA || n.id === selfB) continue;
    if (n.state === "dimmed") continue; // dimmed nodes are visually receding; don't route around them
    const rx1 = n.x - PAD, ry1 = n.y - PAD;
    const rx2 = n.x + NODE_W + PAD, ry2 = n.y + NODE_H + PAD;
    if (!segmentHitsRect(sx, sy, ex, ey, rx1, ry1, rx2, ry2)) continue;
    const midY = (sy + ey) / 2;
    const above = ry1 - 14;
    const below = ry2 + 14;
    const pick = Math.abs(midY - above) <= Math.abs(midY - below) ? above : below;
    const midX = (n.x + NODE_W / 2);
    if (!best || Math.abs(midX - (sx + ex) / 2) < Math.abs(best.midX - (sx + ex) / 2)) {
      best = { detour: pick, midX };
    }
  }
  return best ? best.detour : null;
}

/**
 * Build a cubic bezier between two anchored ports. Control points are pulled
 * along each port's outward normal so curves leave/enter nodes perpendicular
 * to their edge — this keeps the line clearly separated from the node body.
 * Optionally bow the curve toward `detourY` to route around an obstacle.
 */
function edgeCurveFromAnchors(
  from: Anchor, to: Anchor,
  detourY: number | null,
): { d: string; mx: number; my: number } {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const span = Math.max(40, Math.hypot(dx, dy));
  const pull = Math.min(140, span * 0.42);

  const normal = (s: Anchor["side"]) => {
    if (s === "R") return { nx: 1,  ny: 0 };
    if (s === "L") return { nx: -1, ny: 0 };
    if (s === "B") return { nx: 0,  ny: 1 };
    return            { nx: 0,  ny: -1 };
  };
  const nf = normal(from.side);
  const nt = normal(to.side);

  let c1x = from.x + nf.nx * pull;
  let c1y = from.y + nf.ny * pull;
  let c2x = to.x   + nt.nx * pull;
  let c2y = to.y   + nt.ny * pull;

  // Obstacle detour: bow both control points toward detourY
  if (detourY !== null) {
    // Only adjust the axis perpendicular to a horizontal route
    if (from.side === "R" || from.side === "L") {
      c1y = from.y + (detourY - from.y) * 0.85;
      c2y = to.y   + (detourY - to.y)   * 0.85;
    }
  }

  const mx = 0.125 * from.x + 0.375 * c1x + 0.375 * c2x + 0.125 * to.x;
  const my = 0.125 * from.y + 0.375 * c1y + 0.375 * c2y + 0.125 * to.y;

  return { d: `M ${from.x} ${from.y} C ${c1x} ${c1y} ${c2x} ${c2y} ${to.x} ${to.y}`, mx, my };
}

// ── Edge color helpers ────────────────────────────────────────────────────
function edgeStroke(s: EdgeState): string {
  if (s === "active_flow")    return "var(--cg-accent)";
  if (s === "low_confidence") return "var(--cg-warning)";
  if (s === "dimmed")         return "var(--cg-text-muted)";
  return "var(--cg-text-secondary)";
}

function edgeLabelColor(s: EdgeState): string {
  if (s === "active_flow")    return "var(--cg-accent)";
  if (s === "low_confidence") return "var(--cg-warning)";
  return "var(--cg-text-secondary)";
}

function getLabelWidth(label: string) {
  return Math.max(34, label.length * 5.8 + 10);
}

// ── Edge component ────────────────────────────────────────────────────────
type CanvasMode = "overview" | "focused";

function Edge({
  a, b, edge, onClick, canvasMode, obstacles,
}: {
  a: GraphNodeData;
  b: GraphNodeData;
  edge: GraphEdgeData;
  onClick?: () => void;
  canvasMode: CanvasMode;
  obstacles: GraphNodeData[];
}) {
  const [hovered, setHovered] = useState(false);

  const { from, to } = pickAnchors(a, b);
  // Only run obstacle avoidance in focused mode — overview is already laid out
  // hierarchically and routing detours would add noise.
  const detourY = canvasMode === "focused"
    ? findDetourY(from.x, from.y, to.x, to.y, a.id, b.id, obstacles)
    : null;
  const { d, mx, my } = edgeCurveFromAnchors(from, to, detourY);

  const isActive = edge.state === "active_flow";
  const isDim    = edge.state === "dimmed";
  const isLC     = edge.state === "low_confidence";
  const stroke   = edgeStroke(edge.state);

  // ── Visual weight per mode ──
  let lineOpacity: number;
  let strokeWidth: number;
  let showArrow: boolean;
  let showLabel: boolean;
  let showHalo = false;

  if (canvasMode === "overview") {
    // Overview: relationships must be legible — bright primary lines,
    // always-on relation labels so users can read the structure at a glance.
    lineOpacity = isDim ? 0.32 : 0.92;
    strokeWidth = isDim ? 1    : 1.6;
    showArrow   = true;
    showLabel   = !isDim;
    showHalo    = !isDim && hovered;
  } else {
    // Focused: emphasise the active flow, recede background context.
    lineOpacity = isDim ? 0.1 : 1;
    strokeWidth = isActive ? 1.6 : isLC ? 1.2 : 1;
    showArrow   = !isDim;
    showLabel   = !isDim && (isActive || isLC || hovered);
    showHalo    = isActive || (hovered && !isDim);
  }

  const labelW = getLabelWidth(edge.label) + (isLC ? 10 : 0);

  return (
    <g
      className="cg-edge-group"
      onClick={!isDim ? onClick : undefined}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ cursor: isDim ? "default" : "pointer" }}
    >
      {/* Wide invisible hit area */}
      <path d={d} fill="none" stroke="transparent" strokeWidth="14" className="cg-edge-hit" />

      {/* Soft halo behind highlighted edges — preserves continuity over busy backgrounds */}
      {showHalo && (
        <path
          d={d}
          fill="none"
          stroke={isActive ? "var(--cg-accent)" : stroke}
          strokeWidth={strokeWidth + 4}
          strokeLinecap="round"
          opacity={isActive ? 0.18 : 0.12}
          pointerEvents="none"
        />
      )}

      {/* Visible edge line */}
      <path
        d={d}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={isActive && canvasMode === "focused" ? "4 3" : undefined}
        markerEnd={showArrow ? `url(#arr-${edge.state})` : undefined}
        opacity={lineOpacity}
        className={`cg-edge-line${isActive && canvasMode === "focused" ? " cg-edge-active" : ""}`}
      />

      {/* Label — positioned at bezier midpoint, never touching node borders */}
      {showLabel && (
        <g transform={`translate(${mx},${my})`} pointerEvents="none">
          {/* Occluding plate so the line beneath doesn't run through the label */}
          <rect
            x={-labelW / 2 - 1} y={-7.5}
            width={labelW + 2} height={15}
            rx={3}
            fill="var(--cg-bg-canvas)"
          />
          {/* Pill body */}
          <rect
            x={-labelW / 2} y={-7}
            width={labelW} height={14}
            rx={2.5}
            fill="var(--cg-bg-panel)"
            stroke={isActive || isLC ? stroke : "var(--cg-border-hover)"}
            strokeOpacity={isActive || isLC ? 0.7 : 0.9}
          />
          {/* LC warning icon */}
          {isLC && (
            <g transform={`translate(${-labelW / 2 + 6},0)`}>
              <path d="M0,3 L3,-3 L6,3 Z"
                fill="none" stroke="var(--cg-warning)"
                strokeWidth="0.9" strokeLinejoin="round"
              />
              <circle cx="3" cy="1.5" r="0.45" fill="var(--cg-warning)" />
            </g>
          )}
          {/* Label text */}
          <text
            x={isLC ? 5 : 0} y={2.5}
            textAnchor="middle"
            fontSize={9}
            fontFamily="'JetBrains Mono', monospace"
            fill={edgeLabelColor(edge.state)}
          >
            {edge.label}
          </text>
        </g>
      )}
    </g>
  );
}

// ── Node view ─────────────────────────────────────────────────────────────
export function GraphNodeView({ node, standalone }: { node: GraphNodeData; standalone?: boolean }) {
  const isActive  = node.state === "active";
  const isRelated = node.state === "related";
  const isDimmed  = node.state === "dimmed";
  const color = KIND_COLOR[node.kind];

  const style: CSSProperties = {
    position: standalone ? "relative" : "absolute",
    left:     standalone ? undefined : node.x,
    top:      standalone ? undefined : node.y,
    width:  NODE_W,
    height: NODE_H,
    borderRadius: 4,
    background: "var(--cg-bg-panel)",
    border: `1px solid ${
      isActive  ? "var(--cg-accent)" :
      isRelated ? "var(--cg-border-hover)" :
                  "var(--cg-border)"
    }`,
    boxShadow: isActive ? "0 0 0 1px var(--cg-accent-alpha)" : "none",
    opacity:   isDimmed ? 0.28 : 1,
    overflow:  "hidden",
    display:   "flex",
    cursor:    isDimmed ? "default" : "pointer",
    pointerEvents: isDimmed ? "none" : "auto",
    zIndex:    isActive ? 3 : isRelated ? 2 : 1,
  };

  return (
    <div className="cg-node" style={style}>
      {isActive && (
        <div
          className="cg-halo"
          style={{
            position: "absolute", inset: -5, borderRadius: 6,
            border: "1px solid var(--cg-accent)",
            pointerEvents: "none",
          }}
        />
      )}
      <div style={{ width: 2, background: color, flexShrink: 0 }} />
      <div
        style={{
          flex: 1, padding: "5px 8px 6px",
          display: "flex", flexDirection: "column", gap: 1, minWidth: 0,
        }}
      >
        {/* Row 1: kind badge + name */}
        <div className="flex items-center" style={{ gap: 5, minWidth: 0 }}>
          <span
            className="cg-mono"
            style={{ fontSize: 9, color, letterSpacing: 0.4, flexShrink: 0 }}
          >
            {KIND_LABEL[node.kind]}
          </span>
          <span
            className="cg-mono"
            style={{
              fontSize: 12,
              color: "var(--cg-text-primary)",
              fontWeight: isActive ? 500 : 400,
              overflow: "hidden", textOverflow: "ellipsis",
              whiteSpace: "nowrap", minWidth: 0, flex: 1,
            }}
          >
            {node.name}
          </span>
          {isRelated && (
            <span
              style={{
                width: 4, height: 4, borderRadius: 999,
                background: "var(--cg-accent)", flexShrink: 0,
              }}
            />
          )}
        </div>
        {/* Row 2: path + confidence */}
        <div className="flex items-center" style={{ gap: 5, minWidth: 0 }}>
          <span
            className="cg-mono"
            style={{
              fontSize: 10, color: "var(--cg-text-muted)",
              overflow: "hidden", textOverflow: "ellipsis",
              whiteSpace: "nowrap", flex: 1, minWidth: 0,
            }}
          >
            {node.path}
          </span>
          <span
            className="cg-mono"
            style={{ fontSize: 9, color: "var(--cg-text-muted)", flexShrink: 0, letterSpacing: 0.2 }}
          >
            {node.confidence.toFixed(2)}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Canvas chrome ─────────────────────────────────────────────────────────
function GridBackground() {
  return (
    <div
      style={{
        position: "absolute", inset: 0,
        backgroundImage: "radial-gradient(circle, var(--cg-grid) 1px, transparent 1px)",
        backgroundSize: "28px 28px",
        pointerEvents: "none",
        zIndex: 0,
      }}
    />
  );
}

function CanvasControls() {
  return (
    <div
      style={{
        position: "absolute", top: 12, left: 12,
        display: "flex", flexDirection: "column", gap: 4,
        zIndex: 10,
      }}
    >
      <ControlBtn label="+" />
      <ControlBtn label="−" />
      <ControlBtn label="⤢" />
    </div>
  );
}

function ControlBtn({ label }: { label: string }) {
  return (
    <button
      style={{
        width: 22, height: 22, borderRadius: 4,
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        color: "var(--cg-text-secondary)",
        fontSize: 11, cursor: "pointer",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      {label}
    </button>
  );
}

function CanvasStatusBar({ state }: { state: CanvasState }) {
  return (
    <div style={{ position: "absolute", top: 12, right: 12, display: "flex", gap: 4, zIndex: 10 }}>
      <Pill label="layout" value="hierarchical" />
      <Pill label="depth"  value="2" />
      <Pill
        label="filter"
        value={state === "focused" ? "related" : "all"}
        active={state === "focused"}
      />
    </div>
  );
}

function Pill({ label, value, active }: { label: string; value: string; active?: boolean }) {
  return (
    <div
      className="flex items-center"
      style={{
        gap: 5, height: 22, padding: "0 8px",
        background: "var(--cg-bg-panel)",
        border: `1px solid ${active ? "var(--cg-accent)" : "var(--cg-border)"}`,
        borderRadius: 4, fontSize: 10,
      }}
    >
      <span style={{ color: "var(--cg-text-muted)" }}>{label}</span>
      <span className="cg-mono" style={{ color: active ? "var(--cg-accent)" : "var(--cg-text-primary)" }}>
        {value}
      </span>
    </div>
  );
}

function CanvasLegend() {
  const items: { k: NodeKind; label: string }[] = [
    { k: "function",        label: "func"     },
    { k: "method",          label: "method"   },
    { k: "class",           label: "class"    },
    { k: "file",            label: "file"     },
    { k: "test",            label: "test"     },
    { k: "external_symbol", label: "external" },
  ];
  return (
    <div
      style={{
        position: "absolute", left: 12, top: 100, zIndex: 10,
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 4, padding: "6px 8px",
        display: "flex", flexDirection: "column", gap: 4,
      }}
    >
      {items.map((it) => (
        <div key={it.k} className="flex items-center" style={{ gap: 6, fontSize: 10 }}>
          <span style={{ width: 2, height: 10, background: KIND_COLOR[it.k], borderRadius: 1 }} />
          <span className="cg-mono" style={{ color: "var(--cg-text-secondary)" }}>{it.label}</span>
        </div>
      ))}
    </div>
  );
}

// ── Skeleton / state views ────────────────────────────────────────────────
const SKEL_NODES = [
  { x: 360, y: 340, w: NODE_W, h: NODE_H, accent: true  },
  { x: 180, y: 160, w: 144,   h: NODE_H, accent: false },
  { x: 180, y: 510, w: NODE_W, h: NODE_H, accent: false },
  { x: 620, y: 210, w: 148,   h: NODE_H, accent: false },
  { x: 620, y: 340, w: 148,   h: NODE_H, accent: false },
];
const SKEL_EDGES = [
  { x1: 252, y1: 183, x2: 360, y2: 363 },
  { x1: 252, y1: 533, x2: 360, y2: 363 },
  { x1: 528, y1: 363, x2: 620, y2: 233 },
  { x1: 528, y1: 363, x2: 620, y2: 363 },
];

function EmptyState() {
  return (
    <div
      style={{
        flex: 1, height: "100%",
        background: "var(--cg-bg-canvas)",
        display: "flex", alignItems: "center", justifyContent: "center",
        position: "relative",
      }}
    >
      <GridBackground />
      <div
        style={{
          position: "relative",
          textAlign: "center",
          maxWidth: 340,
          display: "flex", flexDirection: "column", alignItems: "center",
        }}
      >
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" style={{ marginBottom: 14, color: "var(--cg-text-muted)" }}>
          <circle cx="12" cy="12" r="4.5" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2 2" />
          <circle cx="36" cy="12" r="4.5" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2 2" />
          <circle cx="24" cy="36" r="4.5" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2 2" />
          <line x1="16" y1="13" x2="32" y2="13" stroke="currentColor" strokeWidth="1" strokeOpacity="0.35" strokeDasharray="2 3" />
          <line x1="13" y1="16" x2="22" y2="32" stroke="currentColor" strokeWidth="1" strokeOpacity="0.35" strokeDasharray="2 3" />
          <line x1="35" y1="16" x2="26" y2="32" stroke="currentColor" strokeWidth="1" strokeOpacity="0.35" strokeDasharray="2 3" />
        </svg>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--cg-text-primary)", marginBottom: 6 }}>
          No graph loaded.
        </div>
        <div style={{ fontSize: 11, color: "var(--cg-text-secondary)", lineHeight: 1.6, marginBottom: 14 }}>
          Run{" "}
          <code className="cg-mono" style={{ fontSize: 10, color: "var(--cg-accent)", background: "var(--cg-accent-alpha)", padding: "1px 5px", borderRadius: 3 }}>
            codegraph index
          </code>{" "}
          to scan your codebase,
          <br />
          or search for a symbol using the topbar search.
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <StateBtn>Run index</StateBtn>
          <StateBtn muted>Learn more →</StateBtn>
        </div>
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div style={{ flex: 1, height: "100%", background: "var(--cg-bg-canvas)", position: "relative", overflow: "hidden" }}>
      <GridBackground />
      <svg
        width="100%" height="100%"
        viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
      >
        {SKEL_EDGES.map((e, i) => (
          <line
            key={i}
            x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
            stroke="var(--cg-border)" strokeWidth="1"
            className="cg-skeleton-edge"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </svg>
      {SKEL_NODES.map((n, i) => (
        <div
          key={i}
          className="cg-skeleton"
          style={{
            position: "absolute",
            left: n.x, top: n.y,
            width: n.w, height: n.h,
            borderRadius: 4,
            border: "1px solid var(--cg-border)",
            overflow: "hidden", display: "flex",
            animationDelay: `${i * 0.1}s`,
          }}
        >
          <div style={{ width: 2, flexShrink: 0, background: n.accent ? "var(--cg-accent)" : "var(--cg-border)", opacity: n.accent ? 0.5 : 0.3 }} />
          <div style={{ flex: 1, padding: "6px 8px", display: "flex", flexDirection: "column", gap: 5 }}>
            <div style={{ height: 7, width: "55%", borderRadius: 2, background: "var(--cg-border)" }} />
            <div style={{ height: 6, width: "80%", borderRadius: 2, background: "var(--cg-border)", opacity: 0.6 }} />
          </div>
        </div>
      ))}
      <div style={{
        position: "absolute", left: "50%", top: "50%",
        transform: "translate(-50%, -50%)",
        display: "flex", alignItems: "center", gap: 8,
        padding: "7px 14px",
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 6,
        boxShadow: "0 4px 16px -8px rgba(0,0,0,0.3)",
        zIndex: 5,
      }}>
        <Spinner size={11} />
        <span style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>Loading graph...</span>
        <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>0.4s</span>
      </div>
    </div>
  );
}

function ErrorState() {
  return (
    <div style={{ flex: 1, height: "100%", background: "var(--cg-bg-canvas)", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
      <GridBackground />
      <div style={{ position: "relative", textAlign: "center", maxWidth: 340, display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{
          width: 36, height: 36, borderRadius: 6,
          background: "var(--cg-error-alpha)",
          border: "1px solid color-mix(in srgb, var(--cg-error) 25%, transparent)",
          display: "flex", alignItems: "center", justifyContent: "center",
          marginBottom: 14, color: "var(--cg-error)",
        }}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
            <circle cx="8" cy="8" r="5.5" />
            <path d="M8 4.5v4M8 11.2v.1" />
          </svg>
        </div>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--cg-text-primary)", marginBottom: 4 }}>Failed to load graph.</div>
        <div style={{ fontSize: 11, color: "var(--cg-text-secondary)", marginBottom: 10 }}>Check index status or retry.</div>
        <div className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)", background: "var(--cg-bg-subtle)", border: "1px solid var(--cg-border)", borderRadius: 4, padding: "4px 10px", marginBottom: 14, letterSpacing: 0.3 }}>
          GRAPH_LOAD_FAILED · src/auth.py:312
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <StateBtn>Retry</StateBtn>
          <StateBtn muted>View logs</StateBtn>
        </div>
      </div>
    </div>
  );
}

function StateBtn({ children, muted }: { children: React.ReactNode; muted?: boolean }) {
  return (
    <button
      style={{
        height: 26, padding: "0 12px",
        background: "transparent",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        color: muted ? "var(--cg-text-muted)" : "var(--cg-text-secondary)",
        fontSize: 11, cursor: "pointer", fontFamily: "inherit",
      }}
    >
      {children}
    </button>
  );
}
