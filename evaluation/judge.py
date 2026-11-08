"""LLM judge (MODEL_SMART, temperature 0) and its calibration against hand grades."""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "eval" / "judge" / "prompt.md"
HAND = ROOT / "eval" / "judge" / "hand_graded.csv"
PROMPT_VERSION = "judge-v1"
VERDICTS = ("correct", "partial", "wrong")


class Verdict(BaseModel):
    verdict: Literal["correct", "partial", "wrong"]
    missing: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    reason: str = ""


def answer_text(card: dict[str, Any]) -> str:
    """What the user saw: rule text, decision, working, tip, older sources (labelled)."""
    parts = [f"Status: {card.get('status')}"]
    if card.get("decision"):
        parts.append(f"Decision: {card['decision']}")
    parts.append(f"Answer: {(card.get('rule') or {}).get('text') or '(no answer)'}")
    for w in card.get("working") or []:
        parts.append(f"  {w.get('label')}: {w.get('value')}")
    if card.get("exception_code"):
        parts.append(f"Exception code: {card['exception_code']}")
    tip = card.get("expert_tip")
    if tip:
        parts.append(f"Expert tip: {tip.get('text')}")
    if card.get("route_to"):
        parts.append(f"Route to: {card['route_to'].get('role')}")
    older = card.get("older_sources") or []
    if older:
        parts.append(
            "Older sources (superseded): "
            + "; ".join(f"{o.get('older_value')} ({o.get('locator')})" for o in older)
        )
    return "\n".join(parts)


def judge(
    question: str,
    gold: str,
    qtype: str,
    card: dict[str, Any],
    structured_fn: Callable[..., Any],
) -> Verdict:
    if card.get("status") in ("unsupported", "unverified") and not (card.get("rule") or {}).get(
        "text"
    ):
        return Verdict(verdict="wrong", reason=f"no answer given ({card.get('status')})")
    prompt = (
        f"Question type: {qtype}\nQuestion: {question}\n\nGold answer: {gold}\n\n"
        f"Answer to grade:\n{answer_text(card)}"
    )
    return structured_fn(
        prompt,
        Verdict,
        system=PROMPT.read_text(encoding="utf-8"),
        model="smart",
        prompt_version=PROMPT_VERSION,
        max_tokens=2048,
    )


# ---------------------------------------------------------------- calibration


def cohen_kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in VERDICTS)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def calibration(judged: dict[str, str], path: Path = HAND) -> dict[str, Any] | None:
    """Agreement and kappa between the resolved hand grades and the judge, if graded."""
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("resolved") or "").strip() in VERDICTS]
    pairs = [
        (r["resolved"].strip(), judged[r["question_id"]])
        for r in rows
        if r["question_id"] in judged
    ]
    if not pairs:
        return None
    hand, auto = [p[0] for p in pairs], [p[1] for p in pairs]
    agree = sum(h == j for h, j in pairs) / len(pairs)
    return {
        "n": len(pairs),
        "agreement": round(agree, 3),
        "kappa": round(cohen_kappa(hand, auto), 3),
        "trusted": agree >= 0.9,
    }


def write_template(results: list[dict[str, Any]], path: Path = HAND) -> int:
    """30 answers for two teammates to grade (10 conflict, 10 factual or procedural, 10 tacit
    or mixed). Never overwrites grades already entered."""
    if path.exists():
        return 0
    want = [("conflict",), ("factual", "procedural"), ("tacit", "scenario")]
    picked = []
    for types in want:
        picked += [r for r in results if r["type"] in types][:10]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "question_id",
                "type",
                "question",
                "gold",
                "answer",
                "grader_1",
                "grader_2",
                "resolved",
            ]
        )
        for r in picked:
            w.writerow([r["id"], r["type"], r["question"], r["gold"], r["answer_text"], "", "", ""])
    return len(picked)
