"""Go language extractor — regex-based source analysis.

Produces ``ExtractorResult`` with symbols, imports, calls, and references
for Go source files. Uses regex patterns since Go has a very regular syntax
amenable to structural scanning.

Extracts:
- Package declarations
- Import statements (standard, aliased, dot, blank)
- Functions and methods (including receiver methods)
- Struct and interface type declarations
- Constants and variables
- Function calls (simple, package-qualified, receiver method)
- Constructor-like calls (NewXxx patterns)
- defer/go call patterns
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from codegraph.graph.models import (
    GraphNode,
    GraphEdge,
    NodeType,
    EdgeType,
    Resolution,
    EdgeMetadata,
    EdgeLocation,
    Location,
)
from codegraph.language_support.extractor import (
    LanguageExtractor,
    ExtractorResult,
    ImportInfo,
    ExportInfo,
    CallEdge,
    RefEdge,
    Diagnostic,
)
from codegraph.language_support.go.frameworks import extract_go_frameworks

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GO_EXTENSIONS = (".go",)

# Edge counter for unique IDs
_edge_counter: list[int] = [0]


def _next_edge_id() -> str:
    _edge_counter[0] += 1
    return f"go_edge_{_edge_counter[0]:06d}"


def _node_id(file_path: str, name: str) -> str:
    """Build a stable node ID like ``pkg/handler.go::ListUsers``."""
    return f"{file_path}::{name}"


def _rel_path(abs_path: str, project_root: str | None) -> str:
    """Convert an absolute path to a POSIX relative path."""
    if project_root:
        try:
            rel = Path(abs_path).relative_to(project_root)
        except ValueError:
            rel = Path(abs_path)
    else:
        rel = Path(abs_path)
    return rel.as_posix()


def _read_content(file_path: str, content: str | None = None) -> str:
    """Return file content, reading from disk if needed."""
    if content is not None:
        return content
    return Path(file_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Go-specific regex patterns
# ---------------------------------------------------------------------------

# Package declaration: package main
_RE_PACKAGE = re.compile(r'^package\s+(\w+)', re.MULTILINE)

# Single import: import "fmt"
_RE_SINGLE_IMPORT = re.compile(r'^import\s+(?:(\.|\w+|\_)\s+)?\"([^\"]+)\"', re.MULTILINE)

# Multi-import block
_RE_IMPORT_BLOCK_START = re.compile(r'^import\s*\(', re.MULTILINE)
_RE_IMPORT_BLOCK_END = re.compile(r'^\)', re.MULTILINE)
_RE_IMPORT_BLOCK_ITEM = re.compile(r'(?:(\.|\w+|\_)\s+)?\"([^\"]+)\"')

# Function declaration: func foo(args) returnType { ... }
_RE_FUNC = re.compile(
    r'^func\s+(\w+)\s*\(([^)]*)\)\s*((?:\([^)]*\)|[\w\[\]\*\.]+(?:\s*,\s*[\w\[\]\*\.]+)*)?)\s*\{',
    re.MULTILINE,
)

# Method declaration: func (r *Receiver) Method(args) returnType { ... }
_RE_METHOD = re.compile(
    r'^func\s+\((\w+)\s+(\*?[\w\.]+)\)\s+(\w+)\s*\(([^)]*)\)\s*((?:\([^)]*\)|[\w\[\]\*\.]+(?:\s*,\s*[\w\[\]\*\.]+)*)?)\s*\{',
    re.MULTILINE,
)

# Type declaration: type Foo struct { ... } or type Foo interface { ... }
_RE_TYPE_STRUCT = re.compile(
    r'^type\s+(\w+)\s+struct\s*\{',
    re.MULTILINE,
)
_RE_TYPE_INTERFACE = re.compile(
    r'^type\s+(\w+)\s+interface\s*\{',
    re.MULTILINE,
)

# Interface method declarations (inside interface blocks)
_RE_INTERFACE_METHOD = re.compile(
    r'^\s*(\w+)\s*\(([^)]*)\)\s*((?:\([^)]*\)|[\w\[\]\*\.]+(?:\s*,\s*[\w\[\]\*\.]+)*)?)',
    re.MULTILINE,
)

# Struct embedding
_RE_STRUCT_EMBED = re.compile(
    r'^\s+(\*?[\w\.]+)\s*$',
    re.MULTILINE,
)

# Function call: name(args)
_RE_CALL = re.compile(
    r'\b(\w+(?:\.\w+)*)\s*\(',
)

# Constructor call pattern: NewXxx(args)
_RE_CONSTRUCTOR = re.compile(
    r'\b(New\w+)\s*\(',
)

# defer / go call
_RE_DEFER_GO = re.compile(
    r'\b(defer|go)\s+(\w+(?:\.\w+)*)\s*\(',
)

# const / var declarations
_RE_CONST = re.compile(r'^const\s+(\w+)\s*=', re.MULTILINE)
_RE_VAR = re.compile(r'^var\s+(\w+)\s+', re.MULTILINE)
_RE_CONST_BLOCK = re.compile(r'^const\s*\(([^)]*)\)', re.MULTILINE | re.DOTALL)
_RE_VAR_BLOCK = re.compile(r'^var\s*\(([^)]*)\)', re.MULTILINE | re.DOTALL)
_RE_BLOCK_IDENT = re.compile(r'(\w+)\s+(?:[\w\[\]\*\.]+)\s*=', re.MULTILINE)

# Selector expression (for references): obj.Field
_RE_SELECTOR = re.compile(r'\b(\w+)\.(\w+)\b')

# Package-level comment/doc
_RE_COMMENT = re.compile(r'//.*$', re.MULTILINE)

# Find balanced braces
def _find_brace_end(src: str, start: int) -> int:
    """Find the matching closing brace for an opening brace at ``start``."""
    depth = 0
    for i in range(start, len(src)):
        ch = src[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i
    return len(src) - 1


def _find_paren_end(src: str, start: int) -> int:
    """Find the matching closing paren for an opening paren at ``start``."""
    depth = 0
    in_string = False
    in_char = False
    escape = False
    for i in range(start, len(src)):
        ch = src[i]
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"' and not in_char:
            in_string = not in_string
            continue
        if ch == '`':
            in_string = not in_string
            continue
        if ch == "'" and not in_string:
            in_char = not in_char
            continue
        if in_string or in_char:
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return i
    return len(src) - 1


def _get_line(src: str, offset: int) -> int:
    """Return 1-based line number for an offset."""
    return src[:offset].count('\n') + 1


def _strip_comments(line: str) -> str:
    """Remove line comments from a line of Go code."""
    return _RE_COMMENT.sub('', line).strip()


# ---------------------------------------------------------------------------
# GoExtractor
# ---------------------------------------------------------------------------


class GoExtractor(LanguageExtractor):
    """Go language extractor using regex-based source analysis.

    Extracts package declarations, imports, functions, methods, structs,
    interfaces, constants, variables, and call edges from Go source files.
    """

    language_id = "go"

    def extract(
        self,
        file_path: str,
        content: str | None = None,
        project_root: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> ExtractorResult:
        src = _read_content(file_path, content)
        rel = _rel_path(file_path, project_root)

        # Remove multi-line comments for cleaner parsing
        src_clean = re.sub(r'/\*.*?\*/', ' ', src, flags=re.DOTALL)

        # Phase 1: Extract package
        package_name = self._extract_package(src_clean)

        # Phase 2: Extract imports
        imports = self._extract_imports(src_clean, rel)

        # Phase 3: Extract symbols
        symbols, struct_fields, interface_methods = self._extract_symbols(
            src_clean, rel, package_name
        )

        # Phase 4: Framework extraction (Gin)
        framework = extract_go_frameworks(
            rel=rel,
            src=src_clean,
            symbols=symbols,
            imports=imports,
            language_id=self.language_id,
        )
        if framework.nodes:
            existing_ids = {s.id for s in symbols}
            for node in framework.nodes:
                if node.id not in existing_ids:
                    symbols.append(node)
                    existing_ids.add(node.id)

        # Phase 5: Extract exports
        exports = self._extract_exports(symbols, rel)

        # Phase 6: Extract calls
        calls = self._extract_calls(src_clean, symbols, rel)

        # Phase 7: Extract references
        references = self._extract_references(src_clean, symbols, rel, struct_fields, interface_methods)

        # Phase 8: Build structural edges
        structural = self._build_structural_edges(symbols, rel, package_name, imports)

        # Phase 9: Diagnostics
        diagnostics = self._collect_diagnostics(src_clean, rel)

        # Set language_id and support_level on all symbols
        for s in symbols:
            s.language_id = self.language_id
            s.language = self.language_id
            if "support_level" not in s.metadata:
                s.metadata["support_level"] = "beta"

        result = ExtractorResult(
            language_id=self.language_id,
            file_path=rel,
            symbols=symbols,
            imports=imports,
            exports=exports,
            calls=calls,
            references=references,
            diagnostics=diagnostics + framework.diagnostics,
        )
        # Attach raw edges for the resolver
        result._raw_edges = (
            structural
            + self._calls_to_edges(calls, symbols, rel)
            + self._refs_to_edges(references, symbols, rel)
            + framework.edges
        )
        return result

    # ── Package extraction ──────────────────────────────────────────────

    def _extract_package(self, src: str) -> str:
        """Extract the package name from a Go file."""
        m = _RE_PACKAGE.search(src)
        return m.group(1) if m else "main"

    # ── Import extraction ───────────────────────────────────────────────

    def _extract_imports(self, src: str, rel: str) -> list[ImportInfo]:
        """Extract all import statements from a Go file.

        Handles:
        - Standard: import "fmt"
        - Aliased: import f "fmt"
        - Dot: import . "fmt"
        - Blank: import _ "fmt"
        - Block: import ( ... )
        """
        imports: list[ImportInfo] = []

        # Single imports
        for m in _RE_SINGLE_IMPORT.finditer(src):
            alias = m.group(1) or ""
            path = m.group(2)
            line = _get_line(src, m.start())
            imports.append(self._make_import(alias, path, line, rel))

        # Import blocks
        for block_match in _RE_IMPORT_BLOCK_START.finditer(src):
            block_start = block_match.end()
            block_end = _find_paren_end(src, block_match.start() + len("import"))
            block_text = src[block_start:block_end]

            for item in _RE_IMPORT_BLOCK_ITEM.finditer(block_text):
                alias = item.group(1) or ""
                path = item.group(2)
                line = _get_line(src, block_start + item.start())
                imports.append(self._make_import(alias, path, line, rel))

        return imports

    def _make_import(self, alias: str, path: str, line: int, rel: str) -> ImportInfo:
        """Create an ImportInfo from an import match."""
        # Determine local name
        if alias == "_":
            local_name = "_"  # blank import
        elif alias == ".":
            local_name = ""  # dot import
        elif alias:
            local_name = alias
        else:
            # Default: use last component of import path
            local_name = path.rsplit("/", 1)[-1]

        # Determine if external
        is_external = self._is_external_package(path)

        # The imported name matches the local name for non-alias imports
        imported_name = path.split("/")[-1] if "." not in path.split("/")[-1] else path

        return ImportInfo(
            local_name=local_name or path.split("/")[-1],
            module_path=path,
            imported_name=imported_name,
            is_external=is_external,
            line=line,
        )

    def _is_external_package(self, path: str) -> bool:
        """Check if an import path is an external module.

        Go standard library packages don't have a domain in their path.
        External modules typically have a domain (e.g., github.com/...).
        """
        if path in {
            "fmt", "os", "io", "net", "sync", "time", "strings",
            "strconv", "errors", "log", "math", "sort", "bytes",
            "context", "encoding/json", "encoding/xml", "encoding/csv",
            "net/http", "net/url", "database/sql", "reflect",
            "unicode", "regexp", "bufio", "path", "path/filepath",
            "runtime", "crypto", "hash", "html", "html/template",
            "text/template", "flag", "mime", "mime/multipart",
        }:
            return False

        # Standard library packages start without a domain
        # External packages have domains (github.com, etc.) or gopkg.in
        if "/" not in path:
            return False  # stdlib single-component
        first = path.split("/")[0]
        if "." in first:  # domain present → external
            return True
        # gopkg.in
        if path.startswith("gopkg.in/"):
            return True
        # Common stdlib multi-component
        stdlib_prefixes = (
            "encoding/", "net/", "crypto/", "hash/",
            "html/", "text/", "mime/", "path/", "database/",
            "archive/", "compress/", "container/", "debug/",
            "go/", "image/", "index/", "internal/", "os/", "sync/",
            "testing/", "vendor/",
        )
        for pfx in stdlib_prefixes:
            if path.startswith(pfx):
                return False
        # Heuristic: if path looks like a module path with domain → external
        if re.match(r'^[\w-]+\.[\w-]+/', path):
            return True
        return False

    # ── Symbol extraction ───────────────────────────────────────────────

    def _extract_symbols(
        self, src: str, rel: str, pkg_name: str
    ) -> tuple[list[GraphNode], list[RefEdge], list[RefEdge]]:
        """Extract all symbols from a Go source file.

        Returns ``(symbols, struct_fields, interface_methods)``.
        """
        nodes: list[GraphNode] = []
        struct_fields: list[RefEdge] = []
        interface_methods: list[RefEdge] = []

        # File node
        nodes.append(GraphNode(
            id=rel,
            type=NodeType.file,
            name=Path(rel).name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
        ))

        # Module (package) node
        nodes.append(GraphNode(
            id=f"go_pkg:{pkg_name}",
            type=NodeType.module,
            name=pkg_name,
            qualified_name=pkg_name,
            file_path=rel,
            language_id=self.language_id,
            language=self.language_id,
            metadata={"go_package": pkg_name},
        ))

        seen_names: dict[str, int] = {}

        # Functions (top-level)
        for m in _RE_FUNC.finditer(src):
            name = m.group(1)
            if name in ("init",):
                continue  # skip init functions
            line = _get_line(src, m.start())
            seen_names[name] = seen_names.get(name, 0) + 1
            nid = _node_id(rel, name)
            params = m.group(2)
            returns = m.group(3).strip() if m.group(3) else ""
            sig = f"func {name}({params})"
            if returns:
                sig += f" {returns}"

            # Detect test
            tags: list[str] = []
            ntype = NodeType.function
            if name.startswith("Test"):
                tags.append("test")
                ntype = NodeType.test

            nodes.append(GraphNode(
                id=nid,
                type=ntype,
                name=name,
                qualified_name=f"{rel}::{name}",
                display_name=name,
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(
                    line_start=line,
                    line_end=_get_line(src, _find_brace_end(src, m.start())),
                ),
                signature=sig,
                tags=tags,
                metadata={"support_level": "beta"},
            ))

        # Methods (receiver functions)
        for m in _RE_METHOD.finditer(src):
            recv_name = m.group(1)
            recv_type = m.group(2).lstrip("*")
            method_name = m.group(3)
            params = m.group(4)
            returns = m.group(5).strip() if m.group(5) else ""
            line = _get_line(src, m.start())

            # Qualify as ReceiverType.MethodName
            qual_name = f"{recv_type}.{method_name}"
            nid = _node_id(rel, qual_name)
            sig = f"func ({recv_name} {m.group(2)}) {method_name}({params})"
            if returns:
                sig += f" {returns}"

            nodes.append(GraphNode(
                id=nid,
                type=NodeType.method,
                name=method_name,
                qualified_name=f"{rel}::{qual_name}",
                display_name=qual_name,
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(
                    line_start=line,
                    line_end=_get_line(src, _find_brace_end(src, m.start())),
                ),
                signature=sig,
                metadata={
                    "support_level": "beta",
                    "receiver_type": recv_type,
                    "receiver_name": recv_name,
                    "is_pointer_receiver": m.group(2).startswith("*"),
                },
            ))

        # Struct declarations
        for m in _RE_TYPE_STRUCT.finditer(src):
            name = m.group(1)
            line = _get_line(src, m.start())
            seen_names[name] = seen_names.get(name, 0) + 1
            nid = _node_id(rel, name)

            # Extract embedded types from struct body
            brace_end = _find_brace_end(src, m.end() - 1)
            body = src[m.end():brace_end]
            for emb in _RE_STRUCT_EMBED.finditer(body):
                emb_type = emb.group(1).lstrip("*")
                emb_line = _get_line(src, m.end() + emb.start())
                struct_fields.append(RefEdge(
                    source_node_id=nid,
                    target_expression=emb_type,
                    target_qualified_name=emb_type,
                    line=emb_line,
                ))

            nodes.append(GraphNode(
                id=nid,
                type=NodeType.class_,  # structs map to class
                name=name,
                qualified_name=f"{rel}::{name}",
                display_name=name,
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(
                    line_start=line,
                    line_end=_get_line(src, brace_end),
                ),
                signature=f"type {name} struct",
                tags=["struct"],
                metadata={"support_level": "beta", "go_kind": "struct", "package": pkg_name},
            ))

        # Interface declarations
        for m in _RE_TYPE_INTERFACE.finditer(src):
            name = m.group(1)
            line = _get_line(src, m.start())
            seen_names[name] = seen_names.get(name, 0) + 1
            nid = _node_id(rel, name)

            # Extract interface method signatures
            brace_end = _find_brace_end(src, m.end() - 1)
            body = src[m.end():brace_end]
            for im in _RE_INTERFACE_METHOD.finditer(body):
                im_name = im.group(1)
                im_params = im.group(2) if im.group(2) else ""
                im_returns = im.group(3).strip() if im.group(3) else ""
                im_line = _get_line(src, m.end() + im.start())
                interface_methods.append(RefEdge(
                    source_node_id=nid,
                    target_expression=im_name,
                    target_qualified_name=im_name,
                    line=im_line,
                ))

            nodes.append(GraphNode(
                id=nid,
                type=NodeType.class_,  # interface maps to class
                name=name,
                qualified_name=f"{rel}::{name}",
                display_name=name,
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(
                    line_start=line,
                    line_end=_get_line(src, brace_end),
                ),
                signature=f"type {name} interface",
                tags=["interface"],
                metadata={"support_level": "beta", "go_kind": "interface", "package": pkg_name},
            ))

        # Constants
        for m in _RE_CONST.finditer(src):
            name = m.group(1)
            line = _get_line(src, m.start())
            nid = _node_id(rel, name)
            nodes.append(GraphNode(
                id=nid,
                type=NodeType.function,  # const maps to variable-like
                name=name,
                qualified_name=f"{rel}::{name}",
                display_name=name,
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(line_start=line, line_end=line),
                signature=f"const {name}",
                tags=["const"],
                metadata={"support_level": "beta", "go_kind": "const"},
            ))

        # Const blocks
        for block_match in _RE_CONST_BLOCK.finditer(src):
            block = block_match.group(1)
            block_start = src[:block_match.start()].count('\n') + 1
            for id_m in _RE_BLOCK_IDENT.finditer(block):
                name = id_m.group(1)
                line = block_start + block[:id_m.start()].count('\n')
                nid = _node_id(rel, name)
                nodes.append(GraphNode(
                    id=nid,
                    type=NodeType.function,
                    name=name,
                    qualified_name=f"{rel}::{name}",
                    display_name=name,
                    file_path=rel,
                    language_id=self.language_id,
                    language=self.language_id,
                    location=Location(line_start=line, line_end=line),
                    signature=f"const {name}",
                    tags=["const"],
                    metadata={"support_level": "beta", "go_kind": "const"},
                ))

        # Variables
        for m in _RE_VAR.finditer(src):
            name = m.group(1)
            line = _get_line(src, m.start())
            nid = _node_id(rel, name)
            nodes.append(GraphNode(
                id=nid,
                type=NodeType.function,
                name=name,
                qualified_name=f"{rel}::{name}",
                display_name=name,
                file_path=rel,
                language_id=self.language_id,
                language=self.language_id,
                location=Location(line_start=line, line_end=line),
                signature=f"var {name}",
                tags=["var"],
                metadata={"support_level": "beta", "go_kind": "var"},
            ))

        # Var blocks
        for block_match in _RE_VAR_BLOCK.finditer(src):
            block = block_match.group(1)
            block_start = src[:block_match.start()].count('\n') + 1
            for id_m in _RE_BLOCK_IDENT.finditer(block):
                name = id_m.group(1)
                line = block_start + block[:id_m.start()].count('\n')
                nid = _node_id(rel, name)
                nodes.append(GraphNode(
                    id=nid,
                    type=NodeType.function,
                    name=name,
                    qualified_name=f"{rel}::{name}",
                    display_name=name,
                    file_path=rel,
                    language_id=self.language_id,
                    language=self.language_id,
                    location=Location(line_start=line, line_end=line),
                    signature=f"var {name}",
                    tags=["var"],
                    metadata={"support_level": "beta", "go_kind": "var"},
                ))

        return nodes, struct_fields, interface_methods

    # ── Export extraction ────────────────────────────────────────────────

    def _extract_exports(self, symbols: list[GraphNode], rel: str) -> list[ExportInfo]:
        """Extract exports. In Go, capitalized names are exported."""
        exports: list[ExportInfo] = []
        exported_types = {NodeType.function, NodeType.method, NodeType.class_, NodeType.test}
        for s in symbols:
            if s.type in exported_types and s.name and s.name[0].isupper():
                exports.append(ExportInfo(
                    name=s.name,
                    node_id=s.id,
                    is_default=False,
                ))
        return exports

    # ── Call extraction ─────────────────────────────────────────────────

    def _extract_calls(
        self, src: str, symbols: list[GraphNode], rel: str
    ) -> list[CallEdge]:
        """Extract intra-file call edges from Go source."""
        calls: list[CallEdge] = []
        symbol_names = {s.name: s.id for s in symbols}

        # Build function/method boundaries to assign calls to the right caller
        func_boundaries = self._build_call_boundaries(src, symbols)

        # Find all function calls
        for m in _RE_CALL.finditer(src):
            expr = m.group(1)
            offset = m.start()
            line = _get_line(src, offset)

            # Skip if inside a string literal or comment
            if self._is_in_string_or_comment(src, offset):
                continue

            # Determine which function contains this call
            caller_id = self._find_enclosing_function(offset, func_boundaries, rel)

            # Detect constructor pattern
            call_expr = f"{expr}()"
            target_qualified = expr

            calls.append(CallEdge(
                source_node_id=caller_id or "",
                target_expression=expr,
                target_qualified_name=target_qualified,
                line=line,
                call_expr=call_expr,
                is_dynamic=False,
            ))

        # defer / go calls
        for m in _RE_DEFER_GO.finditer(src):
            expr = m.group(2)
            offset = m.start()
            line = _get_line(src, offset)
            if self._is_in_string_or_comment(src, offset):
                continue
            caller_id = self._find_enclosing_function(offset, func_boundaries, rel)
            calls.append(CallEdge(
                source_node_id=caller_id or "",
                target_expression=expr,
                target_qualified_name=expr,
                line=line,
                call_expr=f"{m.group(1)} {expr}()",
                is_dynamic=False,
            ))

        return calls

    def _build_call_boundaries(
        self, src: str, symbols: list[GraphNode]
    ) -> list[tuple[int, int, str]]:
        """Build a list of (start_offset, end_offset, node_id) for functions.

        Used to determine which function contains a given call site.
        """
        boundaries: list[tuple[int, int, str]] = []
        for s in symbols:
            if s.type in (NodeType.function, NodeType.method, NodeType.test):
                if s.location and s.location.line_start:
                    # Approximate offset from line
                    line_start = s.location.line_start
                    line_end = s.location.line_end
                    start_off = self._line_to_offset(src, line_start)
                    end_off = self._line_to_offset(src, line_end)
                    boundaries.append((start_off, end_off, s.id))
        boundaries.sort(key=lambda x: x[0])
        return boundaries

    def _line_to_offset(self, src: str, line: int) -> int:
        """Convert a 1-based line number to a character offset."""
        lines = src.split('\n')
        if line <= 1:
            return 0
        return sum(len(l) + 1 for l in lines[:line - 1])

    def _find_enclosing_function(
        self, offset: int, boundaries: list[tuple[int, int, str]], rel: str
    ) -> str | None:
        """Find the function node ID that contains the given offset."""
        for start, end, node_id in boundaries:
            if start <= offset <= end:
                return node_id
        return None

    def _is_in_string_or_comment(self, src: str, offset: int) -> bool:
        """Check if the given offset is inside a string literal or comment."""
        line_start = src.rfind('\n', 0, offset) + 1
        line = src[line_start:src.find('\n', offset)] if src.find('\n', offset) >= 0 else src[line_start:]
        stripped = _RE_COMMENT.sub('', line)
        # Rough check: if it's after // on the same line
        comment_pos = line.find('//')
        if comment_pos >= 0 and (offset - line_start) > comment_pos:
            return True
        # Check if inside backtick-quoted string
        before = src[:offset]
        backtick_count = before.count('`')
        if backtick_count % 2 == 1:
            return True
        return False

    # ── Reference extraction ─────────────────────────────────────────────

    def _extract_references(
        self,
        src: str,
        symbols: list[GraphNode],
        rel: str,
        struct_fields: list[RefEdge],
        interface_methods: list[RefEdge],
    ) -> list[RefEdge]:
        """Extract non-call references (embedded structs, interface methods, selector expressions)."""
        references: list[RefEdge] = list(struct_fields) + list(interface_methods)
        symbol_names = {s.name for s in symbols}

        # Selector expression references: pkg.Symbol, obj.Field
        for m in _RE_SELECTOR.finditer(src):
            obj = m.group(1)
            prop = m.group(2)
            offset = m.start()
            line = _get_line(src, offset)
            # Skip if followed by ( — that's a call
            if offset + len(m.group(0)) < len(src) and src[offset + len(m.group(0))] == '(':
                continue
            # Skip known patterns
            if obj in ("fmt", "os", "io", "net", "http", "json", "time", "sync", "log", "strings"):
                continue
            references.append(RefEdge(
                source_node_id="",
                target_expression=f"{obj}.{prop}",
                target_qualified_name=f"{obj}.{prop}",
                line=line,
            ))

        return references

    # ── Structural edges ─────────────────────────────────────────────────

    def _build_structural_edges(
        self,
        symbols: list[GraphNode],
        rel: str,
        pkg_name: str,
        imports: list[ImportInfo],
    ) -> list[GraphEdge]:
        """Build contains, defined_in, and imports edges."""
        edges: list[GraphEdge] = []
        file_id = rel
        module_id = f"go_pkg:{pkg_name}"

        for s in symbols:
            if s.type in (NodeType.file, NodeType.module):
                continue
            # contains: file → symbol
            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.contains,
                source=file_id,
                target=s.id,
                confidence=1.0,
                source_location=EdgeLocation(
                    file_path=rel,
                    line_start=s.location.line_start if s.location else 0,
                    line_end=s.location.line_end if s.location else 0,
                ),
                metadata=EdgeMetadata(
                    resolution=Resolution.exact_ast_match,
                    provenance="ast",
                    reason="symbol defined in file",
                ),
            ))
            # defined_in: symbol → package module
            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.defined_in,
                source=s.id,
                target=module_id,
                confidence=1.0,
                source_location=EdgeLocation(
                    file_path=rel,
                    line_start=s.location.line_start if s.location else 0,
                    line_end=s.location.line_end if s.location else 0,
                ),
                metadata=EdgeMetadata(
                    resolution=Resolution.exact_ast_match,
                    provenance="ast",
                    reason=f"symbol defined in package {pkg_name}",
                ),
            ))

        # imports edges: file → external package
        for imp in imports:
            if not imp.local_name or imp.local_name == "_":
                continue
            target = f"external:{imp.module_path}"
            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.imports,
                source=file_id,
                target=target,
                confidence=0.90 if not imp.is_external else 0.50,
                source_location=EdgeLocation(
                    file_path=rel,
                    line_start=imp.line,
                    line_end=imp.line,
                ),
                metadata=EdgeMetadata(
                    resolution=Resolution.package_import_exact if not imp.is_external else Resolution.external_module,
                    provenance="ast",
                    reason=f"import '{imp.module_path}' as '{imp.local_name}'",
                    evidence={
                        "import_path": imp.module_path,
                        "local_name": imp.local_name,
                        "is_external": imp.is_external,
                    },
                ),
            ))

        return edges

    def _calls_to_edges(
        self, calls: list[CallEdge], symbols: list[GraphNode], rel: str
    ) -> list[GraphEdge]:
        """Convert ``CallEdge`` structs to ``GraphEdge`` objects."""
        edges: list[GraphEdge] = []
        symbol_by_name = {s.name: s.id for s in symbols}
        # Also map qualified names (Receiver.Method)
        for s in symbols:
            if s.type == NodeType.method and "receiver_type" in s.metadata:
                qn = f"{s.metadata['receiver_type']}.{s.name}"
                symbol_by_name[qn] = s.id

        for c in calls:
            expr = c.target_expression
            target_id = symbol_by_name.get(expr)

            if target_id:
                resolution = Resolution.same_file_exact
                confidence = 0.95
            else:
                # Check if it's a package.func call
                if "." in expr:
                    parts = expr.split(".", 1)
                    # Check if the method name part matches any symbol
                    method_name = parts[1]
                    target_id = symbol_by_name.get(method_name)
                    if target_id:
                        resolution = Resolution.name_match_candidate
                        confidence = 0.35
                    else:
                        resolution = Resolution.unknown_external
                        confidence = 0.30
                else:
                    resolution = Resolution.name_match_candidate
                    confidence = 0.35

            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.calls,
                source=c.source_node_id or rel,
                target=target_id or f"unresolved:{expr}",
                confidence=confidence,
                source_location=EdgeLocation(
                    file_path=rel,
                    line_start=c.line,
                    line_end=c.line,
                ),
                metadata=EdgeMetadata(
                    resolution=resolution,
                    provenance="ast",
                    call_expr=c.call_expr,
                    reason=f"call to '{expr}'",
                ),
            ))

        return edges

    def _refs_to_edges(
        self, references: list[RefEdge], symbols: list[GraphNode], rel: str
    ) -> list[GraphEdge]:
        """Convert ``RefEdge`` structs to ``GraphEdge`` objects."""
        edges: list[GraphEdge] = []
        symbol_names = {s.name for s in symbols}

        for r in references:
            expr = r.target_expression
            target_id = f"unresolved:{expr}"
            resolution = Resolution.name_match_candidate
            confidence = 0.30

            # Try to resolve to a known symbol
            if expr in symbol_names:
                for s in symbols:
                    if s.name == expr:
                        target_id = s.id
                        resolution = Resolution.same_file_exact
                        confidence = 0.85
                        break
            elif "." in expr:
                parts = expr.split(".", 1)
                if parts[1] in symbol_names:
                    resolution = Resolution.embedded_method_candidate
                    confidence = 0.40

            edges.append(GraphEdge(
                id=_next_edge_id(),
                type=EdgeType.references,
                source=r.source_node_id or rel,
                target=target_id,
                confidence=confidence,
                source_location=EdgeLocation(
                    file_path=rel,
                    line_start=r.line,
                    line_end=r.line,
                ),
                metadata=EdgeMetadata(
                    resolution=resolution,
                    provenance="ast",
                    reason=f"reference to '{expr}'",
                ),
            ))

        return edges

    # ── Diagnostics ──────────────────────────────────────────────────────

    def _collect_diagnostics(self, src: str, rel: str) -> list[Diagnostic]:
        """Collect extraction diagnostics."""
        diags: list[Diagnostic] = []

        # Warn about cgo usage
        if 'import "C"' in src or "/* #cgo" in src:
            diags.append(Diagnostic(
                level="info",
                message="cgo detected in Go file — C interop symbols not extracted",
                file_path=rel,
                line=1,
            ))

        # Warn about build tags
        if re.search(r'^//go:build\s', src, re.MULTILINE):
            diags.append(Diagnostic(
                level="info",
                message="build tags detected — conditional compilation not resolved",
                file_path=rel,
                line=1,
            ))

        return diags
