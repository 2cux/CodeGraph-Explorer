import { useEffect, useState, useCallback, memo } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import ReactFlow, {
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  type NodeProps,
  type EdgeProps,
  type ReactFlowProps,
  type Node as FlowNode,
  type Edge as FlowEdge,
  BaseEdge,
  getBezierPath,
} from "reactflow";
import "reactflow/dist/style.css";
import { api, type SubgraphResponse, type GraphNodeItem, type GraphEdgeItem } from "../api";
import { Spinner } from "../components/Spinner";
import { IconSearch } from "../components/icons";

type ViewMode = "initial" | "loading" | "graph" | "error";

interface ViewState {
  mode: ViewMode;
  error: string;
  response: SubgraphResponse | null;
}

/* ── Kind config (matching Figma design) ─────────────────────── */

const KIND_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  function: { label: "FUNC", color: "var(--cg-accent)", bg: "var(--cg-accent-alpha)" },
  method: { label: "METH", color: "#A78BFA", bg: "color-mix(in srgb, #A78BFA 14%, transparent)" },
  class: { label: "CLASS", color: "var(--cg-success)", bg: "var(--cg-success-alpha)" },
  file: { label: "FILE", color: "var(--cg-text-secondary)", bg: "color-mix(in srgb, var(--cg-text-secondary) 14%, transparent)" },
  test: { label: "TEST", color: "#4ADE80", bg: "color-mix(in srgb, #4ADE80 14%, transparent)" },
  external_symbol: { label: "EXT", color: "var(--cg-warning)", bg: "var(--cg-warning-alpha)" },
};

function kindConfig(type: string) {
  return KIND_CONFIG[type] || { label: type.toUpperCase(), color: "var(--cg-text-secondary)", bg: "color-mix(in srgb, var(--cg-text-secondary) 14%, transparent)" };
}

function edgeColor(confidence: number | null) {
  if (confidence === null) return "var(--cg-text-muted)";
  if (confidence < 0.6) return "var(--cg-warning)";
  if (confidence >= 0.85) return "var(--cg-success)";
  return "var(--cg-text-muted)";
}

/* ── Custom Node ─────────────────────────────────────────────── */

const GraphNode = memo(({ data }: NodeProps) => {
  const { label, type: nodeType, file_path, confidence } = data as { label: string; type: string; file_path?: string; confidence?: number };
  const cfg = kindConfig(nodeType);
  return (
    <div
      className="cg-node"
      style={{
        width: 168,
        padding: "8px 10px",
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        display: "flex",
        flexDirection: "column",
        gap: 3,
      }}
    >
      <div className="flex items-center" style={{ gap: 5 }}>
        <span
          className="cg-mono"
          style={{
            fontSize: 9,
            color: cfg.color,
            background: cfg.bg,
            padding: "1px 4px",
            borderRadius: 2,
            letterSpacing: 0.5,
            lineHeight: "14px",
          }}
        >
          {cfg.label}
        </span>
        <span
          className="cg-mono"
          style={{
            fontSize: 11,
            fontWeight: 500,
            color: "var(--cg-text-primary)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            flex: 1,
            minWidth: 0,
          }}
        >
          {label}
        </span>
      </div>
      {file_path && (
        <div
          className="cg-mono"
          style={{
            fontSize: 9,
            color: "var(--cg-text-secondary)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {file_path.split("/").pop()}
        </div>
      )}
      {confidence !== undefined && (
        <div
          className="cg-mono"
          style={{
            fontSize: 9,
            color: edgeColor(confidence ?? null),
            textAlign: "right",
          }}
        >
          {confidence.toFixed(2)}
        </div>
      )}
    </div>
  );
});

/* ── Custom Edge ─────────────────────────────────────────────── */

const GraphEdge = memo(({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: EdgeProps) => {
  const { label, confidence } = (data || {}) as { label?: string; confidence?: number };
  const color = edgeColor(confidence ?? null);
  const [edgePath] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: color,
          strokeWidth: selected ? 1.5 : 1,
          transition: "stroke-width 120ms ease",
        }}
      />
      {label && (
        <foreignObject
          width={120}
          height={20}
          x={0}
          y={0}
          style={{ transform: `translate(${(sourceX + targetX) / 2 - 60}px, ${(sourceY + targetY) / 2 - 10}px)`, overflow: "visible" }}
        >
          <div
            className="cg-mono"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 4,
              fontSize: 9,
              color,
              opacity: selected ? 1 : 0.7,
              transition: "opacity 120ms ease",
            }}
          >
            <span style={{
              padding: "1px 5px",
              background: "var(--cg-bg-canvas)",
              border: "1px solid var(--cg-border)",
              borderRadius: 2,
              lineHeight: "16px",
            }}>
              {label}
            </span>
          </div>
        </foreignObject>
      )}
    </>
  );
});

const nodeTypes = { graphNode: GraphNode };
const edgeTypes = { graphEdge: GraphEdge };

