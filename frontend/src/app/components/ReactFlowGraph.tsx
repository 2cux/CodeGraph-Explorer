import { useMemo, useCallback, useRef, useEffect } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  MiniMap,
  Controls,
  Background,
  useReactFlow,
  type Node,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
  type NodeMouseHandler,
  type EdgeMouseHandler,
  SelectionMode,
  BackgroundVariant,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import CustomNode from "./CustomNode";
import CustomEdge from "./CustomEdge";
import HierarchyGroupNode from "./HierarchyGroupNode";
import type { RFNodeData, RFEdgeData } from "./graphTransforms";

// ── Node / Edge types (stable references) ─────────────────────────────

const nodeTypes = { customNode: CustomNode, hierarchyGroup: HierarchyGroupNode };
const edgeTypes = { customEdge: CustomEdge };

// ── Public types ──────────────────────────────────────────────────────

export interface EdgeIdentity {
  source: string;
  target: string;
  type: string;
}

interface ReactFlowGraphProps {
  nodes: Node<RFNodeData>[];
  edges: Edge<RFEdgeData>[];
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string) => void;
  onSelectEdge?: (edge: EdgeIdentity) => void;
  /** Called when a hierarchy group parent is clicked (expand/collapse toggle) */
  onToggleGroup?: (groupId: string) => void;
  /** Non-null when node capping has limited the display */
  cappingWarning?: { visibleNodes: number; totalNodes: number } | null;
}

// ── Outer wrapper (provides ReactFlow context) ────────────────────────

export default function ReactFlowGraph(props: ReactFlowGraphProps) {
  return (
    <ReactFlowProvider>
      <ReactFlowGraphInner {...props} />
    </ReactFlowProvider>
  );
}

// ── Inner component (uses React Flow hooks) ───────────────────────────

