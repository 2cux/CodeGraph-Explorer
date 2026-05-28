import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, type SymbolDetail as SymbolDetailType, type NeighborItem, type CallerCalleeItem } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { InspectorSection } from "../components/Section";
import { SkeletonLine, SkeletonBlock } from "../components/Skeleton";
import { IconArrow } from "../components/icons";

type ViewMode = "loading" | "detail" | "error";
type Tab = "callers" | "callees" | "neighbors";

const KIND_COLORS: Record<string, string> = {
  function: "var(--cg-accent)",
  method: "#A78BFA",
  class: "var(--cg-success)",
  module: "var(--cg-text-secondary)",
  variable: "var(--cg-warning)",
  test: "#4ADE80",
  file: "var(--cg-text-secondary)",
};

const KIND_BG: Record<string, string> = {
  function: "var(--cg-accent-alpha)",
  method: "color-mix(in srgb, #A78BFA 14%, transparent)",
  class: "var(--cg-success-alpha)",
  module: "color-mix(in srgb, var(--cg-text-secondary) 14%, transparent)",
  variable: "var(--cg-warning-alpha)",
  test: "color-mix(in srgb, #4ADE80 14%, transparent)",
  file: "color-mix(in srgb, var(--cg-text-secondary) 14%, transparent)",
};

export default function SymbolDetail() {
  const navigate = useNavigate();
  const { nodeId } = useParams<{ nodeId: string }>();
  const decoded = nodeId ? decodeURIComponent(nodeId) : "";

  const [state, setState] = useState<{ mode: ViewMode; symbol: SymbolDetailType | null; error: string }>({
    mode: "loading", symbol: null, error: "",
  });
  const [activeTab, setActiveTab] = useState<Tab>("neighbors");
  const [neighbors, setNeighbors] = useState<NeighborItem[]>([]);
  const [callers, setCallers] = useState<CallerCalleeItem[]>([]);
  const [callees, setCallees] = useState<CallerCalleeItem[]>([]);
  const [neighborsLoading, setNeighborsLoading] = useState(false);
  const [callersLoading, setCallersLoading] = useState(false);
  const [calleesLoading, setCalleesLoading] = useState(false);

  useEffect(() => {
    if (!decoded) return;
    let cancelled = false;
    (async () => {
      setState({ mode: "loading", symbol: null, error: "" });
      try {
        const sym = await api.symbols.detail(decoded);
        if (cancelled) return;
        setState({ mode: "detail", symbol: sym, error: "" });
        loadNeighbors(sym.id);
      } catch (e: unknown) {
        if (cancelled) return;
        setState({ mode: "error", symbol: null, error: e instanceof Error ? e.message : "Failed to load symbol" });
      }
    })();
    return () => { cancelled = true; };
  }, [decoded]);

  async function loadNeighbors(id: string) {
    setNeighborsLoading(true);
    try { const resp = await api.symbols.neighbors(id, 1); setNeighbors(resp.neighbors); }
    catch { /* silent */ }
    finally { setNeighborsLoading(false); }
  }
  async function loadCallers(id: string) {
    setCallersLoading(true);
    try { const resp = await api.symbols.callers(id); setCallers(resp.callers ?? []); }
    catch { setCallers([]); }
    finally { setCallersLoading(false); }
  }
  async function loadCallees(id: string) {
    setCalleesLoading(true);
    try { const resp = await api.symbols.callees(id); setCallees(resp.callees ?? []); }
    catch { setCallees([]); }
    finally { setCalleesLoading(false); }
  }

  function handleTabChange(tab: Tab) {
    setActiveTab(tab);
    if (tab === "callers" && callers.length === 0 && !callersLoading && state.symbol) loadCallers(state.symbol.id);
    if (tab === "callees" && callees.length === 0 && !calleesLoading && state.symbol) loadCallees(state.symbol.id);
    if (tab === "neighbors" && neighbors.length === 0 && !neighborsLoading && state.symbol) loadNeighbors(state.symbol.id);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="flex items-center" style={{ gap: 8 }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            background: "transparent", border: "none", color: "var(--cg-text-secondary)",
            cursor: "pointer", display: "flex", alignItems: "center", padding: 0, fontFamily: "inherit",
            fontSize: 11,
          }}
        >
          <IconArrow size={10} style={{ transform: "rotate(180deg)" }} />
          <span style={{ marginLeft: 4 }}>Back</span>
        </button>
      </div>

      {state.mode === "loading" && <LoadingSkeleton />}
      {state.mode === "error" && <ErrorState message={state.error} symbolId={decoded} />}
      {state.mode === "detail" && (
        <DetailContent
          symbol={state.symbol!}
          neighbors={neighbors} neighborsLoading={neighborsLoading}
          callers={callers} callersLoading={callersLoading}
          callees={callees} calleesLoading={calleesLoading}
          activeTab={activeTab} onTabChange={handleTabChange}
          onNavigate={navigate}
        />
      )}
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <SkeletonLine width={48} height={16} radius={2} />
        <SkeletonLine width={160} height={14} radius={2} />
      </div>
      <SkeletonLine width={200} height={10} radius={2} />
      <SkeletonBlock height={60} />
      <SkeletonBlock height={120} />
    </div>
  );
}

