import type { Node, Edge } from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import type { SubgraphResponse, NeighborsResponse, GraphNodeItem, GraphEdgeItem } from "../../api";
import { type LayoutPreset, LAYOUT_PRESET_DAGRE } from "./nodeStyles";

// ── React Flow node data ──────────────────────────────────────────────

export interface RFNodeData extends Record<string, unknown> {
  symbolId: string;
  name: string;
  kind: NodeKind;
  filePath: string;
  isCenter: boolean;
  isSelected: boolean;
  /** confidence from the edge that brought this node into view, 1.0 for center */
  confidence: number;
  /** The grouping key for hierarchy folding, e.g. "file:src/auth.py" or "module:src/api" */
  hierarchyGroup?: string;
  /** Hierarchy depth: 0=module, 1=file, 2=class, 3=function/method */
  hierarchyLevel?: number;
  /** True if this is a synthetic parent node representing a collapsed group */
  isGroupParent?: boolean;
  /** For group parents: total count of child symbols */
  childCount?: number;
  /** For group parents: breakdown like "3 func, 2 class, 1 test" */
  childKindSummary?: string;
  /** For group parents: whether this group is currently expanded */
  isExpanded?: boolean;
  /** Priority score for node capping (higher = keep) */
  priorityScore?: number;
}

export type NodeKind =
  | "function"
  | "method"
  | "class"
  | "file"
  | "test"
  | "module"
  | "external_symbol"
  | "module_group"
  | "file_group"
  | "class_group";

// ── React Flow edge data ──────────────────────────────────────────────

export interface RFEdgeData extends Record<string, unknown> {
  edgeType: string;       // "calls" | "tested_by" | "imports" | "references" | "contains"
  confidence: number;
  confidenceLevel: "high" | "medium" | "low" | "unknown";
  isExternal: boolean;
}

// ── Capping types ─────────────────────────────────────────────────────

export interface CappingWarning {
  visibleNodes: number;
  totalNodes: number;
}

// ── Kind helpers ──────────────────────────────────────────────────────

