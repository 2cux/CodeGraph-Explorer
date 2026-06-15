"""Compatibility wrapper for ``workflow.impact`` harness module."""

from codegraph.harness.modules.workflow_impact import (
    WorkflowImpactModule,
    run_workflow_impact,
)

__all__ = ["WorkflowImpactModule", "run_workflow_impact"]
