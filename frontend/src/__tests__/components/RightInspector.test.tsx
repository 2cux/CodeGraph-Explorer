import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RightInspector, type NodeInspectorData, type EdgeInspectorData } from "../../app/components/RightInspector";

const mockNodeData: NodeInspectorData = {
  symbol_id: "src/auth.py::authenticate",
  name: "authenticate",
  type: "function",
  file_path: "src/auth.py",
  line_start: 42,
  line_end: 78,
  signature: "def authenticate(username: str, password: str) -> User",
  docstring: "Authenticates user credentials.",
  tags: ["auth", "api"],
  visibility: "public",
  callers_count: 3,
  callees_count: 5,
  tests_count: 2,
};

const mockEdgeData: EdgeInspectorData = {
  source: "authenticate",
  target: "verify_token",
  type: "calls",
  confidence: 0.72,
  confidence_level: "medium",
  resolution: "imported_function_exact",
  reason_codes: ["import_resolved", "same_module_fallback"],
  evidence: "from app.services.auth_service import verify_token",
  source_location: { file_path: "src/auth.py", line_start: 45 },
};

describe("RightInspector - Node mode", () => {
  it("shows symbol_id, file_path, and name when node data is provided", () => {
    const { container } = render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={mockNodeData}
      />
    );

    const text = container.textContent || "";
    expect(text).toContain("src/auth.py::authenticate");
    expect(text).toContain("src/auth.py");
    expect(text).toContain("authenticate");
    // Signature text appears but is split across colorized spans
    expect(text).toContain("def authenticate");
  });

  it("shows type and tags", () => {
    render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={mockNodeData}
      />
    );

    expect(screen.getByText("FUNCTION")).toBeInTheDocument();
    expect(screen.getByText("auth")).toBeInTheDocument();
    expect(screen.getByText("api")).toBeInTheDocument();
  });

  it("shows empty state when no node data", () => {
    render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={null}
      />
    );

    expect(screen.getByText("Select a node to inspect.")).toBeInTheDocument();
  });

  it("does not contain action directive UI文案", () => {
    const { container } = render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={mockNodeData}
      />
    );

    const text = (container.textContent || "").toLowerCase();
    const forbidden = ["read first", "you should", "must inspect", "next step", "implement"];
    for (const term of forbidden) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });
});

describe("RightInspector - Edge mode", () => {
  it("shows confidence, resolution, and evidence when edge data is provided", () => {
    const { container } = render(
      <RightInspector
        target="edge"
        mode="edge"
        onClose={() => {}}
        edgeData={mockEdgeData}
      />
    );

    const text = container.textContent || "";
    expect(text).toContain("0.72");
    // resolution code is displayed as human-readable label
    expect(text).toContain("Imported function (exact name)");
    expect(text).toContain("from app.services.auth_service import verify_token");
  });

  it("shows confidence level label (Medium)", () => {
    const { container } = render(
      <RightInspector
        target="edge"
        mode="edge"
        onClose={() => {}}
        edgeData={mockEdgeData}
      />
    );

    expect(container.textContent).toContain("Medium");
  });

  it("shows weak signal notice for low-confidence edges", () => {
    const lowConfEdge: EdgeInspectorData = {
      ...mockEdgeData,
      confidence: 0.45,
      confidence_level: "low",
    };

    render(
      <RightInspector
        target="edge"
        mode="edge"
        onClose={() => {}}
        edgeData={lowConfEdge}
      />
    );

    expect(screen.getByText("Weak signal")).toBeInTheDocument();
  });

  it("does NOT show weak signal for high-confidence edges", () => {
    const highConfEdge: EdgeInspectorData = {
      ...mockEdgeData,
      confidence: 0.95,
      confidence_level: "high",
    };

    render(
      <RightInspector
        target="edge"
        mode="edge"
        onClose={() => {}}
        edgeData={highConfEdge}
      />
    );

    expect(screen.queryByText("Weak signal")).not.toBeInTheDocument();
  });

  it("shows empty state when no edge data", () => {
    render(
      <RightInspector
        target="edge"
        mode="edge"
        onClose={() => {}}
        edgeData={null}
      />
    );

    expect(screen.getByText("Select an edge to inspect.")).toBeInTheDocument();
  });

  it("Edge Inspector does not contain action directives", () => {
    const { container } = render(
      <RightInspector
        target="edge"
        mode="edge"
        onClose={() => {}}
        edgeData={mockEdgeData}
      />
    );

    const text = (container.textContent || "").toLowerCase();
    const forbidden = ["read first", "you should", "must inspect", "next step", "implement"];
    for (const term of forbidden) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });
});

