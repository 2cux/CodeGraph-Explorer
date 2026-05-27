import { useState } from "react";
import { api, type ContextPackResponse } from "../api";

/* ── Types matching the API response ─────────────────────────── */

interface EntryPoint {
  symbol_id: string;
  type: string;
  name: string;
  file_path: string;
  location: { line_start?: number; line_end?: number } | null;
  signature: string | null;
  reason: string;
  score: number;
  match_sources: string[];
}

interface RelatedSymbol {
  symbol_id: string;
  relation: string;
  distance: number;
  direction: string;
  reason: string;
  importance: string;
  confidence: number;
}

interface CallGraphNode {
  id: string;
  label: string;
  type: string;
}

interface CallGraphEdge {
  source: string;
  target: string;
  type: string;
  confidence: number;
}

interface CallGraph {
  center: string;
  depth: number;
  nodes: CallGraphNode[];
  edges: CallGraphEdge[];
}

interface AffectedSymbol {
  symbol_id: string;
  reason: string;
  impact_type: string;
  distance: number;
  confidence: number;
}

interface AffectedFile {
  file_path: string;
  reason: string;
  priority: string;
}

interface Risk {
  level: string;
  reasons: string[];
}

interface Impact {
  changed_symbol: string;
  affected_symbols: AffectedSymbol[];
  affected_files: AffectedFile[];
  risk: Risk;
}

interface ContextItem {
  context_id: string;
  type: string;
  symbol_id: string;
  file_path: string;
  line_start: number;
  line_end: number;
  priority: string;
  reason: string;
  content: string;
  estimated_tokens: number;
}

interface ReadingStep {
  step: number;
  action: string;
  target: string;
  reason: string;
}

interface AgentInstructions {
  summary: string;
  recommended_strategy: string[];
  warnings: string[];
}

interface ContextPack {
  pack_id: string;
  task: { raw_request: string; intent: string; keywords: string[] };
  entry_points: EntryPoint[];
  related_symbols: RelatedSymbol[];
  call_graph: CallGraph;
  impact: Impact;
  recommended_context: ContextItem[];
  reading_plan: ReadingStep[];
  agent_instructions: AgentInstructions;
}

type ViewMode = "initial" | "loading" | "pack" | "error";

interface ViewState {
  mode: ViewMode;
  pack: ContextPackResponse | null;
  error: string;
}

/* ── Main component ──────────────────────────────────────────── */

