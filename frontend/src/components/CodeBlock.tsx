export function CodeBlock({ lines, language = "py" }: { lines: string[]; language?: "py" | "plain" }) {
  return (
    <pre
      className="cg-mono"
      style={{
        margin: 0,
        padding: 8,
        background: "var(--cg-bg-subtle)",
        border: "1px solid var(--cg-border)",
        borderRadius: 4,
        fontSize: 11,
        lineHeight: 1.55,
        color: "var(--cg-text-primary)",
        overflowX: "auto",
        whiteSpace: "pre",
      }}
    >
      {lines.map((l, i) => (
        <div key={i}>{language === "py" ? colorize(l) : l}</div>
      ))}
    </pre>
  );
}

function colorize(line: string) {
  const tokens = line.split(/(\bdef\b|\bif\b|\bis\b|\bnot\b|\bNone\b|\breturn\b|\bstr\b|\bint\b|\bUser\b|\bSession\b|->)/);
  return tokens.map((t, i) => {
    if (["def", "if", "is", "not", "return"].includes(t))
      return <span key={i} style={{ color: "var(--cg-accent)" }}>{t}</span>;
    if (["str", "int", "None", "User", "Session"].includes(t))
      return <span key={i} style={{ color: "var(--cg-success)" }}>{t}</span>;
    if (t === "->") return <span key={i} style={{ color: "var(--cg-text-muted)" }}>{t}</span>;
    return <span key={i}>{t}</span>;
  });
}