function ReactFlowGraphInner({
  nodes,
  edges,
  selectedNodeId,
  onSelectNode,
  onSelectEdge,
  onToggleGroup,
  cappingWarning,
}: ReactFlowGraphProps) {
  const { fitView } = useReactFlow();

  // Compute neighbor ids for selected node
  const neighborIds = useMemo(() => {
    if (!selectedNodeId) return new Set<string>();
    const ids = new Set<string>();
    for (const e of edges) {
      if (e.source === selectedNodeId) ids.add(e.target);
      if (e.target === selectedNodeId) ids.add(e.source);
    }
    return ids;
  }, [selectedNodeId, edges]);

  // Augment nodes with dimming info
  const displayNodes = useMemo(() => {
    if (!selectedNodeId) return nodes;
    return nodes.map((n) => ({
      ...n,
      data: {
        ...n.data,
        isSelected: n.id === selectedNodeId,
      },
      style: {
        ...n.style,
        opacity:
          n.id === selectedNodeId
            ? 1
            : neighborIds.has(n.id)
              ? 0.9
              : 0.25,
        transition: "opacity 200ms ease",
      },
    }));
  }, [nodes, selectedNodeId, neighborIds]);

  // Augment edges with dimming info
  const displayEdges = useMemo(() => {
    if (!selectedNodeId) return edges;
    return edges.map((e) => {
      const connected =
        e.source === selectedNodeId || e.target === selectedNodeId;
      return {
        ...e,
        style: {
          opacity: connected ? 0.9 : 0.12,
          transition: "opacity 200ms ease",
        },
        animated: connected,
      };
    });
  }, [edges, selectedNodeId]);

  // Fit view when nodes change (e.g. new center loaded)
  const prevNodeCount = useRef(0);
  useEffect(() => {
    if (nodes.length > 0 && nodes.length !== prevNodeCount.current) {
      prevNodeCount.current = nodes.length;
      const timer = setTimeout(() => {
        fitView({ padding: 0.2, duration: 300 });
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [nodes.length, fitView]);

  // Handlers
  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      const data = node.data as RFNodeData;
      // If clicking a group parent, toggle expand/collapse
      if (data.isGroupParent && onToggleGroup) {
        onToggleGroup(node.id);
        return;
      }
      onSelectNode?.(node.id);
    },
    [onSelectNode, onToggleGroup],
  );

  const handleEdgeClick: EdgeMouseHandler = useCallback(
    (_event, edge) => {
      const data = edge.data as RFEdgeData | undefined;
      onSelectEdge?.({
        source: edge.source,
        target: edge.target,
        type: data?.edgeType || "calls",
      });
    },
    [onSelectEdge],
  );

  const handleFitView = useCallback(() => {
    fitView({ padding: 0.2, duration: 300 });
  }, [fitView]);

  // Don't persist internal layout changes (we control positions)
  const handleNodesChange: OnNodesChange = useCallback(() => {}, []);
  const handleEdgesChange: OnEdgesChange = useCallback(() => {}, []);

  // Handle MiniMap node click to navigate
  const handleMiniMapNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      const data = node.data as RFNodeData;
      if (data.isGroupParent && onToggleGroup) {
        onToggleGroup(node.id);
        return;
      }
      onSelectNode?.(node.id);
    },
    [onSelectNode, onToggleGroup],
  );

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <ReactFlow
        nodes={displayNodes}
        edges={displayEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={handleNodeClick}
        onEdgeClick={handleEdgeClick}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        fitView={false}
        minZoom={0.1}
        maxZoom={3}
        defaultViewport={{ x: 0, y: 0, zoom: 0.8 }}
        proOptions={{ hideAttribution: true }}
        selectNodesOnDrag={false}
        selectionMode={SelectionMode.Partial}
        nodesDraggable={true}
        nodesConnectable={false}
        elementsSelectable={true}
        deleteKeyCode={null}
        multiSelectionKeyCode={null}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="var(--cg-grid, #333)"
        />
        <Controls
          position="bottom-right"
          style={{
            background: "var(--cg-bg-panel)",
            border: "1px solid var(--cg-border)",
            borderRadius: 6,
          }}
          className="cg-rf-controls"
        />
        <MiniMap
          position="bottom-left"
          onNodeClick={handleMiniMapNodeClick}
          style={{
            background: "var(--cg-bg-panel)",
            border: "1px solid var(--cg-border)",
            borderRadius: 6,
          }}
          maskColor="var(--cg-bg-canvas, #111)CC"
          nodeColor={(n) => {
            const kind = (n.data as RFNodeData)?.kind;
            if (kind === "class" || kind === "class_group") return "#34d399";
            if (kind === "function" || kind === "method") return "#6366f1";
            if (kind === "test") return "#4ADE80";
            if (kind === "file_group") return "#a78bfa";
            if (kind === "module_group") return "#818cf8";
            if (kind === "external_symbol") return "#f59e0b";
            return "#888";
          }}
        />
        <Panel position="top-right">
          <button
            onClick={handleFitView}
            title="Fit view"
            style={{
              padding: "4px 10px",
              fontSize: 11,
              borderRadius: 4,
              border: "1px solid var(--cg-border)",
              background: "var(--cg-bg-panel)",
              color: "var(--cg-text-secondary)",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            Fit View
          </button>
        </Panel>

        {/* Cap warning banner */}
        {cappingWarning && (
          <Panel position="top-center">
            <div
              className="cg-cap-warning"
              style={{
                padding: "6px 14px",
                borderRadius: 6,
                background: "var(--cg-warning-alpha)",
                border: "1px solid color-mix(in srgb, var(--cg-warning) 30%, transparent)",
                fontSize: 11,
                color: "var(--cg-text-primary)",
                textAlign: "center" as const,
                whiteSpace: "nowrap" as const,
              }}
            >
              Showing top {cappingWarning.visibleNodes} of{" "}
              {cappingWarning.totalNodes} nodes. Use search to explore
              more or expand groups.
            </div>
          </Panel>
        )}
      </ReactFlow>
    </div>
  );
}
