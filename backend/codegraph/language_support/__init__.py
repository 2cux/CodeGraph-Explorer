"""Multi-language abstraction layer for CodeGraph Explorer.

Provides:
- LanguageRegistry: detect and manage supported languages
- LanguageExtractor: unified extraction interface per language
- Resolver: unified cross-file resolution interface per language
- PythonExtractor / PythonResolver: Python language implementation
"""

from codegraph.language_support.registry import (
    SupportLevel,
    LanguageRegistration,
    LanguageRegistry,
    get_registry,
)

from codegraph.language_support.extractor import (
    ExtractorResult,
    LanguageExtractor,
)

from codegraph.language_support.resolver import (
    Provenance,
    ResolvedEdge,
    ResolvedEdges,
    Resolver,
)

__all__ = [
    # Registry
    "SupportLevel",
    "LanguageRegistration",
    "LanguageRegistry",
    "get_registry",
    # Extractor
    "ExtractorResult",
    "LanguageExtractor",
    # Resolver
    "Provenance",
    "ResolvedEdge",
    "ResolvedEdges",
    "Resolver",
]
