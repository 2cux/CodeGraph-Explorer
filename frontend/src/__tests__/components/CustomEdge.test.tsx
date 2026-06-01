import { describe, it, expect } from "vitest";
import {
  EDGE_TYPE_STYLE,
  EDGE_TYPE_LABEL_COLOR,
  LOW_CONF_EDGE_STYLE,
  EXTERNAL_EDGE_STYLE,
} from "../../app/components/nodeStyles";

describe("Edge type styles", () => {
  it("calls edge is solid with opacity >= 0.7", () => {
    expect(EDGE_TYPE_STYLE.calls.strokeDasharray).toBe("none");
    expect(EDGE_TYPE_STYLE.calls.opacity).toBeGreaterThanOrEqual(0.7);
  });

  it("tested_by edge is dashed", () => {
    expect(EDGE_TYPE_STYLE.tested_by.strokeDasharray).not.toBe("none");
  });

  it("imports edge has lower opacity than calls", () => {
    expect(EDGE_TYPE_STYLE.imports.opacity).toBeLessThan(EDGE_TYPE_STYLE.calls.opacity);
  });

  it("references edge has lower opacity than calls", () => {
    expect(EDGE_TYPE_STYLE.references.opacity).toBeLessThan(EDGE_TYPE_STYLE.calls.opacity);
  });

  it("contains edge is dashed with reduced opacity", () => {
    expect(EDGE_TYPE_STYLE.contains.strokeDasharray).not.toBe("none");
    expect(EDGE_TYPE_STYLE.contains.opacity).toBeLessThan(0.5);
  });
});

describe("Low-confidence edge override", () => {
  it("uses warning color", () => {
    expect(LOW_CONF_EDGE_STYLE.stroke).toContain("warning");
  });

  it("is dashed", () => {
    expect(LOW_CONF_EDGE_STYLE.strokeDasharray).not.toBe("none");
  });

  it("has opacity between 0.4 and 0.55", () => {
    expect(LOW_CONF_EDGE_STYLE.opacity).toBeGreaterThanOrEqual(0.4);
    expect(LOW_CONF_EDGE_STYLE.opacity).toBeLessThanOrEqual(0.55);
  });
});

describe("External edge override", () => {
  it("has very low opacity (< 0.3)", () => {
    expect(EXTERNAL_EDGE_STYLE.opacity).toBeLessThan(0.3);
  });

  it("is dashed", () => {
    expect(EXTERNAL_EDGE_STYLE.strokeDasharray).not.toBe("none");
  });

  it("has strokeWidth of 1", () => {
    expect(EXTERNAL_EDGE_STYLE.strokeWidth).toBe(1);
  });
});

describe("Edge type label colors", () => {
  it("calls uses text-secondary", () => {
    expect(EDGE_TYPE_LABEL_COLOR.calls).toContain("text-secondary");
  });

  it("tested_by uses success color", () => {
    expect(EDGE_TYPE_LABEL_COLOR.tested_by).toContain("success");
  });

  it("imports and references use muted color", () => {
    expect(EDGE_TYPE_LABEL_COLOR.imports).toContain("muted");
    expect(EDGE_TYPE_LABEL_COLOR.references).toContain("muted");
  });
});
