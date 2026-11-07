"""Run a plug-in calculator against the graph: the only way the core invokes plug-in maths.

The plug-in's entry module (plugin.yaml `entry`, e.g. `calc.registry`) must expose
`CALCULATORS` and `run(family, params, rules)`. Rules come from `BoundRules`, so every threshold
is a current fact reached through the plug-in's bindings.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.graph.ontology import Ontology
from app.plugins import registry
from app.plugins.bindings import BoundRules


def entry(plugin: str) -> Any:
    p = registry.get(plugin)
    if p is None:
        raise LookupError(f"plug-in {plugin!r} is not enabled")
    return p.module(p.manifest.get("entry", "calc.registry"))


def families(plugin: str) -> list[str]:
    return list(entry(plugin).CALCULATORS)


def calculate(
    session: Session,
    onto: Ontology,
    plugin: str,
    family: str,
    params: dict[str, Any],
    today: date | None = None,
) -> Any:
    rules = BoundRules(session, onto, plugin, today=today)
    return entry(plugin).run(family, params, rules)
