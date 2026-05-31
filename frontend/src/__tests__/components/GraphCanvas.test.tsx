import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { GraphCanvas, type GraphNodeData, type GraphEdgeData } from "../../app/components/GraphCanvas";

const mockNodes: GraphNodeData[] = [
  { id: "src/auth.py::login", x: 360, y: 360, kind: "function", name: "login", path: "src/auth.py", confidence: 0.95, state: "active" },
  { id: "src/auth.py::verify_token", x: 570, y: 190, kind: "function", name: "verify_token", path: "src/auth.py", confidence: 0.72, state: "normal" },
];

const mockEdges: GraphEdgeData[] = [
  { from: "src/auth.py::login", to: "src/auth.py::verify_token", label: "calls", state: "default" },
];

describe("GraphCanvas - edge click", () => {
  it("passes edge identity (source, target, type) to onSelectEdge callback", () => {
    const handleEdge = vi.fn();

    render(
      <GraphCanvas
        state="focused"
        nodes={mockNodes}
        edges={mockEdges}
        onSelectEdge={handleEdge}
      />
    );

    // Click the edge group — the SVG <g> wrapping the edge line
    const edgeGroups = document.querySelectorAll(".cg-edge-group");
    expect(edgeGroups.length).toBeGreaterThanOrEqual(1);

    // Simulate click on the edge group
    fireEvent.click(edgeGroups[0]);

    expect(handleEdge).toHaveBeenCalledTimes(1);
    expect(handleEdge).toHaveBeenCalledWith({
      source: "src/auth.py::login",
      target: "src/auth.py::verify_token",
      type: "calls",
    });
  });

  it("onSelectEdge is optional — does not crash when not provided", () => {
    render(
      <GraphCanvas
        state="focused"
        nodes={mockNodes}
        edges={mockEdges}
      />
    );

    const edgeGroups = document.querySelectorAll(".cg-edge-group");
    expect(edgeGroups.length).toBeGreaterThanOrEqual(1);

    // Click without callback should not throw
    expect(() => fireEvent.click(edgeGroups[0])).not.toThrow();
  });

  it("renders edges with from/to/label as source/target/type for identity", () => {
    const { container } = render(
      <GraphCanvas
        state="focused"
        nodes={mockNodes}
        edges={mockEdges}
      />
    );

    const text = container.textContent || "";
    // The edge label "calls" should be visible
    expect(text).toContain("calls");
  });
});
