import { useState } from "react";
import { api, type ImpactResponse } from "../api";

// Types are imported from "../api" as ImpactResponse

const RISK_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border-red-300",
  high: "bg-orange-100 text-orange-800 border-orange-300",
  medium: "bg-yellow-100 text-yellow-800 border-yellow-300",
  low: "bg-green-100 text-green-800 border-green-300",
  unknown: "bg-gray-100 text-gray-800 border-gray-300",
};

const IMPACT_TYPE_LABELS: Record<string, string> = {
  direct_definition: "Direct Definition",
  upstream_caller: "Upstream Caller",
  downstream_call: "Downstream Call",
  test_coverage: "Test Coverage",
};

function ImpactBadge({ level }: { level: string }) {
  const colors = RISK_COLORS[level] || RISK_COLORS.unknown;
  return (
    <span
      className={`inline-block px-3 py-1 text-sm font-semibold rounded border ${colors}`}
    >
      {level.toUpperCase()}
    </span>
  );
}

export default function ImpactView() {
  const [symbolId, setSymbolId] = useState("");
  const [depth, setDepth] = useState(2);
  const [result, setResult] = useState<ImpactResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function analyzeImpact() {
    if (!symbolId.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const data = await api.symbols.impact(symbolId, depth);
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Impact View</h1>
      <p className="text-gray-600">
        Analyze what is affected when modifying a code symbol.
      </p>

      {/* Search form */}
      <div className="flex gap-3 items-end">
        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Symbol ID
          </label>
          <input
            type="text"
            value={symbolId}
            onChange={(e) => setSymbolId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && analyzeImpact()}
            placeholder="e.g. src/app/api/auth.py::login"
            className="w-full px-3 py-2 border rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Depth
          </label>
          <select
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            className="px-3 py-2 border rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
            <option value={4}>4</option>
            <option value={5}>5</option>
          </select>
        </div>
        <button
          onClick={analyzeImpact}
          disabled={loading || !symbolId.trim()}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Analyzing..." : "Analyze"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700">
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <>
          {/* Summary */}
          <div className="p-4 border rounded bg-white shadow-sm">
            <div className="flex items-center gap-3 mb-2">
              <h2 className="text-lg font-semibold">
                {result.changed_symbol}
              </h2>
              {result.changed_symbol_type && (
                <span className="text-sm text-gray-500">
                  ({result.changed_symbol_type})
                </span>
              )}
            </div>
            {result.risk && (
              <div className="flex items-center gap-2">
                <ImpactBadge level={result.risk.level} />
                <span className="text-sm text-gray-600">
                  {result.affected_symbols.length} affected symbols,{" "}
                  {result.affected_files.length} affected files
                </span>
              </div>
            )}
          </div>

          {/* Risk Reasons */}
          {result.risk && result.risk.reasons.length > 0 && (
            <div className="p-4 border rounded bg-white shadow-sm">
              <h3 className="font-semibold mb-2">Risk Factors</h3>
              <ul className="space-y-1">
                {result.risk.reasons.map((reason, i) => (
                  <li key={i} className="text-sm text-gray-700 flex gap-2">
                    <span className="text-blue-500 mt-0.5">&#8226;</span>
                    {reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Warnings */}
          {result.warnings.length > 0 && (
            <div className="p-3 border border-yellow-300 rounded bg-yellow-50">
              <h3 className="font-semibold text-yellow-800 mb-1">Warnings</h3>
              {result.warnings.map((w, i) => (
                <p key={i} className="text-sm text-yellow-700">
                  {w}
                </p>
              ))}
            </div>
          )}

          {/* Recommendations */}
          {result.recommendations.length > 0 && (
            <div className="p-4 border rounded bg-white shadow-sm">
              <h3 className="font-semibold mb-2">Recommendations</h3>
              <ol className="space-y-2">
                {result.recommendations.map((rec) => (
                  <li key={rec.step} className="text-sm text-gray-700 flex gap-2">
                    <span className="font-medium text-blue-600 min-w-[1.5rem]">
                      {rec.step}.
                    </span>
                    {rec.message}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Affected Symbols */}
          {result.affected_symbols.length > 0 && (
            <div className="p-4 border rounded bg-white shadow-sm">
              <h3 className="font-semibold mb-3">
                Affected Symbols ({result.affected_symbols.length})
              </h3>
              <div className="space-y-2">
                {result.affected_symbols.map((sym, i) => (
                  <div
                    key={i}
                    className="p-3 border rounded text-sm hover:bg-gray-50"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-gray-100">
                        D{sym.distance}
                      </span>
                      <span className="font-medium">{sym.symbol_id}</span>
                      {sym.type && (
                        <span className="text-gray-400">({sym.type})</span>
                      )}
                      <span className="ml-auto text-gray-400 text-xs">
                        conf={sym.confidence.toFixed(2)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                      <span
                        className={`px-1.5 py-0.5 rounded ${
                          sym.impact_type === "test_coverage"
                            ? "bg-purple-100 text-purple-700"
                            : sym.impact_type === "direct_definition"
                              ? "bg-blue-100 text-blue-700"
                              : sym.impact_type === "upstream_caller"
                                ? "bg-amber-100 text-amber-700"
                                : "bg-gray-100"
                        }`}
                      >
                        {IMPACT_TYPE_LABELS[sym.impact_type] || sym.impact_type}
                      </span>
                      <span>{sym.reason}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Affected Files */}
          {result.affected_files.length > 0 && (
            <div className="p-4 border rounded bg-white shadow-sm">
              <h3 className="font-semibold mb-3">
                Affected Files ({result.affected_files.length})
              </h3>
              <div className="space-y-2">
                {result.affected_files.map((f, i) => (
                  <div
                    key={i}
                    className={`p-3 border rounded text-sm ${
                      f.priority === "high"
                        ? "border-red-200 bg-red-50"
                        : "hover:bg-gray-50"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`font-mono text-xs px-1.5 py-0.5 rounded ${
                          f.priority === "high"
                            ? "bg-red-100 text-red-700"
                            : "bg-gray-100"
                        }`}
                      >
                        {f.priority.toUpperCase()}
                      </span>
                      <span className="font-medium">{f.file_path}</span>
                    </div>
                    <p className="text-xs text-gray-500">{f.reason}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
