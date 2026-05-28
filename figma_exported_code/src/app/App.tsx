import { useCallback, useMemo, useState } from "react";
import { ThemeTokens } from "./components/tokens";
import { Topbar } from "./components/Topbar";
import { GraphCanvas, type CanvasState } from "./components/GraphCanvas";
import { RightInspector, type InspectorTarget, type InspectorMode } from "./components/RightInspector";
import { ContextPackOverlay, type ContextPackStatus } from "./components/ContextPackOverlay";
import { ReadingPlan, type ReadingPlanStatus } from "./components/ReadingPlan";
import { Library } from "./components/Library";
import { type IndexStatus } from "./components/Topbar";
import { Toast, type ToastData } from "./components/Toast";

type Theme = "system" | "light" | "dark";

export default function App() {
  const [theme, setTheme] = useState<Theme>("dark");
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [inspectorTarget, setInspectorTarget] = useState<InspectorTarget>("node");
  const [inspectorMode, setInspectorMode] = useState<InspectorMode | "auto">("auto");
  const [packOpen, setPackOpen] = useState(true);
  const [packStatus, setPackStatus] = useState<ContextPackStatus>("generated");
  const [planOpen, setPlanOpen] = useState(false);
  const [planStatus, setPlanStatus] = useState<ReadingPlanStatus>("ready");
  const [activeStep, setActiveStep] = useState(0);
  const [canvasState, setCanvasState] = useState<CanvasState>("focused");
  const [indexStatus, setIndexStatus] = useState<IndexStatus>("indexed");
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [toast, setToast] = useState<ToastData | null>(null);
  const dismissToast = useCallback(() => setToast(null), []);
  function showToast(type: ToastData["type"], message: string, detail?: string) {
    setToast({ type, message, detail });
  }

  const themeClass = useMemo(() => {
    if (theme === "dark") return "cg-dark";
    if (theme === "light") return "cg-light";
    return typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: dark)").matches
      ? "cg-dark"
      : "cg-light";
  }, [theme]);

  const showSidePanels = canvasState === "focused" || canvasState === "overview";

  // Reading plan button is only visible when context pack is generated
  const planVisible = packStatus === "generated";

  return (
    <>
      <ThemeTokens />
      <div
        className={`cg-root ${themeClass}`}
        style={{
          width: "100%", height: "100vh",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}
      >
        <Topbar theme={theme} setTheme={setTheme} onOpenLibrary={() => setLibraryOpen(true)} indexStatus={indexStatus} />
        <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
          <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
            <GraphCanvas
              state={canvasState}
              onSelectEdge={() => {
                setInspectorOpen(true);
                setInspectorTarget("edge");
                setInspectorMode("auto");
              }}
            />
            {showSidePanels && (
              <>
                <ContextPackOverlay
                  open={packOpen}
                  onToggle={() => setPackOpen((v) => !v)}
                  onClose={() => setPackOpen(false)}
                  status={packStatus}
                  onRetry={() => setPackStatus("generating")}
                />
                <ReadingPlan
                  visible={planVisible}
                  open={planOpen}
                  onToggle={() => setPlanOpen((v) => !v)}
                  status={planStatus}
                  activeStep={activeStep}
                  onStepClick={setActiveStep}
                />
              </>
            )}
            <StateSwitcher
              canvas={canvasState}
              setCanvas={setCanvasState}
              inspector={inspectorMode}
              setInspector={(m) => {
                setInspectorMode(m);
                setInspectorOpen(true);
              }}
              packStatus={packStatus}
              setPackStatus={setPackStatus}
              planStatus={planStatus}
              setPlanStatus={setPlanStatus}
              indexStatus={indexStatus}
              setIndexStatus={setIndexStatus}
              onToast={showToast}
            />
          </div>
          {inspectorOpen && showSidePanels && (
            <RightInspector
              target={inspectorTarget}
              mode={inspectorMode === "auto" ? inspectorTarget : inspectorMode}
              onSwitch={(t) => { setInspectorTarget(t); setInspectorMode("auto"); }}
              onClose={() => setInspectorOpen(false)}
              onRetry={() => setInspectorMode("auto")}
            />
          )}
        </div>
        {libraryOpen && <Library onClose={() => setLibraryOpen(false)} />}
        <Toast toast={toast} onDismiss={dismissToast} />
      </div>
    </>
  );
}

