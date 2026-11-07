"""Shared pieces for calculators.

A calculator is a pure function: typed inputs + a `Rules` lookup -> CalcResult.
It never holds a threshold itself (CLAUDE.md rule 2): every number comes from a
current claim, found through the pack's calculators.yaml mapping. A missing rule
raises RuleNotFound; there is no fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from app.core.pack import Pack, get_pack
from app.graph.rules import RuleNotFound, RuleValue


class Rules(Protocol):
    def get(
        self, topic: str, parameter: str, client: str | None = None, as_of: date | None = None
    ) -> RuleValue: ...


class DbRules:
    """Rules read from the claims graph."""

    def __init__(self, session: Any, today: date | None = None) -> None:
        self.session = session
        self.today = today

    def get(
        self, topic: str, parameter: str, client: str | None = None, as_of: date | None = None
    ) -> RuleValue:
        from app.graph.rules import get_rule

        return get_rule(
            self.session, topic, parameter, client=client, as_of=as_of, today=self.today
        )


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
        if all(c.claim_id != rule.claim_id for c in self.citations):
            self.citations.append(rule)
        return rule


def config(family: str, pack: Pack | None = None) -> dict[str, Any]:
    cfg = (pack or get_pack()).pack_file("calculators.yaml").get("calculators", {}).get(family)
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