function ErrorState({ message, symbolId }: { message: string; symbolId: string }) {
  const is404 = message.includes("not found") || message.includes("404");
  return (
    <div style={{
      padding: "10px 12px",
      background: "var(--cg-error-alpha)",
      border: "1px solid color-mix(in srgb, var(--cg-error) 30%, transparent)",
      borderRadius: 6,
    }}>
      <div style={{ fontSize: 11, fontWeight: 500, color: "var(--cg-error)", marginBottom: 4 }}>
        {is404 ? "Symbol Not Found" : "Error Loading Symbol"}
      </div>
      {is404 ? (
        <p style={{ fontSize: 11, color: "var(--cg-text-secondary)", margin: 0 }}>
          No symbol with ID <span className="cg-mono" style={{ background: "var(--cg-bg-subtle)", padding: "1px 4px", borderRadius: 2 }}>{symbolId}</span> was found.
        </p>
      ) : (
        <p style={{ fontSize: 11, color: "var(--cg-text-secondary)", margin: 0 }}>{message}</p>
      )}
    </div>
  );
}

function DetailContent({
  symbol, neighbors, neighborsLoading, callers, callersLoading, callees, calleesLoading,
  activeTab, onTabChange, onNavigate,
}: {
  symbol: SymbolDetailType;
  neighbors: NeighborItem[]; neighborsLoading: boolean;
  callers: CallerCalleeItem[]; callersLoading: boolean;
  callees: CallerCalleeItem[]; calleesLoading: boolean;
  activeTab: Tab; onTabChange: (t: Tab) => void;
  onNavigate: (to: string) => void;
}) {
  const kindColor = KIND_COLORS[symbol.type] || "var(--cg-text-secondary)";
  const kindBg = KIND_BG[symbol.type] || "color-mix(in srgb, var(--cg-text-secondary) 14%, transparent)";

  return (
    <>
      {/* Header card */}
      <div style={{
        padding: 16,
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 6,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}>
        <div className="flex items-center" style={{ gap: 8 }}>
          <span className="cg-mono" style={{ fontSize: 10, color: kindColor, background: kindBg, padding: "1px 6px", borderRadius: 2, letterSpacing: 0.5 }}>
            {symbol.type.toUpperCase()}
          </span>
          <h2 className="cg-mono" style={{ fontSize: 14, fontWeight: 500, color: "var(--cg-text-primary)", margin: 0 }}>
            {symbol.name}
          </h2>
        </div>
        {symbol.qualified_name && (
          <p className="cg-mono" style={{ fontSize: 11, color: "var(--cg-text-secondary)", margin: 0 }}>
            {symbol.qualified_name}
          </p>
        )}
        <div style={{ fontSize: 11, color: "var(--cg-text-secondary)", display: "flex", flexDirection: "column", gap: 4 }}>
          <div><span style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>File:</span> <span className="cg-mono" style={{ fontSize: 10 }}>{symbol.file_path}</span></div>
          {symbol.module && <div><span style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>Module:</span> <span className="cg-mono" style={{ fontSize: 10 }}>{symbol.module}</span></div>}
          {symbol.position && <div><span style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>Lines:</span> {symbol.position.line_start}–{symbol.position.line_end}</div>}
          {symbol.visibility && <div><span style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>Visibility:</span> {symbol.visibility}</div>}
          <div><span style={{ fontWeight: 500, color: "var(--cg-text-primary)" }}>ID:</span> <span className="cg-mono" style={{ fontSize: 9, color: "var(--cg-text-muted)" }}>{symbol.id}</span></div>
        </div>
        {symbol.tags.length > 0 && (
          <div className="flex items-center" style={{ gap: 4, flexWrap: "wrap" }}>
            {symbol.tags.map((tag) => (
              <span key={tag} className="cg-mono" style={{ fontSize: 9, padding: "1px 5px", background: "var(--cg-bg-subtle)", color: "var(--cg-text-muted)", borderRadius: 2 }}>
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Signature */}
      {symbol.signature && (
        <div style={{ padding: 14, background: "var(--cg-bg-panel)", border: "1px solid var(--cg-border)", borderRadius: 6 }}>
          <InspectorSection title="Signature" first>
            <CodeBlock lines={symbol.signature.split("\n")} />
          </InspectorSection>
        </div>
      )}

      {/* Docstring */}
      {symbol.docstring && (
        <div style={{ padding: 14, background: "var(--cg-bg-panel)", border: "1px solid var(--cg-border)", borderRadius: 6 }}>
          <InspectorSection title="Docstring" first>
            <p style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: "var(--cg-text-secondary)", whiteSpace: "pre-wrap" }}>
              {symbol.docstring}
            </p>
          </InspectorSection>
        </div>
      )}

      {/* Code preview */}
      {symbol.code_preview && (
        <div style={{ padding: 14, background: "var(--cg-bg-panel)", border: "1px solid var(--cg-border)", borderRadius: 6 }}>
          <InspectorSection title="Code Preview" first>
            <CodeBlock lines={symbol.code_preview.split("\n")} />
          </InspectorSection>
        </div>
      )}

      {/* Action links */}
      <div className="flex items-center" style={{ gap: 8 }}>
        <ActionBtn onClick={() => onNavigate(`/graph?symbol=${encodeURIComponent(symbol.id)}`)}>
          View in Graph
        </ActionBtn>
        <ActionBtn onClick={() => onNavigate(`/impact?symbol=${encodeURIComponent(symbol.id)}`)}>
          Analyze Impact
        </ActionBtn>
      </div>

      {/* Tabs: neighbors / callers / callees */}
      <div style={{
        background: "var(--cg-bg-panel)",
        border: "1px solid var(--cg-border)",
        borderRadius: 6,
        overflow: "hidden",
      }}>
        <div className="flex items-center" style={{ borderBottom: "1px solid var(--cg-border)", height: 30 }}>
          {(["neighbors", "callers", "callees"] as Tab[]).map((tab) => {
            const count = tab === "neighbors" ? neighbors.length : tab === "callers" ? callers.length : callees.length;
            const isActive = activeTab === tab;
            return (
              <button
                key={tab}
                onClick={() => onTabChange(tab)}
                style={{
                  height: "100%", padding: "0 12px",
                  border: "none", borderBottom: isActive ? "2px solid var(--cg-accent)" : "2px solid transparent",
                  background: "transparent",
                  color: isActive ? "var(--cg-text-primary)" : "var(--cg-text-secondary)",
                  fontSize: 11, cursor: "pointer", fontFamily: "inherit",
                  transition: "color 120ms ease",
                }}
              >
                {tab} <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>({count})</span>
              </button>
            );
          })}
        </div>
        <div style={{ padding: 12 }}>
          <TabContent
            tab={activeTab}
            neighbors={neighbors} neighborsLoading={neighborsLoading}
            callers={callers} callersLoading={callersLoading}
            callees={callees} calleesLoading={calleesLoading}
            onSelect={(id) => onNavigate(`/symbol/${encodeURIComponent(id)}`)}
          />
        </div>
      </div>
    </>
  );
}

function ActionBtn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        height: 26, padding: "0 10px",
        background: "transparent", border: "1px solid var(--cg-border)",
        borderRadius: 4, color: "var(--cg-text-primary)", fontSize: 11,
        cursor: "pointer", fontFamily: "inherit",
        transition: "background 120ms ease, border-color 120ms ease",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--cg-bg-subtle)"; e.currentTarget.style.borderColor = "var(--cg-border-hover)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.borderColor = "var(--cg-border)"; }}
    >
      {children}
    </button>
  );
}

