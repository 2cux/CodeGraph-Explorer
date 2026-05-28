import { useState } from "react";
import {
  IconChevronDown,
  IconChevronRight,
  IconCopy,
  IconExport,
  IconWarning,
  IconClose,
} from "./icons";
import { Spinner } from "./Spinner";

export type ContextPackStatus = "empty" | "generating" | "generated" | "error";

interface Props {
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  status: ContextPackStatus;
  onRetry?: () => void;
}

export function ContextPackOverlay({ open, onToggle, onClose, status, onRetry }: Props) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  }

  return (
    <div
      style={{
        position: "absolute",
        left: 16,
        bottom: 16,
        width: 300,
        background: "var(--cg-bg-elevated)",
        border: "1px solid var(--cg-border)",
        borderRadius: 6,
        boxShadow: "0 4px 16px -8px rgba(0,0,0,0.28)",
        zIndex: 10,
        overflow: "hidden",
      }}
    >
      {/* Header / collapsed bar */}
      <div
        onClick={onToggle}
        style={{
          display: "flex",
          alignItems: "center",
          height: 30,
          padding: "0 8px 0 10px",
          gap: 6,
          cursor: "pointer",
          borderBottom: open ? "1px solid var(--cg-border)" : "none",
          userSelect: "none",
        }}
      >
        <span
          style={{
            color: "var(--cg-text-muted)",
            display: "flex",
            alignItems: "center",
            flexShrink: 0,
          }}
        >
          {open ? <IconChevronDown size={11} /> : <IconChevronRight size={11} />}
        </span>

        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "var(--cg-text-primary)",
            letterSpacing: 0.1,
          }}
        >
          Context Pack
        </span>

        {status === "generating" && (
          <span style={{ display: "flex", alignItems: "center" }}>
            <Spinner size={10} />
          </span>
        )}

        <span style={{ flex: 1 }} />

        {!open && status === "generated" && (
          <span
            className="cg-mono"
            style={{ fontSize: 10, color: "var(--cg-text-muted)" }}
          >
            generated
          </span>
        )}

        {open && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onClose();
            }}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 20,
              height: 20,
              padding: 0,
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: "var(--cg-text-muted)",
              borderRadius: 3,
              flexShrink: 0,
            }}
          >
            <IconClose size={10} />
          </button>
        )}
      </div>

      {/* Expanded body */}
      {open && (
        <div
          style={{
            padding: "10px",
            display: "flex",
            flexDirection: "column",
            gap: 8,
            maxHeight: 230,
            overflowY: "auto",
          }}
          className="cg-scroll"
        >
          {status === "empty" && <EmptyBody />}
          {status === "generating" && <GeneratingBody />}
          {status === "error" && <ErrorBody onRetry={onRetry} />}
          {status === "generated" && (
            <GeneratedBody copied={copied} onCopy={handleCopy} />
          )}
        </div>
      )}
    </div>
  );
}

/* ─── States ─── */

function EmptyBody() {
  return (
    <p
      style={{
        margin: 0,
        fontSize: 11,
        color: "var(--cg-text-muted)",
        padding: "3px 0",
      }}
    >
      No context pack generated.
    </p>
  );
}

function GeneratingBody() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontSize: 11,
        color: "var(--cg-text-secondary)",
        padding: "3px 0",
      }}
    >
      <Spinner size={11} />
      <span>Generating...</span>
    </div>
  );
}

function ErrorBody({ onRetry }: { onRetry?: () => void }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontSize: 11,
        padding: "3px 0",
      }}
    >
      <span style={{ color: "var(--cg-error)", flex: 1 }}>
        Failed to generate context pack.
      </span>
      {onRetry && (
        <MiniBtn onClick={onRetry}>Retry</MiniBtn>
      )}
    </div>
  );
}

