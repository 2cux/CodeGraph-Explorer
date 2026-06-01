import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ImpactView from "../../pages/ImpactView";

describe("ImpactView", () => {
  it("renders impact analysis input", () => {
    render(<ImpactView onSelectSymbol={() => {}} />);
    expect(screen.getByPlaceholderText(/symbol_id/i)).toBeInTheDocument();
    expect(screen.getByText("Analyze")).toBeInTheDocument();
  });

  it("has filter controls for tests and possible impact", () => {
    render(<ImpactView onSelectSymbol={() => {}} />);
    // Checkboxes are rendered as labels
    const labels = screen.getAllByRole("checkbox");
    expect(labels.length).toBeGreaterThanOrEqual(1);
  });

  it("does not contain action directives in the UI", () => {
    const { container } = render(<ImpactView onSelectSymbol={() => {}} />);
    const text = (container.textContent || "").toLowerCase();
    const forbidden = [
      "read first",
      "you should",
      "must inspect",
      "next step",
      "implement here",
      "modify here",
      "add tests",
      "before editing",
    ];
    for (const term of forbidden) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });

  it("renders without crashing", () => {
    const { container } = render(<ImpactView onSelectSymbol={() => {}} />);
    expect(container.querySelector("input")).toBeInTheDocument();
  });

  it("accepts initialSymbolId prop without crashing", () => {
    const { container } = render(
      <ImpactView onSelectSymbol={() => {}} initialSymbolId="src/auth.py::login" />,
    );
    expect(container.querySelector("input")).toBeInTheDocument();
  });

  it("accepts onSelectFile prop without crashing", () => {
    render(
      <ImpactView onSelectSymbol={() => {}} onSelectFile={() => {}} />,
    );
    expect(screen.getByText("Analyze")).toBeInTheDocument();
  });

  it("shows depth selector with options 1-5", () => {
    render(<ImpactView onSelectSymbol={() => {}} />);
    const options = screen.getAllByRole("option");
    expect(options.length).toBe(5);
    expect(options.map((o) => o.textContent)).toEqual(["1", "2", "3", "4", "5"]);
  });

  it("does not contain forbidden phrases (including with initialSymbolId)", () => {
    const { container } = render(
      <ImpactView onSelectSymbol={() => {}} initialSymbolId="test.py::foo" />,
    );
    const text = (container.textContent || "").toLowerCase();
    const forbidden = [
      "read first", "you should", "must inspect", "next step",
      "implement here", "modify here", "add tests", "before editing",
    ];
    for (const term of forbidden) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });
});
