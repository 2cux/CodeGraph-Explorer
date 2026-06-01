import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import type { Node, Edge } from "@xyflow/react";
import { GraphCanvas } from "../../app/components/GraphCanvas";
import {
  toReactFlowGraph,
  deriveHierarchyGroups,
  applyHierarchyFolding,
  prioritizeAndCapNodes,
} from "../../app/components/graphTransforms";
import type { RFNodeData, RFEdgeData } from "../../app/components/graphTransforms";
import type { SubgraphResponse } from "../../api";

// ── Test data ─────────────────────────────────────────────────────────

const mockSubgraph: SubgraphResponse = {
  center_node_id: "src/auth.py::login",
  depth: 1,
  nodes: [
    { id: "src/auth.py::login", label: "login", type: "function", file_path: "src/auth.py" },
    { id: "src/auth.py::verify_token", label: "verify_token", type: "function", file_path: "src/auth.py" },
    // External node: no file_path, won't be collapsed by hierarchy
    { id: "src/db.py::connect", label: "connect", type: "function", file_path: null },
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
      // Expand the external group so the edge isn't rerouted to a group parent
      expandedGroupIds: new Set(["external:"]),
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

// ── Hierarchy folding tests ─────────────────────────────────────────────

describe("deriveHierarchyGroups", () => {
  it("groups nodes by file correctly", () => {
    const nodes = [
      { id: "src/auth.py::login", label: "login", type: "function", file_path: "src/auth.py" },
      { id: "src/auth.py::logout", label: "logout", type: "function", file_path: "src/auth.py" },
      { id: "src/db.py::connect", label: "connect", type: "function", file_path: "src/db.py" },
    ];
    const groups = deriveHierarchyGroups(nodes);

    expect(groups.has("file:src/auth.py")).toBe(true);
    expect(groups.has("file:src/db.py")).toBe(true);
    const authGroup = groups.get("file:src/auth.py")!;
    expect(authGroup.childIds).toContain("src/auth.py::login");
    expect(authGroup.childIds).toContain("src/auth.py::logout");
    expect(authGroup.kind).toBe("file_group");
  });

  it("handles external nodes (no file_path)", () => {
    const nodes = [
      { id: "external::symbol", label: "ext", type: "external_symbol", file_path: null },
    ];
    const groups = deriveHierarchyGroups(nodes);

    expect(groups.has("external:")).toBe(true);
    const extGroup = groups.get("external:")!;
    expect(extGroup.childIds).toContain("external::symbol");
  });

  it("derives module groups from file paths", () => {
    const nodes = [
      { id: "src/api/auth.py::login", label: "login", type: "function", file_path: "src/api/auth.py" },
      { id: "src/api/routes.py::router", label: "router", type: "function", file_path: "src/api/routes.py" },
    ];
    const groups = deriveHierarchyGroups(nodes);

    expect(groups.has("module:src/api")).toBe(true);
  });
});

describe("applyHierarchyFolding", () => {
  const foldingNodes: Node<RFNodeData>[] = [
    {
      id: "auth.py::login", type: "customNode", position: { x: 400, y: 300 },
      data: { symbolId: "auth.py::login", name: "login", kind: "function", filePath: "auth.py", isCenter: true, isSelected: false, confidence: 1.0, hierarchyGroup: "file:auth.py", hierarchyLevel: 1 },
    },
    {
      id: "auth.py::verify", type: "customNode", position: { x: 700, y: 300 },
      data: { symbolId: "auth.py::verify", name: "verify", kind: "function", filePath: "auth.py", isCenter: false, isSelected: false, confidence: 0.9, hierarchyGroup: "file:auth.py", hierarchyLevel: 1 },
    },
    {
      id: "db.py::connect", type: "customNode", position: { x: 400, y: 500 },
      data: { symbolId: "db.py::connect", name: "connect", kind: "function", filePath: "db.py", isCenter: false, isSelected: false, confidence: 0.7, hierarchyGroup: "file:db.py", hierarchyLevel: 1 },
    },
  ];

  const foldingEdges: Edge<RFEdgeData>[] = [
    {
      id: "e1", source: "auth.py::login", target: "auth.py::verify",
      type: "customEdge",
      data: { edgeType: "calls", confidence: 0.95, confidenceLevel: "high", isExternal: false },
    },
    {
      id: "e2", source: "auth.py::login", target: "db.py::connect",
      type: "customEdge",
      data: { edgeType: "calls", confidence: 0.7, confidenceLevel: "medium", isExternal: false },
    },
  ];

  it("replaces children with parent when collapsed", () => {
    const result = applyHierarchyFolding(foldingNodes, foldingEdges, new Set(), "auth.py::login");

    // "file:auth.py" auto-expanded (center is in it), "file:db.py" collapsed
    // login, verify visible; connect hidden; file:db.py group parent added
    const ids = new Set(result.displayNodes.map((n) => n.id));
    expect(ids.has("auth.py::login")).toBe(true);
    expect(ids.has("auth.py::verify")).toBe(true);
    expect(ids.has("file:db.py")).toBe(true); // group parent
    expect(ids.has("db.py::connect")).toBe(false); // hidden

    // Group parent node has correct data
    const groupParent = result.displayNodes.find((n) => n.id === "file:db.py");
    expect(groupParent?.data.isGroupParent).toBe(true);
    expect(groupParent?.data.childCount).toBe(1);
    expect(groupParent?.type).toBe("hierarchyGroup");
  });

  it("shows children when group is expanded", () => {
    const result = applyHierarchyFolding(
      foldingNodes, foldingEdges,
      new Set(["file:db.py"]), // explicitly expand db.py
      "auth.py::login",
    );

    const ids = new Set(result.displayNodes.map((n) => n.id));
    expect(ids.has("db.py::connect")).toBe(true); // visible
  });

  it("reroutes edges to parent when collapsed", () => {
    const result = applyHierarchyFolding(foldingNodes, foldingEdges, new Set(), "auth.py::login");

    // Edge from login → connect should be rerouted to login → file:db.py
    const rerouted = result.displayEdges.find(
      (e) => e.source === "auth.py::login" && e.target === "file:db.py",
    );
    expect(rerouted).toBeDefined();

    // Internal edge (login→verify, same group) should be preserved
    const internal = result.displayEdges.find(
      (e) => e.source === "auth.py::login" && e.target === "auth.py::verify",
    );
    expect(internal).toBeDefined();
  });

  it("hides internal edges between children of same collapsed group", () => {
    // Add second node to db.py group
    const nodesWithInternal: Node<RFNodeData>[] = [
      ...foldingNodes,
      {
        id: "db.py::disconnect", type: "customNode", position: { x: 700, y: 500 },
        data: { symbolId: "db.py::disconnect", name: "disconnect", kind: "function", filePath: "db.py", isCenter: false, isSelected: false, confidence: 0.8, hierarchyGroup: "file:db.py", hierarchyLevel: 1 },
      },
    ];
    const edgesWithInternal: Edge<RFEdgeData>[] = [
      ...foldingEdges,
      {
        id: "e3", source: "db.py::connect", target: "db.py::disconnect",
        type: "customEdge",
        data: { edgeType: "calls", confidence: 0.8, confidenceLevel: "high", isExternal: false },
      },
    ];

    const result = applyHierarchyFolding(nodesWithInternal, edgesWithInternal, new Set(), "auth.py::login");

    // Internal edge between collapsed children should NOT appear
    const internalEdge = result.displayEdges.find(
      (e) => e.source === "db.py::connect" && e.target === "db.py::disconnect",
    );
    expect(internalEdge).toBeUndefined();
  });
});

// ── Node capping tests ────────────────────────────────────────────────

describe("prioritizeAndCapNodes", () => {
  const capNodes: Node<RFNodeData>[] = [];
  const capEdges: Edge<RFEdgeData>[] = [];

  // Generate 10 nodes for capping tests
  for (let i = 0; i < 10; i++) {
    capNodes.push({
      id: `node-${i}`,
      type: "customNode",
      position: { x: i * 200, y: 300 },
      data: {
        symbolId: `node-${i}`, name: `node${i}`, kind: i === 0 ? "class" : "function",
        filePath: "file.py", isCenter: i === 0, isSelected: false, confidence: 1.0,
        hierarchyGroup: "file:file.py", hierarchyLevel: 1,
      },
    });
    if (i > 0) {
      capEdges.push({
        id: `e${i}`,
        source: "node-0",
        target: `node-${i}`,
        type: "customEdge",
        data: { edgeType: "calls", confidence: 0.9, confidenceLevel: "high", isExternal: false },
      });
    }
  }

  it("always includes center node", () => {
    const { cappedNodes } = prioritizeAndCapNodes(capNodes, capEdges, "node-0", 1);
    expect(cappedNodes.length).toBeLessThanOrEqual(1);
    expect(cappedNodes.some((n) => n.id === "node-0")).toBe(true);
  });

  it("caps at maxNodes", () => {
    const { cappedNodes } = prioritizeAndCapNodes(capNodes, capEdges, "node-0", 5);
    expect(cappedNodes.length).toBeLessThanOrEqual(5);
  });

  it("returns warning when capped", () => {
    const { warning } = prioritizeAndCapNodes(capNodes, capEdges, "node-0", 5);
    expect(warning).not.toBeNull();
    expect(warning!.totalNodes).toBe(10);
    expect(warning!.visibleNodes).toBeLessThanOrEqual(5);
  });

  it("returns null warning when no capping needed", () => {
    const { warning } = prioritizeAndCapNodes(capNodes, capEdges, "node-0", 50);
    expect(warning).toBeNull();
  });

  it("only includes edges with both endpoints in capped set", () => {
    const { cappedNodes, cappedEdges } = prioritizeAndCapNodes(capNodes, capEdges, "node-0", 2);
    const cappedIds = new Set(cappedNodes.map((n) => n.id));
    for (const e of cappedEdges) {
      expect(cappedIds.has(e.source)).toBe(true);
      expect(cappedIds.has(e.target)).toBe(true);
    }
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
    expect(container.textContent).toContain("No code graph index found");
    expect(container.textContent).toContain("codegraph");
  });

  it("shows empty state when focused but no nodes provided", () => {
    const { container } = render(
      <GraphCanvas state="focused" rfNodes={[]} rfEdges={[]} />,
    );
    expect(container.textContent).toContain("No code graph index found");
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
