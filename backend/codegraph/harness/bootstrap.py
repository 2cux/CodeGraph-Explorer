"""Register builtin harness modules."""

from __future__ import annotations

from codegraph.harness.agent_ab_regression import AgentAbRegressionModule
from codegraph.harness.benchmark_gate import BenchmarkGateModule
from codegraph.harness.doctor_run import DoctorRunModule
from codegraph.harness.enrich_import import EnrichImportModule
from codegraph.harness.enrich_prepare import EnrichPrepareModule
from codegraph.harness.enrich_validate import EnrichValidateModule
from codegraph.harness.mcp_execute import McpExecuteModule
from codegraph.harness.registry import register_module
from codegraph.harness.modules.workflow_impact import WorkflowImpactModule
from codegraph.harness.workflow_explain import WorkflowExplainModule
from codegraph.harness.workflow_find import WorkflowFindModule
from codegraph.harness.workflow_test_audit import WorkflowTestAuditModule


def register_builtin_modules() -> None:
    """Register builtin stable and reserved harness modules."""
    for module in (
        WorkflowImpactModule,
        WorkflowTestAuditModule,
        WorkflowExplainModule,
        WorkflowFindModule,
        DoctorRunModule,
        EnrichPrepareModule,
        EnrichValidateModule,
        EnrichImportModule,
        BenchmarkGateModule,
        AgentAbRegressionModule,
        McpExecuteModule,
    ):
        register_module(module)
