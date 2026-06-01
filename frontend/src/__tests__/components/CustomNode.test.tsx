import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import CustomNode from "../../app/components/CustomNode";
import type { RFNodeData } from "../../app/components/graphTransforms";
import { NODE_DIMS } from "../../app/components/nodeStyles";

// Helper to render node inside ReactFlow context
function renderNode(data: RFNodeData, selected = false) {
  const nodeProps = {
    id: data.symbolId,
    type: "customNode",
    data,
    selected,
    dragging: false,
    zIndex: 0,
    isConnectable: true,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    xPos: 0,
    yPos: 0,
  } as any;

  return render(
    <ReactFlowProvider>
      <CustomNode {...nodeProps} />
    </ReactFlowProvider>,
  );
}

const baseData: RFNodeData = {
  symbolId: "src/auth.py::login",
  name: "login",
  kind: "function",
  filePath: "src/auth.py",
  isCenter: false,
  isSelected: false,
  confidence: 1.0,
};

describe("CustomNode — dimensions", () => {
  it("has minWidth >= 160px", () => {
    const { container } = renderNode(baseData);
    const node = container.querySelector(".cg-rf-node") as HTMLElement;
    expect(node).not.toBeNull();
    const style = node.style.minWidth;
    expect(style).toBe(`${NODE_DIMS.minWidth}px`);
  });

  it("has minHeight in style", () => {
    const { container } = renderNode(baseData);
    const inner = container.querySelector(".cg-rf-node > div") as HTMLElement;
    expect(inner).not.toBeNull();
    expect(inner.style.minHeight).toBe(`${NODE_DIMS.minHeight}px`);
  });
});

describe("CustomNode — state CSS classes", () => {
  it("applies cg-node--center class for center node", () => {
    const { container } = renderNode({ ...baseData, isCenter: true });
    expect(container.querySelector(".cg-node--center")).toBeTruthy();
  });

  it("applies cg-node--selected class when selected via prop", () => {
    const { container } = renderNode({ ...baseData, isSelected: true });
    expect(container.querySelector(".cg-node--selected")).toBeTruthy();
  });

  it("applies cg-node--selected class when React Flow selected", () => {
    const { container } = renderNode(baseData, true);
    expect(container.querySelector(".cg-node--selected")).toBeTruthy();
  });

  it("applies cg-node--external class for external symbols", () => {
    const { container } = renderNode({
      ...baseData,
      kind: "external_symbol",
      confidence: 0.3,
    });
    expect(container.querySelector(".cg-node--external")).toBeTruthy();
  });

  it("applies cg-node--low-confidence class for low confidence", () => {
    const { container } = renderNode({ ...baseData, confidence: 0.45 });
    expect(container.querySelector(".cg-node--low-confidence")).toBeTruthy();
  });

  it("does NOT apply low-confidence class when node is center", () => {
    const { container } = renderNode({ ...baseData, isCenter: true, confidence: 0.45 });
    expect(container.querySelector(".cg-node--low-confidence")).toBeFalsy();
  });
});

describe("CustomNode — content rendering", () => {
  it("renders node name", () => {
    const { container } = renderNode(baseData);
    expect(container.textContent).toContain("login");
  });

  it("renders file path short", () => {
    const { container } = renderNode(baseData);
    expect(container.textContent).toContain("auth.py");
  });

  it("renders type label badge", () => {
    const { container } = renderNode({ ...baseData, kind: "class" });
    expect(container.textContent).toContain("CLASS");
  });

  it("renders left color bar", () => {
    const { container } = renderNode(baseData);
    const colorBar = container.querySelector(".cg-rf-node > div > div:first-child") as HTMLElement;
    expect(colorBar).not.toBeNull();
    expect(colorBar.style.width).toBe("4px");
  });
});

describe("CustomNode — tooltip", () => {
  it("shows filePath and filepath in content", () => {
    const { container } = renderNode({
      ...baseData,
      filePath: "src/utils/helpers/auth.py",
    });
    // filePathShort shows last 2 segments
    expect(container.textContent).toContain("helpers/auth.py");
  });
});
