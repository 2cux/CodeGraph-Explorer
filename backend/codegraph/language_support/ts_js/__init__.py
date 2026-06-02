"""TypeScript / JavaScript language support for CodeGraph Explorer.

Provides:
- TypeScriptExtractor: tree-sitter based TS/TSX file extraction
- JavaScriptExtractor: tree-sitter based JS/JSX/MJS/CJS file extraction
- TypeScriptResolver: cross-file import resolution for TypeScript
- JavaScriptResolver: cross-file import resolution for JavaScript
- TreeSitterParser: shared parser adapter
"""

from codegraph.language_support.ts_js.extractor import (
    TypeScriptExtractor,
    JavaScriptExtractor,
)
from codegraph.language_support.ts_js.resolver import (
    TypeScriptResolver,
    JavaScriptResolver,
)
from codegraph.language_support.ts_js.parser import (
    TreeSitterParser,
    get_parser,
)

__all__ = [
    "TypeScriptExtractor",
    "JavaScriptExtractor",
    "TypeScriptResolver",
    "JavaScriptResolver",
    "TreeSitterParser",
    "get_parser",
]
