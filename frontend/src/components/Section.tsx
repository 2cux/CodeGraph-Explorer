export function InspectorSection({
  title, children, first = false,
}: { title: string; children: React.ReactNode; first?: boolean }) {
  return (
    <section
      style={{
        display: "flex", flexDirection: "column", gap: 8,
        paddingTop: first ? 0 : 14,
        borderTop: first ? "none" : "1px solid var(--cg-border)",
        marginTop: first ? 0 : 14,
      }}
    >
      <div
        style={{
          display: "flex", alignItems: "center", gap: 6,
          fontSize: 10, letterSpacing: 0.5, fontWeight: 600,
          color: "var(--cg-text-secondary)", textTransform: "none",
        }}
      >
        <span style={{ color: "var(--cg-text-muted)" }}>──</span>
        <span>{title}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>{children}</div>
    </section>
  );
}
