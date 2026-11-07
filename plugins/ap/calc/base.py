"""Shared pieces for calculators.

A calculator is a pure function: typed inputs + a `Rules` lookup -> CalcResult.
It never holds a threshold itself (CLAUDE.md rule 2): every number comes from a current
fact in the graph, read through the plug-in's bindings (calculators.yaml names the bound
parameters). A missing rule or binding raises RuleNotFound; there is no fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from app.graph.rules import RuleNotFound, RuleValue

PLUGIN_DIR = Path(__file__).resolve().parents[1]


class Rules(Protocol):
    def get(
        self, topic: str, parameter: str, client: str | None = None, as_of: date | None = None
    ) -> RuleValue: ...


@dataclass
class Step:
    label: str
    value: str


@dataclass
class CalcResult:
    family: str
    decision: str
    passed: bool | None
    exception_code: str | None = None
    next_owner: str | None = None
    working: list[Step] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    citations: list[RuleValue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def cite(self, rule: RuleValue) -> RuleValue:
        if all(c.fact_id != rule.fact_id for c in self.citations):
            self.citations.append(rule)
        return rule


@lru_cache
def calculators_yaml() -> dict[str, Any]:
    return yaml.safe_load((PLUGIN_DIR / "calculators.yaml").read_text(encoding="utf-8"))


def config(family: str) -> dict[str, Any]:
    cfg = calculators_yaml().get("calculators", {}).get(family)
    if cfg is None:
        raise KeyError(f"calculators.yaml has no entry for {family!r}")
    return cfg


def rule(
    rules: Rules,
    cfg: dict[str, Any],
    key: str,
    client: str | None = None,
    as_of: date | None = None,
) -> RuleValue:
    ref = cfg["rules"].get(key)
    if not ref:
        raise RuleNotFound(f"calculators.yaml maps no rule for {key!r}")
    topic, _, parameter = ref.partition(".")
    return rules.get(topic, parameter, client=client, as_of=as_of)


def inr(amount: float) -> str:
    """Indian digit grouping: 197500 -> '₹1,97,500'; keeps paise when present."""
    neg = amount < 0
    whole, frac = f"{abs(amount):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    s = ",".join([*groups, tail]) if groups else tail
    return f"{'-' if neg else ''}₹{s}" + ("" if frac == "00" else f".{frac}")


def pct(n: float) -> str:
    return f"{n:g}%"


def fmt_day(d: date) -> str:
    return f"{d:%A} {d.day} {d:%B %Y}"
