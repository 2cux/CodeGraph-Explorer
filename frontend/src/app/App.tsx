import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { SearchResult, OverviewResponse, StatusResponse } from "../api";
import { Topbar, type IndexStatus } from "./components/Topbar";
import { GraphCanvas, type CanvasState, type GraphNodeData, type GraphEdgeData, type NodeKind } from "./components/GraphCanvas";
import { RightInspector, type InspectorTarget, type InspectorMode } from "./components/RightInspector";
import { ContextPackOverlay, type ContextPackStatus } from "./components/ContextPackOverlay";
import { Library } from "./components/Library";
import { Toast, type ToastData } from "./components/Toast";

type Theme = "system" | "light" | "dark";

export default function App() {
  const [theme, setTheme] = useState<Theme>("dark");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorTarget, setInspectorTarget] = useState<InspectorTarget>("node");
  const [inspectorMode, setInspectorMode] = useState<InspectorMode | "auto">("auto");
  const [packOpen, setPackOpen] = useState(false);
  const [packStatus, setPackStatus] = useState<ContextPackStatus>("empty");
  const [packData, setPackData] = useState<{} | null>(null);
  const [packTask, setPackTask] = useState("");
  const [canvasState, setCanvasState] = useState<CanvasState>("loading");
  const [indexStatus, setIndexStatus] = useState<IndexStatus>("missing");
  const [indexDetails, setIndexDetails] = useState<StatusResponse | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [toast, setToast] = useState<ToastData | null>(null);

  // Real data state
  const [graphNodes, setGraphNodes] = useState<GraphNodeData[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdgeData[]>([]);
  const [overviewData, setOverviewData] = useState<OverviewResponse | null>(null);

  const dismissToast = useCallback(() => setToast(null), []);
  const showToast = useCallback((type: ToastData["type"], message: string, detail?: string) => {
    setToast({ type, message, detail });
  }, []);

  const themeClass = useMemo(() => {
    if (theme === "dark") return "cg-dark";
    if (theme === "light") return "cg-light";
    return typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: dark)").matches
      ? "cg-dark"
      : "cg-light";
  }, [theme]);

  const showSidePanels = canvasState === "focused" || canvasState === "overview";

  // Load dashboard stats on mount
  useEffect(() => {
    async function load() {
      // Check index status first
      try {
        const statusRes = await api.repo.status();
        setIndexDetails(statusRes);
        if (statusRes.status === "fresh") setIndexStatus("fresh");
        else if (statusRes.status === "stale") setIndexStatus("stale");
        else setIndexStatus("missing");
      } catch {
        setIndexStatus("missing");
      }

      // Load overview
      try {
        setIndexStatus((prev) => prev === "missing" ? "indexing" : prev);
        const ov = await api.graph.overview();
        setOverviewData(ov);
        setCanvasState("overview");
        // Re-check status after loading to set correct state
        const statusRes = await api.repo.status();
        if (statusRes.status === "fresh") setIndexStatus("fresh");
        else if (statusRes.status === "stale") setIndexStatus("stale");
      } catch {
        setCanvasState("empty");
        setIndexStatus("missing");
      }
    }
    load();
  }, []);

  // Re-index handlers
  const handleReindex = useCallback(async () => {
    try {
      setIndexStatus("indexing");
      await api.repo.index("force");
      const statusRes = await api.repo.status();
      setIndexDetails(statusRes);
      setIndexStatus(statusRes.status === "stale" ? "stale" : "fresh");
      // Reload overview
      const ov = await api.graph.overview();
      setOverviewData(ov);
      setCanvasState("overview");
      showToast("info", "Index rebuilt successfully.");
    } catch (e) {
      setIndexStatus("error");
      showToast("error", "Re-index failed.");
    }
  }, [showToast]);

  const handleIncrementalIndex = useCallback(async () => {
    try {
      setIndexStatus("indexing");
      await api.repo.index("incremental");
      const statusRes = await api.repo.status();
      setIndexDetails(statusRes);
      setIndexStatus(statusRes.status === "stale" ? "stale" : "fresh");
      // Reload overview
      const ov = await api.graph.overview();
      setOverviewData(ov);
      setCanvasState("overview");
      showToast("info", "Incremental index complete.");
    } catch (e) {
      setIndexStatus("error");
      showToast("error", "Incremental update failed.");
    }
  }, [showToast]);

  // Handle symbol search in Topbar
  const handleSearch = useCallback(async (query: string): Promise<SearchResult[]> => {
    if (!query.trim()) return [];
    try {
      const res = await api.symbols.search(query);
      return res.results;
    } catch {
      return [];
    }
  }, []);

  // Handle node selection → focus graph + open inspector
  const handleSelectNode = useCallback(async (nodeId: string) => {
    setInspectorOpen(true);
    setInspectorTarget("node");
    setInspectorMode("loading");

    try {
      const [detail, neighbors] = await Promise.all([
        api.symbols.detail(nodeId),
        api.symbols.neighbors(nodeId, 1),
      ]);

      // Transform to graph nodes
      const nodes: GraphNodeData[] = [
        {
          id: nodeId,
          x: 360, y: 360,
          kind: (detail.type?.toLowerCase() || "function") as NodeKind,
          name: detail.name || nodeId,
          path: detail.file_path || "",
          confidence: 1,
          state: "active",
        },
        ...neighbors.neighbors.map((n, i) => ({
          id: n.node_id,
          x: 180 + (i % 3) * 180,
          y: 170 + Math.floor(i / 3) * 170,
          kind: (n.type?.toLowerCase() || "function") as NodeKind,
          name: n.name,
          path: n.file_path,
          confidence: parseFloat(n.confidence) || 0.5,
          state: "normal" as const,
        })),
      ];

      const edges: GraphEdgeData[] = neighbors.neighbors.map((n) => ({
        from: n.edge_type === "caller" ? n.node_id : nodeId,
        to: n.edge_type === "caller" ? nodeId : n.node_id,
        label: "calls" as const,
        state: (parseFloat(n.confidence) < 0.6 ? "low_confidence" : "default") as GraphEdgeData["state"],
      }));

      setGraphNodes(nodes);
      setGraphEdges(edges);
      setCanvasState("focused");
      setInspectorMode("node");
    } catch {
      setInspectorMode("error");
      showToast("error", "Failed to load symbol details.");
    }
  }, [showToast]);

  // Handle file-level node click in overview → find top symbol → focus
  const handleSelectFile = useCallback(async (filePath: string) => {
    setInspectorOpen(true);
    setInspectorTarget("node");
    setInspectorMode("loading");
    setCanvasState("loading");

    try {
      // Search for symbols in this file, get the top result
      const searchRes = await api.symbols.search("", undefined, filePath, 5, 0);
      const top = searchRes.results[0];
      if (top) {
        await handleSelectNode(top.symbol_id);
      } else {
        setCanvasState("overview");
        setInspectorMode("error");
        showToast("warning", `No symbols found in ${filePath}`);
      }
    } catch {
      setCanvasState("overview");
      setInspectorMode("error");
      showToast("error", "Failed to load symbols for this file.");
    }
  }, [handleSelectNode, showToast]);

  // Generate evidence pack
  const handleGeneratePack = useCallback(async (task: string) => {
    if (!task.trim()) return;
    setPackTask(task);
    setPackStatus("generating");
    setPackOpen(true);

    try {
      const result = await api.context.generate(task);
      setPackData(result);
      setPackStatus("generated");
      showToast("info", `Evidence pack generated: ${result.pack_id}`);
    } catch {
      setPackStatus("error");
      showToast("error", "Failed to generate evidence pack.");
    }
  }, [showToast]);

  return (
    <>
      <div
        className={`cg-root ${themeClass}`}
        style={{
          width: "100%", height: "100vh",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}
      >
        <Topbar
          theme={theme}
          setTheme={setTheme}
          onOpenLibrary={() => setLibraryOpen(true)}
          indexStatus={indexStatus}
          indexDetails={indexDetails ?? undefined}
          onReindex={handleReindex}
          onIncrementalIndex={handleIncrementalIndex}
          onSearch={handleSearch}
          onSelectResult={handleSelectNode}
        />
        <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
          <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
            <GraphCanvas
              state={canvasState}
              nodes={canvasState === "focused" ? graphNodes : undefined}
              edges={canvasState === "focused" ? graphEdges : undefined}
              overviewData={overviewData}
              onSelectNode={handleSelectNode}
              onSelectFile={handleSelectFile}
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
                  packData={packData ?? undefined}
                  task={packTask}
                  onRetry={() => handleGeneratePack(packTask)}
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
  packStatus, setPackStatus,
  indexStatus, setIndexStatus, onToast,
}: {
  canvas: CanvasState; setCanvas: (s: CanvasState) => void;
  inspector: InspectorMode | "auto"; setInspector: (m: InspectorMode | "auto") => void;
  packStatus: ContextPackStatus; setPackStatus: (s: ContextPackStatus) => void;
  indexStatus: IndexStatus; setIndexStatus: (s: IndexStatus) => void;
  onToast: (type: ToastData["type"], message: string, detail?: string) => void;
}) {
  const canvasOpts: CanvasState[] = ["overview", "focused", "empty", "loading", "error"];
  const inspectorOpts: (InspectorMode | "auto")[] = ["auto", "loading", "error"];
  const packOpts: ContextPackStatus[] = ["empty", "generating", "generated", "error"];
  const indexOpts: IndexStatus[] = ["fresh", "stale", "missing", "indexing", "error"];

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
      <Group label="toast">
        <SegBtn active={false} onClick={() => onToast("error", "Export failed.", "EXPORT_ERROR · permission denied")}>err</SegBtn>
        <SegBtn active={false} onClick={() => onToast("warning", "Low-confidence edges detected.", "47 edges below 0.7 threshold")}>warn</SegBtn>
        <SegBtn active={false} onClick={() => onToast("info", "Evidence pack copied to clipboard.")}>info</SegBtn>
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
