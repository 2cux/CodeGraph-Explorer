import type { Node, Edge } from "@xyflow/react";
import type { SubgraphResponse, NeighborsResponse } from "../../api";

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
}

export type NodeKind = "function" | "method" | "class" | "file" | "test" | "module" | "external_symbol";

// ── React Flow edge data ──────────────────────────────────────────────

export interface RFEdgeData extends Record<string, unknown> {
  edgeType: string;       // "calls" | "tested_by" | "imports" | "references" | "contains"
  confidence: number;
  confidenceLevel: "high" | "medium" | "low" | "unknown";
  isExternal: boolean;
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
};

export const KIND_COLOR: Record<NodeKind, string> = {
  function: "var(--cg-accent)",
  method: "#A78BFA",
  class: "var(--cg-success)",
  file: "var(--cg-text-secondary)",
  test: "#4ADE80",
  module: "var(--cg-text-muted)",
  external_symbol: "var(--cg-warning)",
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
}

/**
 * Transform a SubgraphResponse into React Flow nodes and edges.
 * The center node is always included (even if the subgraph doesn't contain it),
 * placed at origin, and marked with isCenter=true.
 */
export function toReactFlowGraph(
  subgraph: SubgraphResponse,
  opts: ToReactFlowOptions,
): { nodes: Node<RFNodeData>[]; edges: Edge<RFEdgeData>[] } {
  const { centerNodeId, centerName, centerFilePath, selectedNodeId } = opts;

  // Build a set of all node ids to detect external/unresolved edges
  const nodeIds = new Set(subgraph.nodes.map((n) => n.id));
  nodeIds.add(centerNodeId);

  // ── Nodes ──────────────────────────────────────────────────────────

  const rfNodes: Node<RFNodeData>[] = subgraph.nodes.map((n, i) => {
    const isCenter = n.id === centerNodeId;
    const isSelected = n.id === selectedNodeId;
    const kind = normalizeKind(n.type);
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
        filePath: n.file_path || "",
        isCenter,
        isSelected,
        confidence: 1.0,
      },
    };
  });

  // Ensure center node exists in the list
  if (!nodeIds.has(centerNodeId) || !rfNodes.find((n) => n.id === centerNodeId)) {
    const alreadyHas = rfNodes.some((n) => n.id === centerNodeId);
    if (!alreadyHas) {
      rfNodes.unshift({
        id: centerNodeId,
        type: "customNode",
        position: { x: 400, y: 300 },
        data: {
          symbolId: centerNodeId,
          name: centerName || centerNodeId.split("::").pop() || centerNodeId,
          kind: "function",
          filePath: centerFilePath || "",
          isCenter: true,
          isSelected: centerNodeId === selectedNodeId,
          confidence: 1.0,
        },
      });
    }
  }

  // ── Edges ──────────────────────────────────────────────────────────

  const rfEdges: Edge<RFEdgeData>[] = subgraph.edges.map((e, i) => {
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
      // metadata for edge inspector
      style: { stroke: undefined as unknown as string }, // placeholder, CustomEdge handles this
      animated: false,
    } as Edge<RFEdgeData>;
  });

  return { nodes: rfNodes, edges: rfEdges };
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

  // Center node
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

  // Neighbor nodes
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

  // Edges
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
      style: {},
      animated: false,
    } as Edge<RFEdgeData>;
  });

  return { nodes: rfNodes, edges: rfEdges };
}

/**
 * Get file path shortened for display.
 */
export { filePathShort };
