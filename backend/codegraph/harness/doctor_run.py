"""Harness module for ``doctor.run``."""

from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

from codegraph.cli.main import app
from codegraph.harness.manifest import manifest_for
from codegraph.harness.module_utils import coerce_bool, json_report


class DoctorRunModule:
    """Wrap the existing CLI doctor command inside harness execution."""

    manifest = manifest_for("doctor.run")

    def run(self, ctx, input_data: dict[str, Any]) -> dict[str, Any]:
        repair = coerce_bool(input_data.get("repair"), default=False)
        command = ["doctor", "--root", str(ctx.project_root)]
        if repair:
            command.append("--repair")
        ctx.log_info("running codegraph doctor")
        runner = CliRunner()
        result = runner.invoke(app, command, catch_exceptions=False)
        payload = {
            "ok": result.exit_code == 0,
            "status": "ok" if result.exit_code == 0 else "failed",
            "exit_code": result.exit_code,
            "repair": repair,
            "command": command,
            "output": result.stdout,
        }
        ctx.artifact_json("report.json", payload)
        ctx.artifact_text("report.md", json_report("Doctor Run", payload))
        return payload
