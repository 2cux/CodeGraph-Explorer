import type { Node, Edge } from "@xyflow/react";
import { GraphCanvas, type CanvasState, type GraphNodeData, type GraphEdgeData, type NodeKind } from "../app/components/GraphCanvas";
import type { RFNodeData, RFEdgeData } from "../app/components/graphTransforms";
import type { EdgeIdentity } from "../app/components/ReactFlowGraph";

interface Props {
  canvasState: CanvasState;
  /** React Flow nodes (for focused state) */
  rfNodes?: Node<RFNodeData>[];
  /** React Flow edges (for focused state) */
  rfEdges?: Edge<RFEdgeData>[];
  /** Currently selected node ID for dimming */
  selectedNodeId?: string | null;
  /** Overview data (for overview state) */
  overviewData?: import("../api").OverviewResponse | null;
  indexStatus?: "fresh" | "stale" | "missing" | "indexing" | "error";
  onSelectNode?: (nodeId: string) => void;
  onSelectFile?: (filePath: string) => void;
  onSelectEdge?: (edge: EdgeIdentity) => void;
  onSearchSelect?: (symbolId: string) => void;
  /** @deprecated kept for tests */
  nodes?: GraphNodeData[];
  /** @deprecated kept for tests */
  edges?: GraphEdgeData[];
}

export default function GraphExplorer({
  canvasState,
  rfNodes,
  rfEdges,
  selectedNodeId,
  overviewData,
  indexStatus,
  onSelectNode,
  onSelectFile,
  onSelectEdge,
  onSearchSelect,
  nodes,
  edges,
}: Props) {
  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      {/* Index stale warning */}
      {indexStatus === "stale" && canvasState !== "empty" && canvasState !== "error" && (
        <div style={{
          position: "absolute", top: 8, left: "50%", transform: "translateX(-50%)", zIndex: 20,
          display: "flex", alignItems: "center", gap: 8,
          padding: "4px 12px", borderRadius: 4,
          background: "color-mix(in srgb, var(--cg-warning) 10%, var(--cg-bg-panel))",
          border: "1px solid color-mix(in srgb, var(--cg-warning) 30%, transparent)",
          fontSize: 10, color: "var(--cg-warning)",
        }}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
            <path d="M8 2.5L14 13.5H2L8 2.5zM8 7v3M8 11.6v.1" />
          </svg>
          <span>Index is stale — graph data may be out of date</span>
        </div>
      )}

      {/* No index banner */}
      {indexStatus === "missing" && canvasState === "empty" && (
        <div style={{
          position: "absolute", top: 8, left: "50%", transform: "translateX(-50%)", zIndex: 20,
          display: "flex", alignItems: "center", gap: 8,
          padding: "4px 12px", borderRadius: 4,
          background: "color-mix(in srgb, var(--cg-text-muted) 10%, var(--cg-bg-panel))",
          border: "1px solid color-mix(in srgb, var(--cg-text-muted) 20%, transparent)",
          fontSize: 10, color: "var(--cg-text-secondary)",
        }}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
            <circle cx="8" cy="8" r="5.5" />
            <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" />
          </svg>
          <span>
            No <code style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>.codegraph</code> index found.
            Run: <code style={{ fontSize: 10, color: "var(--cg-text-secondary)" }}>codegraph index &lt;project&gt;</code>
          </span>
        </div>
      )}

      {/* API connection error banner */}
      {indexStatus === "error" && canvasState === "error" && (
        <div style={{
          position: "absolute", top: 8, left: "50%", transform: "translateX(-50%)", zIndex: 20,
          display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
          padding: "8px 12px", borderRadius: 4,
          background: "color-mix(in srgb, var(--cg-error) 10%, var(--cg-bg-panel))",
          border: "1px solid color-mix(in srgb, var(--cg-error) 30%, transparent)",
          fontSize: 10, color: "var(--cg-error)",
        }}>
          <span style={{ fontWeight: 500 }}>Cannot connect to CodeGraph API.</span>
          <span style={{ color: "var(--cg-text-secondary)" }}>
            Start it with: <code style={{ fontSize: 10 }}>codegraph api --root &lt;project_path&gt;</code>
          </span>
        </div>
      )}

      <GraphCanvas
        state={canvasState}
        rfNodes={rfNodes}
        rfEdges={rfEdges}
        selectedNodeId={selectedNodeId}
        overviewData={overviewData}
        onSelectNode={onSelectNode}
        onSelectFile={onSelectFile}
        onSelectEdge={onSelectEdge}
        onSearchSelect={onSearchSelect}
        nodes={nodes}
        edges={edges}
      />
    </div>
  );
}

// Re-export types used by GraphExplorer consumers
export type { CanvasState, GraphNodeData, GraphEdgeData, NodeKind, EdgeIdentity };
