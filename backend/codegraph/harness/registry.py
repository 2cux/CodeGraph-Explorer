"""Simple in-process harness module registry."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from codegraph.harness.models import HarnessModuleManifest

_MODULES: dict[str, "HarnessModule"] = {}


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
    return _MODULES.get(module_id)


def list_modules() -> list[HarnessModuleManifest]:
    """Return manifests for all registered modules."""
    manifests = [_coerce_manifest(module) for module in _MODULES.values()]
    return sorted(manifests, key=lambda manifest: manifest.id)


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
