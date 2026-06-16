"""Compatibility shim for the migrated ``workflow.find`` module."""

from codegraph.harness.modules.workflow_find import (
    WorkflowFindModule,
    run_workflow_find,
)

__all__ = ["WorkflowFindModule", "run_workflow_find"]