export const KIND_LABEL: Record<NodeKind, string> = {
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

export const KIND_COLOR: Record<NodeKind, string> = {
  function: "var(--cg-accent)",
  method: "#A78BFA",
  class: "var(--cg-success)",
  file: "var(--cg-text-secondary)",
  test: "#4ADE80",
  module: "var(--cg-text-muted)",
  external_symbol: "var(--cg-warning)",
  module_group: "var(--cg-hierarchy-module, #818cf8)",
  file_group: "var(--cg-hierarchy-file, #a78bfa)",
  class_group: "var(--cg-hierarchy-class, #34d399)",
};

function normalizeKind(raw: string | null | undefined): NodeKind {
  const t = (raw || "").toLowerCase();
  if (t === "function") return "function";
  if (t === "method") return "method";
  if (t === "class") return "class";
  if (t === "file") return "file";
  if (t === "test") return "test";
  if (t === "module") return "module";
  if (t === "external_symbol") return "external_symbol";
  return "function"; // fallback
}

function filePathShort(fp: string | null | undefined): string {
  if (!fp) return "";
  const parts = fp.replace(/\\/g, "/").split("/");
  if (parts.length <= 1) return parts[0] || "";
  return parts.slice(-2).join("/");
}

function confidenceLevel(c: number): RFEdgeData["confidenceLevel"] {
  if (c >= 0.80) return "high";
  if (c >= 0.60) return "medium";
  if (c >= 0.40) return "low";
  return "unknown";
}

// ── Hierarchy grouping ────────────────────────────────────────────────

export interface HierarchyGroup {
  groupId: string;
  level: number;          // 0=module, 1=file, 2=class
  label: string;
  childIds: string[];
  kind: NodeKind;         // type of the group node
}

/**
 * Derive hierarchy groups from flat node data.
 * Groups nodes by module → file hierarchy based on file_path.
 * External nodes (no file_path) go into a synthetic "External" group.
 */
export function deriveHierarchyGroups(
  nodes: readonly GraphNodeItem[],
  _edges?: readonly GraphEdgeItem[],
): Map<string, HierarchyGroup> {
  const groups = new Map<string, HierarchyGroup>();
  const fileToNodes = new Map<string, string[]>();
  const externalIds: string[] = [];

  for (const n of nodes) {
    if (!n.file_path) {
      externalIds.push(n.id);
      continue;
    }
    const fp = n.file_path.replace(/\\/g, "/");
    if (!fileToNodes.has(fp)) fileToNodes.set(fp, []);
    fileToNodes.get(fp)!.push(n.id);
  }

  // Create file groups
  for (const [fp, ids] of fileToNodes) {
    const groupId = `file:${fp}`;
    const parts = fp.split("/");
    const label = parts[parts.length - 1] || fp;
    groups.set(groupId, {
      groupId,
      level: 1,
      label,
      childIds: ids,
      kind: "file_group",
    });

    // Derive module path from file path (everything except filename)
    if (parts.length > 1) {
      const modulePath = parts.slice(0, -1).join("/");
      const moduleId = `module:${modulePath}`;
      if (!groups.has(moduleId)) {
        groups.set(moduleId, {
          groupId: moduleId,
          level: 0,
          label: modulePath,
          childIds: [],
          kind: "module_group",
        });
      }
      // Module group doesn't directly own nodes; file groups do
    }
  }

  // Create external group
  if (externalIds.length > 0) {
    groups.set("external:", {
      groupId: "external:",
      level: 1,
      label: "External / Unresolved",
      childIds: externalIds,
      kind: "file_group",
    });
  }

  return groups;
}

// ── Hierarchy folding ─────────────────────────────────────────────────

export interface FoldingResult {
  displayNodes: Node<RFNodeData>[];
  displayEdges: Edge<RFEdgeData>[];
}

/**
 * Apply hierarchy folding to a set of React Flow nodes and edges.
 *
 * When a group is collapsed (not in expandedGroupIds):
 *  - All children are replaced by a single synthetic group parent node.
 *  - Edges to/from any child are rerouted to the parent.
 *  - Internal edges (between children of the same group) are hidden.
 *
 * When a group is expanded:
 *  - Children remain visible (and individually clickable).
 *  - A visual container node is NOT added (keep things flat and clean).
 *
 * The center node's file group is auto-expanded by default.
 */
export function applyHierarchyFolding(
  nodes: Node<RFNodeData>[],
  edges: Edge<RFEdgeData>[],
  expandedGroupIds: ReadonlySet<string>,
  centerNodeId?: string,
): FoldingResult {
  // Build childId → groupId map from hierarchy data on nodes
  const childToGroup = new Map<string, string>();
  for (const n of nodes) {
    if (n.data.hierarchyGroup) {
      childToGroup.set(n.id, n.data.hierarchyGroup);
    }
  }

  // Auto-expand the center node's group
  const effectiveExpanded = new Set(expandedGroupIds);
  if (centerNodeId) {
    const centerGroup = childToGroup.get(centerNodeId);
    if (centerGroup) effectiveExpanded.add(centerGroup);
  }

  // Determine which groups need parent nodes (collapsed groups)
  const groupChildren = new Map<string, string[]>();
  for (const n of nodes) {
    const gid = childToGroup.get(n.id);
    if (gid) {
      if (!groupChildren.has(gid)) groupChildren.set(gid, []);
      groupChildren.get(gid)!.push(n.id);
    }
  }

  const collapsedGroups = new Map<string, string[]>();
  const expandedGroups = new Map<string, string[]>();
  for (const [gid, childIds] of groupChildren) {
    if (effectiveExpanded.has(gid)) {
      expandedGroups.set(gid, childIds);
    } else {
      collapsedGroups.set(gid, childIds);
    }
  }

  // Collect all child IDs that should be hidden
  const hiddenChildIds = new Set<string>();
  for (const ids of collapsedGroups.values()) {
    for (const id of ids) hiddenChildIds.add(id);
  }

  // Build display nodes: keep non-hidden nodes, add group parents for collapsed groups
  const displayNodes: Node<RFNodeData>[] = [];

  for (const n of nodes) {
    if (hiddenChildIds.has(n.id)) continue;
    displayNodes.push(n);
  }

  // Create group parent nodes for collapsed groups
  for (const [gid, childIds] of collapsedGroups) {
    // Derive group info from child nodes
    const childNodes = nodes.filter((n) => childIds.includes(n.id));
    if (childNodes.length === 0) continue;

    const firstChild = childNodes[0];
    const groupKind: NodeKind = gid.startsWith("module:") ? "module_group"
      : gid.startsWith("file:") ? "file_group"
      : "class_group";

    // Build kind summary
    const kindCounts = new Map<string, number>();
    for (const cn of childNodes) {
      const k = cn.data.kind;
      kindCounts.set(k, (kindCounts.get(k) || 0) + 1);
    }
    const summaryParts: string[] = [];
    for (const [k, c] of kindCounts) {
      const label = KIND_LABEL[k as NodeKind] || k;
      summaryParts.push(`${c} ${label}`);
    }
    const childKindSummary = summaryParts.join(", ");

    // Determine label
    let label: string;
    if (gid.startsWith("file:")) {
      label = gid.slice("file:".length).replace(/\\/g, "/").split("/").pop() || gid;
    } else if (gid.startsWith("module:")) {
      label = gid.slice("module:".length);
    } else {
      label = gid;
    }

    const parentNode: Node<RFNodeData> = {
      id: gid,
      type: "hierarchyGroup",
      position: childNodes[0]?.position || { x: 400, y: 300 },
      data: {
        symbolId: gid,
        name: label,
        kind: groupKind,
        filePath: firstChild.data.filePath || gid,
        isCenter: false,
        isSelected: false,
        confidence: 1.0,
        hierarchyGroup: gid,
        hierarchyLevel: gid.startsWith("module:") ? 0 : gid.startsWith("file:") ? 1 : 2,
        isGroupParent: true,
        childCount: childIds.length,
        childKindSummary,
        isExpanded: false,
      },
    };
    displayNodes.push(parentNode);
  }

  // Build display edges: filter internal edges, reroute to parents
  const displayEdges: Edge<RFEdgeData>[] = [];
  const collapsedChildToParent = new Map<string, string>();
  for (const [gid, childIds] of collapsedGroups) {
    for (const cid of childIds) {
      collapsedChildToParent.set(cid, gid);
    }
  }

  // Also allow expanded group children to keep their edges
  const expandedChildIds = new Set<string>();
  for (const ids of expandedGroups.values()) {
    for (const id of ids) expandedChildIds.add(id);
  }

  for (const e of edges) {
    const sourceHidden = hiddenChildIds.has(e.source);
    const targetHidden = hiddenChildIds.has(e.target);

    // If both endpoints are hidden (internal edge of collapsed group), skip
    if (sourceHidden && targetHidden) {
      const srcGroup = collapsedChildToParent.get(e.source);
      const tgtGroup = collapsedChildToParent.get(e.target);
      if (srcGroup === tgtGroup) continue; // internal edge
    }

    // Reroute hidden endpoints to their parent group
    let newSource = e.source;
    let newTarget = e.target;

    if (sourceHidden) {
      const parent = collapsedChildToParent.get(e.source);
      if (parent) newSource = parent;
    }
    if (targetHidden) {
      const parent = collapsedChildToParent.get(e.target);
      if (parent) newTarget = parent;
    }

    // Skip self-loops created by rerouting
    if (newSource === newTarget) continue;

    // Create display edge with possibly rerouted endpoints
    const displayEdge: Edge<RFEdgeData> = {
      ...e,
      id: `${newSource}→${newTarget}::${e.data?.edgeType || "calls"}::${displayEdges.length}`,
      source: newSource,
      target: newTarget,
    };
    displayEdges.push(displayEdge);
  }

  return { displayNodes, displayEdges };
}

// ── Node capping ──────────────────────────────────────────────────────

/**
 * Assign priority scores and cap the node list at maxNodes.
 * Returns the capped array plus a warning if capping occurred.
 */
export function prioritizeAndCapNodes(
  nodes: Node<RFNodeData>[],
  edges: Edge<RFEdgeData>[],
  centerNodeId: string | undefined,
  maxNodes: number = 150,
): { cappedNodes: Node<RFNodeData>[]; cappedEdges: Edge<RFEdgeData>[]; warning: CappingWarning | null } {
  const total = nodes.length;
  if (total <= maxNodes) {
    return { cappedNodes: nodes, cappedEdges: edges, warning: null };
  }

  // Compute degree for each node
  const degree = new Map<string, number>();
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) || 0) + 1);
    degree.set(e.target, (degree.get(e.target) || 0) + 1);
  }

  // Compute neighbor set of center
  const neighborSet = new Set<string>();
  if (centerNodeId) {
    for (const e of edges) {
      if (e.source === centerNodeId) neighborSet.add(e.target);
      if (e.target === centerNodeId) neighborSet.add(e.source);
    }
  }

  // Type priority base scores
  const typeScore: Record<string, number> = {
    class: 50, file_group: 50, module_group: 45,
    function: 30, method: 25, file: 20,
    module: 15, test: 10, external_symbol: 5,
  };

  // Compute priority for each node
  const withPriority = nodes.map((n) => {
    let score = 0;

    // Center node: highest priority
    if (n.id === centerNodeId) {
      score = 1000;
    } else if (neighborSet.has(n.id)) {
      score = 100;
    }

    // Type bonus
    score += typeScore[n.data.kind] ?? 10;

    // Degree bonus (up to 40)
    const d = degree.get(n.id) || 0;
    score += Math.min(d * 2, 40);

    // Group parents always kept (they represent many children)
    if (n.data.isGroupParent) score += 200;

    // External nodes deprioritized
    if (n.data.kind === "external_symbol") score = Math.floor(score * 0.3);

    return { node: n, score };
  });

  // Sort by score descending
  withPriority.sort((a, b) => b.score - a.score);

  // Take top maxNodes
  const capped = withPriority.slice(0, maxNodes).map((wp) => {
    return {
      ...wp.node,
      data: { ...wp.node.data, priorityScore: wp.score },
    };
  });

  // Build set of included IDs for edge filtering
  const includedIds = new Set(capped.map((n) => n.id));

  // Filter edges: only include edges where BOTH endpoints are in the capped set
  const cappedEdges: Edge<RFEdgeData>[] = [];
  const seenEdges = new Set<string>();
  for (const e of edges) {
    if (includedIds.has(e.source) && includedIds.has(e.target)) {
      const key = `${e.source}→${e.target}`;
      // Deduplicate edges with same source→target (may occur from rerouting)
      if (!seenEdges.has(key)) {
        seenEdges.add(key);
        cappedEdges.push(e);
      }
    }
  }

  return {
    cappedNodes: capped,
    cappedEdges,
    warning: { visibleNodes: capped.length, totalNodes: total },
  };
}

