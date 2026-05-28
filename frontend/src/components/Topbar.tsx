import { useLocation, useNavigate } from "react-router-dom";
import { IconLogo, IconSun, IconMoon, IconMonitor } from "./icons";

type Theme = "system" | "light" | "dark";

interface Props {
  theme: Theme;
  setTheme: (t: Theme) => void;
}

const navItems = [
  { to: "/", label: "Overview" },
  { to: "/search", label: "Search" },
  { to: "/graph", label: "Graph" },
  { to: "/impact", label: "Impact" },
  { to: "/context", label: "Context" },
];

const THEME_ICONS: Record<Theme, React.FC<{ size?: number }>> = {
  system: IconMonitor,
  light: IconSun,
  dark: IconMoon,
};

const THEME_NEXT: Record<Theme, Theme> = {
  system: "light",
  light: "dark",
  dark: "system",
};

export function Topbar({ theme, setTheme }: Props) {
  const location = useLocation();
  const navigate = useNavigate();
  const ThemeIcon = THEME_ICONS[theme];

  return (
    <div
      style={{
        height: 36,
        display: "flex",
        alignItems: "center",
        padding: "0 10px",
        gap: 10,
        background: "var(--cg-bg-panel)",
        borderBottom: "1px solid var(--cg-border)",
        flexShrink: 0,
      }}
    >
      {/* Logo */}
      <div className="flex items-center" style={{ gap: 6, cursor: "pointer" }} onClick={() => navigate("/")}>
        <span style={{ color: "var(--cg-accent)", display: "flex", alignItems: "center" }}>
          <IconLogo size={16} />
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "var(--cg-text-primary)",
            letterSpacing: 0.2,
          }}
        >
          CodeGraph
        </span>
      </div>

      <span style={{ width: 1, height: 20, background: "var(--cg-border)", flexShrink: 0 }} />

      {/* Navigation */}
      <nav className="flex items-center" style={{ gap: 2 }}>
        {navItems.map(({ to, label }) => {
          const isActive = location.pathname === to || (to !== "/" && location.pathname.startsWith(to));
          return (
            <button
              key={to}
              onClick={() => navigate(to)}
              style={{
                height: 26,
                padding: "0 8px",
                border: "none",
                borderRadius: 4,
                background: isActive ? "var(--cg-bg-subtle)" : "transparent",
                color: isActive ? "var(--cg-text-primary)" : "var(--cg-text-secondary)",
                fontSize: 11,
                cursor: "pointer",
                fontFamily: "inherit",
                fontWeight: isActive ? 500 : 400,
              }}
            >
              {label}
            </button>
          );
        })}
      </nav>

      <div style={{ flex: 1 }} />

      {/* Theme toggle */}
      <button
        onClick={() => setTheme(THEME_NEXT[theme])}
        style={{
          width: 26, height: 26, borderRadius: 4, border: "none",
          background: "transparent", color: "var(--cg-text-muted)",
          cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
        }}
        aria-label={`Theme: ${theme}`}
      >
        <ThemeIcon size={13} />
      </button>
    </div>
  );
}
