import { useEffect, useRef } from "react";
import { IconClose, IconWarning } from "./icons";

export type ToastType = "error" | "warning" | "info";

export interface ToastData {
  type: ToastType;
  message: string;
  detail?: string;
}

const TYPE_COLOR: Record<ToastType, string> = {
  error: "var(--cg-error)",
  warning: "var(--cg-warning)",
  info: "var(--cg-accent)",
};

const TYPE_BG: Record<ToastType, string> = {
  error: "color-mix(in srgb, var(--cg-error) 8%, transparent)",
  warning: "color-mix(in srgb, var(--cg-warning) 8%, transparent)",
  info: "color-mix(in srgb, var(--cg-accent) 8%, transparent)",
};

const TYPE_BORDER: Record<ToastType, string> = {
  error: "color-mix(in srgb, var(--cg-error) 22%, var(--cg-border))",
  warning: "color-mix(in srgb, var(--cg-warning) 22%, var(--cg-border))",
  info: "color-mix(in srgb, var(--cg-accent) 18%, var(--cg-border))",
};

interface Props {
  toast: ToastData | null;
  onDismiss: () => void;
}

export function Toast({ toast, onDismiss }: Props) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!toast) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(onDismiss, 3000);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [toast, onDismiss]);

  if (!toast) return null;

  return (
    <div
      style={{
        position: "fixed",
        bottom: 80,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 300,
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "9px 12px 9px 10px",
        background: TYPE_BG[toast.type],
        border: `1px solid ${TYPE_BORDER[toast.type]}`,
        borderRadius: 6,
        boxShadow: "0 4px 20px -6px rgba(0,0,0,0.35)",
        maxWidth: 380,
        minWidth: 260,
        pointerEvents: "auto",
      }}
    >
      {/* Accent bar */}
      <span
        style={{
          width: 2,
          height: "100%",
          minHeight: 16,
          borderRadius: 2,
          background: TYPE_COLOR[toast.type],
          flexShrink: 0,
          alignSelf: "stretch",
        }}
      />

      {/* Icon */}
      <span
        style={{
          color: TYPE_COLOR[toast.type],
          display: "flex",
          alignItems: "center",
          flexShrink: 0,
          marginTop: 1,
        }}
      >
        {toast.type === "error" ? (
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <circle cx="8" cy="8" r="5.5" />
            <path d="M8 4.5v4M8 11.2v.1" />
          </svg>
        ) : toast.type === "warning" ? (
          <IconWarning size={12} />
        ) : (
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <circle cx="8" cy="8" r="5.5" />
            <path d="M8 6v4M8 4.5v.1" />
          </svg>
        )}
      </span>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 11,
            fontWeight: 500,
            color: "var(--cg-text-primary)",
            lineHeight: 1.4,
          }}
        >
          {toast.message}
        </div>
        {toast.detail && (
          <div
            className="cg-mono"
            style={{
              fontSize: 10,
              color: "var(--cg-text-muted)",
              marginTop: 3,
              lineHeight: 1.4,
            }}
          >
            {toast.detail}
          </div>
        )}
      </div>

      {/* Dismiss */}
      <button
        onClick={onDismiss}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 18,
          height: 18,
          background: "transparent",
          border: "none",
          cursor: "pointer",
          color: "var(--cg-text-muted)",
          borderRadius: 3,
          flexShrink: 0,
          padding: 0,
        }}
      >
        <IconClose size={10} />
      </button>
    </div>
  );
}
