"""Answer verification (BUILD_PLAN Phase 4), in order:

1. Every cited passage was in the evidence, and its quote occurs in the passage text.
2. Every number in rule.text appears in a cited passage, the calculator output or the question.
3. No value that is not in force (superseded, overridden, or not yet valid on the day asked)
   appears in rule.text for the attributes the answer is about (deterministic, from the facts).
4. A MODEL_FAST support check confirms each sentence is backed by its cited evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, Field

from app.store.facts import FactRow

PROMPT_VERSION = "support-v2"

# ---------------------------------------------------------------- text helpers

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_QUOTES).lower()
    return re.sub(r"\s+", " ", s).strip()


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;:])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


def find_quote(quote: str, passage: str) -> str | None:
    """The quote as it appears in the passage (exact after normalising), else a near-identical
    passage sentence (ratio >= 0.9). Quotes with '...' must match part by part."""
    q, p = norm(quote).strip(" .\"'"), norm(passage)
    if not q:
        return None
    parts = [x.strip(" .") for x in re.split(r"\.\.\.|…", q) if x.strip(" .")]
    if parts and all(x in p for x in parts):
        return quote.strip()
    for sent in _sentences(passage):
        if SequenceMatcher(None, q, norm(sent)).ratio() >= 0.9:
            return sent
    return None


def best_sentence(passage: str, claim: str) -> str:
    """The passage sentence sharing the most words with `claim` (a real span, never invented)."""
    words = set(re.findall(r"[a-z0-9]+", norm(claim)))
    sents = _sentences(passage) or [passage.strip()]
    return max(sents, key=lambda s: len(words & set(re.findall(r"[a-z0-9]+", norm(s)))))[:400]


# ---------------------------------------------------------------- numbers

_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}


def scales(units: dict[str, float] | None) -> dict[str, float]:
    """Number words with their multipliers: generic ones plus the schema's word units > 1."""
    out = dict(_SCALES)
    for k, v in (units or {}).items():
        if v and v > 1 and k.isalpha():
            out[k.lower()] = float(v)
    return out


_ORDINAL = re.compile(r"\b(first|second|third|fourth|fifth)\b")
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}


def numbers(text: str) -> set[float]:
    """Numbers written with digits ('4,80,000' and '480,000' are both 480000)."""
    out = set()
    for m in _NUM.findall(text):
        m = m.rstrip(",")
        try:
            out.add(float(m.replace(",", "")))
        except ValueError:
            continue
    return out


def word_numbers(text: str, units: dict[str, float] | None = None) -> set[float]:
    """Numbers written in words ('five hundred' -> 500, 'two' -> 2, 'second' -> 2)."""
    out: set[float] = set()
    sc = scales(units)
    total = current = 0
    seen = False
    for w in [*re.findall(r"[a-z]+", text.lower()), "."]:
        if w in _WORDS:
            current += _WORDS[w]
            seen = True
        elif w in sc and seen:
            current = max(current, 1) * sc[w]
            if sc[w] >= 1000:
                total += current
                current = 0
        elif w == "and" and seen:
            continue
        else:
            if seen:
                out.add(float(total + current))
            total = current = 0
            seen = False
    out.update(float(_ORD[m]) for m in _ORDINAL.findall(text.lower()))
    return out


def _strip_markers(text: str) -> str:
    return re.sub(r"\[\d+\]", " ", text)


def check_numbers(
    rule_text: str, allowed_texts: list[str], units: dict[str, float] | None = None
) -> list[str]:
    allowed: set[float] = set()
    for t in allowed_texts:
        allowed |= numbers(t) | word_numbers(t, units)
    bad = sorted(n for n in numbers(_strip_markers(rule_text)) if n not in allowed)
    return [f"the number {n:g} is not in any cited passage or the calculator output" for n in bad]


# ---------------------------------------------------------------- values not in force


def _currency_re(units: dict[str, float], currencies: list[str]) -> str:
    """Currency markers: the schema's base currency and its symbol units (multiplier 1)."""
    marks = {c.lower() for c in currencies if c}
    marks |= {k.lower() for k, v in units.items() if v == 1 and k and not k[0].isalnum()}
    marks |= {"$", "€", "£"}
    return "(?:" + "|".join(sorted(map(re.escape, marks), key=len, reverse=True)) + ")"