function GeneratedBody({
  copied,
  onCopy,
}: {
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <>
      {/* task + intent */}
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <MetaRow label="task">
          <span
            style={{
              fontSize: 11,
              fontWeight: 500,
              color: "var(--cg-text-primary)",
            }}
          >
            Add MFA to login flow
          </span>
        </MetaRow>
        <MetaRow label="intent">
          <span
            className="cg-mono"
            style={{ fontSize: 10, color: "var(--cg-accent)" }}
          >
            authentication_security
          </span>
        </MetaRow>
      </div>

      {/* stats row */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "4px 12px",
          padding: "6px 8px",
          background: "var(--cg-bg-subtle)",
          borderRadius: 4,
        }}
      >
        {[
          { label: "entry points", value: "3" },
          { label: "symbols", value: "8" },
          { label: "files", value: "5" },
        ].map((s) => (
          <div
            key={s.label}
            style={{ display: "flex", alignItems: "baseline", gap: 4 }}
          >
            <span
              className="cg-mono"
              style={{
                fontSize: 11,
                fontWeight: 500,
                color: "var(--cg-text-primary)",
              }}
            >
              {s.value}
            </span>
            <span
              style={{ fontSize: 10, color: "var(--cg-text-muted)" }}
            >
              {s.label}
            </span>
          </div>
        ))}
      </div>

      {/* risk + warnings */}
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 10.5,
          }}
        >
          <span
            style={{
              color: "var(--cg-text-muted)",
              width: 30,
              flexShrink: 0,
            }}
          >
            risk
          </span>
          <span
            className="cg-mono"
            style={{
              color: "var(--cg-warning)",
              fontWeight: 500,
              fontSize: 10,
            }}
          >
            medium
          </span>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 6,
            padding: "5px 7px",
            background:
              "color-mix(in srgb, var(--cg-warning) 8%, transparent)",
            border:
              "1px solid color-mix(in srgb, var(--cg-warning) 20%, transparent)",
            borderRadius: 4,
            fontSize: 10.5,
          }}
        >
          <span
            style={{
              color: "var(--cg-warning)",
              flexShrink: 0,
              marginTop: 1,
              display: "flex",
              alignItems: "center",
            }}
          >
            <IconWarning size={10} />
          </span>
          <span style={{ color: "var(--cg-text-secondary)", lineHeight: 1.4 }}>
            <span
              style={{ color: "var(--cg-warning)", fontWeight: 500 }}
            >
              2 warnings
            </span>
            {" · "}Session.create has low test coverage
          </span>
        </div>
      </div>

      {/* actions */}
      <div style={{ display: "flex", gap: 6, paddingTop: 1 }}>
        <OutlineBtn icon={<IconCopy size={10} />} onClick={onCopy}>
          {copied ? "Copied!" : "Copy Markdown"}
        </OutlineBtn>
        <OutlineBtn icon={<IconExport size={10} />}>Export JSON</OutlineBtn>
      </div>
    </>
  );
}

/* ─── Primitives ─── */

function MetaRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span
        style={{
          fontSize: 10,
          color: "var(--cg-text-muted)",
          width: 30,
          flexShrink: 0,
        }}
      >
        {label}
      </span>
      {children}
    </div>
  );
}

function OutlineBtn({
  icon,
  children,
  onClick,
  disabled,
}: {
  icon?: React.ReactNode;
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 5,
        height: 24,
        padding: "0 8px",
        background: "transparent",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        color: disabled ? "var(--cg-text-muted)" : "var(--cg-text-secondary)",
        fontSize: 10.5,
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.5 : 1,
        fontFamily: "inherit",
        whiteSpace: "nowrap",
      }}
    >
      {icon && (
        <span
          style={{
            color: "var(--cg-text-muted)",
            display: "flex",
            alignItems: "center",
          }}
        >
          {icon}
        </span>
      )}
      {children}
    </button>
  );
}

function MiniBtn({
  children,
  onClick,
}: {
  children: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        height: 22,
        padding: "0 8px",
        background: "transparent",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        color: "var(--cg-text-secondary)",
        fontSize: 10.5,
        cursor: "pointer",
        fontFamily: "inherit",
        flexShrink: 0,
      }}
    >
      {children}
    </button>
  );
}
