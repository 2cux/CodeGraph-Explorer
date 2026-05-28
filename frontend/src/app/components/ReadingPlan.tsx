import { useState } from "react";
import { IconBook, IconChevronDown, IconChevronRight, IconClose } from "./icons";
import { Spinner } from "./Spinner";

export type ReadingPlanStatus = "loading" | "ready" | "empty";

interface Step {
  action: "READ" | "INSPECT" | "RUN";
  target: string;
  path: string;
  reason: string;
}

const ACTION_COLOR: Record<Step["action"], string> = {
  READ: "var(--cg-success)",
  INSPECT: "var(--cg-accent)",
  RUN: "var(--cg-warning)",
};

const ACTION_BG: Record<Step["action"], string> = {
  READ: "color-mix(in srgb, var(--cg-success) 14%, transparent)",
  INSPECT: "color-mix(in srgb, var(--cg-accent) 14%, transparent)",
  RUN: "color-mix(in srgb, var(--cg-warning) 14%, transparent)",
};

interface Props {
  visible: boolean;
  open: boolean;
  onToggle: () => void;
  status?: ReadingPlanStatus;
  activeStep?: number;
  onStepClick?: (i: number) => void;
  steps?: { step?: number; action?: string; target?: string; reason?: string }[];
}

const DEFAULT_STEPS: Step[] = [
  { action: "READ", target: "authenticate", path: "src/auth.py:42", reason: "Review entry point for login flow" },
  { action: "READ", target: "verify_token", path: "src/auth.py:104", reason: "Understand token validation logic" },
  { action: "READ", target: "MFAForm", path: "src/ui/mfa.tsx:18", reason: "MFA implementation details" },
  { action: "READ", target: "test_auth_mfa", path: "tests/test_auth.py:31", reason: "Verify MFA integration" },
];

export function ReadingPlan({
  visible, open, onToggle, status = "ready", activeStep = 0, onStepClick, steps: externalSteps,
}: Props) {
  const steps: Step[] = externalSteps
    ? externalSteps.map((s) => ({
        action: (s.action as Step["action"]) || "READ",
        target: s.target || "unknown",
        path: "",
        reason: s.reason || "",
      }))
    : DEFAULT_STEPS;
  if (!visible) return null;

  return (
    <div
      style={{
        position: "absolute",
        right: 16,
        bottom: 16,
        zIndex: 10,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        gap: 8,
      }}
    >
      {open && (
        <div
          style={{
            width: 300,
            background: "var(--cg-bg-elevated)",
            border: "1px solid var(--cg-border)",
            borderRadius: 6,
            boxShadow: "0 4px 16px -8px rgba(0,0,0,0.28)",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            className="flex items-center"
            style={{
              height: 30,
              padding: "0 8px 0 10px",
              borderBottom: "1px solid var(--cg-border)",
              flexShrink: 0,
              gap: 6,
            }}
          >
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--cg-text-primary)", flex: 1, letterSpacing: 0.1 }}>
              Reading Plan
            </span>
            {status === "ready" && (
              <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                {steps.length} steps
              </span>
            )}
            <button
              onClick={onToggle}
              style={{
                display: "flex", alignItems: "center", justifyContent: "center",
                width: 20, height: 20, padding: 0, background: "transparent",
                border: "none", cursor: "pointer", color: "var(--cg-text-muted)",
                borderRadius: 3, flexShrink: 0,
              }}
            >
              <IconClose size={10} />
            </button>
          </div>

          <div className="cg-scroll" style={{ flex: 1, overflowY: "auto", maxHeight: 320 }}>
            {status === "loading" && <LoadingBody />}
            {status === "empty" && <EmptyBody />}
            {status === "ready" && (
              <ol style={{ margin: 0, padding: "4px 0", listStyle: "none" }}>
                {steps.map((step, i) => (
                  <StepItem
                    key={i}
                    step={step}
                    index={i}
                    isActive={i === activeStep}
                    onClick={() => onStepClick?.(i)}
                  />
                ))}
              </ol>
            )}
          </div>
        </div>
      )}

      <TriggerButton
        open={open}
        status={status}
        stepCount={steps.length}
        onClick={onToggle}
      />
    </div>
  );
}

function TriggerButton({
  open, status, stepCount, onClick,
}: {
  open: boolean; status: ReadingPlanStatus; stepCount: number; onClick: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", alignItems: "center", gap: 6, height: 28,
        padding: "0 10px",
        background: hovered ? "var(--cg-bg-subtle)" : "var(--cg-bg-elevated)",
        border: "1px solid var(--cg-border)", borderRadius: 6,
        color: "var(--cg-text-primary)", fontSize: 11, fontWeight: 500,
        cursor: "pointer", boxShadow: "0 2px 6px -3px rgba(0,0,0,0.2)",
        fontFamily: "inherit", transition: "background 100ms ease",
      }}
    >
      <span style={{ color: "var(--cg-accent)", display: "flex", alignItems: "center" }}>
        <IconBook size={12} />
      </span>
      <span>Reading Plan</span>
      {status === "ready" && (
        <span
          className="cg-mono"
          style={{
            fontSize: 10, padding: "1px 5px",
            background: "var(--cg-bg-subtle)", color: "var(--cg-text-secondary)", borderRadius: 2,
          }}
        >
          {stepCount}
        </span>
      )}
      {status === "loading" && (
        <span style={{ display: "flex", alignItems: "center" }}>
          <Spinner size={10} />
        </span>
      )}
      <span style={{ color: "var(--cg-text-muted)", display: "flex", alignItems: "center" }}>
        {open ? <IconChevronDown size={10} /> : <IconChevronRight size={10} style={{ transform: "rotate(-90deg)" }} />}
      </span>
    </button>
  );
}

