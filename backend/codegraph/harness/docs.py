"""Generate harness module reference docs from registry/manifest metadata."""

from __future__ import annotations

import json
from pathlib import Path

from codegraph.harness.manifest import list_builtin_manifests

_DOC_MODULE_ORDER: tuple[str, ...] = (
    "workflow.impact",
    "workflow.test_audit",
    "workflow.explain",
    "workflow.find",
    "doctor.run",
    "enrich.prepare",
    "enrich.validate",
    "enrich.import",
    "benchmark.gate",
    "agent_ab.regression",
    "mcp.execute",
)


def _ordered_manifests():
    manifest_map = {manifest.id: manifest for manifest in list_builtin_manifests()}
    ordered_ids = list(_DOC_MODULE_ORDER)
    ordered_ids.extend(
        module_id for module_id in sorted(manifest_map) if module_id not in _DOC_MODULE_ORDER
    )
    return [manifest_map[module_id] for module_id in ordered_ids]


def _status_label(is_stable: bool) -> str:
    return "stable" if is_stable else "reserved"


def _json_block(schema: dict | None) -> list[str]:
    if not schema:
        return ["```json", "{}", "```"]
    return [
        "```json",
        json.dumps(schema, indent=2, ensure_ascii=False),
        "```",
    ]


class DocsGenerator:
    """Render harness module documentation from builtin manifests."""

    def render(self) -> str:
        lines = [
            "# Harness Modules",
            "",
            "| Module | Category | Status | Description |",
            "|---|---|---|---|",
        ]
        for manifest in _ordered_manifests():
            lines.append(
                f"| `{manifest.id}` | `{manifest.category}` | `{_status_label(manifest.is_stable)}` | {manifest.description} |"
            )

        for manifest in _ordered_manifests():
            lines.extend(
                [
                    "",
                    f"## {manifest.id}",
                    "",
                    "Input schema:",
                    *_json_block(manifest.input_schema),
                    "",
                    "Output schema:",
                    *_json_block(manifest.output_schema),
                    "",
                    "Artifacts:",
                ]
            )
            if manifest.default_artifacts:
                lines.extend(f"- {artifact}" for artifact in manifest.default_artifacts)
            else:
                lines.append("- None declared.")
        return "\n".join(lines).rstrip() + "\n"

    def write(self, project_root: Path) -> Path:
        docs_path = project_root / "docs" / "harness-modules.md"
        docs_path.parent.mkdir(parents=True, exist_ok=True)
        docs_path.write_text(self.render(), encoding="utf-8")
        return docs_path