// ── Dagre layout ──────────────────────────────────────────────────────

const NODE_WIDTH = 180;
const NODE_HEIGHT = 48;
const GROUP_NODE_WIDTH = 240;
const GROUP_NODE_HEIGHT = 56;

/**
 * Use dagre to compute graph layout positions.
 * Replaces the simple grid positioning with a proper layered graph layout.
 */
export function computeDagreLayout(
  nodes: Node<RFNodeData>[],
  edges: Edge<RFEdgeData>[],
  preset: LayoutPreset = "local",
): Node<RFNodeData>[] {
  if (nodes.length === 0) return nodes;

  const cfg = LAYOUT_PRESET_DAGRE[preset];

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: cfg.rankdir, nodesep: cfg.nodesep, ranksep: cfg.ranksep, marginx: cfg.marginx, marginy: cfg.marginy });

  for (const n of nodes) {
    const isGroup = n.data.isGroupParent ?? false;
    const w = isGroup ? GROUP_NODE_WIDTH : NODE_WIDTH;
    const h = isGroup ? GROUP_NODE_HEIGHT : NODE_HEIGHT;
    g.setNode(n.id, { width: w, height: h });
  }

  for (const e of edges) {
    g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (pos) {
      const isGroup = n.data.isGroupParent ?? false;
      const w = isGroup ? GROUP_NODE_WIDTH : NODE_WIDTH;
      const h = isGroup ? GROUP_NODE_HEIGHT : NODE_HEIGHT;
      return {
        ...n,
        position: { x: pos.x - w / 2, y: pos.y - h / 2 },
      };
    }
    return n;
  });
}

