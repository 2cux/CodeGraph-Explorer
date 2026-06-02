"""Language registry — detects and manages supported languages.

Provides extension-match and filename-match detection, enable/disable,
and support-level classification.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


# ── Support level ──────────────────────────────────────────────────────

class SupportLevel(str, Enum):
    """Production readiness tier for a registered language."""
    PRODUCTION = "production"
    BETA = "beta"
    EXPERIMENTAL = "experimental"
    UNSUPPORTED = "unsupported"


# ── Registration model ──────────────────────────────────────────────────

class LanguageRegistration(BaseModel):
    """Describes a single registered language.

    A file matches this language when its extension appears in *extensions*
    **or** its filename (basename) appears in *filenames*.
    """

    language_id: str
    extensions: list[str] = Field(default_factory=list)
    filenames: list[str] = Field(default_factory=list)
    support_level: SupportLevel = SupportLevel.PRODUCTION
    enabled: bool = True


# ── Registry ────────────────────────────────────────────────────────────

class LanguageRegistry:
    """Detect and manage registered languages.

    Usage::

        reg = LanguageRegistry()
        reg.register(LanguageRegistration(
            language_id="python",
            extensions=[".py", ".pyi"],
            support_level=SupportLevel.PRODUCTION,
        ))

        lang = reg.detect("src/app/auth.py")   # → "python"
        lang = reg.detect("README.md")         # → None
    """

    def __init__(self) -> None:
        self._languages: dict[str, LanguageRegistration] = {}
        # Fast lookup: extension (with dot) → language_id
        self._ext_map: dict[str, str] = {}
        # Fast lookup: basename → language_id
        self._name_map: dict[str, str] = {}

    # ── registration ──────────────────────────────────────────────────

    def register(self, reg: LanguageRegistration) -> None:
        """Register (or replace) a language."""
        self._languages[reg.language_id] = reg

        # Rebuild lookup maps
        if reg.enabled:
            for ext in reg.extensions:
                normalized = ext if ext.startswith(".") else f".{ext}"
                self._ext_map[normalized] = reg.language_id
            for fname in reg.filenames:
                self._name_map[fname] = reg.language_id
        else:
            for ext in reg.extensions:
                normalized = ext if ext.startswith(".") else f".{ext}"
                self._ext_map.pop(normalized, None)
            for fname in reg.filenames:
                self._name_map.pop(fname, None)

    def unregister(self, language_id: str) -> None:
        """Remove a language registration."""
        reg = self._languages.pop(language_id, None)
        if reg:
            for ext in reg.extensions:
                normalized = ext if ext.startswith(".") else f".{ext}"
                self._ext_map.pop(normalized, None)
            for fname in reg.filenames:
                self._name_map.pop(fname, None)

    # ── detection ─────────────────────────────────────────────────────

    def detect(self, file_path: str | Path) -> str | None:
        """Return *language_id* for *file_path*, or ``None`` if unsupported.

        Matching order:
        1. Extension (suffix) match
        2. Filename (basename) match
        """
        path = Path(file_path)
        suffix = path.suffix
        basename = path.name

        # Extension match
        if suffix in self._ext_map:
            lang_id = self._ext_map[suffix]
            reg = self._languages.get(lang_id)
            if reg and reg.enabled:
                return lang_id

        # Filename match (e.g. "Makefile", "Dockerfile")
        if basename in self._name_map:
            lang_id = self._name_map[basename]
            reg = self._languages.get(lang_id)
            if reg and reg.enabled:
                return lang_id

        return None

    def is_supported(self, file_path: str | Path) -> bool:
        """Return ``True`` when *file_path* matches a registered, enabled language."""
        return self.detect(file_path) is not None

    # ── access ────────────────────────────────────────────────────────

    def get(self, language_id: str) -> LanguageRegistration | None:
        """Return the registration for *language_id*, or ``None``."""
        return self._languages.get(language_id)

    def list_enabled(self) -> list[LanguageRegistration]:
        """Return all enabled registrations."""
        return [r for r in self._languages.values() if r.enabled]

    def list_all(self) -> list[LanguageRegistration]:
        """Return all registrations, including disabled."""
        return list(self._languages.values())

    def language_ids(self) -> list[str]:
        """Return list of enabled language IDs."""
        return [r.language_id for r in self._languages.values() if r.enabled]

    def __len__(self) -> int:
        return len(self._languages)

    def __contains__(self, language_id: str) -> bool:
        return language_id in self._languages


# ── Singleton access ───────────────────────────────────────────────────

_registry: LanguageRegistry | None = None


def get_registry() -> LanguageRegistry:
    """Return the singleton :class:`LanguageRegistry`, creating it with
    default registrations on first call.

    Default registrations:
    - ``python``: ``.py``, ``.pyi`` — production
    """
    global _registry
    if _registry is None:
        _registry = LanguageRegistry()
        _registry.register(LanguageRegistration(
            language_id="python",
            extensions=[".py", ".pyi"],
            filenames=[],
            support_level=SupportLevel.PRODUCTION,
            enabled=True,
        ))
    return _registry


def reset_registry() -> None:
    """Reset the singleton registry (useful for tests)."""
    global _registry
    _registry = None
