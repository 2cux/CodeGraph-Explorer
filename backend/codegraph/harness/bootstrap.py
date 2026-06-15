"""Register builtin harness modules."""

from __future__ import annotations

def register_builtin_modules() -> None:
    """Register builtin stable and reserved harness modules once."""
    from codegraph.harness.registry import (
        builtin_modules_registered,
        mark_builtin_modules_registered,
        register_module,
    )

    if builtin_modules_registered():
        return

    from codegraph.harness.agent_ab_regression import AgentAbRegressionModule
    from codegraph.harness.benchmark_gate import BenchmarkGateModule
    from codegraph.harness.doctor_run import DoctorRunModule
    from codegraph.harness.enrich_import import EnrichImportModule
    from codegraph.harness.enrich_prepare import EnrichPrepareModule
    from codegraph.harness.enrich_validate import EnrichValidateModule
    from codegraph.harness.mcp_execute import McpExecuteModule
    from codegraph.harness.modules.workflow_impact import WorkflowImpactModule
    from codegraph.harness.modules.workflow_test_audit import WorkflowTestAuditModule
    from codegraph.harness.workflow_explain import WorkflowExplainModule
    from codegraph.harness.workflow_find import WorkflowFindModule

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
    mark_builtin_modules_registered()
