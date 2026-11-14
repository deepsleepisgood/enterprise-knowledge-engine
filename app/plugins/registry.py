"""Plug-in discovery. Plug-ins are folders under PLUGINS_DIR, loaded by path at runtime.

The core never imports a plug-in package by name (a test enforces this). A plug-in folder has:
    plugin.yaml              name, title, calculators, entry module
    bindings.yaml            the parameters its calculators need, in plain language
    roles.yaml               who owns which topics (routing "who to ask")
    baseline_schema/schema.yaml   optional hand-written ontology (SCHEMA_MODE=baseline)
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from app.core.config import get_settings

_LOAD_LOCK = threading.RLock()  # re-entrant: loading a module may load its parent package


@dataclass
class Plugin:
    name: str
    path: Path
    manifest: dict[str, Any] = field(default_factory=dict)

    def file(self, rel: str) -> dict[str, Any]:
        p = self.path / rel
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {} if p.exists() else {}

    @property
    def title(self) -> str:
        return self.manifest.get("title", self.name)

    def baseline_schema(self) -> dict[str, Any] | None:
        data = self.file("baseline_schema/schema.yaml")
        return data or None

    def module(self, dotted: str) -> ModuleType:
        """Import `<plugin>/<dotted path>.py` by file path (e.g. 'calc.registry')."""
        modname = f"_plugin_{self.name}." + dotted
        # The module is in sys.modules before its code has run; without the lock a second
        # thread would get it half-loaded (missing names).
        with _LOAD_LOCK:
            if modname in sys.modules:
                return sys.modules[modname]
            return self._load(modname, dotted)

    def _load(self, modname: str, dotted: str) -> ModuleType:
        self._ensure_package()
        rel = Path(*dotted.split("."))
        target = self.path / f"{rel}.py"
        if not target.exists():
            target = self.path / rel / "__init__.py"
        parent = modname.rsplit(".", 1)[0]
        if parent != f"_plugin_{self.name}" and parent not in sys.modules:
            self.module(dotted.rsplit(".", 1)[0])
        spec = importlib.util.spec_from_file_location(
            modname,
            target,
            submodule_search_locations=[str(target.parent)]
            if target.name == "__init__.py"
            else None,
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            del sys.modules[modname]  # never leave a broken module for the next caller
            raise
        return mod

    def _ensure_package(self) -> None:
        root = f"_plugin_{self.name}"
        if root in sys.modules:
            return
        spec = importlib.util.spec_from_loader(root, loader=None, is_package=True)
        assert spec
        pkg = importlib.util.module_from_spec(spec)
        pkg.__path__ = [str(self.path)]  # type: ignore[attr-defined]
        sys.modules[root] = pkg


@lru_cache
def plugins() -> tuple[Plugin, ...]:
    s = get_settings()
    out = []
    for name in s.enabled_plugins:
        path = s.plugins_dir / name
        if not path.is_dir():
            continue
        manifest_path = path / "plugin.yaml"
        manifest = (
            yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            if manifest_path.exists()
            else {}
        )
        out.append(Plugin(name=manifest.get("name", name), path=path, manifest=manifest))
    return tuple(out)


def hooks(event: str) -> list[tuple[Plugin, Any]]:
    """Callables plug-ins declare for an event in plugin.yaml (`hooks: {event: module.func}`)."""
    out = []
    for p in plugins():
        ref = (p.manifest.get("hooks") or {}).get(event)
        if ref:
            mod, _, fn = ref.rpartition(".")
            out.append((p, getattr(p.module(mod), fn)))
    return out


def get(name: str) -> Plugin | None:
    return next((p for p in plugins() if p.name == name), None)


def roles() -> dict[str, dict[str, Any]]:
    """Roles plug-ins declare (roles.yaml): key -> {name, owns, topics, default_for, asker}.
    `asker: true` marks the people who ask questions: the router never sends a question back."""
    out: dict[str, dict[str, Any]] = {}
    for p in plugins():
        for key, r in (p.file(p.manifest.get("roles", "roles.yaml")).get("roles") or {}).items():
            out.setdefault(key, {"key": key, **(r or {})})
    return out


def baseline_schema() -> dict[str, Any] | None:
    """The first enabled plug-in's hand-written schema, for SCHEMA_MODE=baseline."""
    for p in plugins():
        data = p.baseline_schema()
        if data:
            return data
    return None
