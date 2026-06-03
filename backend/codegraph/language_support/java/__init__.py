"""Java language support — beta.

Provides JavaExtractor, JavaResolver, and SpringResolver for
Java + Spring Boot code graph indexing.
"""

from codegraph.language_support.java.extractor import JavaExtractor
from codegraph.language_support.java.resolver import JavaResolver
from codegraph.language_support.java.frameworks import SpringResolver

__all__ = ["JavaExtractor", "JavaResolver", "SpringResolver"]
