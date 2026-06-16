# Harness Modules

| Module | Category | Status | Description |
|---|---|---|---|
| `workflow.impact` | `workflow` | `stable` | Analyze callers, files, and tests affected by planned edits. |
| `workflow.test_audit` | `workflow` | `stable` | Audit graph-based test coverage gaps for the selected scope. |
| `workflow.explain` | `workflow` | `stable` | Produce an evidence-backed explanation for a symbol or file. |
| `workflow.find` | `workflow` | `stable` | Search indexed symbols and files by keyword, type, and path scope. |
| `doctor.run` | `doctor` | `stable` | Run CodeGraph doctor diagnostics and optionally perform repair. |
| `enrich.prepare` | `enrich` | `reserved` | Reserved / planned: generate bounded enrichment input from the index. |
| `enrich.validate` | `enrich` | `reserved` | Reserved / planned: validate agent-produced enrichment JSON. |
| `enrich.import` | `enrich` | `reserved` | Reserved / planned: import validated enrichment data into storage. |
| `benchmark.gate` | `benchmark` | `reserved` | Reserved / planned: run benchmark regression gate checks. |
| `agent_ab.regression` | `agent` | `reserved` | Reserved / planned: run agent A/B regression evaluation workflows. |
| `mcp.execute` | `mcp` | `reserved` | Reserved / planned: wrap MCP tool execution and record harness runs. |

## workflow.impact

Input schema:
```json
{
  "type": "object",
  "properties": {
    "files": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [],
      "description": "Repository-relative file paths to inspect."
    },
    "symbols": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [],
      "description": "Qualified symbol ids or names to inspect."
    },
    "change_type": {
      "type": "string",
      "default": "unknown",
      "description": "Change classification such as refactor, bugfix, or feature."
    },
    "description": {
      "type": "string",
      "description": "Optional free-form change description."
    },
    "include_tests": {
      "type": "boolean",
      "default": true,
      "description": "Whether to include related test recommendations."
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "default": 50,
      "description": "Maximum number of related items to keep in result lists."
    }
  },
  "additionalProperties": false
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean"
    },
    "workflow": {
      "type": "string",
      "const": "impact"
    },
    "input": {
      "type": "object"
    },
    "change_type": {
      "type": "string"
    },
    "description": {
      "type": "string"
    },
    "index_status": {
      "type": "object"
    },
    "risk_level": {
      "type": "string"
    },
    "planned_files": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [],
      "description": "Normalized planned files."
    },
    "planned_symbols": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [],
      "description": "Normalized planned symbols."
    },
    "impact_summary": {
      "type": "object"
    },
    "affected_callers": {
      "type": "array"
    },
    "affected_files": {
      "type": "array"
    },
    "affected_tests": {
      "type": "array"
    },
    "recommended_checks": {
      "type": "array"
    },
    "impact_errors": {
      "type": "array"
    },
    "warnings": {
      "type": "array"
    },
    "artifacts": {
      "type": "object"
    }
  },
  "required": [
    "ok",
    "workflow",
    "input",
    "risk_level",
    "impact_summary",
    "affected_files",
    "warnings",
    "artifacts"
  ]
}
```

Artifacts:
- report.md
- report.json

## workflow.test_audit

