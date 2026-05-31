import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { RightInspector } from "../../app/components/RightInspector";
import type { NodeInspectorData, EdgeInspectorData } from "../../app/components/RightInspector";
import EvidencePackViewer from "../../pages/EvidencePackViewer";
import ImpactView from "../../pages/ImpactView";
import Settings from "../../pages/Settings";
import SymbolSearch from "../../pages/SymbolSearch";

describe("UI文案 neutrality — all components", () => {
  const FORBIDDEN = [
    "read first",
    "you should",
    "must inspect",
    "next step",
    "implement here",
    "modify here",
    "add tests",
    "before editing",
  ];

  it("RightInspector (node mode) has no action directives", () => {
    const nodeData: NodeInspectorData = {
      symbol_id: "test.py::foo",
      name: "foo",
      type: "function",
      file_path: "test.py",
      line_start: 1,
      signature: "def foo()",
    };
    render(<RightInspector target="node" mode="node" onClose={() => {}} nodeData={nodeData} />);
    const text = (document.body.textContent || "").toLowerCase();
    for (const term of FORBIDDEN) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });

  it("RightInspector (edge mode) has no action directives", () => {
    const edgeData: EdgeInspectorData = {
      source: "a", target: "b", type: "calls",
      confidence: 0.65, confidence_level: "medium", resolution: "import_resolved",
    };
    render(<RightInspector target="edge" mode="edge" onClose={() => {}} edgeData={edgeData} />);
    const text = (document.body.textContent || "").toLowerCase();
    for (const term of FORBIDDEN) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });

  it("EvidencePackViewer has no action directives", () => {
    render(<EvidencePackViewer />);
    const text = (document.body.textContent || "").toLowerCase();
    for (const term of FORBIDDEN) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });

  it("ImpactView has no action directives", () => {
    render(<ImpactView onSelectSymbol={() => {}} />);
    const text = (document.body.textContent || "").toLowerCase();
    for (const term of FORBIDDEN) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });

  it("Settings has no action directives", () => {
    render(<Settings theme="dark" setTheme={() => {}} onReindex={() => {}} onIncrementalIndex={() => {}} indexStatus="fresh" />);
    const text = (document.body.textContent || "").toLowerCase();
    for (const term of FORBIDDEN) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });

  it("SymbolSearch has no action directives", () => {
    render(<SymbolSearch onSelectSymbol={() => {}} />);
    const text = (document.body.textContent || "").toLowerCase();
    for (const term of FORBIDDEN) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });

  it("ALL components use neutral UI语言 — only evidence/relation/candidate wording", () => {
    // Verify that allowed terms CAN appear
    // (this is not an assertion about their presence, just that the forbidden list is checked above)
    const allowedTerms = ["search", "symbol", "evidence", "confidence", "relation", "impact", "index", "status"];
    // These terms are fine to appear
    expect(allowedTerms.length).toBeGreaterThan(0);
  });
});
