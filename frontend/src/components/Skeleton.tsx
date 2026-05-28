export function SkeletonLine({
  width, height = 8, radius = 2, delay = 0,
}: { width: number | string; height?: number; radius?: number; delay?: number }) {
  return (
    <div className="cg-skeleton" style={{ height, width, borderRadius: radius, animationDelay: `${delay}s`, flexShrink: 0 }} />
  );
}

export function SkeletonBlock({ height, delay = 0 }: { height: number; delay?: number }) {
  return (
    <div className="cg-skeleton" style={{ height, borderRadius: 4, border: "1px solid var(--cg-border)", animationDelay: `${delay}s` }} />
  );
}

export function SkeletonSectionHeader({ delay = 0 }: { delay?: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
      <SkeletonLine width={16} height={6} radius={1} delay={delay} />
      <SkeletonLine width={64} height={8} radius={2} delay={delay + 0.02} />
    </div>
  );
}