function StepItem({
  step, index, isActive, onClick,
}: { step: Step; index: number; isActive: boolean; onClick: () => void }) {
  const [hovered, setHovered] = useState(false);
  return (
    <li
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: "8px 10px", display: "flex", gap: 8, cursor: "pointer",
        background: isActive
          ? "color-mix(in srgb, var(--cg-accent) 6%, transparent)"
          : hovered ? "color-mix(in srgb, var(--cg-text-primary) 3%, transparent)"
          : "transparent",
        borderLeft: isActive ? "2px solid var(--cg-accent)" : "2px solid transparent",
        transition: "background 100ms ease",
      }}
    >
      <div
        style={{
          width: 16, flexShrink: 0, marginTop: 2, fontSize: 11,
          fontWeight: 600, lineHeight: 1,
          color: isActive ? "var(--cg-accent)" : "var(--cg-text-muted)",
          textAlign: "right",
        }}
      >
        {index + 1}
      </div>
      <div style={{ minWidth: 0, flex: 1, display: "flex", flexDirection: "column", gap: 3 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            className="cg-mono"
            style={{
              fontSize: 9, fontWeight: 500, color: ACTION_COLOR[step.action],
              background: ACTION_BG[step.action],
              padding: "1px 4px", borderRadius: 2, letterSpacing: 0.5, flexShrink: 0,
            }}
          >
            {step.action}
          </span>
          <span
            className="cg-mono"
            style={{
              fontSize: 11, fontWeight: 500, color: "var(--cg-text-primary)",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}
          >
            {step.target}
          </span>
        </div>
        <div
          className="cg-mono"
          style={{
            fontSize: 10, color: "var(--cg-text-muted)", lineHeight: 1.3,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}
        >
          {step.path}
        </div>
        <div style={{ fontSize: 10, color: "var(--cg-text-secondary)", lineHeight: 1.4 }}>
          {step.reason}
        </div>
      </div>
    </li>
  );
}

function LoadingBody() {
  return (
    <div className="flex items-center" style={{ gap: 8, padding: "14px 10px", fontSize: 11, color: "var(--cg-text-secondary)" }}>
      <Spinner size={11} />
      <span>Generating reading plan...</span>
    </div>
  );
}

function EmptyBody() {
  return (
    <div style={{ padding: "14px 10px", fontSize: 11, color: "var(--cg-text-muted)" }}>
      No reading plan available.
    </div>
  );
}
