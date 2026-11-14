"""Citation accuracy and outdated-answer detection (TEST_PLAN level 5)."""

from __future__ import annotations

import re
from typing import Any

from app.answer.verify import mentions, norm

UNITS = {"%": 0.01, "lakh": 100_000.0, "crore": 10_000_000.0, "₹": 1.0}

# ---------------------------------------------------------------- citations


def norm_loc(s: str) -> str:
    """'§4.2' = '4.2'; 'Part C (CM-INF-02)' = 'part c'; whitespace and case folded."""
    s = re.sub(r"\([^)]*\)", " ", s or "")
    s = s.replace("§", " ").lower()
    return re.sub(r"\s+", " ", s).strip(" .")


def gold_targets(file: str, section: str, also_valid: list[str]) -> list[tuple[str, list[str]]]:
    """(file, locator alternatives) pairs; '8.2 and 11' matches either section."""
    out = [(file, [x for x in re.split(r"\s+and\s+", section) if x.strip()] or [section])]
    for item in also_valid:
        m = re.match(r"(\S+\.\w{2,5})\s*(.*)", item.strip())
        if m:
            out.append((m.group(1), [m.group(2)] if m.group(2) else [""]))
    return out


def _loc_match(gold: str, cit: dict[str, Any], lenient: bool) -> bool:
    g = norm_loc(gold)
    if not g:
        return True  # a whole-file citation is all the key asks for
    loc, label = norm_loc(cit.get("locator", "")), norm_loc(cit.get("short_label", ""))
    if g in (loc, label) or label.endswith(" " + g) or loc.endswith(" " + g):
        return True
    if not lenient:
        return False
    base = g.split(",")[0].strip()  # "part b, step 3" -> "part b"
    numeric_gold = re.fullmatch(r"[\d.]+", g) is not None
    for cand in (loc, label):
        tail = cand.split(" ")[-1] if cand else ""
        if cand.startswith((g + ".", g + ",", base + ",", base + " ")) or cand == base:
            return True
        numeric = re.fullmatch(r"[\d.]+", g) and re.fullmatch(r"[\d.]+", tail)
        if numeric and (tail == g or tail.startswith(g + ".")):
            return True
        if base and (cand.endswith(" " + base) or f" {base}," in f" {cand}"):
            return True
        if numeric_gold and re.search(rf"(?<![\d.]){re.escape(g)}(?![\d])", cand):
            return True  # "Section 4.2 Price tolerance"
    return False


def citation_correct(
    card: dict[str, Any], file: str, section: str, also_valid: list[str], lenient: bool = False
) -> bool:
    cites = (card.get("rule") or {}).get("citations") or []
    tip = card.get("expert_tip") or {}
    if tip.get("citation"):
        cites = [*cites, tip["citation"]]
    for gfile, alts in gold_targets(file, section, also_valid):
        for c in cites:
            if (c.get("file") or "").lower() != gfile.lower():
                continue
            if any(_loc_match(a, c, lenient) for a in alts):
                return True
    return False


# ---------------------------------------------------------------- outdated answers


def current_text(card: dict[str, Any]) -> str:
    """The current-rule part of a card: rule text, decision and working (not older_sources)."""
    parts = [(card.get("rule") or {}).get("text") or "", card.get("decision") or ""]
    parts += [f"{w.get('label', '')} {w.get('value', '')}" for w in card.get("working") or []]
    return "\n".join(parts)


# Ways an answer explicitly rejects an old value ("{V}" is the value). Only the value inside such
# a phrase is ignored: "It is 1%, not 2%" rejects 2%, while "Use 2%, not 1%" still states 2%.
_REJECTED = [
    r"\b(?:not|never|instead of|rather than|no longer)\s+(?:the\s+|a\s+|an\s+)?{V}",
    r"{V}(?:\s+[\w-]+){{0,3}}?\s+(?:does not|doesn't|do not|don't|no longer|is not|isn't|"
    r"is no longer|are not|aren't)\s+(?:apply|applies|valid|in force|current|used)\b",
    r"{V}(?:\s+[\w-]+){{0,3}}?\s+(?:was|were|has been|have been|is|are)\s+"
    r"(?:replaced|superseded|withdrawn|retired|removed|outdated|obsolete)\b",
    r"\b(?:old|older|outdated|superseded|previous|former|legacy|withdrawn)\s+(?:[\w-]+\s+){{0,2}}?{V}",
    r"{V}(?:\s+[\w-]+){{0,2}}\s+(?:on|in|from|of)\s+(?:some\s+|the\s+|an?\s+)?"
    r"(?:old|older|outdated|legacy|previous|superseded)\b",
]
_FIGURE = re.compile(r"₹\s*[\d,.]+(?:\s*(?:lakh|crore))?|\d[\d,.]*\s*%|\w*\d\w*")


def _value_pattern(value: str) -> str:
    """The value with optional spaces or commas between its characters ('₹1,000' ~ '₹ 1000')."""
    chars = re.sub(r"[\s,]", "", value)
    return r"[\s,]*".join(re.escape(c) for c in chars)


def rejected_removed(text: str, must_not_say: str) -> str:
    """`text` with every mention of the must-not-say value (or of a figure in it) that the answer
    explicitly rejects replaced by a marker, so only mentions that state the value remain."""
    values = sorted({must_not_say, *_FIGURE.findall(must_not_say)}, key=len, reverse=True)
    for v in values:
        if not re.sub(r"[\s,]", "", v):
            continue
        val = rf"(?<![\w.]){_value_pattern(v)}(?![\w])" if v[-1].isalnum() else _value_pattern(v)
        for pat in _REJECTED:
            text = re.sub(pat.format(V=val), " [rejected value] ", text, flags=re.I)
    return text


def outdated(card: dict[str, Any], must_not_say: str | None) -> bool:
    """True if the must-not-say value appears in the current-rule part of the card.

    String match after normalisation, or every amount / percentage in the must-not-say value
    appearing as the same kind of figure (so '₹1,000' matches 'Rs 1000' and '₹1 thousand' does
    not slip through as text). A mention the answer explicitly rejects ("the 2% tolerance does
    not apply", "not 2%", "the old 2% setting") is not a statement of the value and is ignored
    (`rejected_removed`); any other mention still counts."""
    if not must_not_say:
        return False
    text = rejected_removed(current_text(card), must_not_say)
    t, m = norm(text), norm(must_not_say)
    squash = lambda s: re.sub(r"[\s,]", "", s)  # noqa: E731
    if squash(m) and re.search(rf"(?<![\d.]){re.escape(squash(m))}", squash(t)):
        return True
    want = mentions(must_not_say, UNITS, ["₹", "rs", "inr"])
    have = mentions(text, UNITS, ["₹", "rs", "inr"])
    figures = [(k, v) for k in ("percentage", "money") for v in want[k]]
    if figures and all(v in have[k] for k, v in figures):
        return True
    words = re.findall(r"[a-z]+", m)
    nums = re.findall(r"\d+(?:\.\d+)?", m)
    if not figures and nums:
        # e.g. "60 days": the number with its unit word, never the unit word alone.
        unit = rf"\s*{words[0]}" if len(words) == 1 else ""
        return all(re.search(rf"(?<![\d.]){re.escape(n)}{unit}\b", t) for n in nums)
    if not figures and len(words) == 1 and len(words[0]) > 3:  # e.g. "Thursday"
        return re.search(rf"\b{words[0]}\b", t) is not None
    return False
