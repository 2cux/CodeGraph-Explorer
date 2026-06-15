"""Reserved harness module for ``agent_ab.regression``."""

from __future__ import annotations

from codegraph.harness.manifest import manifest_for


class AgentAbRegressionModule:
    manifest = manifest_for("agent_ab.regression")

    def run(self, ctx, input_data):
        return {
            "ok": False,
            "status": "reserved",
            "message": "This module is reserved for a later implementation.",
        }
