# Multi-Project Setup

CodeGraph Explorer supports two MCP configuration modes:

1. **Global auto-detect** (recommended for multiple projects)
2. **Project-bound** (for a single fixed project)

---

## Global Auto-Detect Configuration (Recommended)

In this mode, the MCP server **auto-detects** the current project by walking up from the working directory to find `.codegraph/`. No `CODEGRAPH_PROJECT_ROOT` env var is set in the MCP config.

### Setup

```bash
codegraph configure all
```

This writes a global MCP config like:

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "C:\\path\\to\\python.exe",
      "args": ["-m", "codegraph.mcp_server"]
    }
  }
}
```

No `CODEGRAPH_PROJECT_ROOT` is set — the MCP server follows the current project's CWD.

### How it works

When the MCP server starts:

1. Checks if `--project-root` was explicitly passed
2. Checks `CODEGRAPH_PROJECT_ROOT` env var (explicit override)
3. Walks up from CWD to find `.codegraph/`
4. Falls back to git root
5. Falls back to CWD

### Initialize each project

Each project needs its own `.codegraph/` index:

```bash
cd project-a
codegraph init

cd ../project-b
codegraph init
```

The MCP server will automatically pick up the correct index based on the working directory.

### Verify

Use `codegraph_repo_status` (MCP tool) or `codegraph doctor` (CLI) to verify which project CodeGraph is querying:

```bash
codegraph doctor
```

Look for section **7. MCP project binding**. It shows whether each MCP config is auto-detect or bound to a fixed project, and warns about mismatches:
```
7. MCP project binding
  [OK]    claude: Global MCP config uses auto-detect project root.
```

---

## Project-Bound Configuration

Use this when you want CodeGraph to **always** query a specific project, regardless of CWD.

### Setup

```bash
codegraph configure all --root /path/to/project
```

Or use project-level config:

```bash
cd your-project
codegraph configure all --project
```

This writes a config with `CODEGRAPH_PROJECT_ROOT`:

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "C:\\path\\to\\python.exe",
      "args": ["-m", "codegraph.mcp_server"],
      "env": {
        "CODEGRAPH_PROJECT_ROOT": "/path/to/project"
      }
    }
  }
}
```

### Important warning

When you configure a fixed project root, the CLI will show:

```
Mode: project-bound
  This MCP config is bound to:
  /path/to/project
  The MCP server will always query this project.
  Use global auto-detect config if you want CodeGraph to follow
  the current project:  codegraph configure all --force
```

Project-level config (`.mcp.json` or `.cursor/mcp.json`) is placed inside the project directory. It only affects MCP clients when working in that directory.

---

## Not Recommended: Global Config with Fixed Root

**Avoid** running `codegraph configure all` from one project directory and then working in another project. This writes the first project's path into the global config, causing the MCP server to always query the wrong index.

### How to detect

Run `codegraph doctor` and check section 7:

```
[warn] claude: Global MCP config is bound to a fixed project:
       D:\project\CodeGraph-Explorer

     Current project (CWD):
       D:\project\other-project

     This may cause CodeGraph MCP to query the wrong index.

     Suggested fix:
       codegraph configure all --force
     or use project-scoped config:
       codegraph configure all --project
```

### Fix

```bash
# Switch to global auto-detect (recommended)
codegraph configure all --force

# Or switch to project-bound for the current project
codegraph configure all --root $(pwd) --force
```

---

## Troubleshooting: "Which project am I querying?"

### Via MCP tool (from your Agent)

Ask your agent:

```
Please call codegraph_repo_status and tell me the project_root and index_path.
```

The response includes:

- `project_root` — the resolved project root CodeGraph is querying
- `index_path` — the `.codegraph/` directory path
- `cwd` — current working directory
- `resolution_method` — how the root was resolved (`env`, `walk_up`, `git_root`, `cwd`, `explicit`)
- `warnings` — includes `fixed_project_root` if `CODEGRAPH_PROJECT_ROOT` is set, `cwd_outside_project` if CWD is under a different project, `index_missing` if no `.codegraph/` found, `index_empty` if 0 symbols

### Via CLI

```bash
codegraph doctor
```

Section 7 shows the MCP project root for each configured target.

```bash
codegraph configure show
```

Shows whether each target has a fixed `Root` or is in `auto-detect` mode.

---

## Summary

| Setup | Config | Best for |
|-------|--------|----------|
| Global auto-detect | `codegraph configure all` | Multiple projects, MCP follows CWD |
| Project-bound | `codegraph configure all --root <path>` | Single fixed project |
| Project-level | `codegraph configure all --project` | Config lives in project, scoped to that project |
| ❌ Global with old fixed root | `codegraph configure all --force` to fix | Run doctor to detect and fix |