function StateSwitcher({
  canvas, setCanvas, inspector, setInspector,
  packStatus, setPackStatus, planStatus, setPlanStatus,
  indexStatus, setIndexStatus, onToast,
}: {
  canvas: CanvasState; setCanvas: (s: CanvasState) => void;
  inspector: InspectorMode | "auto"; setInspector: (m: InspectorMode | "auto") => void;
  packStatus: ContextPackStatus; setPackStatus: (s: ContextPackStatus) => void;
  planStatus: ReadingPlanStatus; setPlanStatus: (s: ReadingPlanStatus) => void;
  indexStatus: IndexStatus; setIndexStatus: (s: IndexStatus) => void;
  onToast: (type: ToastData["type"], message: string, detail?: string) => void;
}) {
  const canvasOpts: CanvasState[] = ["overview", "focused", "empty", "loading", "error"];
  const inspectorOpts: (InspectorMode | "auto")[] = ["auto", "loading", "error"];
  const packOpts: ContextPackStatus[] = ["empty", "generating", "generated", "error"];
  const planOpts: ReadingPlanStatus[] = ["ready", "loading", "empty"];
  const indexOpts: IndexStatus[] = ["indexed", "indexing", "failed", "not-indexed"];

  return (
    <div
      style={{
        position: "absolute", bottom: 16, left: "50%", transform: "translateX(-50%)",
        display: "flex", gap: 5, zIndex: 9, flexWrap: "wrap", justifyContent: "center",
      }}
    >
      <Group label="canvas">
        {canvasOpts.map((o) => (
          <SegBtn key={o} active={canvas === o} onClick={() => setCanvas(o)}>{o}</SegBtn>
        ))}
      </Group>
      <Group label="inspector">
        {inspectorOpts.map((o) => (
          <SegBtn key={o} active={inspector === o} onClick={() => setInspector(o)}>{o}</SegBtn>
        ))}
      </Group>
      <Group label="index">
        {indexOpts.map((o) => (
          <SegBtn key={o} active={indexStatus === o} onClick={() => setIndexStatus(o)}>{o}</SegBtn>
        ))}
      </Group>
      <Group label="pack">
        {packOpts.map((o) => (
          <SegBtn key={o} active={packStatus === o} onClick={() => setPackStatus(o)}>{o}</SegBtn>
        ))}
      </Group>
      <Group label="plan">
        {planOpts.map((o) => (
          <SegBtn key={o} active={planStatus === o} onClick={() => setPlanStatus(o)}>{o}</SegBtn>
        ))}
      </Group>
      <Group label="toast">
        <SegBtn active={false} onClick={() => onToast("error", "Export failed.", "EXPORT_ERROR · permission denied")}>err</SegBtn>
        <SegBtn active={false} onClick={() => onToast("warning", "Low-confidence edges detected.", "47 edges below 0.7 threshold")}>warn</SegBtn>
        <SegBtn active={false} onClick={() => onToast("info", "Context pack copied to clipboard.")}>info</SegBtn>
      </Group>
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      className="flex items-center"
      style={{
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 6, padding: 2, gap: 2,
      }}
    >
      <span
        className="cg-mono"
        style={{
          fontSize: 9, color: "var(--cg-text-muted)",
          letterSpacing: 0.5, padding: "0 6px",
        }}
      >
        {label}
      </span>
      {children}
    </div>
  );
}

function SegBtn({
  active, onClick, children,
}: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="cg-mono"
      style={{
        height: 22, padding: "0 10px",
        border: "none", borderRadius: 4, cursor: "pointer",
        background: active ? "var(--cg-bg-subtle)" : "transparent",
        color: active ? "var(--cg-text-primary)" : "var(--cg-text-muted)",
        fontSize: 10, letterSpacing: 0.4,
      }}
    >
      {children}
    </button>
  );
}
