import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type SymbolDetail as SymbolDetailType, type NeighborItem } from "../api";

type ViewMode = "loading" | "detail" | "error";

interface ViewState {
  mode: ViewMode;
  symbol: SymbolDetailType | null;
  neighbors: NeighborItem[];
  error: string;
}

type Tab = "callers" | "callees" | "neighbors";

export default function SymbolDetail() {
  const { nodeId } = useParams<{ nodeId: string }>();
  const decoded = nodeId ? decodeURIComponent(nodeId) : "";

  const [state, setState] = useState<ViewState>({
    mode: "loading",
    symbol: null,
    neighbors: [],
    error: "",
  });
  const [activeTab, setActiveTab] = useState<Tab>("neighbors");
  const [neighborsLoading, setNeighborsLoading] = useState(false);

  useEffect(() => {
    if (!decoded) return;
    let cancelled = false;
    (async () => {
      setState((s) => ({ ...s, mode: "loading", error: "" }));
      try {
        const sym = await api.symbols.detail(decoded);
        if (cancelled) return;
        setState({ mode: "detail", symbol: sym, neighbors: [], error: "" });
        // Fetch neighbors once detail loads
        loadNeighbors(sym.id);
      } catch (e: unknown) {
        if (cancelled) return;
        setState({
          mode: "error",
          symbol: null,
          neighbors: [],
          error: e instanceof Error ? e.message : "Failed to load symbol",
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [decoded]);

  async function loadNeighbors(id: string) {
    setNeighborsLoading(true);
    try {
      const resp = await api.symbols.neighbors(id, 1);
      setState((s) => ({ ...s, neighbors: resp.neighbors }));
    } catch {
      // silently fail
    } finally {
      setNeighborsLoading(false);
    }
  }

  const renderContent = () => {
    switch (state.mode) {
      case "loading":
        return <LoadingSkeleton />;
      case "error":
        return <ErrorState message={state.error} symbolId={decoded} />;
      case "detail":
        return (
          <DetailContent
            symbol={state.symbol!}
            neighbors={state.neighbors}
            neighborsLoading={neighborsLoading}
            activeTab={activeTab}
            onTabChange={setActiveTab}
          />
        );
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <Link
          to="/search"
          className="text-sm text-blue-600 hover:text-blue-800"
        >
          &larr; Back to Search
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 mt-1">Symbol Detail</h1>
      </div>
      {renderContent()}
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────── */

function LoadingSkeleton() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="h-8 bg-gray-200 rounded w-1/3" />
      <div className="h-4 bg-gray-200 rounded w-1/2" />
      <div className="h-32 bg-gray-200 rounded" />
      <div className="h-64 bg-gray-200 rounded" />
    </div>
  );
}

function ErrorState({ message, symbolId }: { message: string; symbolId: string }) {
  const is404 = message.includes("not found") || message.includes("404");
  return (
    <div className="p-6 bg-red-50 border border-red-200 rounded-lg">
      <h2 className="font-semibold text-red-700 mb-1">
        {is404 ? "Symbol Not Found" : "Error Loading Symbol"}
      </h2>
      {is404 ? (
        <p className="text-sm text-red-600">
          No symbol with ID <code className="bg-red-100 px-1 rounded">{symbolId}</code> was found in the graph.
          Make sure the symbol exists and the repo has been indexed.
        </p>
      ) : (
        <p className="text-sm text-red-600">{message}</p>
      )}
    </div>
  );
}

/* ── Detail content ───────────────────────────────────────────── */

const TYPE_COLORS: Record<string, string> = {
  function: "bg-emerald-100 text-emerald-700",
  method: "bg-blue-100 text-blue-700",
  class: "bg-violet-100 text-violet-700",
  module: "bg-gray-100 text-gray-700",
  variable: "bg-amber-100 text-amber-700",
};

function TypeBadge({ type }: { type: string }) {
  const colors = TYPE_COLORS[type] || "bg-gray-100 text-gray-600";
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors}`}>
      {type}
    </span>
  );
}

function DetailContent({
  symbol,
  neighbors,
  neighborsLoading,
  activeTab,
  onTabChange,
}: {
  symbol: SymbolDetailType;
  neighbors: NeighborItem[];
  neighborsLoading: boolean;
  activeTab: Tab;
  onTabChange: (t: Tab) => void;
}) {
  // Neighbors are shown in tabs below; no pre-filtering needed here

  return (
    <div className="space-y-4">
      {/* Header card */}
      <div className="bg-white border rounded-xl p-5 space-y-3">
        <div className="flex items-center gap-3">
          <TypeBadge type={symbol.type} />
          <h2 className="text-xl font-bold font-mono text-gray-900">
            {symbol.name}
          </h2>
        </div>
        {symbol.qualified_name && (
          <p className="text-sm text-gray-500 font-mono">
            {symbol.qualified_name}
          </p>
        )}
        <div className="text-sm text-gray-600 space-y-1">
          <div>
            <span className="font-medium text-gray-700">File:</span>{" "}
            <code className="text-xs">{symbol.file_path}</code>
          </div>
          {symbol.module && (
            <div>
              <span className="font-medium text-gray-700">Module:</span>{" "}
              <code className="text-xs">{symbol.module}</code>
            </div>
          )}
          {symbol.position && (
            <div>
              <span className="font-medium text-gray-700">Lines:</span>{" "}
              {symbol.position.line_start}–{symbol.position.line_end}
            </div>
          )}
          {symbol.visibility && (
            <div>
              <span className="font-medium text-gray-700">Visibility:</span>{" "}
              {symbol.visibility}
            </div>
          )}
          <div>
            <span className="font-medium text-gray-700">ID:</span>{" "}
            <code className="text-[10px] bg-gray-50 px-1 rounded">{symbol.id}</code>
          </div>
        </div>
        {symbol.tags.length > 0 && (
          <div className="flex gap-1.5 flex-wrap">
            {symbol.tags.map((tag) => (
              <span
                key={tag}
                className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Signature */}
      {symbol.signature && (
        <div className="bg-white border rounded-xl p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Signature</h3>
          <pre className="text-sm bg-gray-50 p-3 rounded-lg overflow-x-auto font-mono">
            {symbol.signature}
          </pre>
        </div>
      )}

      {/* Docstring */}
      {symbol.docstring && (
        <div className="bg-white border rounded-xl p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Docstring</h3>
          <pre className="text-sm text-gray-600 whitespace-pre-wrap font-sans">
            {symbol.docstring}
          </pre>
        </div>
      )}

      {/* Code preview */}
      {symbol.code_preview && (
        <div className="bg-white border rounded-xl p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Code Preview</h3>
          <pre className="text-sm bg-gray-50 p-3 rounded-lg overflow-x-auto font-mono">
            {symbol.code_preview}
          </pre>
        </div>
      )}

      {/* Action links */}
      <div className="flex gap-3">
        <Link
          to={`/graph?symbol=${encodeURIComponent(symbol.id)}`}
          className="px-4 py-2 text-sm bg-gray-100 rounded-lg hover:bg-blue-50 hover:text-blue-700 transition-colors"
        >
          View in Graph
        </Link>
        <Link
          to={`/impact?symbol=${encodeURIComponent(symbol.id)}`}
          className="px-4 py-2 text-sm bg-gray-100 rounded-lg hover:bg-blue-50 hover:text-blue-700 transition-colors"
        >
          Analyze Impact
        </Link>
      </div>

      {/* Neighbors / Callers / Callees tabs */}
      <div className="bg-white border rounded-xl">
        <div className="flex border-b">
          {(["neighbors", "callers", "callees"] as Tab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => onTabChange(tab)}
              className={`px-4 py-2.5 text-sm font-medium capitalize transition-colors ${
                activeTab === tab
                  ? "text-blue-600 border-b-2 border-blue-600"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab}
              {tab === "neighbors" && (
                <span className="ml-1.5 text-xs text-gray-400">
                  ({neighbors.length})
                </span>
              )}
            </button>
          ))}
        </div>
        <div className="p-4">
          {neighborsLoading ? (
            <div className="text-sm text-gray-400">Loading...</div>
          ) : (
            <NeighborList items={neighbors} tab={activeTab} />
          )}
        </div>
      </div>
    </div>
  );
}

function NeighborList({
  items,
  tab,
}: {
  items: NeighborItem[];
  tab: string;
}) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-gray-400">
        No {tab} found for this symbol.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <a
          key={`${item.node_id}-${item.edge_type}`}
          href={`/symbol/${encodeURIComponent(item.node_id)}`}
          className="flex items-center gap-2 p-2 rounded hover:bg-gray-50 transition-colors text-sm"
        >
          <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
            {item.edge_type}
          </span>
          <span className="font-mono font-medium text-gray-800">
            {item.name}
          </span>
          {item.confidence !== "unknown" && (
            <span className="text-[10px] text-gray-400 ml-auto">
              conf={item.confidence}
            </span>
          )}
        </a>
      ))}
    </div>
  );
}
