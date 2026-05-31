import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import GraphExplorer from "../../pages/GraphExplorer";

describe("GraphExplorer", () => {
  it("shows stale index warning banner when index is stale", () => {
    render(
      <GraphExplorer
        canvasState="overview"
        indexStatus="stale"
      />
    );

    expect(screen.getByText(/Index is stale/)).toBeInTheDocument();
  });

  it("does NOT show stale warning when index is fresh", () => {
    render(
      <GraphExplorer
        canvasState="overview"
        indexStatus="fresh"
      />
    );

    expect(screen.queryByText(/Index is stale/)).not.toBeInTheDocument();
  });

  it("does NOT show stale warning when index is missing", () => {
    render(
      <GraphExplorer
        canvasState="overview"
        indexStatus="missing"
      />
    );

    expect(screen.queryByText(/Index is stale/)).not.toBeInTheDocument();
  });

  it("does NOT show stale warning when index is indexing", () => {
    render(
      <GraphExplorer
        canvasState="overview"
        indexStatus="indexing"
      />
    );

    expect(screen.queryByText(/Index is stale/)).not.toBeInTheDocument();
  });

  it("does not display action directives in warning banner", () => {
    render(
      <GraphExplorer
        canvasState="overview"
        indexStatus="stale"
      />
    );

    const banner = screen.getByText(/Index is stale/);
    expect(banner.textContent).not.toContain("you should");
    expect(banner.textContent).not.toContain("must");
    expect(banner.textContent).not.toContain("read first");
  });
});
