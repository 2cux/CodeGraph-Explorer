# CodeGraph Enrich Workflow

Agent-side zero-config semantic enrichment for the CodeGraph index.
This workflow orchestrates LLM-powered analysis WITHOUT requiring
any API keys on the CodeGraph server side — all LLM calls use your
coding agent's own model.

## Rules

1. Always start with `codegraph enrich status` to check current state
2. Run `codegraph enrich prepare` to generate bounded input
3. Spawn sub-agents (`codegraph-file-enricher`, `codegraph-symbol-enricher`)
   to analyze files and symbols in parallel batches
4. Merge sub-agent outputs into `.codegraph/intermediate/enrich_output.json`
5. Run `codegraph enrich validate` to check output correctness
6. If validation fails, spawn `codegraph-enrich-reviewer` to fix errors
7. Run `codegraph enrich import` to write enrichment into SQLite
8. Run `codegraph enrich status` to confirm import

## Expected Flow

1. `codegraph enrich status` — check if enrichment already exists
2. `codegraph enrich prepare --max-files 100` — generate input
3. Read `.codegraph/intermediate/enrich_input.json`
4. For each batch of 10-20 files, spawn a `codegraph-file-enricher` agent
   and a `codegraph-symbol-enricher` agent in parallel
5. Collect all agent outputs and merge into one JSON
6. Write merged output to `.codegraph/intermediate/enrich_output.json`
7. `codegraph enrich validate` — check output
8. If errors: spawn `codegraph-enrich-reviewer` to fix, re-validate
9. `codegraph enrich import` — write to SQLite
10. `codegraph enrich status` — confirm counts

## Output Format

The enrichment output must conform to `codegraph_enrichment_v1` schema:

```json
{
  "schema_version": "codegraph_enrichment_v1",
  "enriched_at": "ISO 8601 timestamp",
  "files": [{ "path": "...", "summary": "...", "tags": [...], "role": "...", "confidence": "medium", "evidence": [...] }],
  "symbols": [{ "symbol": "...", "file": "...", "summary": "...", "responsibilities": [...], "edge_cases": [...], "test_relevance": "...", "confidence": "medium", "evidence": [...] }]
}
```

## Constraints (from prepare output)

- `max_summary_chars`: 500
- `max_tags`: 10
- `relative_paths_only`: true
- `evidence_required`: true
- `confidence_values`: ["high", "medium", "low"]

## Anti-Patterns

- ❌ Do NOT call external LLM APIs from CodeGraph server code
- ❌ Do NOT hardcode any API keys or provider configs
- ❌ Do NOT create symbols or files that don't exist in the index
- ❌ Do NOT use absolute paths in file/symbol references
- ❌ Do NOT skip the validate step before import
- ❌ Do NOT embed full source code in evidence — use line ranges only
