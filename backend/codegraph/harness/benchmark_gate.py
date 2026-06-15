"""Reserved harness module for ``benchmark.gate``."""

from __future__ import annotations

from codegraph.harness.manifest import manifest_for


class BenchmarkGateModule:
    manifest = manifest_for("benchmark.gate")

    def run(self, ctx, input_data):
        return {
            "ok": False,
            "status": "reserved",
            "message": "This module is reserved for a later implementation.",
        }
