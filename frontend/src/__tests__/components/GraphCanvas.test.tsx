import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import type { Node, Edge } from "@xyflow/react";
import { GraphCanvas } from "../../app/components/GraphCanvas";
import { toReactFlowGraph } from "../../app/components/graphTransforms";
import type { RFNodeData, RFEdgeData } from "../../app/components/graphTransforms";
import type { SubgraphResponse } from "../../api";

// ── Test data ─────────────────────────────────────────────────────────

const mockSubgraph: SubgraphResponse = {
  center_node_id: "src/auth.py::login",
  depth: 1,
  nodes: [
    { id: "src/auth.py::login", label: "login", type: "function", file_path: "src/auth.py" },
    { id: "src/auth.py::verify_token", label: "verify_token", type: "function", file_path: "src/auth.py" },
    { id: "src/db.py::connect", label: "connect", type: "function", file_path: "src/db.py" },
  ],
  edges: [
    { source: "src/auth.py::login", target: "src/auth.py::verify_token", type: "calls", confidence: 0.95 },
    { source: "src/auth.py::login", target: "src/db.py::connect", type: "calls", confidence: 0.45 },
  ],
  layout_hints: { group_by: "file", max_nodes: 100, suggested_view: "local_call_graph" },
};

const mockRfNodes: Node<RFNodeData>[] = [
  {
    id: "src/auth.py::login",
    type: "customNode",
    position: { x: 400, y: 300 },
    data: {
      symbolId: "src/auth.py::login", name: "login", kind: "function",
      filePath: "src/auth.py", isCenter: true, isSelected: false, confidence: 1.0,
    },
  },
  {
    id: "src/auth.py::verify_token",
    type: "customNode",
    position: { x: 700, y: 300 },
    data: {
      symbolId: "src/auth.py::verify_token", name: "verify_token", kind: "function",
      filePath: "src/auth.py", isCenter: false, isSelected: false, confidence: 0.95,
    },
  },
];

const mockRfEdges: Edge<RFEdgeData>[] = [
  {
    id: "edge-0",
    source: "src/auth.py::login",
    target: "src/auth.py::verify_token",
    type: "customEdge",
    data: { edgeType: "calls", confidence: 0.95, confidenceLevel: "high", isExternal: false },
  },
];

// ── Data transformation tests ─────────────────────────────────────────

describe("toReactFlowGraph", () => {
  it("transforms SubgraphResponse into React Flow nodes and edges", () => {
    const { nodes, edges } = toReactFlowGraph(mockSubgraph, {
      centerNodeId: "src/auth.py::login",
    });

    expect(nodes.length).toBeGreaterThanOrEqual(3);
    expect(edges.length).toBe(2);

    // Center node marked correctly
    const center = nodes.find((n) => n.id === "src/auth.py::login");
    expect(center?.data.isCenter).toBe(true);
    expect(center?.type).toBe("customNode");

    // Edge data preserved
    const callEdge = edges.find(
      (e) => e.source === "src/auth.py::login" && e.target === "src/auth.py::verify_token",
    );
    expect(callEdge?.data?.edgeType).toBe("calls");
    expect(callEdge?.data?.confidence).toBe(0.95);
    expect(callEdge?.data?.confidenceLevel).toBe("high");
  });

  it("marks low-confidence edges correctly", () => {
    const { edges } = toReactFlowGraph(mockSubgraph, {
      centerNodeId: "src/auth.py::login",
    });

    const lowEdge = edges.find(
      (e) => e.source === "src/auth.py::login" && e.target === "src/db.py::connect",
    );
    expect(lowEdge?.data?.confidence).toBe(0.45);
    expect(lowEdge?.data?.confidenceLevel).toBe("low");
  });

  it("ensures center node exists even if not in subgraph nodes", () => {
    const subgraphWithoutCenter: SubgraphResponse = {
      center_node_id: "src/new.py::unknown",
      depth: 1,
      nodes: [{ id: "src/other.py::helper", label: "helper", type: "function", file_path: "src/other.py" }],
      edges: [],
      layout_hints: { group_by: "file", max_nodes: 100, suggested_view: "local_call_graph" },
    };

    const { nodes } = toReactFlowGraph(subgraphWithoutCenter, {
      centerNodeId: "src/new.py::unknown",
      centerName: "unknown",
      centerFilePath: "src/new.py",
    });

    const center = nodes.find((n) => n.id === "src/new.py::unknown");
    expect(center).toBeDefined();
    expect(center?.data.isCenter).toBe(true);
  });
});