/* ── Main component ──────────────────────────────────────────── */

export default function GraphExplorer() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialSymbol = searchParams.get("symbol") || "";

  const [symbolId, setSymbolId] = useState(initialSymbol);
  const [depth, setDepth] = useState(1);
  const [state, setState] = useState<ViewState>({
    mode: initialSymbol ? "loading" : "initial",
    error: "",
    response: null,
  });
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const loadGraph = useCallback(async (sym: string) => {
    if (!sym.trim()) {
      setState({ mode: "initial", error: "", response: null });
      setNodes([]);
      setEdges([]);
      return;
    }
    setState((s) => ({ ...s, mode: "loading", error: "" }));
    try {
      const resp = await api.graph.subgraph(sym, depth);
      setState({ mode: "graph", error: "", response: resp });
      setNodes(toFlowNodes(resp.nodes, resp.center_node_id));
      setEdges(toFlowEdges(resp.edges));
    } catch (e: unknown) {
      setState({
        mode: "error",
        error: e instanceof Error ? e.message : "Failed to load graph",
        response: null,
      });
      setNodes([]);
      setEdges([]);
    }
  }, [depth, setNodes, setEdges]);

  useEffect(() => {
    if (initialSymbol) loadGraph(initialSymbol);
  }, [initialSymbol]);

  const handleExplore = () => loadGraph(symbolId);

  const renderContent = () => {
    switch (state.mode) {
      case "initial": return <InitialState />;
      case "loading": return <LoadingState />;
      case "error": return <ErrorState message={state.error} />;
      case "graph": return (
        <GraphCanvas
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          response={state.response!}
          onNodeClick={(id) => navigate(`/symbol/${encodeURIComponent(id)}`)}
        />
      );
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, height: "100%" }}>
      <div>
        <h1 style={{ fontSize: 18, fontWeight: 500, color: "var(--cg-text-primary)", margin: 0 }}>
          Graph Explorer
        </h1>
        <p style={{ fontSize: 12, color: "var(--cg-text-secondary)", margin: "4px 0 0" }}>
          Visualize the local call graph centered on a symbol.
        </p>
      </div>

      {/* Controls */}
      <div className="flex items-center" style={{ gap: 8 }}>
        <div style={{ flex: 1, position: "relative" }}>
          <span style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", color: "var(--cg-text-muted)", display: "flex", alignItems: "center" }}>
            <IconSearch size={12} />
          </span>
          <input
            type="text"
            value={symbolId}
            onChange={(e) => setSymbolId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleExplore()}
            placeholder="e.g. src/app/api/auth.py::login"
            style={{
              width: "100%", height: 30, padding: "0 8px 0 28px",
              border: "1px solid var(--cg-border)", borderRadius: 4,
              background: "var(--cg-bg-panel)", color: "var(--cg-text-primary)",
              fontSize: 12, fontFamily: "inherit", outline: "none",
            }}
            onFocus={(e) => e.currentTarget.style.borderColor = "var(--cg-accent)"}
            onBlur={(e) => e.currentTarget.style.borderColor = "var(--cg-border)"}
          />
        </div>
        <select
          value={depth}
          onChange={(e) => setDepth(Number(e.target.value))}
          style={{
            height: 30, padding: "0 8px",
            border: "1px solid var(--cg-border)", borderRadius: 4,
            background: "var(--cg-bg-panel)", color: "var(--cg-text-primary)",
            fontSize: 11, fontFamily: "inherit", outline: "none",
          }}
        >
          {[1, 2, 3].map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <button
          onClick={handleExplore}
          disabled={state.mode === "loading" || !symbolId.trim()}
          style={{
            height: 30, padding: "0 14px",
            background: "var(--cg-accent)", color: "#fff",
            border: "none", borderRadius: 4,
            fontSize: 11, fontWeight: 500,
            cursor: state.mode === "loading" || !symbolId.trim() ? "default" : "pointer",
            fontFamily: "inherit", opacity: state.mode === "loading" || !symbolId.trim() ? 0.6 : 1,
          }}
        >
          {state.mode === "loading" ? "Loading..." : "Explore"}
        </button>
      </div>

      {renderContent()}
    </div>
  );
}

/* ── Sub-components ──────────────────────────────────────────── */

function InitialState() {
  return (
    <div style={{ textAlign: "center", padding: "40px 20px", border: "1px dashed var(--cg-border)", borderRadius: 8 }}>
      <div style={{ fontSize: 32, color: "var(--cg-text-muted)", marginBottom: 12 }}>⬡</div>
      <h2 style={{ fontSize: 14, fontWeight: 500, color: "var(--cg-text-secondary)", margin: "0 0 4px" }}>
        Enter a symbol ID to explore
      </h2>
      <p style={{ fontSize: 11, color: "var(--cg-text-muted)", margin: 0 }}>
        The graph will show the local call neighborhood around the symbol.
      </p>
    </div>
  );
}