describe("RightInspector - Edge evidence display", () => {
  it("shows reason field when provided", () => {
    const edgeData: EdgeInspectorData = {
      ...mockEdgeData,
      reason: "Resolved verify_token via from-import in auth module.",
    };

    const { container } = render(
      <RightInspector target="edge" mode="edge" onClose={() => {}} edgeData={edgeData} />
    );

    expect(container.textContent).toContain("Resolved verify_token via from-import");
  });

  it("shows 'No detailed evidence available' when evidence is empty", () => {
    const edgeData: EdgeInspectorData = {
      ...mockEdgeData,
      evidence: "",
    };

    render(
      <RightInspector target="edge" mode="edge" onClose={() => {}} edgeData={edgeData} />
    );

    expect(screen.getByText("No detailed evidence available")).toBeInTheDocument();
  });

  it("shows 'No detailed evidence available' when evidence is null", () => {
    const edgeData: EdgeInspectorData = {
      ...mockEdgeData,
      evidence: undefined,
    };

    render(
      <RightInspector target="edge" mode="edge" onClose={() => {}} edgeData={edgeData} />
    );

    expect(screen.getByText("No detailed evidence available")).toBeInTheDocument();
  });

  it("shows all required fields: source, target, type, confidence, confidence_level, resolution", () => {
    const { container } = render(
      <RightInspector target="edge" mode="edge" onClose={() => {}} edgeData={mockEdgeData} />
    );

    const text = container.textContent || "";
    expect(text).toContain("authenticate");
    expect(text).toContain("verify_token");
    expect(text).toContain("calls");
    expect(text).toContain("0.72");
    expect(text).toContain("Medium");
    expect(text).toContain("Imported function (exact name)");
  });

  it("displays source_location when provided", () => {
    const { container } = render(
      <RightInspector target="edge" mode="edge" onClose={() => {}} edgeData={mockEdgeData} />
    );

    expect(container.textContent).toContain("src/auth.py:45");
  });

  it("displays reason_codes as badges", () => {
    render(
      <RightInspector target="edge" mode="edge" onClose={() => {}} edgeData={mockEdgeData} />
    );

    expect(screen.getByText("import_resolved")).toBeInTheDocument();
    expect(screen.getByText("same_module_fallback")).toBeInTheDocument();
  });
});

describe("RightInspector - Node: Copy buttons and confidence", () => {
  it("shows Copy Symbol ID button when onCopyToClipboard is provided", () => {
    render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={{ ...mockNodeData, confidence: 0.95 }}
        onCopyToClipboard={() => {}}
      />
    );
    expect(screen.getByText("Copy ID")).toBeInTheDocument();
  });

  it("shows Copy File Path button when onCopyToClipboard is provided", () => {
    render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={mockNodeData}
        onCopyToClipboard={() => {}}
      />
    );
    expect(screen.getByText("Copy Path")).toBeInTheDocument();
  });

  it("shows confidence field when provided", () => {
    const { container } = render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={{ ...mockNodeData, confidence: 0.95 }}
      />
    );
    expect(container.textContent).toContain("confidence");
    expect(container.textContent).toContain("0.95");
  });
});

describe("RightInspector - Node: Quick action buttons", () => {
  it("shows Callers, Callees, Neighbors, Impact buttons for non-group nodes", () => {
    render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={mockNodeData}
        onSelectSymbol={() => {}}
        onShowCallers={() => {}}
        onShowCallees={() => {}}
        onShowImpact={() => {}}
      />
    );
    expect(screen.getByText("Callers")).toBeInTheDocument();
    expect(screen.getByText("Callees")).toBeInTheDocument();
    expect(screen.getByText("Neighbors")).toBeInTheDocument();
    expect(screen.getByText("Impact")).toBeInTheDocument();
  });

  it("does NOT show quick action buttons for group parent nodes", () => {
    const { container } = render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={{
          symbol_id: "file:src/auth.py",
          name: "auth.py",
          type: "file_group",
          file_path: "src/auth.py",
          is_group_parent: true,
          child_count: 3,
        }}
        onSelectSymbol={() => {}}
      />
    );
    expect(container.textContent).not.toContain("Callers");
    expect(container.textContent).not.toContain("Callees");
    expect(container.textContent).not.toContain("Neighbors");
    expect(container.textContent).not.toContain("Impact");
  });
});

