"""The ontology a tenant's graph is built with (schema induction output, or a plug-in baseline).

Attributes are keyed `<topic>.<parameter>`. Facts about a rule hang off the topic's entity
(type `topic`); facts about one named thing (a supplier, a system) hang off that entity.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

ValueType = Literal[
    "percentage", "money", "days", "number", "date", "enum", "text", "list", "boolean"
]
Risk = Literal["high", "medium", "low"]


class EntityType(BaseModel):
    name: str
    description: str = ""


class Topic(BaseModel):
    key: str = Field(description="snake_case topic key")
    label: str
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)
    risk: Risk = "low"


class Attribute(BaseModel):
    key: str = Field(description="<topic>.<parameter>, snake_case")
    topic: str
    label: str
    description: str = ""
    value_type: ValueType
    unit: str | None = None
    synonyms: list[str] = Field(default_factory=list)


class SourceRank(BaseModel):
    doc_type: str
    rank: int = Field(description="1 = most authoritative")
    practice: bool = Field(False, description="Records personal practice, never rules")
    reason: str = ""


class SenderAuthority(BaseModel):
    who: str = Field(description="A role, team or person")
    client: str = Field("all", description="The scope they may change")
    topics: list[str] = Field(default_factory=list, description="Topic keys, or ['all']")


class Ontology(BaseModel):
    name: str = "induced"
    base_currency: str | None = None
    units: dict[str, float] = Field(default_factory=dict, description="Unit -> multiplier")
    entity_types: list[EntityType] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)
    attributes: list[Attribute] = Field(default_factory=list)
    source_ranking: list[SourceRank] = Field(default_factory=list)
    scope_keys: list[str] = Field(default_factory=lambda: ["client"])
    sender_authority: list[SenderAuthority] = Field(default_factory=list)

    # ------------------------------------------------------------ lookups

    def attribute(self, key: str) -> Attribute | None:
        return next((a for a in self.attributes if a.key == key), None)

    def topic(self, key: str) -> Topic | None:
        return next((t for t in self.topics if t.key == key), None)

    def rank_of(self, doc_type: str) -> SourceRank:
        for r in self.source_ranking:
            if r.doc_type == doc_type:
                return r
        worst = max((r.rank for r in self.source_ranking), default=8)
        return SourceRank(doc_type=doc_type, rank=worst + 1, reason="not ranked")

    def risk_of(self, topic_key: str) -> str:
        t = self.topic(topic_key)
        return t.risk if t else "low"

    def find_attributes(self, phrase: str) -> list[Attribute]:
        """Attributes whose key, label or synonyms mention `phrase` (for bindings and rules)."""
        p = _norm(phrase)
        out = []
        for a in self.attributes:
            topic = self.topic(a.topic)
            names = [a.key, a.label, *a.synonyms, *(topic.synonyms if topic else [])]
            if any(p == _norm(n) or p in _norm(n) for n in names):
                out.append(a)
        return out

    def prompt_text(self) -> str:
        """The vocabulary as shown to the extractor."""
        lines = []
        for t in self.topics:
            syn = f" (also: {', '.join(t.synonyms[:8])})" if t.synonyms else ""
            lines.append(f"{t.key}: {t.label}{syn}")
            for a in self.attributes:
                if a.topic == t.key:
                    unit = f", unit {a.unit}" if a.unit else ""
                    desc = f" — {a.description}" if a.description else ""
                    lines.append(f"  - {a.key} [{a.value_type}{unit}]{desc}")
        return "\n".join(lines)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def load(data: dict[str, Any]) -> Ontology:
    return Ontology.model_validate(data)
