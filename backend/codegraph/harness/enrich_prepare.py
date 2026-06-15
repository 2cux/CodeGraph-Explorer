"""Reserved harness module for ``enrich.prepare``."""

from __future__ import annotations

from codegraph.harness.manifest import manifest_for


class EnrichPrepareModule:
    manifest = manifest_for("enrich.prepare")

    def run(self, ctx, input_data):
        return {
            "ok": False,
            "status": "reserved",
            "message": "This module is reserved for a later implementation.",
        }
