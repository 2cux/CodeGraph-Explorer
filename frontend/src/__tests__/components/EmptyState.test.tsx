import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { EmptyState, type EmptyStateIcon } from "../../app/components/EmptyState";

const ALL_ICONS: EmptyStateIcon[] = [
  "no-index",
  "api-error",
  "no-results",
  "no-neighbors",
  "no-impact",
  "no-callers",
];

describe("EmptyState — all icon variants render", () => {
  for (const icon of ALL_ICONS) {
    it(`renders "${icon}" without crashing`, () => {
      const { container } = render(
        <EmptyState icon={icon} title={`Title for ${icon}`} />,
      );
      expect(container.querySelector("svg")).toBeTruthy();
      expect(container.textContent).toContain(`Title for ${icon}`);
    });
  }
});

describe("EmptyState — title and description", () => {
  it("renders title", () => {
    const { container } = render(
      <EmptyState icon="no-index" title="Custom Title" />,
    );
    expect(container.textContent).toContain("Custom Title");
  });

  it("renders description when provided", () => {
    const { container } = render(
      <EmptyState icon="no-index" title="T" description="Some description text" />,
    );
    expect(container.textContent).toContain("Some description text");
  });

  it("renders without description", () => {
    const { container } = render(
      <EmptyState icon="no-index" title="Just a title" />,
    );
    expect(container.querySelector("svg")).toBeTruthy();
  });
});

describe("EmptyState — command", () => {
  it("renders command as code block when provided", () => {
    const { container } = render(
      <EmptyState icon="no-index" title="T" command="codegraph index ./project" />,
    );
    expect(container.textContent).toContain("codegraph index ./project");
    expect(container.querySelector("code")).toBeTruthy();
  });

  it("does not render command element when not provided", () => {
    const { container } = render(
      <EmptyState icon="no-index" title="T" />,
    );
    expect(container.querySelector("code")).toBeFalsy();
  });
});

describe("EmptyState — no forbidden phrases", () => {
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

  for (const icon of ALL_ICONS) {
    it(`"${icon}" has no forbidden phrases`, () => {
      const { container } = render(
        <EmptyState
          icon={icon}
          title={`Title ${icon}`}
          description="Test description for scanning"
          command="codegraph index ."
        />,
      );
      const text = (container.textContent || "").toLowerCase();
      for (const term of FORBIDDEN) {
        expect(text).not.toContain(term.toLowerCase());
      }
    });
  }
});

describe("EmptyState — each icon renders an SVG", () => {
  for (const icon of ALL_ICONS) {
    it(`"${icon}" has SVG element`, () => {
      const { container } = render(
        <EmptyState icon={icon} title="T" />,
      );
      expect(container.querySelector("svg")).not.toBeNull();
    });
  }
});
