import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  MarkerType,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeTypes,
  type ReactFlowProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { api, type SubgraphResponse, type GraphNodeItem, type GraphEdgeItem } from "../api";

type ViewMode = "initial" | "loading" | "graph" | "error";

interface ViewState {
  mode: ViewMode;
  error: string;
  response: SubgraphResponse | null;
}

/* ── Custom node component ────────────────────────────────────── */

const TYPE_COLORS: Record<string, string> = {
  function: "#059669",
  method: "#2563eb",
  class: "#7c3aed",
  module: "#6b7280",
  variable: "#d97706",
  constant: "#e11d48",
};

function GraphNode({ data }: { data: { label: string; type: string; file_path?: string } }) {
  const color = TYPE_COLORS[data.type] || "#6b7280";
  return (
    <div
      className="px-3 py-2 rounded-lg shadow-md border-2 bg-white text-xs"
      style={{ borderColor: color }}
    >
      <div className="font-bold font-mono text-gray-800">{data.label}</div>
      <div className="flex items-center gap-1.5 mt-0.5">
        <span
          className="w-1.5 h-1.5 rounded-full inline-block"
          style={{ backgroundColor: color }}
        />
        <span className="text-gray-500">{data.type}</span>
      </div>
      {data.file_path && (
        <div className="text-[10px] text-gray-400 mt-0.5 truncate max-w-[160px]">
          {data.file_path.split("/").pop()}
        </div>
      )}
    </div>
  );
}

const nodeTypes: NodeTypes = {
  graphNode: GraphNode,
};

/* ── Helpers to convert API response to React Flow nodes/edges ── */

function toFlowNodes(
  nodes: GraphNodeItem[],
  centerId: string,
): Node[] {
  const positions = distributeInCircle(nodes.length, 300);
  return nodes.map((n, i) => ({
    id: n.id,
    type: "graphNode",
    position: n.id === centerId ? { x: 0, y: 0 } : positions[i],
    data: { label: n.label, type: n.type, file_path: n.file_path },
  }));
}

function toFlowEdges(edges: GraphEdgeItem[]): Edge[] {
  return edges.map((e) => ({
    id: `${e.source}→${e.target}`,
    source: e.source,
    target: e.target,
    label: e.confidence != null ? e.confidence.toFixed(2) : e.type,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed },
    style: {
      stroke: e.confidence != null && e.confidence < 0.6 ? "#f59e0b" : "#94a3b8",
      strokeWidth: e.confidence != null && e.confidence >= 0.6 ? 2 : 1.5,
    },
  }));
}

function distributeInCircle(count: number, radius: number) {
  if (count === 0) return [];
  return Array.from({ length: count }, (_, i) => {
    const angle = (2 * Math.PI * i) / count - Math.PI / 2;
    return {
      x: radius * Math.cos(angle),
      y: radius * Math.sin(angle),
    };
  });
}

/* ── Main component ──────────────────────────────────────────── */

export default function GraphExplorer() {
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

  const loadGraph = useCallback(
    async (sym: string) => {
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
        const flowNodes = toFlowNodes(resp.nodes, resp.center_node_id);
        const flowEdges = toFlowEdges(resp.edges);
        setNodes(flowNodes);
        setEdges(flowEdges);
      } catch (e: unknown) {
        setState({
          mode: "error",
          error: e instanceof Error ? e.message : "Failed to load graph",
          response: null,
        });
        setNodes([]);
        setEdges([]);
      }
    },
    [depth, setNodes, setEdges],
  );

  // Load if symbol was passed via query param
  useEffect(() => {
    if (initialSymbol) loadGraph(initialSymbol);
  }, [initialSymbol]); // only on mount

  const handleExplore = () => loadGraph(symbolId);

  const renderContent = () => {
    switch (state.mode) {
      case "initial":
        return <InitialState />;
      case "loading":
        return <LoadingState />;
      case "error":
        return <ErrorState message={state.error} />;
      case "graph":
        return (
          <GraphCanvas
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            response={state.response!}
          />
        );
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Graph Explorer</h1>
        <p className="text-gray-500 text-sm mt-1">
          Visualize the local call graph centered on a symbol.
        </p>
      </div>

      {/* Controls */}
      <div className="flex gap-3 items-end">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Center Symbol ID
          </label>
          <input
            type="text"
            value={symbolId}
            onChange={(e) => setSymbolId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleExplore()}
            placeholder="e.g. src/app/api/auth.py::login"
            className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Depth
          </label>
          <select
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            className="px-3 py-2 border rounded-lg bg-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
          </select>
        </div>
        <button
          onClick={handleExplore}
          disabled={state.mode === "loading" || !symbolId.trim()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {state.mode === "loading" ? "Loading..." : "Explore"}
        </button>
      </div>

      {renderContent()}
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────── */

function InitialState() {
  return (
    <div className="text-center py-16 border-2 border-dashed border-gray-300 rounded-xl">
      <div className="text-5xl text-gray-300 mb-4">⬡</div>
      <h2 className="text-lg font-semibold text-gray-500">
        Enter a symbol ID to explore
      </h2>
      <p className="text-sm text-gray-400 mt-1">
        The graph will show the local call neighborhood around the symbol.
      </p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="h-[600px] border rounded-xl bg-gray-50 flex items-center justify-center animate-pulse">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
        <p className="text-sm text-gray-400 mt-3">Loading graph...</p>
      </div>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  const is404 = message.includes("not found") || message.includes("404");
  return (
    <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
      {is404
        ? "Symbol not found in the graph. Make sure the repo has been indexed and the symbol ID is correct."
        : message}
    </div>
  );
}

function GraphCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  response,
}: {
  nodes: Node[];
  edges: Edge[];
  onNodesChange: ReactFlowProps["onNodesChange"];
  onEdgesChange: ReactFlowProps["onEdgesChange"];
  response: SubgraphResponse;
}) {
  const legendItems = Object.entries(TYPE_COLORS).map(([type, color]) => ({
    type,
    color,
  }));

  return (
    <div className="border rounded-xl overflow-hidden" style={{ height: 600 }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        attributionPosition="bottom-left"
      >
        <Background />
        <Controls />
        <MiniMap
          nodeStrokeWidth={3}
          nodeColor={(n) => {
            const t = (n.data as { type?: string })?.type;
            return TYPE_COLORS[t || ""] || "#6b7280";
          }}
        />
      </ReactFlow>

      {/* Legend */}
      <div className="absolute bottom-4 right-4 bg-white/90 backdrop-blur rounded-lg shadow p-3 text-xs space-y-1.5 z-10">
        <p className="font-semibold text-gray-700 mb-1">Legend</p>
        {legendItems.map(({ type, color }) => (
          <div key={type} className="flex items-center gap-2">
            <span
              className="w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="capitalize text-gray-600">{type}</span>
          </div>
        ))}
        <div className="flex items-center gap-2 mt-1.5 pt-1.5 border-t border-gray-200">
          <span className="w-4 h-0.5 bg-amber-500 inline-block" />
          <span className="text-gray-500">low confidence (&lt;0.6)</span>
        </div>
      </div>

      {/* Stats overlay */}
      <div className="absolute top-3 left-3 bg-white/90 backdrop-blur rounded-lg shadow px-3 py-2 text-xs z-10">
        <span className="text-gray-600">
          {nodes.length} nodes · {edges.length} edges · depth {response.depth}
        </span>
      </div>
    </div>
  );
}