export default function ContextPackViewer() {
  const [task, setTask] = useState("");
  const [maxTokens, setMaxTokens] = useState(6000);
  const [includeTests, setIncludeTests] = useState(true);
  const [depth, setDepth] = useState(2);
  const [state, setState] = useState<ViewState>({
    mode: "initial",
    pack: null,
    error: "",
  });

  async function generate() {
    if (!task.trim()) return;
    setState({ mode: "loading", pack: null, error: "" });
    try {
      const data = await api.context.generate(task, maxTokens, includeTests, depth);
      setState({ mode: "pack", pack: data, error: "" });
    } catch (e: unknown) {
      setState({
        mode: "error",
        pack: null,
        error: e instanceof Error ? e.message : "Generation failed",
      });
    }
  }

  const renderContent = () => {
    switch (state.mode) {
      case "initial":
        return <InitialState />;
      case "loading":
        return <LoadingState task={task} />;
      case "error":
        return <ErrorState message={state.error} />;
      case "pack":
        return <PackContent pack={state.pack!} />;
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Context Pack Viewer</h1>
        <p className="text-gray-500 text-sm mt-1">
          Generate a task-aware code context pack for AI coding agents.
        </p>
      </div>

      {/* Form */}
      <div className="bg-white border rounded-xl p-4 space-y-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Task Description
          </label>
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="e.g. Add MFA support to the login flow"
            rows={3}
            className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>
        <div className="flex gap-4 flex-wrap">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Max Tokens
            </label>
            <select
              value={maxTokens}
              onChange={(e) => setMaxTokens(Number(e.target.value))}
              className="px-3 py-2 border rounded-lg bg-white text-sm"
            >
              <option value={3000}>3,000</option>
              <option value={6000}>6,000</option>
              <option value={12000}>12,000</option>
              <option value={24000}>24,000</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Depth
            </label>
            <select
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              className="px-3 py-2 border rounded-lg bg-white text-sm"
            >
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
            </select>
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={includeTests}
                onChange={(e) => setIncludeTests(e.target.checked)}
                className="rounded"
              />
              Include tests
            </label>
          </div>
          <div className="flex items-end">
            <button
              onClick={generate}
              disabled={state.mode === "loading" || !task.trim()}
              className="px-5 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {state.mode === "loading" ? "Generating..." : "Generate"}
            </button>
          </div>
        </div>
      </div>

      {renderContent()}
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────── */

function InitialState() {
  return (
    <div className="text-center py-16 border-2 border-dashed border-gray-300 rounded-xl">
      <div className="text-5xl text-gray-300 mb-4">⊞</div>
      <h2 className="text-lg font-semibold text-gray-500">Describe your task</h2>
      <p className="text-sm text-gray-400 mt-1">
        Enter a natural language task description to generate a Context Pack.
      </p>
    </div>
  );
}

function LoadingState({ task }: { task: string }) {
  return (
    <div className="p-6 border rounded-xl bg-white space-y-4">
      <div className="flex items-center gap-3">
        <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm text-gray-600">
          Analyzing codebase for: <strong>"{task}"</strong>
        </p>
      </div>
      <div className="animate-pulse space-y-2">
        <div className="h-4 bg-gray-100 rounded w-3/4" />
        <div className="h-4 bg-gray-100 rounded w-1/2" />
        <div className="h-4 bg-gray-100 rounded w-5/6" />
        <div className="h-4 bg-gray-100 rounded w-2/3" />
      </div>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
      {message}
    </div>
  );
}

/* ── Pack content ────────────────────────────────────────────── */

function PackContent({ pack }: { pack: ContextPack }) {
  return (
    <div className="space-y-4">
      {/* Pack header */}
      <div className="bg-white border rounded-xl p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-semibold text-gray-800">
              Context Pack: <span className="font-mono text-sm">{pack.pack_id}</span>
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Intent: {pack.task.intent} &middot; Keywords:{" "}
              {pack.task.keywords.join(", ")}
            </p>
          </div>
        </div>
      </div>

      {/* Agent instructions */}
      <Section title="Agent Instructions">
        <p className="text-sm text-gray-700 mb-2">{pack.agent_instructions.summary}</p>
        {pack.agent_instructions.recommended_strategy.length > 0 && (
          <div className="mb-2">
            <p className="text-xs font-medium text-gray-600 mb-1">Recommended Strategy:</p>
            <ul className="space-y-1">
              {pack.agent_instructions.recommended_strategy.map((s, i) => (
                <li key={i} className="text-sm text-gray-700 flex gap-2">
                  <span className="text-blue-500">{i + 1}.</span>
                  {s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {pack.agent_instructions.warnings.length > 0 && (
          <div className="p-2 bg-yellow-50 border border-yellow-200 rounded text-xs text-yellow-800">
            {pack.agent_instructions.warnings.map((w, i) => (
              <p key={i}>{w}</p>
            ))}
          </div>
        )}
      </Section>

      {/* Entry points */}
      <Section title={`Entry Points (${pack.entry_points.length})`}>
        {pack.entry_points.length === 0 ? (
          <EmptyText />
        ) : (
          <div className="space-y-2">
            {pack.entry_points.map((ep, i) => (
              <SymbolCard key={i} symbolId={ep.symbol_id} name={ep.name} type={ep.type} filePath={ep.file_path}>
                <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                  <span>score: {ep.score.toFixed(2)}</span>
                  <span>{ep.reason}</span>
                </div>
                {ep.match_sources.length > 0 && (
                  <div className="flex gap-1 mt-1">
                    {ep.match_sources.map((s) => (
                      <span
                        key={s}
                        className="px-1 py-0.5 bg-gray-100 rounded text-[10px] text-gray-500"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                )}
              </SymbolCard>
            ))}
          </div>
        )}
      </Section>

      {/* Related symbols */}
      <Section title={`Related Symbols (${pack.related_symbols.length})`}>
        {pack.related_symbols.length === 0 ? (
          <EmptyText />
        ) : (
          <div className="space-y-2">
            {pack.related_symbols.map((rs, i) => (
              <SymbolCard key={i} symbolId={rs.symbol_id} name={rs.symbol_id} type={rs.relation} filePath="">
                <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                  <span className={`px-1 py-0.5 rounded ${
                    rs.importance === "high" ? "bg-red-100 text-red-700" : rs.importance === "critical" ? "bg-red-200 text-red-800" : "bg-gray-100"
                  }`}>
                    {rs.importance}
                  </span>
                  <span>D{rs.distance} {rs.direction}</span>
                  <span>conf={rs.confidence.toFixed(2)}</span>
                  <span>{rs.reason}</span>
                </div>
              </SymbolCard>
            ))}
          </div>
        )}
      </Section>

      {/* Call graph */}
      <Section title="Call Graph">
        {pack.call_graph.nodes.length === 0 ? (
          <EmptyText />
        ) : (
          <div className="text-sm text-gray-600">
            <p className="mb-2">
              Center: <code className="bg-gray-100 px-1 rounded">{pack.call_graph.center}</code>
              {" "}&middot; Depth: {pack.call_graph.depth}
              {" "}&middot; {pack.call_graph.nodes.length} nodes, {pack.call_graph.edges.length} edges
            </p>
            {pack.call_graph.edges.length > 0 && (
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {pack.call_graph.edges.map((e, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs font-mono text-gray-500">
                    <span>{e.source}</span>
                    <span className="text-gray-300">→</span>
                    <span>{e.target}</span>
                    <span className="text-[10px] text-gray-400">({e.type}, conf={e.confidence.toFixed(2)})</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Section>

      {/* Impact */}
      <Section title="Impact Analysis">
        {!pack.impact.changed_symbol ? (
          <EmptyText />
        ) : (
          <div className="space-y-2 text-sm">
            <p>
              Changing: <code className="bg-gray-100 px-1 rounded">{pack.impact.changed_symbol}</code>
            </p>
            <div className="flex items-center gap-2">
              <RiskBadge level={pack.impact.risk.level} />
              <span className="text-gray-500">
                {pack.impact.affected_symbols.length} symbols, {pack.impact.affected_files.length} files
              </span>
            </div>
            {pack.impact.risk.reasons.length > 0 && (
              <ul className="space-y-1">
                {pack.impact.risk.reasons.map((r, i) => (
                  <li key={i} className="text-xs text-gray-600 flex gap-1">
                    <span className="text-blue-500">&bull;</span> {r}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Section>

      {/* Reading plan */}
      <Section title="Reading Plan">
        {pack.reading_plan.length === 0 ? (
          <EmptyText />
        ) : (
          <ol className="space-y-2">
            {pack.reading_plan.map((step) => (
              <li key={step.step} className="flex gap-3 text-sm">
                <span className="font-medium text-blue-600 min-w-[1.5rem]">
                  {step.step}.
                </span>
                <div>
                  <span className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded">
                    {step.action}
                  </span>
                  <code className="ml-2 text-gray-800">{step.target}</code>
                  {step.reason && (
                    <p className="text-xs text-gray-500 mt-0.5">{step.reason}</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Section>

      {/* Recommended context */}
      {pack.recommended_context.length > 0 && (
        <Section title={`Recommended Context (${pack.recommended_context.length})`}>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {pack.recommended_context.map((rc, i) => (
              <div key={i} className="p-2 border rounded text-sm hover:bg-gray-50">
                <div className="flex items-center gap-2">
                  <PriorityBadge priority={rc.priority} />
                  <code className="text-xs">{rc.file_path}:{rc.line_start}–{rc.line_end}</code>
                  <span className="text-xs text-gray-400 ml-auto">~{rc.estimated_tokens} tokens</span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5">{rc.reason}</p>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border rounded-xl p-4">
      <h3 className="font-semibold text-gray-800 mb-3 text-sm">{title}</h3>
      {children}
    </div>
  );
}

function EmptyText() {
  return <p className="text-sm text-gray-400 italic">None</p>;
}

function SymbolCard({
  symbolId,
  name,
  type,
  filePath,
  children,
}: {
  symbolId: string;
  name: string;
  type: string;
  filePath: string;
  children?: React.ReactNode;
}) {
  return (
    <a
      href={`/symbol/${encodeURIComponent(symbolId)}`}
      className="block p-2 border rounded hover:bg-gray-50 transition-colors"
    >
      <div className="flex items-center gap-2">
        <span className="px-1.5 py-0.5 bg-gray-100 rounded text-xs text-gray-600">
          {type}
        </span>
        <span className="font-mono text-sm font-medium">{name}</span>
        {filePath && <span className="text-xs text-gray-400 ml-auto">{filePath}</span>}
      </div>
      {children}
    </a>
  );
}

const RISK_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-800",
  high: "bg-orange-100 text-orange-800",
  medium: "bg-yellow-100 text-yellow-800",
  low: "bg-green-100 text-green-800",
};

function RiskBadge({ level }: { level: string }) {
  const colors = RISK_COLORS[level] || "bg-gray-100 text-gray-600";
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors}`}>
      {level.toUpperCase()}
    </span>
  );
}

const PRIORITY_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-blue-100 text-blue-700",
  low: "bg-gray-100 text-gray-600",
};

function PriorityBadge({ priority }: { priority: string }) {
  const colors = PRIORITY_COLORS[priority] || "bg-gray-100 text-gray-600";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${colors}`}>
      {priority}
    </span>
  );
}
