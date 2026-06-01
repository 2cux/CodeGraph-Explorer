import type { NodeKind } from "./graphTransforms";

// ── Node type colors ───────────────────────────────────────────────────
// All values reference CSS custom properties from theme.css

export const NODE_TYPE_COLOR: Record<NodeKind, string> = {
  function: "var(--cg-node-function)",
  method: "var(--cg-node-method)",
  class: "var(--cg-node-class)",
  file: "var(--cg-node-file)",
  test: "var(--cg-node-test)",
  module: "var(--cg-node-module)",
  external_symbol: "var(--cg-node-external)",
  module_group: "var(--cg-node-group)",
  file_group: "var(--cg-node-file)",
  class_group: "var(--cg-node-class)",
};

export const NODE_TYPE_LABEL: Record<NodeKind, string> = {
  function: "FUNC",
  method: "METH",
  class: "CLASS",
  file: "FILE",
  test: "TEST",
  module: "MOD",
  external_symbol: "EXT",
  module_group: "MOD",
  file_group: "FILE",
  class_group: "CLASS",
};

// ── Node state CSS classes ─────────────────────────────────────────────
// Applied to the cg-rf-node wrapper div via className

export const NODE_STATE_CLASS = {
  default: "",
  hover: "",
  selected: "cg-node--selected",
  center: "cg-node--center",
  neighbor: "cg-node--neighbor",
  unrelated: "cg-node--unrelated",
  external: "cg-node--external",
  "low-confidence": "cg-node--low-confidence",
} as const;

export type NodeStateName = keyof typeof NODE_STATE_CLASS;

// ── Edge type styles ───────────────────────────────────────────────────
// Default style per edge type; low-confidence/external override still applies

export interface EdgeTypeStyle {
  stroke: string;
  strokeDasharray: string;
  opacity: number;
  strokeWidth: number;
}

export const EDGE_TYPE_STYLE: Record<string, EdgeTypeStyle> = {
  calls: {
    stroke: "var(--cg-edge-calls)",
    strokeDasharray: "none",
    opacity: 0.75,
    strokeWidth: 1.5,
  },
  tested_by: {
    stroke: "var(--cg-edge-tested_by)",
    strokeDasharray: "6 3",
    opacity: 0.65,
    strokeWidth: 1.5,
  },
  imports: {
    stroke: "var(--cg-edge-imports)",
    strokeDasharray: "none",
    opacity: 0.35,
    strokeWidth: 1,
  },
  references: {
    stroke: "var(--cg-edge-references)",
    strokeDasharray: "none",
    opacity: 0.35,
    strokeWidth: 1,
  },
  contains: {
    stroke: "var(--cg-edge-contains)",
    strokeDasharray: "2 4",
    opacity: 0.45,
    strokeWidth: 1,
  },
};

export const EDGE_TYPE_LABEL_COLOR: Record<string, string> = {
  calls: "var(--cg-text-secondary)",
  tested_by: "var(--cg-success)",
  imports: "var(--cg-text-muted)",
  references: "var(--cg-text-muted)",
  contains: "var(--cg-text-muted)",
};

// Low-confidence edge override
export const LOW_CONF_EDGE_STYLE: EdgeTypeStyle = {
  stroke: "var(--cg-warning)",
  strokeDasharray: "4 4",
  opacity: 0.5,
  strokeWidth: 1.5,
};

// External / unresolved edge override
export const EXTERNAL_EDGE_STYLE: EdgeTypeStyle = {
  stroke: "var(--cg-text-muted)",
  strokeDasharray: "2 6",
  opacity: 0.25,
  strokeWidth: 1,
};

// ── Confidence level helpers ────────────────────────────────────────────

export function confidenceLevel(c: number): "high" | "medium" | "low" | "unknown" {
  if (c >= 0.80) return "high";
  if (c >= 0.60) return "medium";
  if (c >= 0.40) return "low";
  return "unknown";
}

export function confidenceLabel(c: number): { label: string; tone: "success" | "warning" | "muted" } {
  if (c >= 0.80) return { label: "High", tone: "success" };
  if (c >= 0.60) return { label: "Medium", tone: "warning" };
  if (c >= 0.40) return { label: "Low", tone: "warning" };
  return { label: "Unknown", tone: "muted" };
}

// ── Node dimensions ─────────────────────────────────────────────────────

export const NODE_DIMS = {
  minWidth: 160,
  maxWidth: 240,
  minHeight: 52,
} as const;

// ── Layout presets ──────────────────────────────────────────────────────

export type LayoutPreset = "local" | "impact";

export const LAYOUT_PRESET_LABEL: Record<LayoutPreset, string> = {
  local: "Local",
  impact: "Impact",
};

export interface DagreConfig {
  rankdir: "LR" | "TB";
  nodesep: number;
  ranksep: number;
  marginx: number;
  marginy: number;
}

export const LAYOUT_PRESET_DAGRE: Record<LayoutPreset, DagreConfig> = {
  local: { rankdir: "LR", nodesep: 60, ranksep: 120, marginx: 60, marginy: 60 },
  impact: { rankdir: "TB", nodesep: 80, ranksep: 100, marginx: 60, marginy: 60 },
};
