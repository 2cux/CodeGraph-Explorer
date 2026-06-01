import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Node, Edge } from "@xyflow/react";
import { api, lastApiError } from "../api";
import type { SearchResult, OverviewResponse, StatusResponse } from "../api";
import { Topbar, type IndexStatus, type PageTab } from "./components/Topbar";
import { RightInspector, type InspectorTarget, type InspectorMode, type NodeInspectorData, type EdgeInspectorData } from "./components/RightInspector";
import { Library } from "./components/Library";
import { Toast, type ToastData } from "./components/Toast";
import { toReactFlowGraph, type RFNodeData, type RFEdgeData, type CappingWarning } from "./components/graphTransforms";
import type { EdgeIdentity } from "./components/ReactFlowGraph";
import { type LayoutPreset } from "./components/nodeStyles";
import NavBar, { type BreadcrumbItem } from "./components/NavBar";
import GraphExplorer, { type CanvasState } from "../pages/GraphExplorer";
import SymbolSearch from "../pages/SymbolSearch";
import ImpactView from "../pages/ImpactView";
import EvidencePackViewer from "../pages/EvidencePackViewer";
import Settings from "../pages/Settings";

// ── Navigation history ──────────────────────────────────────────────

interface NavEntry {
  type: "overview" | "symbol" | "impact";
  label: string;
  symbolId?: string;
  tab: PageTab;
}

const MAX_HISTORY = 50;

type Theme = "system" | "light" | "dark";

const THEME_STORAGE_KEY = "codegraph_theme";

function loadTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch { /* localStorage unavailable */ }
  return "dark";
}

