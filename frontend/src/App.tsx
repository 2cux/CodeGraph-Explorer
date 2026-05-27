import { BrowserRouter, Routes, Route, Navigate, NavLink } from "react-router-dom";
import ProjectOverview from "./pages/ProjectOverview";
import SymbolSearch from "./pages/SymbolSearch";
import SymbolDetail from "./pages/SymbolDetail";
import GraphExplorer from "./pages/GraphExplorer";
import ImpactView from "./pages/ImpactView";
import ContextPackViewer from "./pages/ContextPackViewer";

const navItems = [
  { to: "/", label: "Project Overview", icon: "◉" },
  { to: "/search", label: "Symbol Search", icon: "⌕" },
  { to: "/graph", label: "Graph Explorer", icon: "⬡" },
  { to: "/impact", label: "Impact View", icon: "⚡" },
  { to: "/context", label: "Context Pack", icon: "⊞" },
];

function Sidebar() {
  return (
    <aside className="w-60 bg-gray-900 text-gray-300 flex flex-col shrink-0">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-lg font-bold text-white tracking-tight">
          CodeGraph Explorer
        </h1>
        <p className="text-xs text-gray-500 mt-0.5">Code Context for Agents</p>
      </div>
      <nav className="flex-1 p-3 space-y-1">
        {navItems.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors ${
                isActive
                  ? "bg-blue-600 text-white"
                  : "text-gray-400 hover:text-white hover:bg-gray-800"
              }`
            }
          >
            <span className="w-5 text-center">{icon}</span>
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-gray-700 text-[10px] text-gray-600">
        v0.1.0 — local dashboard
      </div>
    </aside>
  );
}

function Layout() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6">
        <Routes>
          <Route path="/" element={<ProjectOverview />} />
          <Route path="/search" element={<SymbolSearch />} />
          <Route path="/symbol/:nodeId" element={<SymbolDetail />} />
          <Route path="/graph" element={<GraphExplorer />} />
          <Route path="/impact" element={<ImpactView />} />
          <Route path="/context" element={<ContextPackViewer />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  );
}
