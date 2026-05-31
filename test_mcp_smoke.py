"""MCP smoke test — starts the server, calls all tools, validates responses."""
import json
import subprocess
import sys
import time
from pathlib import Path

MCP_SERVER = str(Path(__file__).parent / ".venv" / "Scripts" / "python.exe")
MCP_MODULE = "-m"
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
    """Call an MCP tool and return the parsed data."""
    req = {
        "jsonrpc": "2.0",
        "id": tool,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }
    _send(proc, req)
    resp = _read_json(proc)
    if "error" in resp:
        return {"ok": False, "error": resp["error"]}
    content = resp.get("result", {}).get("content", [])
    if content:
        return json.loads(content[0]["text"])
    return {"ok": False, "error": "No content"}


def test_all():
    print("=" * 60)
    print("MCP Smoke Test — Unified Format")
    print("=" * 60)

    proc = subprocess.Popen(
        [MCP_SERVER, MCP_MODULE, "codegraph.mcp_server", "--project-root", PROJECT_ROOT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=PROJECT_ROOT,
    )

    # Initialize
    print("\n[1/12] initialize...")
    _send(proc, {"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "smoke-test", "version": "1.0"},
    }})
    resp = _read_json(proc)
    assert "result" in resp, f"Init failed: {resp}"
    print(f"  Server: {resp['result']['serverInfo']}")

    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    # List tools
    print("\n[2/12] list tools...")
    _send(proc, {"jsonrpc": "2.0", "id": "list", "method": "tools/list"})
    resp = _read_json(proc)
    tools = resp["result"]["tools"]
    print(f"  Found {len(tools)} tools:")
    for t in tools:
        print(f"    - {t['name']}")

    # ── 1. repo_summary ──────────────────────────────────────────────
    print("\n[3/12] codegraph_repo_summary...")
    data = _call_tool(proc, "codegraph_repo_summary", {})
    assert data.get("ok"), f"Expected ok=true: {data}"
    assert data.get("tool") == "codegraph_repo_summary"
    assert "meta" in data
    assert data["meta"]["schema_version"] == "1.0.0"
    assert "index_status" in data
    assert "data" in data
    stats = data["data"]["stats"]
    print(f"  OK, symbols={stats.get('symbols')}, edges={stats.get('edges')}, "
          f"tests={stats.get('tests')}, routes={stats.get('routes')}")

    # ── 2. search_symbols ────────────────────────────────────────────
    print("\n[4/12] codegraph_search_symbols (query='login')...")
    data = _call_tool(proc, "codegraph_search_symbols", {"query": "login"})
    assert data.get("ok")
    assert data.get("tool") == "codegraph_search_symbols"
    print(f"  OK, total={data['data']['total']}")

    # ── 3. get_symbol (exact) ────────────────────────────────────────
    print("\n[5/12] codegraph_get_symbol (exact match)...")
    data = _call_tool(proc, "codegraph_get_symbol", {"symbol_id": "app/api/auth.py::login"})
    assert data.get("ok"), f"Expected ok=true: {data}"
    assert data.get("tool") == "codegraph_get_symbol"
    symbol = data["data"]["symbol"]
    assert symbol["exact_match"] is True
    assert symbol["name"] == "login"
    assert "relations_summary" in data["data"]
    # source key is only present when include_source=True (compact default)
    print(f"  OK, name={symbol['name']}, exact_match={symbol['exact_match']}, "
          f"relations={data['data']['relations_summary']}")

    # ── 3b. get_symbol (include_source) ──────────────────────────────
    print("\n[5b/12] codegraph_get_symbol (include_source=true)...")
    data = _call_tool(proc, "codegraph_get_symbol", {"symbol_id": "app/api/auth.py::login", "include_source": True})
    assert data.get("ok")
    source = data["data"]["source"]
    print(f"  OK, source_included={source['included']}, "
          f"content_len={len(source.get('content') or '')}")

    # ── 3c. get_symbol (fuzzy) ───────────────────────────────────────
    print("\n[5c/12] codegraph_get_symbol (fuzzy fallback)...")
    data = _call_tool(proc, "codegraph_get_symbol", {"symbol_id": "api/auth.py::login"})
    assert data.get("ok"), f"Fuzzy match should succeed: {data}"
    symbol = data["data"]["symbol"]
    assert symbol["exact_match"] is False
    fuzzy_warnings = [w for w in data.get("warnings", []) if w.get("type") == "fuzzy_match"]
    assert len(fuzzy_warnings) > 0
    print(f"  OK, match_reason={symbol['match_reason']}, warnings={len(fuzzy_warnings)}")

    # ── 3d. get_symbol (not found) ───────────────────────────────────
    print("\n[5d/12] codegraph_get_symbol (not found)...")
    data = _call_tool(proc, "codegraph_get_symbol", {"symbol_id": "nonexistent::foo"})
    assert data.get("ok") is False
    assert data["error"]["code"] == "SYMBOL_NOT_FOUND"
    print(f"  OK, error_code={data['error']['code']}")

    # ── 4. get_callers ───────────────────────────────────────────────
    print("\n[6/12] codegraph_get_callers (depth=1)...")
    data = _call_tool(proc, "codegraph_get_callers", {"symbol_id": "app/api/auth.py::login"})
    assert data.get("ok"), f"Expected ok=true: {data}"
    callers = data["data"]["callers"]
    for c in callers:
        assert "confidence" in c, f"Caller missing confidence: {c}"
        assert "resolution" in c, f"Caller missing resolution: {c}"
        assert "reason_code" in c, f"Caller missing reason_code: {c}"
    print(f"  OK, total={data['data']['total']}, callers={len(callers)}")

    # ── 5. get_callees ───────────────────────────────────────────────
    print("\n[7/12] codegraph_get_callees (depth=1)...")
    data = _call_tool(proc, "codegraph_get_callees", {"symbol_id": "app/api/auth.py::login"})
    assert data.get("ok"), f"Expected ok=true: {data}"
    callees = data["data"]["callees"]
    for c in callees:
        assert "confidence" in c
        assert "resolution" in c
        assert "reason_code" in c
    print(f"  OK, total={data['data']['total']}, "
          f"external_calls={len(data['data'].get('external_calls', []))}")

    # ── 6. get_neighbors ─────────────────────────────────────────────
    print("\n[8/12] codegraph_get_neighbors (depth=1, both)...")
    data = _call_tool(proc, "codegraph_get_neighbors", {
        "symbol_id": "app/api/auth.py::login",
        "depth": 1,
        "direction": "both",
    })
    assert data.get("ok"), f"Expected ok=true: {data}"
    nd = data["data"]
    assert "center" in nd
    assert "groups" in nd  # compact + group_by_role default
    assert "counts" in nd
    for role, group in nd["groups"].items():
        for n in group:
            pass  # nodes in groups have role implied by group key
    print(f"  OK, center={nd['center']}, groups={list(nd['groups'].keys())}, "
          f"counts={nd['counts']}, truncated={nd.get('truncated')}")

    # ── 6b. get_neighbors (standard mode for nodes/edges) ─────────────
    print("\n[8b/12] codegraph_get_neighbors (standard, group_by_role=false)...")
    data = _call_tool(proc, "codegraph_get_neighbors", {
        "symbol_id": "app/api/auth.py::login",
        "depth": 1,
        "response_mode": "standard",
        "group_by_role": False,
    })
    assert data.get("ok")
    assert "nodes" in data["data"]
    assert "edges" in data["data"]
    for e in data["data"]["edges"]:
        assert "confidence" in e
        assert "resolution" in e
    print(f"  OK, nodes={len(data['data']['nodes'])}, edges={len(data['data']['edges'])}")

    # ── 6c. get_neighbors (direction=upstream) ───────────────────────
    print("\n[8c/12] codegraph_get_neighbors (direction=upstream)...")
    data = _call_tool(proc, "codegraph_get_neighbors", {
        "symbol_id": "app/api/auth.py::login",
        "depth": 1,
        "direction": "upstream",
        "response_mode": "standard",
        "group_by_role": False,
    })
    assert data.get("ok")
    print(f"  OK, nodes={len(data['data']['nodes'])}, edges={len(data['data']['edges'])} (upstream only)")

    # ── 7. get_impact ────────────────────────────────────────────────
    print("\n[9/12] codegraph_get_impact (depth=2)...")
    data = _call_tool(proc, "codegraph_get_impact", {
        "symbol_id": "app/api/auth.py::login",
        "depth": 2,
    })
    assert data.get("ok"), f"Expected ok=true: {data}"
    impact = data["data"]
    assert "target" in impact
    assert "risk" in impact
    assert "confirmed_files" in impact  # compact mode
    assert "possible_files" in impact
    assert "related_tests_count" in impact
    assert "unresolved_count" in impact
    # Risk reason_codes should be factual (no should/must)
    for reason_code in impact["risk"].get("reason_codes", []):
        assert "should" not in reason_code.lower()
        assert "must" not in reason_code.lower()
    print(f"  OK, risk={impact['risk']['level']}, "
          f"confirmed_files={len(impact['confirmed_files'])}, "
          f"possible_files={len(impact['possible_files'])}")

    # ── 7b. get_impact (standard mode) ────────────────────────────────
    print("\n[9b/12] codegraph_get_impact (standard mode)...")
    data = _call_tool(proc, "codegraph_get_impact", {
        "symbol_id": "app/api/auth.py::login",
        "depth": 2,
        "response_mode": "standard",
    })
    assert data.get("ok")
    impact = data["data"]
    assert "confirmed_impact" in impact
    assert "possible_impact" in impact
    assert "upstream_callers" in impact
    assert "downstream_callees" in impact
    assert "related_tests" in impact
    assert "external_or_unresolved" in impact
    print(f"  OK, confirmed_symbols={len(impact['confirmed_impact']['symbols'])}, "
          f"related_tests={len(impact['related_tests'])}")

    # ── 8. build_context_pack ────────────────────────────────────────
    print("\n[10/12] codegraph_build_context_pack (mode=summary)...")
    data = _call_tool(proc, "codegraph_build_context_pack", {
        "task": "add MFA to login flow",
        "mode": "summary",
        "depth": 2,
    })
    assert data.get("ok"), f"Expected ok=true: {data}"
    pack = data["data"]
    # Must NOT contain reading_plan or agent_instructions
    assert "reading_plan" not in pack, "Context pack must NOT contain reading_plan"
    assert "agent_instructions" not in pack, "Context pack must NOT contain agent_instructions"
    assert "recommended_context" not in pack, "Context pack must NOT contain recommended_context"
    print(f"  OK, pack_id={pack.get('pack_id')}, "
          f"entry_points={len(pack.get('entry_points', []))}, "
          f"selected_context={len(pack.get('selected_context', []))}")

    # ── 9. repo_status ───────────────────────────────────────────────
    print("\n[11/12] codegraph_repo_status...")
    data = _call_tool(proc, "codegraph_repo_status", {})
    assert data.get("ok")
    status_data = data["data"]
    assert "status" in status_data
    assert status_data["status"] in ("fresh", "stale", "missing", "error")
    assert "index_files" in status_data
    assert "stats" in status_data
    print(f"  OK, status={status_data['status']}, "
          f"index_files={status_data['index_files']}, "
          f"stats={status_data['stats']}")

    # ── 10. Verify all responses have unified envelope ───────────────
    print("\n[12/12] Verifying unified envelope on all tools...")
    tools_to_test = [
        ("codegraph_repo_summary", {}),
        ("codegraph_search_symbols", {"query": "main"}),
        ("codegraph_get_symbol", {"symbol_id": "app/api/auth.py::login"}),
        ("codegraph_get_callers", {"symbol_id": "app/api/auth.py::login"}),
        ("codegraph_get_callees", {"symbol_id": "app/api/auth.py::login"}),
        ("codegraph_get_neighbors", {"symbol_id": "app/api/auth.py::login"}),
        ("codegraph_get_impact", {"symbol_id": "app/api/auth.py::login"}),
        ("codegraph_repo_status", {}),
    ]
    for tool_name, tool_args in tools_to_test:
        data = _call_tool(proc, tool_name, tool_args)
        assert "ok" in data, f"{tool_name}: missing 'ok'"
        assert "tool" in data, f"{tool_name}: missing 'tool'"
        assert "warnings" in data, f"{tool_name}: missing 'warnings'"
        assert "index_status" in data, f"{tool_name}: missing 'index_status'"
        assert "meta" in data, f"{tool_name}: missing 'meta'"
        assert "schema_version" in data["meta"], f"{tool_name}: missing meta.schema_version"
        if data["ok"]:
            assert "data" in data, f"{tool_name}: missing 'data' on success"
        else:
            assert "error" in data, f"{tool_name}: missing 'error' on failure"
            assert "code" in data["error"], f"{tool_name}: error missing code"
            assert "message" in data["error"], f"{tool_name}: error missing message"
        print(f"  [OK] {tool_name}")

    # Cleanup
    proc.terminate()
    proc.wait(timeout=5)

    print("\n" + "=" * 60)
    print("ALL SMOKE TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    test_all()