function TabContent({
  tab, neighbors, neighborsLoading, callers, callersLoading, callees, calleesLoading, onSelect,
}: {
  tab: Tab;
  neighbors: NeighborItem[]; neighborsLoading: boolean;
  callers: CallerCalleeItem[]; callersLoading: boolean;
  callees: CallerCalleeItem[]; calleesLoading: boolean;
  onSelect: (id: string) => void;
}) {
  const isLoading =
    (tab === "neighbors" && neighborsLoading) ||
    (tab === "callers" && callersLoading) ||
    (tab === "callees" && calleesLoading);

  if (isLoading) return <div style={{ fontSize: 11, color: "var(--cg-text-muted)" }}>Loading...</div>;

  const items: (NeighborItem | CallerCalleeItem)[] =
    tab === "neighbors" ? neighbors : tab === "callers" ? callers : callees;

  if (items.length === 0) return <p style={{ fontSize: 11, color: "var(--cg-text-muted)", margin: 0 }}>No {tab} found.</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {items.map((item) => {
        const edgeType = "edge_type" in item ? item.edge_type : "";
        const confidence = "confidence" in item ? item.confidence : undefined;
        return (
          <div
            key={`${item.node_id}-${edgeType}`}
            onClick={() => onSelect(item.node_id)}
            style={{
              padding: "6px 8px", borderRadius: 4, cursor: "pointer",
              fontSize: 11, transition: "background 120ms ease",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--cg-bg-subtle)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            <div className="flex items-center" style={{ gap: 6 }}>
              <span style={{ fontSize: 9, padding: "1px 4px", background: "var(--cg-bg-subtle)", color: "var(--cg-text-muted)", borderRadius: 2 }}>
                {edgeType || "rel"}
              </span>
              <span className="cg-mono" style={{ color: "var(--cg-text-primary)", fontWeight: 500 }}>
                {item.name}
              </span>
              <span style={{ flex: 1 }} />
              {confidence !== undefined && confidence !== "unknown" && (
                <span className="cg-mono" style={{ fontSize: 10, color: "var(--cg-text-muted)" }}>
                  conf={confidence}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