// ── Main transform: SubgraphResponse → React Flow nodes + edges ──────

export interface ToReactFlowOptions {
  /** The center node's id */
  centerNodeId: string;
  /** The center node's name (fallback if not in subgraph nodes) */
  centerName?: string;
  /** The center node's file path */
  centerFilePath?: string;
  /** Currently selected node id (for highlighting) */
  selectedNodeId?: string;
  /** Set of expanded group ids for hierarchy folding */
  expandedGroupIds?: ReadonlySet<string>;
  /** Maximum nodes to display (for capping) */
  nodeCap?: number;
  /** Layout preset for dagre configuration */
  layoutPreset?: LayoutPreset;
}

export interface ToReactFlowResult {
  nodes: Node<RFNodeData>[];
  edges: Edge<RFEdgeData>[];
  /** Non-null when node capping was applied */
  cappingWarning: CappingWarning | null;
}

/**
 * Transform a SubgraphResponse into React Flow nodes and edges.
 *
 * Pipeline:
 *   1. Flat nodes + edges from subgraph response
 *   2. Derive hierarchy groups from node data
 *   3. Apply hierarchy folding (collapsed groups → parent nodes)
 *   4. Prioritize and cap nodes at maxNodes
 *   5. Compute dagre layout
 */
export function toReactFlowGraph(
  subgraph: SubgraphResponse,
  opts: ToReactFlowOptions,
): ToReactFlowResult {
  const {
    centerNodeId,
    centerName,
    centerFilePath,
    selectedNodeId,
    expandedGroupIds = new Set<string>(),
    nodeCap = 150,
    layoutPreset = "local",
  } = opts;

  // Build a set of all node ids
  const nodeIds = new Set(subgraph.nodes.map((n) => n.id));
  nodeIds.add(centerNodeId);

  // ── Step 1: Flat nodes ─────────────────────────────────────────────

  const flatNodes: Node<RFNodeData>[] = subgraph.nodes.map((n, i) => {
    const isCenter = n.id === centerNodeId;
    const isSelected = n.id === selectedNodeId;
    const kind = normalizeKind(n.type);
    const fp = (n.file_path || "").replace(/\\/g, "/");

    // Derive hierarchy group
    let hierarchyGroup: string | undefined;
    let hierarchyLevel: number | undefined;
    if (fp) {
      hierarchyGroup = `file:${fp}`;
      hierarchyLevel = 1;
    } else {
      hierarchyGroup = "external:";
      hierarchyLevel = 1;
    }

    return {
      id: n.id,
      type: "customNode",
      position: {
        x: isCenter ? 400 : 100 + (i % 3) * 280,
        y: isCenter ? 300 : 80 + Math.floor(i / 3) * 160,
      },
      data: {
        symbolId: n.id,
        name: n.label || n.id.split("::").pop() || n.id,
        kind,
        filePath: fp,
        isCenter,
        isSelected,
        confidence: 1.0,
        hierarchyGroup,
        hierarchyLevel,
      },
    };
  });

  // Ensure center node exists
  if (!nodeIds.has(centerNodeId) || !flatNodes.find((n) => n.id === centerNodeId)) {
    const alreadyHas = flatNodes.some((n) => n.id === centerNodeId);
    if (!alreadyHas) {
      const fp = (centerFilePath || "").replace(/\\/g, "/");
      flatNodes.unshift({
        id: centerNodeId,
        type: "customNode",
        position: { x: 400, y: 300 },
        data: {
          symbolId: centerNodeId,
          name: centerName || centerNodeId.split("::").pop() || centerNodeId,
          kind: "function",
          filePath: fp,
          isCenter: true,
          isSelected: centerNodeId === selectedNodeId,
          confidence: 1.0,
          hierarchyGroup: fp ? `file:${fp}` : "external:",
          hierarchyLevel: fp ? 1 : 1,
        },
      });
    }
  }

  // ── Step 2: Flat edges ─────────────────────────────────────────────

  const flatEdges: Edge<RFEdgeData>[] = subgraph.edges.map((e, i) => {
    const conf = e.confidence ?? 0.5;
    const level = confidenceLevel(conf);
    const sourceExists = nodeIds.has(e.source);
    const targetExists = nodeIds.has(e.target);
    const isExternal = !sourceExists || !targetExists;

    return {
      id: `${e.source}→${e.target}::${e.type}::${i}`,
      source: e.source,
      target: e.target,
      type: "customEdge",
      data: {
        edgeType: e.type,
        confidence: conf,
        confidenceLevel: level,
        isExternal,
      },
      animated: false,
    } as Edge<RFEdgeData>;
  });

  // ── Step 3: Hierarchy folding ──────────────────────────────────────

  const { displayNodes: foldedNodes, displayEdges: foldedEdges } =
    applyHierarchyFolding(flatNodes, flatEdges, expandedGroupIds, centerNodeId);

  // ── Step 4: Node capping ───────────────────────────────────────────

  const {
    cappedNodes,
    cappedEdges,
    warning: cappingWarning,
  } = prioritizeAndCapNodes(foldedNodes, foldedEdges, centerNodeId, nodeCap);

  // ── Step 5: Dagre layout ───────────────────────────────────────────

  const laidOutNodes = computeDagreLayout(cappedNodes, cappedEdges, layoutPreset);

  return { nodes: laidOutNodes, edges: cappedEdges, cappingWarning };
}