Input schema:
```json
{
  "type": "object",
  "properties": {
    "paths": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [],
      "description": "Optional path globs or files to scope the audit."
    },
    "types": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [],
      "description": "Optional production symbol types to keep."
    },
    "include_low_confidence": {
      "type": "boolean",
      "default": true,
      "description": "Whether to include low-confidence tested_by links."
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "default": 50,
      "description": "Maximum number of uncovered items to retain."
    }
  },
  "additionalProperties": false
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean"
    },
    "workflow": {
      "type": "string",
      "const": "test-audit"
    },
    "input": {
      "type": "object"
    },
    "coverage_gaps_summary": {
      "type": "object"
    },
    "summary": {
      "type": "object"
    },
    "top_uncovered_production_symbols": {
      "type": "array"
    },
    "symbols_without_tests": {
      "type": "array"
    },
    "files_without_test_signals": {
      "type": "array"
    },
    "files_without_tests": {
      "type": "array"
    },
    "low_confidence_links": {
      "type": "array"
    },
    "path_resolution": {
      "type": "object"
    },
    "warnings": {
      "type": "array"
    },
    "heuristic_coverage_disclaimer": {
      "type": "string"
    },
    "artifacts": {
      "type": "object"
    }
  },
  "required": [
    "ok",
    "workflow",
    "input",
    "summary",
    "warnings",
    "heuristic_coverage_disclaimer",
    "artifacts"
  ]
}
```

Artifacts:
- report.md
- report.json

## workflow.explain

Input schema:
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Symbol name or id. Required when file is not provided."
    },
    "file": {
      "type": "string",
      "description": "Repository-relative file path. Required when symbol is not provided."
    },
    "include_neighbors": {
      "type": "boolean",
      "default": true,
      "description": "Whether to include caller/callee relationship summaries."
    },
    "include_snippets": {
      "type": "boolean",
      "default": true,
      "description": "Whether to include source snippets when available."
    },
    "include_tests": {
      "type": "boolean",
      "default": true,
      "description": "Whether to include structural test signal data."
    },
    "format": {
      "type": "string",
      "default": "markdown",
      "description": "Requested presentation format."
    },
    "max_snippet_lines": {
      "type": "integer",
      "minimum": 1,
      "default": 40,
      "description": "Maximum source lines to include in the snippet block."
    }
  },
  "oneOf": [
    {
      "required": [
        "symbol"
      ],
      "not": {
        "required": [
          "file"
        ]
      }
    },
    {
      "required": [
        "file"
      ],
      "not": {
        "required": [
          "symbol"
        ]
      }
    }
  ],
  "additionalProperties": false
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean"
    },
    "workflow": {
      "type": "string",
      "const": "explain"
    },
    "input": {
      "type": "object"
    },
    "target": {
      "type": "object"
    },
    "summary": {
      "type": "string"
    },
    "confidence": {
      "type": "string"
    },
    "evidence": {
      "type": "array"
    },
    "relationships": {
      "type": "object"
    },
    "test_signal": {
      "type": "object"
    },
    "warnings": {
      "type": "array"
    },
    "source_snippet": {
      "type": "object"
    },
    "artifacts": {
      "type": "object"
    }
  },
  "required": [
    "ok",
    "workflow",
    "input",
    "target",
    "summary",
    "confidence",
    "evidence",
    "relationships",
    "test_signal",
    "warnings",
    "artifacts"
  ]
}
```

Artifacts:
- report.md
- report.json

## workflow.find

Input schema:
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "minLength": 1,
      "description": "Search query used against indexed symbols."
    },
    "types": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [],
      "description": "Optional symbol types to include."
    },
    "paths": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [],
      "description": "Optional path filters."
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "default": 10,
      "description": "Maximum number of primary results to return."
    },
    "include_details": {
      "type": "boolean",
      "default": true,
      "description": "Whether to enrich matches with symbol metadata."
    },
    "include_snippets": {
      "type": "boolean",
      "default": false,
      "description": "Whether to include source snippets."
    },
    "include_tests": {
      "type": "boolean",
      "default": true,
      "description": "Whether test symbols may appear in results."
    },
    "format": {
      "type": "string",
      "default": "markdown",
      "description": "Requested presentation format."
    }
  },
  "required": [
    "query"
  ],
  "additionalProperties": false
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean"
    },
    "workflow": {
      "type": "string",
      "const": "find"
    },
    "input": {
      "type": "object"
    },
    "results": {
      "type": "array"
    },
    "candidates": {
      "type": "array"
    },
    "reason": {
      "type": "string"
    },
    "confidence": {
      "type": "string"
    },
    "total": {
      "type": "integer"
    },
    "next_required_steps": {
      "type": "array"
    },
    "warnings": {
      "type": "array"
    },
    "artifacts": {
      "type": "object"
    }
  },
  "required": [
    "ok",
    "workflow",
    "input",
    "results",
    "candidates",
    "reason",
    "confidence",
    "total",
    "next_required_steps",
    "warnings",
    "artifacts"
  ]
}
```

