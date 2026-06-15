"""Reserved harness module for ``mcp.execute``."""

from __future__ import annotations

from codegraph.harness.manifest import manifest_for


class McpExecuteModule:
    manifest = manifest_for("mcp.execute")

    def run(self, ctx, input_data):
        return {
            "ok": False,
            "status": "reserved",
            "message": "This module is reserved for a later implementation.",
        }
