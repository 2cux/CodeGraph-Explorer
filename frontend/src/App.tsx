import { useMemo, useState, useCallback } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Topbar } from "./components/Topbar";
import { Toast, type ToastData } from "./components/Toast";
import ProjectOverview from "./pages/ProjectOverview";
import SymbolSearch from "./pages/SymbolSearch";
import SymbolDetail from "./pages/SymbolDetail";
import GraphExplorer from "./pages/GraphExplorer";
import ImpactView from "./pages/ImpactView";
import ContextPackViewer from "./pages/ContextPackViewer";

type Theme = "system" | "light" | "dark";

function AppShell() {
  const [theme, setTheme] = useState<Theme>("dark");
  const [toast, setToast] = useState<ToastData | null>(null);
  const dismissToast = useCallback(() => setToast(null), []);

  const themeClass = useMemo(() => {
    if (theme === "dark") return "cg-dark";
    if (theme === "light") return "cg-light";
    return typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: dark)").matches
      ? "cg-dark"
      : "cg-light";
  }, [theme]);

  return (
    <>
      <div
        className={`cg-root ${themeClass}`}
        style={{
          width: "100%", height: "100vh",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}
      >
        <Topbar theme={theme} setTheme={setTheme} />
        <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
          <div style={{ flex: 1, position: "relative", minWidth: 0, overflow: "auto" }} className="cg-scroll">
            <div style={{ padding: 20, maxWidth: 1100, margin: "0 auto" }}>
              <Routes>
                <Route path="/" element={<ProjectOverview />} />
                <Route path="/search" element={<SymbolSearch />} />
                <Route path="/symbol/:nodeId" element={<SymbolDetail />} />
                <Route path="/graph" element={<GraphExplorer />} />
                <Route path="/impact" element={<ImpactView />} />
                <Route path="/context" element={<ContextPackViewer />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </div>
          </div>
        </div>
      </div>
      <Toast toast={toast} onDismiss={dismissToast} />
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
