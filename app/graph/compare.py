"""Do two claims state the same value?

`compare_values` is deterministic and answers "unknown" when wording differs and it
cannot tell. `LLMComparator` asks MODEL_FAST only for those cases (cached on disk).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from app.graph.schema import ClaimRec, CompareVerdict

Verdict = Literal["same", "different", "narrower", "unknown"]
Comparator = Callable[[ClaimRec, ClaimRec], Verdict]

NUMERIC = {"percentage", "money", "days"}


def _norm_text(s: str) -> str:
    s = s.lower().replace("per cent", "%").replace("percent", "%")
    s = re.sub(r"[^\w%₹. ]+", " ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)  # keep dots only inside numbers ("1.5")
    return re.sub(r"\s+", " ", s).strip()


def _norm_items(items: list[str] | None) -> set[str]:
    return {_norm_text(i).rstrip("s") for i in items or [] if i.strip()}


def compare_values(a: dict[str, Any], b: dict[str, Any]) -> Verdict:
    ta, tb = a.get("type"), b.get("type")
    na, nb = a.get("number"), b.get("number")
    if ta in NUMERIC and tb in NUMERIC:
        if na is None or nb is None:
            return "unknown"
        if (a.get("unit") or "") != (b.get("unit") or ""):
            return "unknown"  # e.g. days vs working_days: not comparable by number alone
        return "same" if abs(float(na) - float(nb)) < 1e-9 else "different"
    if ta == tb == "list":
        sa, sb = _norm_items(a.get("items")), _norm_items(b.get("items"))
        if not sa or not sb:
            return "unknown"
        # A subset can be a special case or a contradiction ("only APIs" vs "APIs and
        # excipients"); only the judge can tell, so anything but equality is unknown.
        return "same" if sa == sb else "unknown"
    if ta == tb and ta in ("enum", "boolean", "date"):
        return (
            "same"
            if _norm_text(str(a.get("text"))) == _norm_text(str(b.get("text")))
            else "different"
        )
    if _norm_text(str(a.get("text", ""))) == _norm_text(str(b.get("text", ""))):
        return "same"
    return "unknown"


def deterministic(a: ClaimRec, b: ClaimRec) -> Verdict:
    return compare_values(a.value, b.value)


class LLMComparator:
    """Deterministic first; falls back to a cached MODEL_FAST judgement."""

    PROMPT_VERSION = "compare-v1"

    def __init__(self, structured_fn: Callable[..., Any] | None = None) -> None:
        if structured_fn is None:
            from app.core.llm import structured

            structured_fn = structured
        self._structured = structured_fn

    def __call__(self, a: ClaimRec, b: ClaimRec) -> Verdict:
        quick = deterministic(a, b)
        if quick != "unknown":
            return quick
        prompt = (
            "Two documents make a claim about the same rule parameter "
            f"({a.topic}.{a.parameter}). Decide whether claim A states the same rule as claim B.\n"
            "Answer 'same' if they mean the same thing even if worded differently, 'narrower' if A "
            "states a subset or special case of B without contradicting it, and 'different' if "
            "following A would give a different result from following B.\n\n"
            f"Claim A: {a.statement}\nValue A: {a.value.get('text')}\n\n"
            f"Claim B: {b.statement}\nValue B: {b.value.get('text')}"
        )
        result: CompareVerdict = self._structured(
            prompt,
            CompareVerdict,
            model="fast",
            prompt_version=self.PROMPT_VERSION,
            max_tokens=1024,
        )
        return result.verdict
