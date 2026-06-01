import type React from "react";

export type EmptyStateIcon =
  | "no-index"
  | "api-error"
  | "no-results"
  | "no-neighbors"
  | "no-impact"
  | "no-callers";

interface EmptyStateProps {
  icon: EmptyStateIcon;
  title: string;
  description?: string;
  command?: string;
}

const ICON_SVG: Record<EmptyStateIcon, React.ReactNode> = {
  "no-index": (
    <svg width="28" height="28" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
      <circle cx="8" cy="8" r="5.5" />
      <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" />
    </svg>
  ),
  "api-error": (
    <svg width="28" height="28" viewBox="0 0 16 16" fill="none" stroke="var(--cg-error)" strokeWidth="1.4" strokeLinecap="round">
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 4.5v4M8 11.2v.1" />
    </svg>
  ),
  "no-results": (
    <svg width="28" height="28" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
      <circle cx="7" cy="7" r="5" />
      <path d="M11 11l2.5 2.5" />
      <path d="M4.5 7h5" />
    </svg>
  ),
  "no-neighbors": (
    <svg width="28" height="28" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
      <circle cx="8" cy="8" r="5.5" />
      <circle cx="5" cy="6" r="1.2" />
      <circle cx="11" cy="6" r="1.2" />
      <circle cx="8" cy="11" r="1.2" />
    </svg>
  ),
  "no-impact": (
    <svg width="28" height="28" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 4v5M8 11.2v.1" />
    </svg>
  ),
  "no-callers": (
    <svg width="28" height="28" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
      <path d="M3 13V3h4l2 2h4v8H3z" />
      <path d="M6 8h4M8 6v4" />
    </svg>
  ),
};

export function EmptyState({ icon, title, description, command }: EmptyStateProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        color: "var(--cg-text-muted)",
        maxWidth: 400,
        textAlign: "center" as const,
        padding: "24px 16px",
      }}
    >
      <span style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
        {ICON_SVG[icon]}
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ fontSize: 12, color: "var(--cg-text-secondary)", fontWeight: 500 }}>
          {title}
        </span>
        {description && (
          <span style={{ fontSize: 11, color: "var(--cg-text-muted)", lineHeight: 1.5 }}>
            {description}
          </span>
        )}
        {command && (
          <code
            style={{
              fontSize: 11,
              marginTop: 4,
              padding: "4px 8px",
              borderRadius: 4,
              background: "var(--cg-bg-subtle)",
              border: "1px solid var(--cg-border)",
              color: "var(--cg-text-secondary)",
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {command}
          </code>
        )}
      </div>
    </div>
  );
}
