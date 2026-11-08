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


def outdated(card: dict[str, Any], must_not_say: str | None) -> bool:
    """True if the must-not-say value appears in the current-rule part of the card.

    String match after normalisation, or every amount / percentage in the must-not-say value
    appearing as the same kind of figure (so '₹1,000' matches 'Rs 1000' and '₹1 thousand' does
    not slip through as text)."""
    if not must_not_say:
        return False
    text = current_text(card)
    t, m = norm(text), norm(must_not_say)
    squash = lambda s: re.sub(r"[\s,]", "", s)  # noqa: E731
    if squash(m) and squash(m) in squash(t):
        return True
    want = mentions(must_not_say, UNITS, ["₹", "rs", "inr"])
    have = mentions(text, UNITS, ["₹", "rs", "inr"])
    figures = [(k, v) for k in ("percentage", "money") for v in want[k]]
    if figures and all(v in have[k] for k, v in figures):
        return True
    words = re.findall(r"[a-z]+", m)
    if not figures and len(words) == 1 and len(words[0]) > 3:  # e.g. "Thursday"
        return re.search(rf"\b{words[0]}\b", t) is not None
    return False
