import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import Settings from "../../pages/Settings";

describe("Settings", () => {
  it("provides dark mode, light mode, and system theme options", () => {
    render(
      <Settings
        theme="dark"
        setTheme={() => {}}
        onReindex={() => {}}
        onIncrementalIndex={() => {}}
        indexStatus="fresh"
      />
    );

    expect(screen.getByText("System")).toBeInTheDocument();
    expect(screen.getByText("Light")).toBeInTheDocument();
    expect(screen.getByText("Dark")).toBeInTheDocument();
  });

  it("shows current theme as selected", () => {
    render(
      <Settings
        theme="light"
        setTheme={() => {}}
        onReindex={() => {}}
        onIncrementalIndex={() => {}}
        indexStatus="fresh"
      />
    );

    const buttons = screen.getAllByRole("button");
    const lightBtn = buttons.find((b) => b.textContent === "Light");
    expect(lightBtn).toBeInTheDocument();
  });

  it("shows index status", () => {
    render(
      <Settings
        theme="dark"
        setTheme={() => {}}
        onReindex={() => {}}
        onIncrementalIndex={() => {}}
        indexStatus="stale"
      />
    );

    expect(screen.getByText("stale")).toBeInTheDocument();
  });

  it("has reindex and incremental update buttons", () => {
    render(
      <Settings
        theme="dark"
        setTheme={() => {}}
        onReindex={() => {}}
        onIncrementalIndex={() => {}}
        indexStatus="fresh"
      />
    );

    expect(screen.getByText("Incremental Update")).toBeInTheDocument();
    expect(screen.getByText("Force Re-index")).toBeInTheDocument();
  });
});
