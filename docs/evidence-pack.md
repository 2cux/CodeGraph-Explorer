# Evidence Pack

Evidence Pack is an optional task-oriented code evidence snapshot. It is **not** the primary interface — MCP tools are. Use it for:

- Human review of task-related code evidence
- Sharing context with non-MCP agents
- Exporting JSON / Markdown as reference material

## What's Included

An Evidence Pack contains:

| Field | Description |
|-------|-------------|
| `task` | The natural language task description |
| `repo` | Repository summary (file count, symbol count, index status) |
| `entry_points` | Candidate entry points with scores and reasons |
| `related_symbols` | Symbols related to the task |
| `call_graph` | Nodes and edges for the relevant call graph |
| `impact` | Impact signals for key symbols |
| `tests` | Related test symbols |
| `selected_context` | Source code snippets (in full mode) |
| `warnings` | Warnings about stale index, low-confidence edges, etc. |
| `pack_notes` | Generation notes (token budget, search strategy) |
| `exports` | Paths to exported Markdown and JSON files |

## What's NOT Included

Evidence Pack explicitly does **not** contain:

- **Reading Plan** — Agents can decide their own reading order
- **Agent Instructions** — No hardcoded advice on how to complete tasks
- **Recommended Context** — No default large source dumps
- **Implementation Plan** — Not a task planner

## Generation

### CLI

```bash
codegraph context "add rate limiting to the login endpoint"

# With options
codegraph context "fix auth bug" --max-tokens 4000 --depth 2 --mode markdown
```

Options:
- `--max-tokens`: Token budget (default: 6000)
- `--depth`: Call-chain traversal depth (default: 2)
- `--include-tests` / `--no-include-tests`
- `--include-code` / `--no-include-code`
- `--mode`: `summary` (default), `full`, or `markdown`

### MCP

```json
{
  "task": "add MFA to login flow",
  "max_tokens": 6000,
  "depth": 2,
  "include_tests": true,
  "mode": "summary"
}
```

## Output Modes

- **summary**: Key insights only — symbol IDs, relation types, impact signals. Default. Designed for agents that will use MCP tools for details.
- **full**: Complete JSON with evidence text, call graphs, and selected context.
- **markdown**: Exports a `.md` file alongside JSON.

## Export Location

```
.codegraph/evidence_packs/<pack_id>.json
.codegraph/evidence_packs/<pack_id>.md
```

## Pipeline

```
task text → intent analysis → keyword extraction → symbol search →
  ranking → call graph traversal → impact analysis → test discovery →
  context selection → warnings → pack notes → export
```

## Design Principle

Evidence Pack is **structured code evidence**, not a task plan. It provides code facts (relationships, confidence, sources) and lets the agent decide how to use them.
