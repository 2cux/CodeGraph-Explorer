"""CodeGraph Enrichment Skill Pack.

Agent-side zero-config LLM enrichment for CodeGraph's code index.
The CodeGraph server never calls LLM APIs directly. Instead:

1. ``codegraph enrich prepare`` generates bounded input from the index
2. The coding agent spawns sub-agents for semantic analysis
3. Sub-agents write batch JSON to ``.codegraph/intermediate/``
4. ``codegraph enrich validate`` checks schema and consistency
5. ``codegraph enrich import`` writes enrichment to SQLite

Existing tools (explain, find, context_pack, coverage_gaps, impact)
automatically read enrichment metadata when available.
"""
