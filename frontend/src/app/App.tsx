import { useCallback, useEffect, useMemo, useState } from "react";
import { api, lastApiError } from "../api";
import type { SearchResult, OverviewResponse, StatusResponse } from "../api";
import { Topbar, type IndexStatus, type PageTab } from "./components/Topbar";
import { RightInspector, type InspectorTarget, type InspectorMode, type NodeInspectorData, type EdgeInspectorData } from "./components/RightInspector";
import type { GraphNodeData, GraphEdgeData, NodeKind } from "./components/GraphCanvas";
import { Library } from "./components/Library";
import { Toast, type ToastData } from "./components/Toast";
import SymbolSearch from "../pages/SymbolSearch";
import GraphExplorer, { type CanvasState } from "../pages/GraphExplorer";
import ImpactView from "../pages/ImpactView";
import EvidencePackViewer from "../pages/EvidencePackViewer";
import Settings from "../pages/Settings";

type Theme = "system" | "light" | "dark";

export default function App() {
  const [theme, setTheme] = useState<Theme>("dark");
  const [activeTab, setActiveTab] = useState<PageTab>("overview");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorTarget, setInspectorTarget] = useState<InspectorTarget>("node");
  const [inspectorMode, setInspectorMode] = useState<InspectorMode | "auto">("auto");
  const [canvasState, setCanvasState] = useState<CanvasState>("loading");
  const [indexStatus, setIndexStatus] = useState<IndexStatus>("missing");
  const [indexDetails, setIndexDetails] = useState<StatusResponse | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [toast, setToast] = useState<ToastData | null>(null);

  // Graph state
  const [graphNodes, setGraphNodes] = useState<GraphNodeData[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdgeData[]>([]);
  const [overviewData, setOverviewData] = useState<OverviewResponse | null>(null);

  // Inspector data
  const [nodeInspectorData, setNodeInspectorData] = useState<NodeInspectorData | null>(null);
  const [edgeInspectorData, setEdgeInspectorData] = useState<EdgeInspectorData | null>(null);

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

  // Load overview on mount
  useEffect(() => {
    async function load() {
      let statusRes: StatusResponse;
      try {
        statusRes = await api.repo.status();
        setIndexDetails(statusRes);
        if (statusRes.status === "fresh") setIndexStatus("fresh");
        else if (statusRes.status === "stale") setIndexStatus("stale");
        else setIndexStatus("missing");
      } catch (e) {
        // API unreachable or no index
        if (e instanceof Error && e.name === "ApiConnectionError") {
          setIndexStatus("error");
          setCanvasState("error");
          showToast("error", "Cannot connect to CodeGraph API.", lastApiError || undefined);
          return;
        }
        setIndexStatus("missing");
        setCanvasState("empty");
        return;
      }

      if (statusRes!.status === "missing") {
        setCanvasState("empty");
        return;
      }

      try {
        const ov = await api.graph.overview();
        setOverviewData(ov);
        setCanvasState("overview");
      } catch {
        setCanvasState("error");
      }
    }
    load();
  }, [showToast]);

  // Re-index handlers
  const handleReindex = useCallback(async () => {
    try {
      setIndexStatus("indexing");
      await api.repo.index("force");
      const statusRes = await api.repo.status();
      setIndexDetails(statusRes);
      setIndexStatus(statusRes.status === "stale" ? "stale" : "fresh");
      const ov = await api.graph.overview();
      setOverviewData(ov);
      setCanvasState("overview");
      showToast("info", "Index rebuilt.");
    } catch {
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
      const ov = await api.graph.overview();
      setOverviewData(ov);
      setCanvasState("overview");
      showToast("info", "Incremental index complete.");
    } catch {
      setIndexStatus("error");
      showToast("error", "Incremental update failed.");
    }
  }, [showToast]);

  // Quick search
  const handleSearch = useCallback(async (query: string): Promise<SearchResult[]> => {
    if (!query.trim()) return [];
    try {
      const res = await api.symbols.search(query);
      return res.results;
    } catch {
      return [];
    }
  }, []);

  // Select symbol → load graph + inspector
  const handleSelectSymbol = useCallback(async (nodeId: string) => {
    setInspectorOpen(true);
    setInspectorTarget("node");
    setInspectorMode("loading");
    setActiveTab("overview"); // switch to graph view

    try {
      const [detail, neighbors] = await Promise.all([
        api.symbols.detail(nodeId),
        api.symbols.neighbors(nodeId, 1),
      ]);

      // Set node inspector data
      setNodeInspectorData({
        symbol_id: detail.id,
        name: detail.name,
        type: detail.type,
        file_path: detail.file_path,
        line_start: detail.position?.line_start,
        line_end: detail.position?.line_end,
        signature: detail.signature,
        docstring: detail.docstring,
        code_preview: detail.code_preview,
        tags: detail.tags,
        visibility: detail.visibility,
        callers_count: 0,
        callees_count: neighbors.total,
        tests_count: 0,
      });

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

  // Select file in overview
  const handleSelectFile = useCallback(async (filePath: string) => {
    setInspectorOpen(true);
    setInspectorTarget("node");
    setInspectorMode("loading");
    setCanvasState("loading");

    try {
      const searchRes = await api.symbols.search("", undefined, filePath, 5, 0);
      const top = searchRes.results[0];
      if (top) {
        await handleSelectSymbol(top.symbol_id);
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
  }, [handleSelectSymbol, showToast]);

  // Edge selection → fetch real edge detail from API
  const handleSelectEdge = useCallback(async (edgeId: { source: string; target: string; type: string }) => {
    setInspectorOpen(true);
    setInspectorTarget("edge");
    setInspectorMode("loading");

    try {
      const res = await api.graph.edge(edgeId.source, edgeId.target, edgeId.type);
      if (res.ok && res.edge) {
        const e = res.edge;
        setEdgeInspectorData({
          source: e.source,
          target: e.target,
          type: e.type,
          confidence: e.confidence,
          confidence_level: e.confidence_level,
          resolution: e.resolution,
          reason_codes: e.reason_codes,
          reason: e.reason,
          evidence: e.evidence,
          source_location: e.source_location,
        });
        setInspectorMode("edge");
      } else {
        setInspectorMode("error");
        showToast("error", res.error?.message || "Edge not found");
      }
    } catch {
      setInspectorMode("error");
      showToast("error", "Failed to load edge details.");
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
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          indexStatus={indexStatus}
          indexDetails={indexDetails ?? undefined}
          onReindex={handleReindex}
          onIncrementalIndex={handleIncrementalIndex}
          onSearch={handleSearch}
          onSelectResult={handleSelectSymbol}
        />
        <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
          {/* Main content area */}
          <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
            {activeTab === "overview" && (
              <GraphExplorer
                canvasState={canvasState}
                nodes={canvasState === "focused" ? graphNodes : undefined}
                edges={canvasState === "focused" ? graphEdges : undefined}
                overviewData={overviewData}
                indexStatus={indexStatus}
                onSelectNode={handleSelectSymbol}
                onSelectFile={handleSelectFile}
                onSelectEdge={handleSelectEdge}
              />
            )}
            {activeTab === "search" && (
              <SymbolSearch onSelectSymbol={handleSelectSymbol} />
            )}
            {activeTab === "impact" && (
              <ImpactView onSelectSymbol={handleSelectSymbol} />
            )}
            {activeTab === "evidence" && (
              <EvidencePackViewer />
            )}
            {activeTab === "settings" && (
              <Settings
                theme={theme}
                setTheme={setTheme}
                onReindex={handleReindex}
                onIncrementalIndex={handleIncrementalIndex}
                indexStatus={indexStatus}
              />
            )}
          </div>

          {/* Right Inspector */}
          {inspectorOpen && (
            <RightInspector
              target={inspectorTarget}
              mode={inspectorMode === "auto" ? inspectorTarget : inspectorMode}
              onSwitch={(t) => { setInspectorTarget(t); setInspectorMode("auto"); }}
              onClose={() => setInspectorOpen(false)}
              onRetry={() => setInspectorMode("auto")}
              nodeData={inspectorTarget === "node" ? nodeInspectorData : null}
              edgeData={inspectorTarget === "edge" ? edgeInspectorData : null}
            />
          )}
        </div>
        {libraryOpen && <Library onClose={() => setLibraryOpen(false)} />}
        <Toast toast={toast} onDismiss={dismissToast} />
      </div>
    </>
  );
}
