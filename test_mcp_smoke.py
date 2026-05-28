"""MCP smoke test — starts the server, calls all tools, validates responses."""
import json
import subprocess
import sys
import time
from pathlib import Path

MCP_SERVER = str(Path(__file__).parent / ".venv" / "Scripts" / "python.exe")
MCP_MODULE = "-m"  # we'll call codegraph.mcp_server
PROJECT_ROOT = str(Path(__file__).parent / "examples" / "demo_python_project")


def _read_json(proc: subprocess.Popen) -> dict:
    """Read one JSON-RPC message from the MCP server's stdout."""
    line = b""
    while True:
        ch = proc.stdout.read(1)
        if not ch:
            raise EOFError("Server closed stdout")
        line += ch
        if ch == b"\n":
            break
    line = line.decode("utf-8").strip()
    if not line:
        raise ValueError("Empty line from server")
    return json.loads(line)


def _send(proc: subprocess.Popen, msg: dict) -> None:
    """Send a JSON-RPC message to the MCP server's stdin."""
    payload = json.dumps(msg) + "\n"
    proc.stdin.write(payload.encode("utf-8"))
    proc.stdin.flush()


def _call_tool(proc: subprocess.Popen, tool: str, args: dict) -> dict:
    """Call an MCP tool and return the result."""
    req = {
        "jsonrpc": "2.0",
        "id": tool,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }
    _send(proc, req)
    resp = _read_json(proc)
    if "error" in resp:
        print(f"  ERROR: {resp['error']}")
    return resp.get("result", {})


def test_all():
    print("=" * 60)
    print("MCP Smoke Test")
    print("=" * 60)

    proc = subprocess.Popen(
        [MCP_SERVER, MCP_MODULE, "codegraph.mcp_server", "--project-root", PROJECT_ROOT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=PROJECT_ROOT,
    )

    # Initialize
    print("\n[1/8] initialize...")
    _send(proc, {"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "smoke-test", "version": "1.0"},
    }})
    resp = _read_json(proc)
    assert "result" in resp, f"Init failed: {resp}"
    print(f"  Server: {resp['result']['serverInfo']}")

    # Notify initialized
    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    # List tools
    print("\n[2/8] list tools...")
    _send(proc, {"jsonrpc": "2.0", "id": "list", "method": "tools/list"})
    resp = _read_json(proc)
    tools = resp["result"]["tools"]
    print(f"  Found {len(tools)} tools:")
    for t in tools:
        print(f"    - {t['name']}: {t.get('description', '')[:80]}")

    # 1. repo_summary
    print("\n[3/8] codegraph_repo_summary...")
    result = _call_tool(proc, "codegraph_repo_summary", {})
    data = json.loads(result["content"][0]["text"])
    print(f"  OK={data.get('ok')}, name={data.get('data', {}).get('name')}, symbols={data.get('data', {}).get('symbol_count')}")

    # 2. search_symbols
    print("\n[4/8] codegraph_search_symbols (query='login')...")
    result = _call_tool(proc, "codegraph_search_symbols", {"query": "login"})
    data = json.loads(result["content"][0]["text"])
    print(f"  OK={data.get('ok')}, total={data.get('data', {}).get('total')}")

    # 3. get_symbol
    print("\n[5/8] codegraph_get_symbol (existing)...")
    result = _call_tool(proc, "codegraph_get_symbol", {"symbol_id": "app/api/auth.py::login"})
    data = json.loads(result["content"][0]["text"])
    print(f"  OK={data.get('ok')}, name={data.get('data', {}).get('name')}, exact_match={data.get('data', {}).get('exact_match')}")

    print("\n[5b/8] codegraph_get_symbol (fuzzy fallback)...")
    result = _call_tool(proc, "codegraph_get_symbol", {"symbol_id": "api/auth.py::login"})
    data = json.loads(result["content"][0]["text"])
    print(f"  OK={data.get('ok')}, name={data.get('data', {}).get('name')}, exact_match={data.get('data', {}).get('exact_match')}, warnings={len(data.get('warnings', []))}")

    print("\n[5c/8] codegraph_get_symbol (not found)...")
    result = _call_tool(proc, "codegraph_get_symbol", {"symbol_id": "nonexistent::foo"})
    data = json.loads(result["content"][0]["text"])
    print(f"  OK={data.get('ok')}, error_code={data.get('error', {}).get('code')}")

    # 4. get_callers
    print("\n[6/8] codegraph_get_callers...")
    result = _call_tool(proc, "codegraph_get_callers", {"symbol_id": "app/api/auth.py::login"})
    data = json.loads(result["content"][0]["text"])
    print(f"  OK={data.get('ok')}, caller_count={len(data.get('data', {}).get('callers', []))}")

    # 5. get_callees
    print("\n[7a/8] codegraph_get_callees (depth=1)...")
    result = _call_tool(proc, "codegraph_get_callees", {"symbol_id": "app/api/auth.py::login", "max_depth": 1})
    data = json.loads(result["content"][0]["text"])
    print(f"  OK={data.get('ok')}, callee_count={len(data.get('data', {}).get('callees', []))}")

    print("\n[7b/8] codegraph_get_neighbors...")
    result = _call_tool(proc, "codegraph_get_neighbors", {"symbol_id": "app/api/auth.py::login", "max_depth": 1})
    data = json.loads(result["content"][0]["text"])
    print(f"  OK={data.get('ok')}, node_id={data.get('data', {}).get('center_id')}, "
          f"callers={len(data.get('data', {}).get('callers', []))}, "
          f"callees={len(data.get('data', {}).get('callees', []))}")

    # 6. get_impact
    print("\n[8a/8] codegraph_get_impact (depth=1)...")
    result = _call_tool(proc, "codegraph_get_impact", {"symbol_id": "app/api/auth.py::login", "max_depth": 1})
    data = json.loads(result["content"][0]["text"])
    print(f"  OK={data.get('ok')}, affected_files={len(data.get('data', {}).get('affected_files', []))}, "
          f"risk_level={data.get('data', {}).get('risk', {}).get('level')}")

    print("\n[8b/8] codegraph_build_context_pack (mode=summary)...")
    result = _call_tool(proc, "codegraph_build_context_pack", {
        "task": "add MFA to login flow",
        "mode": "summary",
        "max_depth": 2,
    })
    data = json.loads(result["content"][0]["text"])
    print(f"  OK={data.get('ok')}, pack_id={data.get('data', {}).get('pack_id')}, "
          f"entry_points={len(data.get('data', {}).get('entry_points', []))}, "
          f"reading_plan_steps={len(data.get('data', {}).get('reading_plan', []))}")

    # Cleanup
    proc.terminate()
    proc.wait(timeout=5)

    print("\n" + "=" * 60)
    print("ALL SMOKE TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    test_all()
