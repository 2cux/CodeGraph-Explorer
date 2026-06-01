import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import NavBar from "../../app/components/NavBar";

describe("NavBar - Back/Forward buttons", () => {
  it("renders Back and Forward buttons", () => {
    render(
      <NavBar
        canGoBack={true}
        canGoForward={true}
        onBack={() => {}}
        onForward={() => {}}
        breadcrumbs={[{ label: "Repo Overview" }]}
      />
    );
    expect(screen.getByLabelText("Go back")).toBeInTheDocument();
    expect(screen.getByLabelText("Go forward")).toBeInTheDocument();
  });

  it("calls onBack when Back button is clicked", () => {
    const handleBack = vi.fn();
    render(
      <NavBar
        canGoBack={true}
        canGoForward={false}
        onBack={handleBack}
        onForward={() => {}}
        breadcrumbs={[{ label: "Repo Overview" }]}
      />
    );
    fireEvent.click(screen.getByLabelText("Go back"));
    expect(handleBack).toHaveBeenCalledTimes(1);
  });

  it("calls onForward when Forward button is clicked", () => {
    const handleForward = vi.fn();
    render(
      <NavBar
        canGoBack={false}
        canGoForward={true}
        onBack={() => {}}
        onForward={handleForward}
        breadcrumbs={[{ label: "Repo Overview" }]}
      />
    );
    fireEvent.click(screen.getByLabelText("Go forward"));
    expect(handleForward).toHaveBeenCalledTimes(1);
  });

  it("disables Back button when canGoBack is false", () => {
    render(
      <NavBar
        canGoBack={false}
        canGoForward={true}
        onBack={() => {}}
        onForward={() => {}}
        breadcrumbs={[{ label: "Repo Overview" }]}
      />
    );
    const backBtn = screen.getByLabelText("Go back");
    expect(backBtn).toBeDisabled();
  });

  it("disables Forward button when canGoForward is false", () => {
    render(
      <NavBar
        canGoBack={true}
        canGoForward={false}
        onBack={() => {}}
        onForward={() => {}}
        breadcrumbs={[{ label: "Repo Overview" }]}
      />
    );
    const fwdBtn = screen.getByLabelText("Go forward");
    expect(fwdBtn).toBeDisabled();
  });
});

describe("NavBar - Breadcrumb", () => {
  it("renders breadcrumb labels", () => {
    render(
      <NavBar
        canGoBack={false}
        canGoForward={false}
        onBack={() => {}}
        onForward={() => {}}
        breadcrumbs={[
          { label: "Repo Overview" },
          { label: "login" },
          { label: "Impact" },
        ]}
      />
    );
    expect(screen.getByText("Repo Overview")).toBeInTheDocument();
    expect(screen.getByText("login")).toBeInTheDocument();
    expect(screen.getByText("Impact")).toBeInTheDocument();
  });

  it("renders clickable breadcrumb items with onClick", () => {
    const handleClick = vi.fn();
    render(
      <NavBar
        canGoBack={false}
        canGoForward={false}
        onBack={() => {}}
        onForward={() => {}}
        breadcrumbs={[
          { label: "Repo Overview", onClick: handleClick },
          { label: "auth.py" },
        ]}
      />
    );
    const link = screen.getByText("Repo Overview");
    fireEvent.click(link);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("does NOT render last breadcrumb item as clickable button", () => {
    render(
      <NavBar
        canGoBack={false}
        canGoForward={false}
        onBack={() => {}}
        onForward={() => {}}
        breadcrumbs={[
          { label: "Repo Overview", onClick: () => {} },
          { label: "Impact" },
        ]}
      />
    );
    // Last item should be a span, not a button
    const lastItem = screen.getByText("Impact");
    expect(lastItem.tagName).toBe("SPAN");
  });
});

describe("NavBar - UI文案", () => {
  it("does not contain forbidden phrases", () => {
    const { container } = render(
      <NavBar
        canGoBack={true}
        canGoForward={true}
        onBack={() => {}}
        onForward={() => {}}
        breadcrumbs={[
          { label: "Repo Overview", onClick: () => {} },
          { label: "login" },
        ]}
      />
    );
    const text = (container.textContent || "").toLowerCase();
    const forbidden = ["read first", "you should", "must inspect", "next step", "implement here", "modify here", "add tests", "before editing"];
    for (const term of forbidden) {
      expect(text).not.toContain(term.toLowerCase());
    }
  });
});
