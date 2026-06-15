"""Heuristic graph enrichment for dynamic dispatch and non-code files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from codegraph.graph.confidence import get_confidence
from codegraph.graph.models import (
    EdgeLocation,
    EdgeMetadata,
    EdgeType,
    GraphEdge,
    GraphNode,
    Location,
    NodeType,
    Resolution,
)
from codegraph.indexer.scanner import EXCLUDE_DIRS, normalize_path


_CODE_EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".cs")
_TS_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def build_dynamic_heuristic_edges(root: Path, nodes: list[GraphNode]) -> list[GraphEdge]:
    """Add medium-confidence dynamic edges that static resolvers miss."""
    nodes_by_file = _nodes_by_file(nodes)
    name_to_ids = _name_to_ids(nodes)
    edges: list[GraphEdge] = []

    for rel, file_nodes in nodes_by_file.items():
        if not rel.endswith(_TS_JS_EXTS):
            continue
        abs_path = root / Path(rel)
        if not abs_path.exists():
            continue
        src = abs_path.read_text(encoding="utf-8")
        edges.extend(_event_emitter_edges(rel, src, file_nodes, name_to_ids))
        edges.extend(_callback_edges(rel, src, file_nodes, name_to_ids))
        edges.extend(_react_event_edges(rel, src, file_nodes, name_to_ids))
        edges.extend(_express_middleware_edges(rel, src, file_nodes, nodes))
        edges.extend(_nest_middleware_edges(rel, src, file_nodes, name_to_ids))
    return edges


def build_non_code_graph(root: Path, nodes: list[GraphNode]) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Create file nodes + heuristic edges for architecture-critical non-code files."""
    code_file_nodes = {
        node.file_path: node
        for node in nodes
        if node.type == NodeType.file and node.file_path.endswith(_CODE_EXTS)
    }
    all_file_nodes = {
        node.file_path: node
        for node in nodes
        if node.type == NodeType.file and node.file_path
    }
    code_files = sorted(code_file_nodes)
    new_nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    candidates: list[tuple[str, str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = normalize_path(path.relative_to(root))
        if any(part in EXCLUDE_DIRS for part in Path(rel).parts):
            continue
        kind = _non_code_kind(rel)
        if not kind:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        candidates.append((rel, kind, content))

    for rel, kind, _content in candidates:
        node = all_file_nodes.get(rel)
        if node is None:
            node = GraphNode(
                id=rel,
                type=NodeType.file,
                name=Path(rel).name,
                qualified_name=rel,
                display_name=Path(rel).name,
                file_path=rel,
                language="text",
                language_id="text",
                location=Location(line_start=1, line_end=1),
                tags=["non_code", kind],
                support_level="beta",
                metadata={"support_level": "beta", "non_code_kind": kind},
            )
            new_nodes.append(node)
            all_file_nodes[rel] = node

    for rel, _kind, content in candidates:
        node = all_file_nodes[rel]
        edges.extend(_non_code_edges(node, content, code_files, all_file_nodes, root))

    return new_nodes, edges


def _nodes_by_file(nodes: list[GraphNode]) -> dict[str, list[GraphNode]]:
    out: dict[str, list[GraphNode]] = {}
    for node in nodes:
        if node.file_path:
            out.setdefault(node.file_path, []).append(node)
    return out


def _name_to_ids(nodes: list[GraphNode]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for node in nodes:
        if node.type not in (NodeType.file, NodeType.module):
            out.setdefault(node.name, []).append(node.id)
    return out


def _resolve_symbol_id(
    expr: str,
    rel: str,
    file_nodes: list[GraphNode],
    name_to_ids: dict[str, list[str]],
) -> str | None:
    expr = expr.strip()
    if not expr:
        return None
    if "." in expr:
        class_name, method_name = expr.split(".", 1)
        exact = f"{rel}::{class_name}.{method_name}"
        for node in file_nodes:
            if node.id == exact:
                return node.id
        matches = name_to_ids.get(method_name, [])
        if len(matches) == 1:
            return matches[0]
        return None
    exact = f"{rel}::{expr}"
    for node in file_nodes:
        if node.id == exact or node.name == expr:
            return node.id
    matches = name_to_ids.get(expr, [])
    if len(matches) == 1:
        return matches[0]
    return None


def _find_enclosing_symbol(rel: str, line: int, file_nodes: list[GraphNode]) -> GraphNode | None:
    candidates = [
        node for node in file_nodes
        if node.location
        and node.type not in (NodeType.file, NodeType.module)
        and node.location.line_start <= line <= node.location.line_end
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda node: (node.location.line_end - node.location.line_start, node.location.line_start))


def _make_heuristic_edge(
    *,
    edge_type: EdgeType,
    source: str,
    target: str,
    rel: str,
    line: int,
    resolution: Resolution,
    synthesized_by: str,
    confidence: float,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> GraphEdge:
    evidence = {
        "synthesized_by": synthesized_by,
        "registered_at": f"{rel}:{line}",
        "triggered_at": f"{rel}:{line}",
        "confidence": confidence,
    }
    if extra:
        evidence.update(extra)
    return GraphEdge(
        id=f"heuristic:{source}:{target}:{edge_type.value}:{line}",
        type=edge_type,
        source=source,
        target=target,
        confidence=confidence,
        source_location=EdgeLocation(file_path=rel, line_start=line, line_end=line),
        metadata=EdgeMetadata(
            resolution=resolution,
            provenance="heuristic",
            reason=reason,
            evidence=evidence,
            is_dynamic=True,
        ),
    )


def _event_emitter_edges(rel: str, src: str, file_nodes: list[GraphNode], name_to_ids: dict[str, list[str]]) -> list[GraphEdge]:
    registrations: dict[tuple[str, str], list[tuple[int, str]]] = {}
    edges: list[GraphEdge] = []
    reg_re = re.compile(
        r"(?P<emitter>\w+)\.(?:on|once|addListener)\(\s*['\"`](?P<event>[^'\"`]+)['\"`]\s*,\s*(?P<handler>[A-Za-z_$][\w$.]*)"
    )
    emit_re = re.compile(r"(?P<emitter>\w+)\.emit\(\s*['\"`](?P<event>[^'\"`]+)['\"`]")
    for match in reg_re.finditer(src):
        key = (match.group("emitter"), match.group("event"))
        line = src.count("\n", 0, match.start()) + 1
        registrations.setdefault(key, []).append((line, match.group("handler")))
    for match in emit_re.finditer(src):
        key = (match.group("emitter"), match.group("event"))
        trigger_line = src.count("\n", 0, match.start()) + 1
        source_node = _find_enclosing_symbol(rel, trigger_line, file_nodes)
        if source_node is None:
            continue
        for reg_line, handler_expr in registrations.get(key, []):
            target_id = _resolve_symbol_id(handler_expr, rel, file_nodes, name_to_ids)
            if not target_id:
                continue
            edge = _make_heuristic_edge(
                edge_type=EdgeType.calls,
                source=source_node.id,
                target=target_id,
                rel=rel,
                line=trigger_line,
                resolution=Resolution.event_emitter_heuristic,
                synthesized_by="event-emitter",
                confidence=get_confidence(Resolution.event_emitter_heuristic),
                reason=f'EventEmitter emit("{match.group("event")}") may dispatch to registered callback.',
                extra={
                    "event_name": match.group("event"),
                    "registered_at": f"{rel}:{reg_line}",
                    "triggered_at": f"{rel}:{trigger_line}",
                    "handler": handler_expr,
                },
            )
            edges.append(edge)
    return edges


def _callback_edges(rel: str, src: str, file_nodes: list[GraphNode], name_to_ids: dict[str, list[str]]) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    patterns = [
        (re.compile(r"\bsetTimeout\(\s*(?P<cb>[A-Za-z_$][\w$.]*)"), "setTimeout"),
        (re.compile(r"\bsetInterval\(\s*(?P<cb>[A-Za-z_$][\w$.]*)"), "setInterval"),
        (re.compile(r"\bqueueMicrotask\(\s*(?P<cb>[A-Za-z_$][\w$.]*)"), "queueMicrotask"),
        (re.compile(r"\.\s*(?:then|catch|finally|map|filter|forEach)\(\s*(?P<cb>[A-Za-z_$][\w$.]*)"), "callback"),
    ]
    for regex, label in patterns:
        for match in regex.finditer(src):
            line = src.count("\n", 0, match.start()) + 1
            source_node = _find_enclosing_symbol(rel, line, file_nodes)
            if source_node is None:
                continue
            callback_expr = match.group("cb")
            target_id = _resolve_symbol_id(callback_expr, rel, file_nodes, name_to_ids)
            if not target_id:
                continue
            edges.append(_make_heuristic_edge(
                edge_type=EdgeType.calls,
                source=source_node.id,
                target=target_id,
                rel=rel,
                line=line,
                resolution=Resolution.callback_invocation_heuristic,
                synthesized_by="callback-registration",
                confidence=get_confidence(Resolution.callback_invocation_heuristic),
                reason=f"{label} callback may be invoked asynchronously.",
                extra={"callback": callback_expr},
            ))
    return edges


def _react_event_edges(rel: str, src: str, file_nodes: list[GraphNode], name_to_ids: dict[str, list[str]]) -> list[GraphEdge]:
    if not rel.endswith((".tsx", ".jsx")):
        return []
    edges: list[GraphEdge] = []
    event_re = re.compile(r"\bon[A-Z][A-Za-z0-9_]*\s*=\s*\{\s*(?P<handler>[A-Za-z_$][\w$.]*)\s*\}")
    for match in event_re.finditer(src):
        line = src.count("\n", 0, match.start()) + 1
        source_node = _find_enclosing_symbol(rel, line, file_nodes)
        if source_node is None:
            continue
        handler_expr = match.group("handler")
        target_id = _resolve_symbol_id(handler_expr, rel, file_nodes, name_to_ids)
        if not target_id:
            continue
        edges.append(_make_heuristic_edge(
            edge_type=EdgeType.calls,
            source=source_node.id,
            target=target_id,
            rel=rel,
            line=line,
            resolution=Resolution.react_event_handler_heuristic,
            synthesized_by="react-event-handler",
            confidence=get_confidence(Resolution.react_event_handler_heuristic),
            reason=f"React JSX event handler {handler_expr} may execute on user interaction.",
            extra={"handler": handler_expr},
        ))
    return edges


def _express_middleware_edges(rel: str, src: str, file_nodes: list[GraphNode], all_nodes: list[GraphNode]) -> list[GraphEdge]:
    route_nodes = {
        (node.metadata.get("http_method"), node.metadata.get("route_path"), node.location.line_start if node.location else 0): node
        for node in all_nodes
        if node.type == NodeType.route and node.file_path == rel and node.framework_id == "express"
    }
    name_to_ids = _name_to_ids(all_nodes)
    edges: list[GraphEdge] = []
    call_re = re.compile(r"\b(?P<obj>\w+)\.(?P<method>get|post|put|patch|delete|use)\s*\(")
    for match in call_re.finditer(src):
        open_idx = src.find("(", match.start())
        close_idx = _find_matching_paren(src, open_idx)
        if close_idx is None:
            continue
        args = _split_args(src[open_idx + 1:close_idx])
        line = src.count("\n", 0, match.start()) + 1
        if match.group("method") == "use":
            if args and _is_string_literal(args[0]):
                middleware_args = args[1:]
                route_path = _strip_string(args[0])
            else:
                middleware_args = args
                route_path = "/"
            route_node = route_nodes.get(("USE", route_path, line))
            if route_node is None:
                route_node = next((node for node in route_nodes.values() if node.location and node.location.line_start == line), None)
        else:
            if len(args) < 2 or not _is_string_literal(args[0]):
                continue
            route_path = _strip_string(args[0])
            middleware_args = args[1:-1]
            route_node = route_nodes.get((match.group("method").upper(), route_path, line))
        if route_node is None:
            continue
        for middleware_expr in middleware_args:
            target_id = _resolve_symbol_id(middleware_expr, rel, file_nodes, name_to_ids)
            if not target_id:
                continue
            edges.append(_make_heuristic_edge(
                edge_type=EdgeType.depends_on,
                source=route_node.id,
                target=target_id,
                rel=rel,
                line=line,
                resolution=Resolution.middleware_chain_heuristic,
                synthesized_by="middleware-chain",
                confidence=get_confidence(Resolution.middleware_chain_heuristic),
                reason=f"Express route chain includes middleware {middleware_expr}.",
                extra={"route_path": route_path, "handler": middleware_expr},
            ))
    return edges


def _nest_middleware_edges(rel: str, src: str, file_nodes: list[GraphNode], name_to_ids: dict[str, list[str]]) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    pattern = re.compile(r"consumer\.apply\((?P<middlewares>[^\)]*)\)\.forRoutes\((?P<targets>[^\)]*)\)")
    for match in pattern.finditer(src):
        line = src.count("\n", 0, match.start()) + 1
        middlewares = [item.strip() for item in _split_args(match.group("middlewares")) if item.strip()]
        targets = [item.strip() for item in _split_args(match.group("targets")) if item.strip()]
        for target_expr in targets:
            source_id = _resolve_symbol_id(target_expr, rel, file_nodes, name_to_ids)
            if not source_id:
                continue
            for middleware_expr in middlewares:
                target_id = _resolve_symbol_id(middleware_expr, rel, file_nodes, name_to_ids)
                if not target_id:
                    continue
                edges.append(_make_heuristic_edge(
                    edge_type=EdgeType.depends_on,
                    source=source_id,
                    target=target_id,
                    rel=rel,
                    line=line,
                    resolution=Resolution.middleware_chain_heuristic,
                    synthesized_by="middleware-chain",
                    confidence=get_confidence(Resolution.middleware_chain_heuristic),
                    reason=f"Nest middleware chain applies {middleware_expr} to {target_expr}.",
                    extra={"handler": middleware_expr},
                ))
    return edges


def _find_matching_paren(src: str, open_idx: int) -> int | None:
    depth = 0
    quote: str | None = None
    escape = False
    for idx in range(open_idx, len(src)):
        ch = src[idx]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _split_args(arg_text: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    escape = False
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for ch in arg_text:
        if quote:
            current.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            current.append(ch)
            continue
        if ch in pairs:
            depth += 1
        elif ch in closing and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def _is_string_literal(value: str) -> bool:
    value = value.strip()
    return len(value) >= 2 and value[0] in "'\"`" and value[-1] == value[0]


def _strip_string(value: str) -> str:
    return value.strip().strip("'\"`")


def _non_code_kind(rel: str) -> str | None:
    path = rel.replace("\\", "/")
    base = Path(path).name
    if path == "package.json":
        return "package"
    if base == "Dockerfile":
        return "docker"
    if path in {"docker-compose.yml", "docker-compose.yaml"}:
        return "compose"
    if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml")):
        return "workflow"
    if path == ".env.example":
        return "env"
    if path == "pyproject.toml":
        return "pyproject"
    if path == "requirements.txt":
        return "requirements"
    if path == "tsconfig.json":
        return "tsconfig"
    if base.startswith("vite.config."):
        return "vite"
    if base.startswith("next.config."):
        return "next"
    if path.endswith(".tf"):
        return "terraform"
    if "/migrations/" in f"/{path}/" and path.endswith(".sql"):
        return "sql_migration"
    if path.endswith((".graphql", ".gql")):
        return "graphql"
    if path.endswith(".md"):
        return "markdown"
    return None


def _non_code_edges(
    node: GraphNode,
    content: str,
    code_files: list[str],
    all_file_nodes: dict[str, GraphNode],
    root: Path,
) -> list[GraphEdge]:
    rel = node.file_path
    kind = node.metadata.get("non_code_kind")
    edges: list[GraphEdge] = []

    def add_many(edge_type: EdgeType, targets: list[str], resolution: Resolution, synthesized_by: str, reason: str) -> None:
        for target in sorted(set(targets)):
            if target == rel or target not in all_file_nodes:
                continue
            edges.append(_make_heuristic_edge(
                edge_type=edge_type,
                source=rel,
                target=target,
                rel=rel,
                line=1,
                resolution=resolution,
                synthesized_by=synthesized_by,
                confidence=get_confidence(resolution),
                reason=reason,
                extra={"target_name": target},
            ))

    if kind == "package":
        targets = [fp for fp in code_files if fp.endswith(_TS_JS_EXTS)]
        add_many(EdgeType.configures, targets, Resolution.non_code_configuration, "package-json", "package.json configures JavaScript/TypeScript source files.")
        try:
            data = json.loads(content)
            scripts = data.get("scripts", {})
            script_targets: list[str] = []
            for value in scripts.values():
                script_targets.extend(_path_refs_from_text(value))
                if "vite" in value:
                    script_targets.extend([fp for fp in all_file_nodes if Path(fp).name.startswith("vite.config.")])
                if "next" in value:
                    script_targets.extend([fp for fp in all_file_nodes if Path(fp).name.startswith("next.config.")])
            add_many(EdgeType.runs_script, script_targets, Resolution.non_code_script, "package-json-script", "package.json script references code or build configuration.")
        except Exception:
            pass
    elif kind in {"pyproject", "requirements"}:
        targets = [fp for fp in code_files if fp.endswith(".py")]
        add_many(EdgeType.configures, targets, Resolution.non_code_configuration, kind, f"{Path(rel).name} configures Python code execution.")
    elif kind in {"tsconfig", "vite", "next", "env"}:
        targets = [fp for fp in code_files if fp.endswith(_TS_JS_EXTS)]
        if kind == "env":
            vars_ = re.findall(r"^([A-Z][A-Z0-9_]+)=", content, flags=re.MULTILINE)
            env_targets = [fp for fp in targets if _file_uses_env(root / fp, vars_)]
            targets = env_targets or targets
        add_many(EdgeType.configures, targets, Resolution.non_code_configuration, kind, f"{Path(rel).name} configures application code.")
    elif kind in {"docker", "compose", "workflow", "terraform"}:
        targets = _path_refs_from_text(content)
        if kind == "docker":
            targets.extend(_docker_targets(content, code_files))
        if kind == "workflow":
            targets.extend(_path_refs_from_text(content))
            if "docker" in content.lower():
                targets.extend([fp for fp in all_file_nodes if Path(fp).name in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}])
        if not targets:
            targets = code_files[:]
        add_many(EdgeType.deploys, targets, Resolution.non_code_deployment, kind, f"{Path(rel).name} participates in build/deploy automation.")
        if kind == "workflow":
            add_many(EdgeType.runs_script, _path_refs_from_text(content), Resolution.non_code_script, "workflow-run", "Workflow runs repository scripts or commands.")
    elif kind == "sql_migration":
        table_names = re.findall(r"\b(?:create|alter)\s+table\s+([A-Za-z_][A-Za-z0-9_]*)", content, flags=re.IGNORECASE)
        targets = _files_matching_tokens(root, code_files, table_names or ["sql", "migration", "db", "store", "repository"])
        add_many(EdgeType.migrates, targets, Resolution.non_code_migration, "sql-migration", "SQL migration affects persistence-related code.")
    elif kind == "graphql":
        type_names = re.findall(r"\b(?:type|input|enum|interface)\s+([A-Za-z_][A-Za-z0-9_]*)", content)
        targets = _files_matching_tokens(root, code_files, type_names or ["resolver", "graphql", "query", "mutation"])
        add_many(EdgeType.defines_schema, targets, Resolution.non_code_schema, "graphql-schema", "GraphQL schema defines application-facing types.")
    elif kind == "markdown":
        targets = _path_refs_from_text(content)
        add_many(EdgeType.documents, targets, Resolution.non_code_documentation, "markdown-doc", "Markdown documentation references repository files.")
    return edges


def _path_refs_from_text(text: str) -> list[str]:
    matches = re.findall(r"([A-Za-z0-9_./-]+\.(?:py|ts|tsx|js|jsx|json|ya?ml|toml|tf|sql|graphql|gql|md))", text)
    return [normalize_path(match) for match in matches]


def _docker_targets(content: str, code_files: list[str]) -> list[str]:
    targets: list[str] = []
    for cmd in re.findall(r"\b(?:CMD|ENTRYPOINT)\s+(.+)", content, flags=re.MULTILINE):
        targets.extend(_path_refs_from_text(cmd))
    if not targets:
        for candidate in ("src/app.ts", "src/index.ts", "main.py", "app.py"):
            if candidate in code_files:
                targets.append(candidate)
    return targets


def _file_uses_env(path: Path, vars_: list[str]) -> bool:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    for var in vars_:
        if f"process.env.{var}" in content or f'process.env["{var}"]' in content or f"os.getenv('{var}')" in content or f'os.getenv("{var}")' in content:
            return True
    return False


def _files_matching_tokens(root: Path, files: list[str], tokens: list[str]) -> list[str]:
    lowered = [token.lower() for token in tokens if token]
    targets: list[str] = []
    for rel in files:
        try:
            content = (root / rel).read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if any(token in content or token in rel.lower() for token in lowered):
            targets.append(rel)
    return targets
