export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" style={{ display: "block" }}>
      <circle cx="8" cy="8" r="6" fill="none" stroke="var(--cg-border)" strokeWidth="1.4" />
      <circle
        cx="8" cy="8" r="6" fill="none"
        stroke="var(--cg-accent)" strokeWidth="1.4"
        strokeDasharray="38" strokeDashoffset="28" strokeLinecap="round"
        transform="rotate(-90 8 8)"
      >
        <animateTransform attributeName="transform" type="rotate" from="0 8 8" to="360 8 8" dur="0.9s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}
