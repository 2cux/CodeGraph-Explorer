interface Props {
  theme: "system" | "light" | "dark";
  setTheme: (t: "system" | "light" | "dark") => void;
  onReindex: () => void;
  onIncrementalIndex: () => void;
  indexStatus: string;
}

export default function Settings({ theme, setTheme, onReindex, onIncrementalIndex, indexStatus }: Props) {
  return (
    <div style={{ height: "100%", overflow: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", letterSpacing: 0.5, marginBottom: 8 }}>
          APPEARANCE
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {(["system", "light", "dark"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTheme(t)}
              style={{
                height: 28, padding: "0 14px", border: theme === t ? "1px solid var(--cg-accent)" : "1px solid var(--cg-border)",
                borderRadius: 4, cursor: "pointer", fontSize: 11, fontFamily: "inherit",
                background: theme === t ? "color-mix(in srgb, var(--cg-accent) 10%, transparent)" : "transparent",
                color: theme === t ? "var(--cg-accent)" : "var(--cg-text-secondary)",
              }}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", letterSpacing: 0.5, marginBottom: 8 }}>
          INDEX
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 11, color: "var(--cg-text-secondary)" }}>Status:</span>
            <span className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-primary)" }}>{indexStatus}</span>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              onClick={onIncrementalIndex}
              disabled={indexStatus === "indexing"}
              style={{
                height: 28, padding: "0 14px", border: "1px solid var(--cg-border)", borderRadius: 4, cursor: "pointer",
                fontSize: 11, fontFamily: "inherit", background: "transparent", color: "var(--cg-text-secondary)",
                opacity: indexStatus === "indexing" ? 0.5 : 1,
              }}
            >
              Incremental Update
            </button>
            <button
              onClick={onReindex}
              disabled={indexStatus === "indexing"}
              style={{
                height: 28, padding: "0 14px", border: "1px solid var(--cg-border)", borderRadius: 4, cursor: "pointer",
                fontSize: 11, fontFamily: "inherit", background: "transparent", color: "var(--cg-text-secondary)",
                opacity: indexStatus === "indexing" ? 0.5 : 1,
              }}
            >
              Force Re-index
            </button>
          </div>
        </div>
      </div>

      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--cg-text-muted)", letterSpacing: 0.5, marginBottom: 8 }}>
          ABOUT
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 11, color: "var(--cg-text-secondary)" }}>
          <div>CodeGraph Explorer v0.2.0</div>
          <div>Evidence Verification Dashboard</div>
          <div style={{ color: "var(--cg-text-muted)", fontSize: 10 }}>
            MCP-first code graph evidence retrieval toolkit
          </div>
        </div>
      </div>
    </div>
  );
}