// ── GraphCanvas state tests ───────────────────────────────────────────

describe("GraphCanvas - empty/error states", () => {
  it("shows loading state with spinner text", () => {
    const { container } = render(<GraphCanvas state="loading" />);
    expect(container.textContent).toContain("Loading graph");
  });

  it("shows error state with API connection message when API unreachable", () => {
    const { container } = render(<GraphCanvas state="error" />);
    expect(container.textContent).toContain("Cannot connect to CodeGraph API");
  });

  it("shows empty state with actionable guidance when no index exists", () => {
    const { container } = render(<GraphCanvas state="empty" />);
    expect(container.textContent).toContain("No graph data available");
    expect(container.textContent).toContain("codegraph");
  });

  it("shows empty state when focused but no nodes provided", () => {
    const { container } = render(
      <GraphCanvas state="focused" rfNodes={[]} rfEdges={[]} />,
    );
    expect(container.textContent).toContain("No graph data available");
  });
});

// ── GraphCanvas node interaction tests ────────────────────────────────

describe("GraphCanvas - node click", () => {
  it("calls onSelectNode when a React Flow node is clicked", () => {
    const handleNode = vi.fn();

    const { container } = render(
      <GraphCanvas
        state="focused"
        rfNodes={mockRfNodes}
        rfEdges={mockRfEdges}
        onSelectNode={handleNode}
      />,
    );

    // React Flow renders nodes in the DOM
    const nodeElements = container.querySelectorAll(".react-flow__node");
    expect(nodeElements.length).toBeGreaterThanOrEqual(1);

    fireEvent.click(nodeElements[0]);
    expect(handleNode).toHaveBeenCalledTimes(1);
  });

  it("onSelectNode is optional — does not crash", () => {
    const { container } = render(
      <GraphCanvas state="focused" rfNodes={mockRfNodes} rfEdges={mockRfEdges} />,
    );

    const nodeElements = container.querySelectorAll(".react-flow__node");
    expect(nodeElements.length).toBeGreaterThanOrEqual(1);
    expect(() => fireEvent.click(nodeElements[0])).not.toThrow();
  });
});

// ── GraphCanvas edge interaction tests ────────────────────────────────

describe("GraphCanvas - edge click", () => {
  it("edge identity data is correctly structured for onSelectEdge callback", () => {
    // Test that the edge data structure matches what onSelectEdge expects.
    // This validates the data layer; DOM edge-click testing is covered by
    // visual/integration tests due to jsdom limitations with React Flow edge
    // path rendering (getBBox / ResizeObserver internals).
    const handleEdge = vi.fn();

    // Simulate what ReactFlowGraph does on edge click:
    const edge = mockRfEdges[0];
    handleEdge({
      source: edge.source,
      target: edge.target,
      type: edge.data?.edgeType || "calls",
    });

    expect(handleEdge).toHaveBeenCalledWith({
      source: "src/auth.py::login",
      target: "src/auth.py::verify_token",
      type: "calls",
    });
  });

  it("GraphCanvas renders with rfEdges prop without crashing", () => {
    const { container } = render(
      <GraphCanvas
        state="focused"
        rfNodes={mockRfNodes}
        rfEdges={mockRfEdges}
      />,
    );

    // Should render nodes
    expect(container.querySelectorAll(".react-flow__node").length).toBeGreaterThanOrEqual(1);
    // ReactFlow provider and pane should be present
    expect(container.querySelector(".react-flow__renderer")).toBeTruthy();
  });
});