/**
 * Transform a NeighborsResponse into React Flow nodes and edges.
 * Used when the subgraph endpoint is not available; mirrors toReactFlowGraph.
 */
export function toReactFlowFromNeighbors(
  neighbors: NeighborsResponse,
  centerName?: string,
  centerFilePath?: string,
  centerKind?: string,
  selectedNodeId?: string,
): { nodes: Node<RFNodeData>[]; edges: Edge<RFEdgeData>[] } {
  const centerNodeId = neighbors.center_node_id;

  const rfNodes: Node<RFNodeData>[] = [
    {
      id: centerNodeId,
      type: "customNode",
      position: { x: 400, y: 300 },
      data: {
        symbolId: centerNodeId,
        name: centerName || centerNodeId.split("::").pop() || centerNodeId,
        kind: normalizeKind(centerKind),
        filePath: centerFilePath || "",
        isCenter: true,
        isSelected: centerNodeId === selectedNodeId,
        confidence: 1.0,
      },
    },
  ];

  const nodeIds = new Set<string>([centerNodeId]);
  for (const n of neighbors.neighbors) {
    if (!nodeIds.has(n.node_id)) {
      nodeIds.add(n.node_id);
      const isIncoming = n.direction === "incoming";
      rfNodes.push({
        id: n.node_id,
        type: "customNode",
        position: {
          x: isIncoming ? 100 : 700,
          y: 80 + rfNodes.length * 160,
        },
        data: {
          symbolId: n.node_id,
          name: n.name,
          kind: normalizeKind(n.type),
          filePath: n.file_path || "",
          isCenter: false,
          isSelected: n.node_id === selectedNodeId,
          confidence: parseFloat(n.confidence) || 0.5,
        },
      });
    }
  }

  const rfEdges: Edge<RFEdgeData>[] = neighbors.neighbors.map((n, i) => {
    const conf = parseFloat(n.confidence) || 0.5;
    const level = confidenceLevel(conf);
    const isIncoming = n.direction === "incoming";

    return {
      id: `${isIncoming ? n.node_id : centerNodeId}→${isIncoming ? centerNodeId : n.node_id}::${n.edge_type}::${i}`,
      source: isIncoming ? n.node_id : centerNodeId,
      target: isIncoming ? centerNodeId : n.node_id,
      type: "customEdge",
      data: {
        edgeType: n.edge_type,
        confidence: conf,
        confidenceLevel: level,
        isExternal: false,
      },
      animated: false,
    } as Edge<RFEdgeData>;
  });

  return { nodes: rfNodes, edges: rfEdges };
}

export { filePathShort };
