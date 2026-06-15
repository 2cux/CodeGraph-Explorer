"""Simple in-process harness module registry."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from codegraph.harness.manifest import manifest_for
from codegraph.harness.models import HarnessModuleManifest

_MODULES: dict[str, "HarnessModule"] = {}
_BUILTIN_MODULES_REGISTERED = False


@runtime_checkable
class HarnessModule(Protocol):
    """Protocol implemented by runnable harness modules."""

    manifest: HarnessModuleManifest | dict[str, Any]

    def run(self, ctx: Any, input_data: dict[str, Any]) -> dict[str, Any] | None:
        """Execute the module and return a structured output payload."""


def register_module(module: HarnessModule | type[HarnessModule]) -> HarnessModule:
    """Register a harness module instance or class."""
    instance = module() if isinstance(module, type) else module
    manifest = _coerce_manifest(instance)
    _MODULES[manifest.id] = instance
    return instance


def get_module(module_id: str) -> HarnessModule | None:
    """Return a registered module instance by id."""
    if module_id not in _MODULES:
        _ensure_builtin_modules_registered(module_id)
    return _MODULES.get(module_id)


def list_modules() -> list[HarnessModuleManifest]:
    """Return manifests for all registered modules."""
    if not _MODULES:
        _ensure_builtin_modules_registered()
    manifests = [_coerce_manifest(module) for module in _MODULES.values()]
    return sorted(manifests, key=lambda manifest: manifest.id)


def builtin_modules_registered() -> bool:
    """Return whether builtin modules were already registered."""
    return _BUILTIN_MODULES_REGISTERED


def mark_builtin_modules_registered() -> None:
    """Mark builtin module registration as complete."""
    global _BUILTIN_MODULES_REGISTERED
    _BUILTIN_MODULES_REGISTERED = True


def reset_builtin_modules_registered() -> None:
    """Reset builtin registration marker for tests."""
    global _BUILTIN_MODULES_REGISTERED
    _BUILTIN_MODULES_REGISTERED = False


def _coerce_manifest(module: HarnessModule) -> HarnessModuleManifest:
    """Normalize a module's manifest into ``HarnessModuleManifest``."""
    raw_manifest = getattr(module, "manifest", None)
    if raw_manifest is None:
        raise ValueError(f"Module {module!r} does not define a manifest")
    if isinstance(raw_manifest, HarnessModuleManifest):
        return raw_manifest
    if not isinstance(raw_manifest, dict):
        raise TypeError(
            f"Module {module!r} manifest must be a HarnessModuleManifest or dict"
        )

    data = dict(raw_manifest)
    module_id = data.get("id") or data.get("module_id")
    if not module_id:
        raise ValueError(f"Module {module!r} manifest is missing 'id'")
    data["id"] = module_id
    return HarnessModuleManifest.model_validate(data)


def _ensure_builtin_modules_registered(module_id: str | None = None) -> None:
    """Register builtin modules lazily only when a builtin is requested."""
    if _BUILTIN_MODULES_REGISTERED:
        return
    if module_id is not None:
        try:
            manifest_for(module_id)
        except KeyError:
            return
    from codegraph.harness.bootstrap import register_builtin_modules

    register_builtin_modules()
