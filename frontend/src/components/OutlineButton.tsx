import { useState } from "react";

export function OutlineButton({
  label, icon, full = true, onClick,
}: { label: string; icon?: React.ReactNode; full?: boolean; onClick?: () => void }) {
  const [hovered, setHovered] = useState(false);

  return (
    <button
      onClick={onClick}
      className="flex items-center"
      style={{
        gap: 6,
        height: 26,
        padding: "0 10px",
        background: hovered ? "var(--cg-bg-subtle)" : "transparent",
        border: `1px solid ${hovered ? "var(--cg-border-hover)" : "var(--cg-border)"}`,
        borderRadius: 4,
        color: "var(--cg-text-primary)",
        fontSize: 11,
        cursor: "pointer",
        justifyContent: "flex-start",
        width: full ? "100%" : undefined,
        transition: "background 120ms ease, border-color 120ms ease",
        fontFamily: "inherit",
        whiteSpace: "nowrap",
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {icon && <span style={{ color: "var(--cg-text-secondary)", display: "flex", alignItems: "center" }}>{icon}</span>}
      <span>{label}</span>
    </button>
  );
}
