"""Redact personal and confidential identifiers before text leaves the process.

Applied to every LLM prompt, every LLM log line and every ingested passage.
Public business registration numbers that embed a tax id are not redacted: the tax-id
pattern cannot match inside one because of the word boundaries.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Every currency symbol (Unicode category Sc), so "<symbol>9876543210" reads as money.
_CURRENCY = "".join(
    re.escape(chr(c)) for c in range(0x20, 0x10000) if unicodedata.category(chr(c)) == "Sc"
)

# Order matters: account numbers before phone numbers (a 10-digit account
# number next to "a/c" should be labelled as an account).
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    (
        "ACCOUNT",
        re.compile(
            r"(?i)(\b(?:account|acct|a/c|ac)\b(?:\s*(?:no\.?|number|#))?[\s:.\-]*)"
            r"(\d[\d \-]{7,20}\d)"
        ),
    ),
    (
        "PHONE",
        re.compile(rf"(?<![\d{_CURRENCY},.])(?:\+91[\s\-]?|0)?[6-9]\d{{4}}[\s\-]?\d{{5}}(?![\d,])"),
    ),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
]


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int]


def redact_with_counts(text: str) -> RedactionResult:
    counts: dict[str, int] = {}
    for label, pattern in _PATTERNS:
        if label == "ACCOUNT":

            def _sub(m: re.Match[str]) -> str:
                digits = re.sub(r"\D", "", m.group(2))
                if not 9 <= len(digits) <= 18:
                    return m.group(0)
                counts["ACCOUNT"] = counts.get("ACCOUNT", 0) + 1
                return f"{m.group(1)}[REDACTED_ACCOUNT]"

            text = pattern.sub(_sub, text)
            continue
        text, n = pattern.subn(f"[REDACTED_{label}]", text)
        if n:
            counts[label] = counts.get(label, 0) + n
    return RedactionResult(text=text, counts=counts)


def redact(text: str) -> str:
    return redact_with_counts(text).text


def contains_sensitive(text: str) -> bool:
    return bool(redact_with_counts(text).counts)
