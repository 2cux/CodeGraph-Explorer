"""Reserved harness module for ``enrich.validate``."""

from __future__ import annotations

from codegraph.harness.manifest import manifest_for


class EnrichValidateModule:
    manifest = manifest_for("enrich.validate")

    def run(self, ctx, input_data):
        return {
            "ok": False,
            "status": "reserved",
            "message": "This module is reserved for a later implementation.",
        }
