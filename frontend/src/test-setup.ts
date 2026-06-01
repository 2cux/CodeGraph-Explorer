import "@testing-library/jest-dom/vitest";

// ── React Flow mocks (required for jsdom test environment) ────────────

// ResizeObserver
if (typeof ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// getBoundingClientRect: React Flow measures node elements for edge path
// calculation. jsdom returns all zeros, so edges never render. Provide a
// reasonable default rect so edge paths are computed.
const origGetBoundingClientRect =
  Element.prototype.getBoundingClientRect;
Element.prototype.getBoundingClientRect = function () {
  const rect = origGetBoundingClientRect.call(this);
  // If the element is a React Flow node, return a plausible rect
  if (this.classList.contains("react-flow__node")) {
    return {
      x: 0, y: 0,
      width: rect.width || 160,
      height: rect.height || 48,
      top: 0, left: 0,
      right: rect.width || 160,
      bottom: rect.height || 48,
      toJSON() {
        return { x: 0, y: 0, width: rect.width || 160, height: rect.height || 48 };
      },
    } as DOMRect;
  }
  return {
    ...rect,
    width: rect.width || 0,
    height: rect.height || 0,
    toJSON() {
      return { x: rect.x, y: rect.y, width: rect.width || 0, height: rect.height || 0 };
    },
  } as DOMRect;
};

// SVGElement getBBox (used by edge path calculation)
const origGetBBox = (SVGElement.prototype as any).getBBox;
if (!origGetBBox) {
  (SVGElement.prototype as any).getBBox = function () {
    return { x: 0, y: 0, width: 0, height: 0 };
  };
}

// scrollIntoView mock
if (typeof Element.prototype.scrollIntoView === "undefined") {
  Element.prototype.scrollIntoView = function () {};
}
