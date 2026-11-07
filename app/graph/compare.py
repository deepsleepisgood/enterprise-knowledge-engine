"""Do two assertions state the same value?

`compare_values` is deterministic and answers "unknown" when wording differs and it cannot
tell. `LLMComparator` asks MODEL_FAST only for those cases (cached on disk).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel

from app.graph.resolve import Assertion, Verdict

NUMERIC = {"percentage", "money", "days", "number"}
PROMPT_VERSION = "compare-v2"


class CompareVerdict(BaseModel):
    verdict: Literal["same", "different", "narrower"]
    reason: str


def _norm_text(s: str) -> str:
    s = s.lower().replace("per cent", "%").replace("percent", "%")
    s = "".join(
        c if c.isalnum() or c in "%. _" or unicodedata.category(c) == "Sc" else " " for c in s
    )
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)  # keep dots only inside numbers ("1.5")
    s = re.sub(r"\s+%", "%", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_items(items: list[str] | None) -> set[str]:
    return {_norm_text(i).rstrip("s") for i in items or [] if i.strip()}


def compare_values(a: dict[str, Any], b: dict[str, Any]) -> Verdict:
    ta, tb = a.get("type"), b.get("type")
    na, nb = a.get("number"), b.get("number")
    if ta in NUMERIC and tb in NUMERIC:
        if na is None or nb is None:
            return "unknown"
        if (a.get("unit") or "").lower() != (b.get("unit") or "").lower():
            return "unknown"  # e.g. days vs working_days: not comparable by number alone
        return "same" if abs(float(na) - float(nb)) < 1e-9 else "different"
    if ta == tb == "list":
        sa, sb = _norm_items(a.get("items")), _norm_items(b.get("items"))
        if not sa or not sb:
            return "unknown"
        # A subset can be a special case or a contradiction; only the judge can tell.
        return "same" if sa == sb else "unknown"
    if ta == tb and ta in ("enum", "boolean", "date"):
        same = _norm_text(str(a.get("text"))) == _norm_text(str(b.get("text")))
        return "same" if same else "different"
    if _norm_text(str(a.get("text", ""))) == _norm_text(str(b.get("text", ""))):
        return "same"
    return "unknown"


def deterministic(a: Assertion, b: Assertion) -> Verdict:
    return compare_values(a.value, b.value)


class LLMComparator:
    """Deterministic first; falls back to a cached MODEL_FAST judgement."""

    def __init__(self, structured_fn: Callable[..., Any] | None = None) -> None:
        if structured_fn is None:
            from app.core.llm import structured

            structured_fn = structured
        self._structured = structured_fn
        self.failures: list[str] = []

    def __call__(self, a: Assertion, b: Assertion) -> Verdict:
        quick = deterministic(a, b)
        if quick != "unknown":
            return quick
        prompt = (
            f"Two documents make a claim about the same parameter ({a.attribute}). Decide "
            "whether claim A states the same rule as claim B.\nAnswer 'same' if they mean the "
            "same thing even if worded differently, 'narrower' if A states a subset or special "
            "case of B without contradicting it, and 'different' if following A would give a "
            "different result from following B.\n\n"
            f"Claim A: {a.statement}\nValue A: {a.value.get('text')}\n\n"
            f"Claim B: {b.statement}\nValue B: {b.value.get('text')}"
        )
        try:
            out: CompareVerdict = self._structured(
                prompt,
                CompareVerdict,
                model="fast",
                prompt_version=PROMPT_VERSION,
                max_tokens=4096,
            )
        except Exception as exc:  # a failed judgement must not abort a graph build
            self.failures.append(f"{a.key} vs {b.key}: {type(exc).__name__}: {exc}")
            return "unknown"
        return out.verdict
