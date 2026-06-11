# Agent Usage Reminder

## Why this matters

MCP tools being available does not mean agents will automatically use them.
Agents often default to grep/glob/read unless usage rules remind them.

CodeGraph provides structured code graph queries (symbol lookup, call chain
traversal, impact analysis, repo overview) that are more token-efficient and
precise than broad grep/glob/read exploration. But if the agent's project
rules don't mention CodeGraph, the agent may never call it — even when the
MCP server is installed, configured, and the index is fresh.

This document explains how to add a lightweight reminder so your coding agent
knows to prefer CodeGraph in appropriate scenarios.

## Recommended reminder

Copy the block below into your target project's agent rule file.

```text
CodeGraph MCP is available for this repository.

For code exploration, bug fixing, refactoring, feature implementation, or
impact analysis, prefer CodeGraph before grep/glob/read-heavy exploration.

Start with `codegraph_build_context_pack` for larger tasks.
Use `codegraph_repo_summary` for repository structure.
Use `codegraph_search_symbols` to find functions, classes, methods, routes,
and entry points.
Use `codegraph_get_neighbors` to inspect symbol relationships.
Use `codegraph_get_callers` / `codegraph_get_callees` instead of grep for
call chains.
Use `codegraph_get_impact` before modifying shared code.

Use `Read` only when exact source text is needed.
```

## Where to put it

| Agent | Target file |
|-------|-------------|
| Claude Code | Target repo `CLAUDE.md` |
| Cursor | Target repo `.cursor/rules/codegraph.mdc` |
| Other agents | Target repo `AGENTS.md` or equivalent rule file |

> **Important**: Put the reminder in the **target project** you want to
> analyze or modify — NOT in the CodeGraph Explorer repository itself.

## How to verify

After adding the reminder to the target project, ask your coding agent:

```text
Did you use CodeGraph MCP in this turn? Which tools did you call?
```

Record:

- Whether `codegraph_build_context_pack` was called
- Whether `codegraph_repo_summary` was called
- Whether `codegraph_search_symbols` was called
- Whether the agent still only used grep/read/glob

If the agent still defaults to grep/read/glob despite the reminder being
present, check that:

1. The MCP server is configured (`codegraph doctor`)
2. The index exists and is fresh (`codegraph status`)
3. The reminder block is in the correct target project file
4. The agent was restarted after adding the reminder

## What this is NOT

- This is NOT a system-level prompt injection mechanism
- This does NOT guarantee the agent will always use CodeGraph
- This does NOT disable grep/read/glob
- This does NOT automatically modify any configuration files
- This is NOT a replacement for MCP tool descriptions

The reminder is advisory — it helps the agent's tool selection but does not
enforce it. The agent still decides which tools to call based on the task.
