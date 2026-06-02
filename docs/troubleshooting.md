# Troubleshooting

Common issues and their fixes when using CodeGraph Explorer.

## MCP Shows "Error" in Claude Code / Cursor

Run the doctor first:

```bash
codegraph doctor
```

`doctor` checks all components and identifies the specific issue.

### 1. No index found

```
No CodeGraph index found.
Run: codegraph init
```

```bash
cd your-project
codegraph init
```

### 2. MCP config path is wrong

If project paths changed or config is stale:

```bash
codegraph configure all --force
```

Check current config:

```bash
codegraph configure show
```

### 3. Command not found in MCP config

From v0.1.1, `codegraph configure` writes the absolute Python interpreter path (e.g. `C:\...\python.exe -m codegraph.mcp_server`), avoiding PATH issues.

If old config uses `codegraph` command and it's not in PATH:

```bash
codegraph configure all --force
```

Verify:

```bash
codegraph --help
python -m codegraph.mcp_server --check
codegraph serve --mcp --check
```

### 4. MCP config not reloaded

MCP config is loaded at editor startup. After modifying `~/.claude.json` or `~/.cursor/mcp.json`, restart the editor.

### 5. Index files incomplete

If `.codegraph/` exists but is missing critical files:

```bash
codegraph init --force
```

### 6. "No .codegraph directory found"

The `CODEGRAPH_PROJECT_ROOT` in MCP config doesn't point to the right project:

```bash
cd your-project
codegraph init
codegraph configure cursor --force
```

Restart the editor afterward.

### 7. Index is stale

If source files changed but the index wasn't updated:

```bash
# Incremental update (recommended)
codegraph init --incremental

# Or start watch mode to auto-sync
codegraph watch
```

## "codegraph: command not found"

The `codegraph` CLI isn't in your PATH. Options:

1. **Use Python module directly** (always works):
   ```bash
   python -m codegraph.cli.main --help
   ```

2. **Reinstall**:
   ```bash
   pip install -e "backend[mcp,watch]"
   ```

3. **Check virtual environment**:
   ```bash
   # Windows
   .venv\Scripts\activate
   # macOS / Linux
   source .venv/bin/activate
   ```

## Windows-Specific Issues

### PATH / venv

Windows may not find `codegraph` command. Use the Python module form:

```bash
python -m codegraph.cli.main <command>
```

Or ensure the venv Scripts directory is in PATH:

```powershell
$env:Path += ";C:\path\to\venv\Scripts"
```

### PowerShell Execution Policy

If you see execution policy errors:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## CODEGRAPH_PROJECT_ROOT

If you need to override the project root (e.g., running from a different directory):

```bash
$env:CODEGRAPH_PROJECT_ROOT = "C:\path\to\project"
codegraph status
```

In MCP config:

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "python",
      "args": ["-m", "codegraph.mcp_server"],
      "env": {
        "CODEGRAPH_PROJECT_ROOT": "/path/to/project"
      }
    }
  }
}
```

## Benchmark Issues

### "No benchmark result files found"

Run the benchmark pipeline first:

```bash
python -m tests.agent_benchmark.runner --mode baseline
python -m tests.agent_benchmark.runner --mode codegraph --response-mode compact
```

Then run the gate:

```bash
python -m tests.agent_benchmark.gate
```

### --skip-run exit code 2

`--skip-run` requires existing result files. If they don't exist, run without `--skip-run` first.

## Quick Self-Check Commands

```bash
# Full environment and config check
codegraph doctor

# Verify MCP server starts (without entering stdio loop)
codegraph serve --mcp --check

# View current MCP config
codegraph configure show

# Check index status
codegraph status

# Run tests
pytest backend/tests/

# Run benchmark gate
make benchmark-gate
```
