"""Go language support — beta.

Provides Go source extraction, cross-file resolution, and Gin / Hertz
framework route detection for the CodeGraph Explorer MCP toolkit.
"""

from codegraph.language_support.go.extractor import GoExtractor
from codegraph.language_support.go.resolver import GoResolver
from codegraph.language_support.go.frameworks import GinResolver, HertzResolver, extract_go_frameworks

__all__ = ["GoExtractor", "GoResolver", "GinResolver", "HertzResolver", "extract_go_frameworks"]
