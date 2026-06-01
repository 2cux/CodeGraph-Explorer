export interface BreadcrumbItem {
  label: string;
  onClick?: () => void;
}

interface NavBarProps {
  canGoBack: boolean;
  canGoForward: boolean;
  onBack: () => void;
  onForward: () => void;
  breadcrumbs: BreadcrumbItem[];
}

export default function NavBar({
  canGoBack,
  canGoForward,
  onBack,
  onForward,
  breadcrumbs,
}: NavBarProps) {
  return (
    <div
      style={{
        height: 28,
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "0 10px",
        background: "var(--cg-bg-panel)",
        borderBottom: "1px solid var(--cg-border)",
      }}
    >
      {/* Back / Forward buttons */}
      <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
        <button
          onClick={onBack}
          disabled={!canGoBack}
          title="Go back"
          aria-label="Go back"
          style={{
            width: 22, height: 20,
            display: "flex", alignItems: "center", justifyContent: "center",
            border: "1px solid var(--cg-border)", borderRadius: 3,
            background: "transparent",
            color: canGoBack ? "var(--cg-text-secondary)" : "var(--cg-text-muted)",
            cursor: canGoBack ? "pointer" : "default",
            opacity: canGoBack ? 1 : 0.4,
          }}
        >
          <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="10 4 6 8 10 12" />
          </svg>
        </button>
        <button
          onClick={onForward}
          disabled={!canGoForward}
          title="Go forward"
          aria-label="Go forward"
          style={{
            width: 22, height: 20,
            display: "flex", alignItems: "center", justifyContent: "center",
            border: "1px solid var(--cg-border)", borderRadius: 3,
            background: "transparent",
            color: canGoForward ? "var(--cg-text-secondary)" : "var(--cg-text-muted)",
            cursor: canGoForward ? "pointer" : "default",
            opacity: canGoForward ? 1 : 0.4,
          }}
        >
          <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="6 4 10 8 6 12" />
          </svg>
        </button>
      </div>

      {/* Separator */}
      <span style={{ width: 1, height: 14, background: "var(--cg-border)", flexShrink: 0 }} />

      {/* Breadcrumb */}
      <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, overflow: "hidden" }}>
        {breadcrumbs.map((crumb, i) => {
          const isLast = i === breadcrumbs.length - 1;
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
              {i > 0 && (
                <span style={{ color: "var(--cg-text-muted)", flexShrink: 0 }}>›</span>
              )}
              {crumb.onClick && !isLast ? (
                <button
                  onClick={crumb.onClick}
                  style={{
                    background: "transparent", border: "none", padding: "0 2px",
                    color: "var(--cg-accent)", cursor: "pointer",
                    fontSize: 11, fontFamily: "inherit",
                    maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}
                >
                  {crumb.label}
                </button>
              ) : (
                <span
                  className="cg-mono"
                  style={{
                    color: isLast ? "var(--cg-text-primary)" : "var(--cg-text-muted)",
                    maxWidth: 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}
                >
                  {crumb.label}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
