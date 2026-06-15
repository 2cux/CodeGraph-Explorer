"""Reserved harness module for ``enrich.import``."""

from __future__ import annotations

from codegraph.harness.manifest import manifest_for


class EnrichImportModule:
    manifest = manifest_for("enrich.import")

    def run(self, ctx, input_data):
        return {
            "ok": False,
            "status": "reserved",
            "message": "This module is reserved for a later implementation.",
        }