export default function App() {
  const [theme, setThemeState] = useState<Theme>(loadTheme);
  const [activeTab, setActiveTab] = useState<PageTab>("overview");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorTarget, setInspectorTarget] = useState<InspectorTarget>("node");
  const [inspectorMode, setInspectorMode] = useState<InspectorMode | "auto">("auto");
  const [canvasState, setCanvasState] = useState<CanvasState>("loading");
  const [indexStatus, setIndexStatus] = useState<IndexStatus>("missing");
  const [indexDetails, setIndexDetails] = useState<StatusResponse | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [toast, setToast] = useState<ToastData | null>(null);

  // Persist theme to localStorage
  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try { localStorage.setItem(THEME_STORAGE_KEY, t); } catch { /* noop */ }
  }, []);

  // ── Layout preset ──────────────────────────────────────────────────
  const [layoutPreset, setLayoutPreset] = useState<LayoutPreset>("local");

  // ── React Flow graph state ──────────────────────────────────────────
  const [rfNodes, setRfNodes] = useState<Node<RFNodeData>[]>([]);
  const [rfEdges, setRfEdges] = useState<Edge<RFEdgeData>[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeSource, setSelectedEdgeSource] = useState<string | null>(null);
  const [selectedEdgeTarget, setSelectedEdgeTarget] = useState<string | null>(null);
  const [overviewData, setOverviewData] = useState<OverviewResponse | null>(null);

  // ── Hierarchy folding state ─────────────────────────────────────────
  const [expandedGroupIds, setExpandedGroupIds] = useState<Set<string>>(new Set());
  const expandedGroupIdsRef = useRef(expandedGroupIds);
  expandedGroupIdsRef.current = expandedGroupIds;
  const [cappingWarning, setCappingWarning] = useState<CappingWarning | null>(null);
  const [pendingImpactSymbolId, setPendingImpactSymbolId] = useState<string | null>(null);

  // ── Navigation history ──────────────────────────────────────────────
  const [historyStack, setHistoryStack] = useState<NavEntry[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const isRestoringRef = useRef(false);

  const pushHistory = useCallback((entry: NavEntry) => {
    if (isRestoringRef.current) return;
    setHistoryStack((prev) => {
      const truncated = prev.slice(0, historyIndex + 1);
      // Dedup consecutive same-type entries for same symbol
      if (truncated.length > 0) {
        const last = truncated[truncated.length - 1];
        if (last.type === entry.type && last.symbolId === entry.symbolId && last.tab === entry.tab) {
          return truncated; // no change, same entry
        }
      }
      const next = [...truncated, entry].slice(-MAX_HISTORY);
      return next;
    });
    setHistoryIndex((prev) => {
      const newLen = Math.min(prev + 2, MAX_HISTORY);
      return Math.min(newLen - 1, MAX_HISTORY - 1);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyIndex]);

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

  // Track whether we've auto-selected an entry point on initial load
  const hasAutoSelected = useRef(false);
  // Track current center node id
  const centerNodeIdRef = useRef<string | null>(null);

  // ── Load on mount: status → summary → auto-select center ──────────
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

      // Also load overview data (for overview tab fallback)
      try {
        const ov = await api.graph.overview();
        setOverviewData(ov);
      } catch {
        // non-critical
      }

      // Auto-select first entry point for local subgraph view
      if (!hasAutoSelected.current) {
        try {
          const summary = await api.repo.summary();
          const firstEp = summary.entry_points?.[0];
          if (firstEp) {
            hasAutoSelected.current = true;
            setTimeout(() => {
              handleSelectSymbol(firstEp.symbol_id);
            }, 0);
          } else {
            // Fallback to overview view if no entry points
            setCanvasState("overview");
          }
        } catch {
          setCanvasState("overview");
        }
      }
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showToast]);

  // ── Re-index handlers ──────────────────────────────────────────────
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

  // ── Quick search (for Topbar) ──────────────────────────────────────
  const handleSearch = useCallback(async (query: string): Promise<SearchResult[]> => {
    if (!query.trim()) return [];
    try {
      const res = await api.symbols.search(query);
      return res.results;
    } catch {
      return [];
    }
  }, []);

  // ── Select symbol → load subgraph + inspector ─────────────────────
  const handleSelectSymbol = useCallback(async (nodeId: string) => {
    // Clear edge selection when selecting a node
    setSelectedEdgeSource(null);
    setSelectedEdgeTarget(null);

    setInspectorOpen(true);
    setInspectorTarget("node");
    setInspectorMode("loading");
    setSelectedNodeId(nodeId);
    setCanvasState("loading");
    setActiveTab("overview"); // switch to graph view

    try {
      // Fetch detail + subgraph in parallel
      const [detail, subgraph] = await Promise.all([
        api.symbols.detail(nodeId),
        api.graph.subgraph(nodeId, 1),
      ]);

      centerNodeIdRef.current = nodeId;

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
        callees_count: subgraph.edges.length,
        tests_count: 0,
        confidence: 1.0,
      });

      // Auto-expand the group containing this symbol
      if (detail.file_path) {
        const fileGroupId = `file:${detail.file_path.replace(/\\/g, "/")}`;
        setExpandedGroupIds((prev) => {
          if (prev.has(fileGroupId)) return prev;
          const next = new Set(prev);
          next.add(fileGroupId);
          return next;
        });
      }

      // Transform to React Flow format with hierarchy + capping
      const { nodes, edges, cappingWarning: capWarn } = toReactFlowGraph(subgraph, {
        centerNodeId: nodeId,
        centerName: detail.name,
        centerFilePath: detail.file_path,
        selectedNodeId: nodeId,
        expandedGroupIds: expandedGroupIdsRef.current,
        nodeCap: 150,
        layoutPreset,
      });

      setRfNodes(nodes);
      setRfEdges(edges);
      setCappingWarning(capWarn);
      setCanvasState("focused");
      setInspectorMode("node");

      // Push to navigation history
      pushHistory({
        type: "symbol",
        label: detail.name || nodeId,
        symbolId: nodeId,
        tab: "overview",
      });
    } catch (e) {
      setInspectorMode("error");
      setCanvasState("error");
      showToast("error", "Failed to load symbol details.");
    }
  }, [showToast, pushHistory]);

  // ── Navigation history handlers (after handleSelectSymbol) ──────────
  const handleBack = useCallback(() => {
    if (historyIndex <= 0) return;
    const newIndex = historyIndex - 1;
    const entry = historyStack[newIndex];
    if (!entry) return;
    isRestoringRef.current = true;
    setHistoryIndex(newIndex);
    setActiveTab(entry.tab);
    if (entry.symbolId) {
      handleSelectSymbol(entry.symbolId);
    }
    setTimeout(() => { isRestoringRef.current = false; }, 300);
  }, [historyIndex, historyStack, handleSelectSymbol]);

  const handleForward = useCallback(() => {
    if (historyIndex >= historyStack.length - 1) return;
    const newIndex = historyIndex + 1;
    const entry = historyStack[newIndex];
    if (!entry) return;
    isRestoringRef.current = true;
    setHistoryIndex(newIndex);
    setActiveTab(entry.tab);
    if (entry.symbolId) {
      handleSelectSymbol(entry.symbolId);
    }
    setTimeout(() => { isRestoringRef.current = false; }, 300);
  }, [historyIndex, historyStack, handleSelectSymbol]);

  // Compute breadcrumb from current state
  const breadcrumbs = useMemo<BreadcrumbItem[]>(() => {
    const crumbs: BreadcrumbItem[] = [
      {
        label: "Repo Overview",
        onClick: () => {
          setActiveTab("overview");
          if (selectedNodeId) {
            pushHistory({ type: "overview", label: "Repo Overview", tab: "overview" });
          }
        },
      },
    ];
    if (activeTab === "overview" && selectedNodeId && centerNodeIdRef.current === selectedNodeId) {
      const name = selectedNodeId.split("::").pop() || selectedNodeId;
      crumbs.push({ label: name });
    }
    if (activeTab === "impact") {
      if (selectedNodeId) {
        const name = selectedNodeId.split("::").pop() || selectedNodeId;
        crumbs.push({ label: name, onClick: () => {
          setActiveTab("overview");
          handleSelectSymbol(selectedNodeId);
        }});
      }
      crumbs.push({ label: "Impact" });
    }
    if (activeTab === "search") {
      crumbs.push({ label: "Search" });
    }
    return crumbs;
  }, [activeTab, selectedNodeId, pushHistory, handleSelectSymbol]);

  // Push initial history entry on overview
  useEffect(() => {
    if (historyStack.length === 0 && activeTab === "overview") {
      pushHistory({ type: "overview", label: "Repo Overview", tab: "overview" });
    }
  }, [historyStack.length, activeTab, pushHistory]);

  // ── Search bar select (from graph overlay) ────────────────────────
  const handleSearchSelect = useCallback(async (symbolId: string) => {
    await handleSelectSymbol(symbolId);
  }, [handleSelectSymbol]);

  // ── Select file in overview ───────────────────────────────────────
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

  // ── Edge selection → fetch edge detail ────────────────────────────
  const handleSelectEdge = useCallback(async (edgeId: EdgeIdentity) => {
    // Set edge selection highlighting
    setSelectedEdgeSource(edgeId.source);
    setSelectedEdgeTarget(edgeId.target);
    setSelectedNodeId(null); // clear node selection

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

  // ── Copy to clipboard ─────────────────────────────────────────────
  const handleCopyToClipboard = useCallback(async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showToast("info", `Copied ${label} to clipboard.`);
    } catch {
      showToast("error", `Failed to copy ${label}.`);
    }
  }, [showToast]);

  // ── Show Callers / Callees / Impact ───────────────────────────────
  const handleShowCallers = useCallback(async (symbolId: string) => {
    setInspectorOpen(true);
    setInspectorTarget("node");
    try {
      const res = await api.symbols.callers(symbolId);
      setNodeInspectorData((prev) => ({
        ...prev,
        symbol_id: prev?.symbol_id || symbolId,
        name: prev?.name || symbolId,
        type: prev?.type || "",
        file_path: prev?.file_path || "",
        callers_count: res.total,
        callers_list: res.callers || [],
      }));
      setInspectorMode("node");
    } catch {
      showToast("error", "Failed to load callers.");
    }
  }, [showToast]);

  const handleShowCallees = useCallback(async (symbolId: string) => {
    setInspectorOpen(true);
    setInspectorTarget("node");
    try {
      const res = await api.symbols.callees(symbolId);
      setNodeInspectorData((prev) => ({
        ...prev,
        symbol_id: prev?.symbol_id || symbolId,
        name: prev?.name || symbolId,
        type: prev?.type || "",
        file_path: prev?.file_path || "",
        callees_count: res.total,
        callees_list: res.callees || [],
      }));
      setInspectorMode("node");
    } catch {
      showToast("error", "Failed to load callees.");
    }
  }, [showToast]);

  const handleShowImpact = useCallback((symbolId: string) => {
    setPendingImpactSymbolId(symbolId);
    setActiveTab("impact");
    pushHistory({
      type: "impact",
      label: "Impact",
      symbolId: symbolId,
      tab: "impact",
    });
  }, [pushHistory]);

  // ── Clear selection (Esc / pane click) ─────────────────────────────
  const handleClearSelection = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedEdgeSource(null);
    setSelectedEdgeTarget(null);
    setInspectorOpen(false);
  }, []);

  // ── Hierarchy group toggle ─────────────────────────────────────────
  const handleToggleGroup = useCallback((groupId: string) => {
    setExpandedGroupIds((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });

    // Show group info in inspector
    setInspectorOpen(true);
    setInspectorTarget("node");
    setSelectedNodeId(groupId);

    // Find the group node in current rfNodes to get its data
    const groupNode = rfNodes.find((n) => n.id === groupId && n.data.isGroupParent);
    if (groupNode) {
      const d = groupNode.data;
      setNodeInspectorData({
        symbol_id: groupId,
        name: d.name,
        type: d.kind,
        file_path: d.filePath || groupId,
        is_group_parent: true,
        child_count: d.childCount,
        child_kind_summary: d.childKindSummary,
      });
      setInspectorMode("node");
    }
  }, [rfNodes]);

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
        <NavBar
          canGoBack={historyIndex > 0}
          canGoForward={historyIndex < historyStack.length - 1}
          onBack={handleBack}
          onForward={handleForward}
          breadcrumbs={breadcrumbs}
        />
        <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
          {/* Main content area */}
          <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
            {activeTab === "overview" && (
              <GraphExplorer
                canvasState={canvasState}
                rfNodes={canvasState === "focused" ? rfNodes : []}
                rfEdges={canvasState === "focused" ? rfEdges : []}
                selectedNodeId={selectedNodeId}
                overviewData={overviewData}
                indexStatus={indexStatus}
                onToggleGroup={handleToggleGroup}
                cappingWarning={cappingWarning}
                hierarchyEnabled={true}
                selectedEdgeSource={selectedEdgeSource}
                selectedEdgeTarget={selectedEdgeTarget}
                onSelectNode={(nodeId) => {
                  // Clear edge selection when clicking a node
                  setSelectedEdgeSource(null);
                  setSelectedEdgeTarget(null);
                  if (nodeId === selectedNodeId) {
                    // Re-click same node: reload center
                    handleSelectSymbol(nodeId);
                  } else {
                    // Click new node: select it locally (highlight neighbors)
                    setSelectedNodeId(nodeId);
                    // Load its detail for inspector
                    setInspectorOpen(true);
                    setInspectorTarget("node");
                    setInspectorMode("loading");
                    api.symbols.detail(nodeId).then((detail) => {
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
                      });
                      setInspectorMode("node");
                    }).catch(() => {
                      setInspectorMode("error");
                    });
                    // If clicking a node that's not the center, reload subgraph centered on it
                    if (nodeId !== centerNodeIdRef.current) {
                      handleSelectSymbol(nodeId);
                    }
                  }
                }}
                onSelectFile={handleSelectFile}
                onSelectEdge={(edge) => {
                  handleSelectEdge(edge);
                }}
                onSearchSelect={handleSearchSelect}
                onClearSelection={handleClearSelection}
                layoutPreset={layoutPreset}
                onPresetChange={setLayoutPreset}
              />
            )}
            {activeTab === "search" && (
              <SymbolSearch onSelectSymbol={handleSelectSymbol} />
            )}
            {activeTab === "impact" && (
              <ImpactView onSelectSymbol={handleSelectSymbol} initialSymbolId={pendingImpactSymbolId ?? undefined} onSelectFile={handleSelectFile} />
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
              onSelectSymbol={handleSelectSymbol}
              onToggleGroup={handleToggleGroup}
              onCopyToClipboard={handleCopyToClipboard}
              onShowCallers={handleShowCallers}
              onShowCallees={handleShowCallees}
              onShowImpact={handleShowImpact}
            />
          )}
        </div>
        {libraryOpen && <Library onClose={() => setLibraryOpen(false)} />}
        <Toast toast={toast} onDismiss={dismissToast} />
      </div>
    </>
  );
}