describe("RightInspector - Node: Callers/Callees list", () => {
  const nodeDataWithLists: NodeInspectorData = {
    ...mockNodeData,
    callers_list: [
      { node_id: "src/x.py::foo", name: "foo", type: "function", file_path: "src/x.py", edge_type: "calls" },
      { node_id: "tests/test_auth.py::test_login", name: "test_login", type: "test", file_path: "tests/test_auth.py", edge_type: "tested_by" },
    ],
    callees_list: [
      { node_id: "src/db.py::query", name: "query", type: "function", file_path: "src/db.py", edge_type: "calls" },
    ],
  };

  it("shows callers list when callers_list is provided", () => {
    const { container } = render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={nodeDataWithLists}
        onSelectSymbol={() => {}}
      />
    );
    expect(container.textContent).toContain("Callers (2)");
    expect(container.textContent).toContain("foo");
    expect(container.textContent).toContain("test_login");
  });

  it("shows callees list when callees_list is provided", () => {
    const { container } = render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={nodeDataWithLists}
        onSelectSymbol={() => {}}
      />
    );
    expect(container.textContent).toContain("Callees (1)");
    expect(container.textContent).toContain("query");
  });
});

describe("RightInspector - Node: Empty callers/callees", () => {
  it("shows 'No callers or callees found' when both counts are 0", () => {
    const { container } = render(
      <RightInspector
        target="node"
        mode="node"
        onClose={() => {}}
        nodeData={{ ...mockNodeData, callers_count: 0, callees_count: 0 }}
      />
    );
    expect(container.textContent).toContain("No callers or callees found");
  });
});

describe("RightInspector - Edge: Unresolved/External markers", () => {
  it("shows Unresolved marker when resolution is 'unresolved'", () => {
    render(
      <RightInspector
        target="edge"
        mode="edge"
        onClose={() => {}}
        edgeData={{ ...mockEdgeData, resolution: "unresolved", confidence: 0.3, confidence_level: "low" }}
      />
    );
    // "Unresolved" appears both as resolution label and as the marker heading
    const elements = screen.getAllByText("Unresolved");
    expect(elements.length).toBeGreaterThanOrEqual(1);
  });

  it("shows External marker when resolution is 'external_symbol'", () => {
    render(
      <RightInspector
        target="edge"
        mode="edge"
        onClose={() => {}}
        edgeData={{ ...mockEdgeData, resolution: "external_symbol", confidence: 0.1, confidence_level: "low" }}
      />
    );
    expect(screen.getByText("External")).toBeInTheDocument();
  });

  it("does NOT show Unresolved or External markers for normal resolutions", () => {
    render(
      <RightInspector
        target="edge"
        mode="edge"
        onClose={() => {}}
        edgeData={mockEdgeData}
      />
    );
    expect(screen.queryByText("Unresolved")).not.toBeInTheDocument();
    expect(screen.queryByText("External")).not.toBeInTheDocument();
  });

  it("does not contain forbidden phrases in edge inspector", () => {
    const { container } = render(
      <RightInspector
        target="edge"
        mode="edge"
        onClose={() => {}}
        edgeData={{ ...mockEdgeData, resolution: "unresolved" }}
      />
    );
    const text = (container.textContent || "").toLowerCase();
    const forbidden = ["read first", "you should", "must inspect", "next step", "implement"];
    for (const term of forbidden) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });
});

describe("RightInspector - Error state", () => {
  it("shows error state when mode is error", () => {
    render(
      <RightInspector target="edge" mode="error" onClose={() => {}} onRetry={() => {}} />
    );

    expect(screen.getByText("Failed to load data.")).toBeInTheDocument();
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });
});
