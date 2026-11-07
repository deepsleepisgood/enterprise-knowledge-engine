"""Claim schemas: what the LLM returns, and the record resolution works on."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

ValueType = Literal["percentage", "money", "days", "date", "enum", "text", "list", "boolean"]
ClaimKind = Literal["rule", "practice", "definition", "procedure"]
ClaimStatus = Literal[
    "current", "superseded", "corroborating", "provisional", "pending", "rejected"
]


# --- LLM output (structured outputs) ------------------------------------------------------


class ExtractedValue(BaseModel):
    type: ValueType
    number: float | None = Field(
        None, description="Numeric value for percentage, money or days, in the unit given. 1% -> 1."
    )
    unit: str | None = Field(
        None,
        description="%, a money unit, days, working_days, hours, months, years, or null",
    )
    text: str = Field(description="The value in words as the passage states it")
    items: list[str] | None = Field(
        None, description="For list values: the items, e.g. materials or categories"
    )


class ExtractedClaim(BaseModel):
    topic: str = Field(description="A topic from the vocabulary, or 'other'")
    parameter: str = Field(description="A parameter of that topic from the vocabulary, or 'other'")
    proposed_name: str | None = Field(None, description="Only when topic or parameter is 'other'")
    subject: str | None = Field(
        None, description="Only when one parameter repeats for several items: the item"
    )
    client: str = Field(description="'all', or the client key the claim is limited to")
    materials: list[str] | None = Field(
        None, description="Materials or categories the claim is limited to"
    )
    value: ExtractedValue
    condition: str | None = Field(None, description="When the claim applies, if conditional")
    statement: str = Field(description="One plain sentence restating the claim")
    kind: ClaimKind
    quote: str = Field(
        description="The exact words in the passage that state this claim, copied verbatim"
    )


class ExtractionResult(BaseModel):
    claims: list[ExtractedClaim]


class CompareVerdict(BaseModel):
    verdict: Literal["same", "different", "narrower"]
    reason: str


# --- Record used by resolution and persistence ----------------------------------------------


@dataclass
class ClaimRec:
    key: str
    topic: str
    parameter: str
    client: str
    value: dict[str, Any]
    kind: str
    statement: str
    source_id: str
    source_kind: str
    source_status: str
    authority_rank: int
    valid_at: date | None
    source_valid_to: date | None = None
    passage_id: str | None = None
    condition: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    # set by resolution
    status: str = "pending"
    invalid_at: date | None = None
    supersedes_key: str | None = None
    reason: str | None = None


@dataclass
class ConflictRec:
    topic: str
    parameter: str
    client: str
    a_key: str
    b_key: str
    kind: str  # value | scope | self_contradiction | practice_vs_rule
    authoritative_key: str | None
    reason: str


@dataclass
class ResolveResult:
    claims: list[ClaimRec]
    conflicts: list[ConflictRec]
