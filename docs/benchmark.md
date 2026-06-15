# Benchmark

CodeGraph Explorer includes a benchmark suite that measures how effectively MCP graph queries reduce tool calls, file reads, and token consumption compared to traditional grep/glob/read exploration.

## Running Benchmarks

```bash
# Full benchmark pipeline (baseline + codegraph + report)
make benchmark

# Or step by step:
python -m tests.agent_benchmark.runner --mode baseline
python -m tests.agent_benchmark.runner --mode codegraph --response-mode compact
python -m tests.agent_benchmark.runner --mode codegraph --response-mode standard
python -m tests.agent_benchmark.report
```

For real agent adoption A/B, use the dedicated recorder instead of the synthetic runner:

```bash
python -m tests.agent_benchmark.adoption --write-template --run-id 2026-06-15 --project your-project --agent codex
python -m tests.agent_benchmark.adoption
```

## Benchmark Gate

The regression gate runs all checks and reports pass/fail:

```bash
python -m tests.agent_benchmark.gate
# or
make benchmark-gate
```

This runs the full pipeline and checks against configured thresholds.

## What the Benchmark Measures

The synthetic benchmark measures tool and token efficiency on bundled fixtures.
Real agent adoption should be tracked separately with the A/B flow in
`docs/agent-adoption-real-ab.md`.

### Recall
- **Symbol recall**: How often the right symbol is found via search
- **File recall**: How often all expected files are covered
- **Recall pass rate**: Fraction of tasks where codegraph >= baseline

### Tool Reduction
- **grep/read reduction**: Fewer grep + read tool calls vs baseline
- **Files read reduction**: Fewer unique files read vs baseline

### Token Efficiency
- **Token reduction**: Estimated token savings vs baseline
- **Compact vs standard payload reduction**: Savings from compact mode
- **Average compact payload**: Tokens per MCP response (should be < 2,000)

### Quality Gates
- **Search top-1 accuracy**: First result correctness
- **Ambiguous rate**: Results requiring disambiguation
- **False edge detection**: No edges confirmed on name-only basis
- **Impact separation**: Confirmed vs possible impact clearly separated
- **Evidence Pack boundaries**: No reading_plan, agent_instructions, or recommended_context leakage

## Threshold Configuration

Thresholds are defined in `tests/agent_benchmark/gate_config.json`. Current values:

| Category | Check | Threshold |
|----------|-------|-----------|
| Recall | Symbol recall | ≥ 55% |
| Recall | File recall | ≥ 75% |
| Recall | Pass rate | ≥ 58% |
| Tokens | Token reduction | ≥ 10% |
| Tokens | Compact vs standard reduction | ≥ 30% |
| Tokens | Max compact payload | ≤ 2,000 |
| grep/read | Reduction | ≥ 40% |
| grep/read | Files read reduction | ≥ 30% |

## Benchmark Fixtures

Benchmarks run against bundled Python projects in `tests/agent_benchmark/fixtures/`:

- `simple_auth_project` — Basic auth module
- `medium_demo_project` — Multi-module demo
- `service_layer_project` — Service-layer architecture with imports

Each fixture includes pre-built `.codegraph/` indexes so benchmarks can run without re-indexing.

## Results

Results are saved to:

```
reports/agent_benchmark.md       # Human-readable report
reports/benchmark_gate.json      # Machine-readable gate report
reports/benchmark_gate.md        # Gate result summary
tests/agent_benchmark/results/   # Raw per-task JSON results
```

## Notes

- Results are based on bundled benchmark fixtures and represent directional improvements, not guarantees for all real-world codebases.
- Token estimates use a model-based tokenizer (not exact API counts).
- The benchmark requires the project to be installed: `pip install -e "backend[mcp,watch]"`.