Artifacts:
- report.md
- report.json

## doctor.run

Input schema:
```json
{
  "type": "object",
  "properties": {
    "repair": {
      "type": "boolean",
      "default": false,
      "description": "Whether to pass --repair to codegraph doctor."
    }
  },
  "additionalProperties": false
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean"
    },
    "status": {
      "type": "string"
    },
    "exit_code": {
      "type": "integer"
    },
    "repair": {
      "type": "boolean"
    },
    "command": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [],
      "description": "Executed CLI command."
    },
    "output": {
      "type": "string"
    }
  },
  "required": [
    "ok",
    "status",
    "exit_code",
    "repair",
    "command",
    "output"
  ]
}
```

Artifacts:
- report.md
- report.json

## enrich.prepare

Input schema:
```json
{
  "type": "object",
  "description": "Reserved module. Input contract is not finalized yet.",
  "additionalProperties": true
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean",
      "const": false
    },
    "status": {
      "type": "string",
      "const": "reserved"
    },
    "message": {
      "type": "string"
    }
  },
  "required": [
    "ok",
    "status",
    "message"
  ],
  "additionalProperties": false
}
```

Artifacts:
- None declared.

## enrich.validate

Input schema:
```json
{
  "type": "object",
  "description": "Reserved module. Input contract is not finalized yet.",
  "additionalProperties": true
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean",
      "const": false
    },
    "status": {
      "type": "string",
      "const": "reserved"
    },
    "message": {
      "type": "string"
    }
  },
  "required": [
    "ok",
    "status",
    "message"
  ],
  "additionalProperties": false
}
```

Artifacts:
- None declared.

## enrich.import

Input schema:
```json
{
  "type": "object",
  "description": "Reserved module. Input contract is not finalized yet.",
  "additionalProperties": true
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean",
      "const": false
    },
    "status": {
      "type": "string",
      "const": "reserved"
    },
    "message": {
      "type": "string"
    }
  },
  "required": [
    "ok",
    "status",
    "message"
  ],
  "additionalProperties": false
}
```

Artifacts:
- None declared.

## benchmark.gate

Input schema:
```json
{
  "type": "object",
  "description": "Reserved module. Input contract is not finalized yet.",
  "additionalProperties": true
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean",
      "const": false
    },
    "status": {
      "type": "string",
      "const": "reserved"
    },
    "message": {
      "type": "string"
    }
  },
  "required": [
    "ok",
    "status",
    "message"
  ],
  "additionalProperties": false
}
```

Artifacts:
- None declared.

## agent_ab.regression

Input schema:
```json
{
  "type": "object",
  "description": "Reserved module. Input contract is not finalized yet.",
  "additionalProperties": true
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean",
      "const": false
    },
    "status": {
      "type": "string",
      "const": "reserved"
    },
    "message": {
      "type": "string"
    }
  },
  "required": [
    "ok",
    "status",
    "message"
  ],
  "additionalProperties": false
}
```

Artifacts:
- None declared.

## mcp.execute

Input schema:
```json
{
  "type": "object",
  "description": "Reserved module. Input contract is not finalized yet.",
  "additionalProperties": true
}
```

Output schema:
```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean",
      "const": false
    },
    "status": {
      "type": "string",
      "const": "reserved"
    },
    "message": {
      "type": "string"
    }
  },
  "required": [
    "ok",
    "status",
    "message"
  ],
  "additionalProperties": false
}
```

Artifacts:
- None declared.