def mentions(
    text: str, units: dict[str, float], currencies: list[str] | None = None
) -> dict[str, set[float]]:
    """Percentages, money (in base units, using the schema's unit multipliers) and day counts."""
    t = norm(_strip_markers(text))
    scale = {k: v for k, v in scales(units).items() if v > 1}
    scale_re = "|".join(sorted(map(re.escape, scale), key=len, reverse=True)) or "(?!x)x"
    pct = {
        float(m.replace(",", "")) for m in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*(?:%|per ?cent)", t)
    }
    money: set[float] = set()
    num_re = r"(\d[\d,]*(?:\.\d+)?)"
    cur_re = _currency_re(units, currencies or [])
    money_re = rf"{cur_re}\s*{num_re}(?:\s*({scale_re}))?|{num_re}\s*({scale_re})\b"
    for m in re.finditer(money_re, t):
        num = m.group(1) or m.group(3)
        unit = m.group(2) or m.group(4)
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        money.add(v * scale.get((unit or "").lower(), 1.0))
    days = {float(m) for m in re.findall(r"(\d+)\s*(?:working |calendar |business )?days?\b", t)}
    return {"percentage": pct, "money": money, "days": days}


def _kind(v: dict[str, Any]) -> str | None:
    typ, unit = (v.get("type") or "").lower(), (v.get("unit") or "").lower()
    if typ == "percentage" or unit in ("%", "percent"):
        return "percentage"
    if typ == "money":
        return "money"
    if typ in ("days", "duration") or "day" in unit:
        return "days"
    return None


def check_not_in_force(
    rule_text: str,
    not_in_force: list[FactRow],
    in_force: list[FactRow],
    units: dict[str, float],
    when: str = "current",
    currencies: list[str] | None = None,
) -> list[str]:
    found = mentions(rule_text, units, currencies)
    in_force_keys = {(f.subject_id, f.attribute) for f in in_force}
    not_in_force = [f for f in not_in_force if (f.subject_id, f.attribute) in in_force_keys]
    t = norm(_strip_markers(rule_text))
    problems = []
    for old in not_in_force:
        attr_now = [
            f for f in in_force if f.attribute == old.attribute and f.subject_id == old.subject_id
        ]
        kind = _kind(old.value)
        n = old.value.get("number")
        if kind and n is not None:
            if any(f.value.get("number") == n for f in attr_now):
                continue
            if float(n) in found[kind]:
                problems.append(
                    f"'{old.value.get('text') or n}' ({old.attribute}) is not the {when} rule "
                    f"({old.status}, {old.source_label or 'older source'}); do not state it"
                )
        elif old.status == "superseded":
            txt = norm(str(old.value.get("text") or ""))
            if (
                len(txt) >= 6
                and txt in t
                and not any(txt in norm(str(f.value.get("text") or "")) for f in attr_now)
            ):
                problems.append(f"'{old.value.get('text')}' ({old.attribute}) is not in force")
    return problems


# ---------------------------------------------------------------- support check


class SupportItem(BaseModel):
    sentence: int
    supported: bool
    problem: str = Field("", description="What is not backed by the evidence, if anything")


class SupportOut(BaseModel):
    items: list[SupportItem]


SUPPORT_SYSTEM = """You check an answer sentence by sentence against the evidence it cites.
A sentence is supported when the cited evidence states it or it follows directly from it
(restating a calculator result counts as supported when the calculator output is given).
It is NOT supported if it adds facts, numbers, conditions or advice the evidence does not
contain, or if it presents an older or different value as the rule. Be strict but fair:
paraphrase is fine. The facts of the asker's own case (figures, names and dates stated in the
question) are given: repeating them is supported. Return one item per sentence."""


def support_check(
    sentences: list[tuple[str, list[tuple[str, str]]]],
    calc_text: str | None,
    structured_fn: Callable[..., Any],
    question: str = "",
) -> list[str]:
    """`sentences`: (text, [(label, passage text)]). Returns the problems found."""
    if not sentences:
        return []
    blocks = [f"Question (the asker's case, given): {question}"] if question else []
    for i, (text, cited) in enumerate(sentences, start=1):
        ev = "\n".join(f"    [{lbl}] {body[:1500]}" for lbl, body in cited)
        blocks.append(f"Sentence {i}: {text}\n  Evidence:\n{ev}")
    if calc_text:
        blocks.append(f"Calculator output (evidence for every sentence):\n{calc_text}")
    out: SupportOut = structured_fn(
        "\n\n".join(blocks),
        SupportOut,
        system=SUPPORT_SYSTEM,
        model="fast",
        prompt_version=PROMPT_VERSION,
        max_tokens=2048,
    )
    problems = []
    for item in out.items:
        if not item.supported and 1 <= item.sentence <= len(sentences):
            problems.append(
                f"sentence {item.sentence} is not supported by its citations: "
                f"{item.problem or 'no backing found'}"
            )
    return problems