function LoadingState() {
  return (
    <div style={{
      flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
      background: "var(--cg-bg-panel)", border: "1px solid var(--cg-border)", borderRadius: 6,
      minHeight: 400,
    }}>
      <div className="flex items-center" style={{ gap: 8, color: "var(--cg-text-muted)" }}>
        <Spinner size={14} />
        <span style={{ fontSize: 11 }}>Loading graph...</span>
      </div>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  const is404 = message.includes("not found") || message.includes("404");
  return (
    <div style={{
      padding: "8px 10px",
      background: "var(--cg-error-alpha)",
      border: "1px solid color-mix(in srgb, var(--cg-error) 30%, transparent)",
      borderRadius: 4, fontSize: 11,
      color: is404 ? "var(--cg-text-secondary)" : "var(--cg-text-secondary)",
    }}>
      {is404
        ? "Symbol not found in the graph. Make sure the repo has been indexed and the symbol ID is correct."
        : message}
    </div>
  );
}

/* ── Graph Canvas ────────────────────────────────────────────── */

function GraphCanvas({
  nodes, edges, onNodesChange, onEdgesChange, response, onNodeClick,
}: {
  nodes: FlowNode[]; edges: FlowEdge[];
  onNodesChange: ReactFlowProps["onNodesChange"];
  onEdgesChange: ReactFlowProps["onEdgesChange"];
  response: SubgraphResponse;
  onNodeClick: (id: string) => void;
}) {
  return (
    <div style={{
      flex: 1, border: "1px solid var(--cg-border)", borderRadius: 6, overflow: "hidden",
      position: "relative", minHeight: 400,
    }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        attributionPosition="bottom-left"
        defaultEdgeOptions={{ type: "graphEdge" }}
        onNodeClick={(_, node) => onNodeClick(node.id)}
        style={{ background: "var(--cg-bg-canvas)" }}
      >
        <Background
          color="var(--cg-grid)"
          gap={28}
          size={1}
        />
        <Controls
          style={{
            background: "var(--cg-bg-panel)",
            border: "1px solid var(--cg-border)",
            borderRadius: 4,
          }}
        />
      </ReactFlow>

      {/* Stats */}
      <div style={{
        position: "absolute", top: 8, left: 8,
        padding: "4px 10px",
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        fontSize: 10,
        color: "var(--cg-text-muted)",
        zIndex: 10,
      }}>
        <span className="cg-mono">
          {nodes.length} nodes · {edges.length} edges · depth {response.depth}
        </span>
      </div>

      {/* Legend */}
      <div style={{
        position: "absolute", bottom: 8, right: 8,
        padding: "8px 10px",
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        zIndex: 10,
        display: "flex",
        flexDirection: "column",
        gap: 3,
      }}>
        <span style={{ fontSize: 9, fontWeight: 600, color: "var(--cg-text-secondary)", letterSpacing: 0.3, marginBottom: 2 }}>Legend</span>
        {Object.entries(KIND_CONFIG).map(([type, cfg]) => (
          <div key={type} className="flex items-center" style={{ gap: 5 }}>
            <span style={{
              width: 6, height: 6, borderRadius: "50%",
              background: cfg.color, display: "inline-block",
            }} />
            <span className="cg-mono" style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>
              {type}
            </span>
          </div>
        ))}
        <div className="flex items-center" style={{ gap: 5, marginTop: 2, paddingTop: 4, borderTop: "1px solid var(--cg-border)" }}>
          <span style={{ width: 12, height: 2, background: "var(--cg-warning)", display: "inline-block" }} />
          <span style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>low confidence</span>
        </div>
      </div>
    </div>
  );
}

/* ── Helpers ─────────────────────────────────────────────────── */

function toFlowNodes(
  apiNodes: GraphNodeItem[],
  centerId: string,
): FlowNode[] {
  const positions = distributeInCircle(apiNodes.length, 250);
  return apiNodes.map((n, i) => ({
    id: n.id,
    type: "graphNode",
    position: n.id === centerId ? { x: 0, y: 0 } : positions[i],
    data: { label: n.label, type: n.type, file_path: n.file_path, confidence: undefined },
  }));
}

function toFlowEdges(apiEdges: GraphEdgeItem[]): FlowEdge[] {
  return apiEdges.map((e) => ({
    id: `${e.source}→${e.target}`,
    source: e.source,
    target: e.target,
    type: "graphEdge",
    data: {
      label: e.confidence != null ? e.confidence.toFixed(2) : e.type,
      confidence: e.confidence,
      edgeType: e.type, // used by GraphEdge data
    },
    style: { stroke: edgeColor(e.confidence) },
  }));
}

function distributeInCircle(count: number, radius: number) {
  if (count === 0) return [];
  return Array.from({ length: count }, (_, i) => {
    const angle = (2 * Math.PI * i) / count - Math.PI / 2;
    return { x: radius * Math.cos(angle), y: radius * Math.sin(angle) };
  });
}
