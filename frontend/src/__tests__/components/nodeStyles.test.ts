import { describe, it, expect } from "vitest";
import {
  NODE_TYPE_COLOR,
  NODE_TYPE_LABEL,
  NODE_STATE_CLASS,
  EDGE_TYPE_STYLE,
  LOW_CONF_EDGE_STYLE,
  EXTERNAL_EDGE_STYLE,
  confidenceLevel,
  confidenceLabel,
  NODE_DIMS,
  LAYOUT_PRESET_DAGRE,
} from "../../app/components/nodeStyles";

describe("nodeStyles — NODE_TYPE_COLOR", () => {
  const requiredKinds = [
    "function", "method", "class", "file", "test",
    "module", "external_symbol", "module_group", "file_group", "class_group",
  ];

  it("has color for all NodeKind values", () => {
    for (const kind of requiredKinds) {
      expect(NODE_TYPE_COLOR).toHaveProperty(kind);
      expect(typeof NODE_TYPE_COLOR[kind as keyof typeof NODE_TYPE_COLOR]).toBe("string");
    }
  });

  it("all colors reference CSS custom properties", () => {
    for (const color of Object.values(NODE_TYPE_COLOR)) {
      expect(color).toContain("var(--cg-");
    }
  });
});

describe("nodeStyles — NODE_TYPE_LABEL", () => {
  it("has label for all NodeKind values", () => {
    const kinds = ["function", "method", "class", "file", "test", "module", "external_symbol"];
    for (const kind of kinds) {
      expect(NODE_TYPE_LABEL).toHaveProperty(kind);
    }
  });

  it("labels are short uppercase strings", () => {
    for (const label of Object.values(NODE_TYPE_LABEL)) {
      expect(label).toBe(label.toUpperCase());
      expect(label.length).toBeLessThanOrEqual(5);
    }
  });
});

describe("nodeStyles — NODE_STATE_CLASS", () => {
  it("covers all 9 state names", () => {
    const states = ["default", "hover", "selected", "center", "neighbor", "unrelated", "external", "low-confidence"];
    for (const state of states) {
      expect(NODE_STATE_CLASS).toHaveProperty(state);
    }
  });
});

describe("nodeStyles — EDGE_TYPE_STYLE", () => {
  it("has entries for all edge types", () => {
    const types = ["calls", "tested_by", "imports", "references", "contains"];
    for (const t of types) {
      expect(EDGE_TYPE_STYLE).toHaveProperty(t);
      const style = EDGE_TYPE_STYLE[t];
      expect(style).toHaveProperty("stroke");
      expect(style).toHaveProperty("strokeDasharray");
      expect(style).toHaveProperty("opacity");
      expect(style).toHaveProperty("strokeWidth");
    }
  });

  it("tested_by uses dashed style", () => {
    expect(EDGE_TYPE_STYLE.tested_by.strokeDasharray).not.toBe("none");
  });

  it("calls uses solid style", () => {
    expect(EDGE_TYPE_STYLE.calls.strokeDasharray).toBe("none");
  });
});

describe("nodeStyles — low-confidence / external overrides", () => {
  it("LOW_CONF_EDGE_STYLE uses warning color", () => {
    expect(LOW_CONF_EDGE_STYLE.stroke).toContain("warning");
  });

  it("LOW_CONF_EDGE_STYLE is dashed", () => {
    expect(LOW_CONF_EDGE_STYLE.strokeDasharray).not.toBe("none");
  });

  it("EXTERNAL_EDGE_STYLE has low opacity", () => {
    expect(EXTERNAL_EDGE_STYLE.opacity).toBeLessThan(0.3);
  });
});

describe("nodeStyles — confidence helpers", () => {
  it("confidence >= 0.80 is high", () => {
    expect(confidenceLevel(0.95)).toBe("high");
    expect(confidenceLevel(0.80)).toBe("high");
  });

  it("confidence 0.60-0.79 is medium", () => {
    expect(confidenceLevel(0.75)).toBe("medium");
    expect(confidenceLevel(0.60)).toBe("medium");
  });

  it("confidence 0.40-0.59 is low", () => {
    expect(confidenceLevel(0.50)).toBe("low");
    expect(confidenceLevel(0.40)).toBe("low");
  });

  it("confidence < 0.40 is unknown", () => {
    expect(confidenceLevel(0.30)).toBe("unknown");
  });

  it("confidenceLabel returns correct tone", () => {
    expect(confidenceLabel(0.90).tone).toBe("success");
    expect(confidenceLabel(0.70).tone).toBe("warning");
    expect(confidenceLabel(0.50).tone).toBe("warning");
    expect(confidenceLabel(0.20).tone).toBe("muted");
  });
});

describe("nodeStyles — NODE_DIMS", () => {
  it("has minWidth, maxWidth, minHeight", () => {
    expect(NODE_DIMS.minWidth).toBeGreaterThan(0);
    expect(NODE_DIMS.maxWidth).toBeGreaterThan(NODE_DIMS.minWidth);
    expect(NODE_DIMS.minHeight).toBeGreaterThan(0);
  });
});

describe("nodeStyles — LAYOUT_PRESET_DAGRE", () => {
  it("has local and impact presets", () => {
    expect(LAYOUT_PRESET_DAGRE).toHaveProperty("local");
    expect(LAYOUT_PRESET_DAGRE).toHaveProperty("impact");
  });

  it("local preset uses LR direction", () => {
    expect(LAYOUT_PRESET_DAGRE.local.rankdir).toBe("LR");
  });

  it("impact preset uses TB direction", () => {
    expect(LAYOUT_PRESET_DAGRE.impact.rankdir).toBe("TB");
  });
});
