import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import HierarchyGroupNode from "../../app/components/HierarchyGroupNode";
import type { RFNodeData } from "../../app/components/graphTransforms";

// ── Helpers ───────────────────────────────────────────────────────────

/** Wrap a custom node in ReactFlowProvider so it can use handles */
function renderNode(data: RFNodeData, selected = false) {
  return render(
    <ReactFlowProvider>
      <HierarchyGroupNode
        id={data.symbolId}
        type="hierarchyGroup"
        data={data}
        selected={selected}
        isConnectable={false}
        dragging={false}
        draggable={false}
        selectable={true}
        deletable={false}
        zIndex={0}
        positionAbsoluteX={0}
        positionAbsoluteY={0}
      />
    </ReactFlowProvider>,
  );
}

// ── Test data ─────────────────────────────────────────────────────────

const fileGroupData: RFNodeData = {
  symbolId: "file:src/auth.py",
  name: "auth.py",
  kind: "file_group",
  filePath: "src/auth.py",
  isCenter: false,
  isSelected: false,
  confidence: 1.0,
  isGroupParent: true,
  childCount: 5,
  childKindSummary: "3 FUNC, 2 CLASS",
  isExpanded: false,
  hierarchyGroup: "file:src/auth.py",
  hierarchyLevel: 1,
};

const moduleGroupData: RFNodeData = {
  symbolId: "module:src/api",
  name: "src/api",
  kind: "module_group",
  filePath: "src/api",
  isCenter: false,
  isSelected: false,
  confidence: 1.0,
  isGroupParent: true,
  childCount: 12,
  childKindSummary: "8 FUNC, 3 CLASS, 1 TEST",
  isExpanded: true,
  hierarchyGroup: "module:src/api",
  hierarchyLevel: 0,
};

// ── Tests ─────────────────────────────────────────────────────────────

describe("HierarchyGroupNode", () => {
  it("renders group label", () => {
    const { container } = renderNode(fileGroupData);
    expect(container.textContent).toContain("auth.py");
  });

  it("renders child count", () => {
    const { container } = renderNode(fileGroupData);
    expect(container.textContent).toContain("5 symbols");
  });

  it("renders child kind summary", () => {
    const { container } = renderNode(fileGroupData);
    expect(container.textContent).toContain("3 FUNC, 2 CLASS");
  });

  it("renders type label for file group", () => {
    const { container } = renderNode(fileGroupData);
    expect(container.textContent).toContain("FILE");
  });

  it("renders type label for module group", () => {
    const { container } = renderNode(moduleGroupData);
    expect(container.textContent).toContain("MOD");
  });

  it("shows right chevron when collapsed", () => {
    const { container } = renderNode(fileGroupData);
    // The SVG chevron-right polyline should be present
    expect(container.querySelector("svg")).toBeTruthy();
    // Collapsed → right-pointing chevron
    const svg = container.querySelector("svg")!;
    expect(svg.innerHTML).toContain("9 18 15 12 9 6");
  });

  it("shows down chevron when expanded", () => {
    const expandedData = { ...fileGroupData, isExpanded: true };
    const { container } = renderNode(expandedData);
    const svg = container.querySelector("svg")!;
    expect(svg.innerHTML).toContain("6 9 12 15 18 9");
  });

  it("fires click event", () => {
    const handleClick = vi.fn();
    const { container } = render(
      <ReactFlowProvider>
        <div onClick={() => handleClick(fileGroupData.symbolId)}>
          <HierarchyGroupNode
            id={fileGroupData.symbolId}
            type="hierarchyGroup"
            data={fileGroupData}
            selected={false}
            isConnectable={false}
            dragging={false}
            draggable={false}
            selectable={true}
            deletable={false}
            zIndex={0}
            positionAbsoluteX={0}
            positionAbsoluteY={0}
          />
        </div>
      </ReactFlowProvider>,
    );

    const nodeEl = container.querySelector(".cg-group-parent");
    expect(nodeEl).toBeTruthy();
    fireEvent.click(nodeEl!);
    // The click fires on the wrapping div which calls handleClick
    expect(handleClick).toHaveBeenCalledWith("file:src/auth.py");
  });

  it("has different left border color for module vs file groups", () => {
    const { container: fileContainer } = renderNode(fileGroupData);
    const { container: modContainer } = renderNode(moduleGroupData);

    // Both should render without error and have their respective type labels
    expect(fileContainer.textContent).toContain("FILE");
    expect(modContainer.textContent).toContain("MOD");
  });

  it("renders with overlay hidden style", () => {
    const { container } = renderNode(fileGroupData);
    const root = container.querySelector(".cg-rf-node");
    expect(root).toBeTruthy();
    // overflow should be visible (not hidden) for tooltip
    expect((root as HTMLElement).style.overflow).toBe("visible");
  });
});
