"""Duplicate check on invoice numbers: are two numbers the same once normalised?

The normalisation is not held here. It is read from the rule in force (e.g. "remove spaces,
slashes, hyphens and leading zeros, and drop a trailing suffix of /A, /R or -REV"): which
separators to remove, whether leading zeros go, and which trailing suffixes to drop. A change to
that rule changes this calculator's result. A rule text this reader cannot understand raises
RuleNotFound rather than falling back to a built-in normalisation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.graph.rules import RuleNotFound

from .base import CalcResult, Rules, Step, config, rule

# Words a rule uses for separator characters (vocabulary, not rule values).
SEPARATOR_WORDS = {
    "space": " ",
    "slash": "/",
    "backslash": "\\",
    "hyphen": "-",
    "dash": "-",
    "dot": ".",
    "full stop": ".",
    "underscore": "_",
    "comma": ",",
}


class DuplicateInput(BaseModel):
    invoice_number: str = Field(min_length=1)
    other_invoice_number: str = Field(min_length=1)
    client: str | None = None


@dataclass
class Normalisation:
    separators: str
    leading_zeros: bool
    suffixes: list[str]

    def apply(self, number: str) -> str:
        s = number.strip()
        for suf in sorted(self.suffixes, key=len, reverse=True):
            if s.upper().endswith(suf.upper()) and len(s) > len(suf):
                s = s[: -len(suf)]
                break
        parts = re.split(f"[{re.escape(self.separators)}]+", s) if self.separators else [s]
        if self.leading_zeros:
            # Per segment, so "2026/0881" keeps the boundary: 2026 + 881, not 20260881.
            parts = [re.sub(r"(?<!\d)0+(?=\d)", "", p) for p in parts]
        return "".join(parts).upper()


def read_normalisation(text: str) -> Normalisation:
    """Parse a normalisation rule written in words into its steps."""
    low = text.lower()
    seps = "".join(
        sorted({ch for word, ch in SEPARATOR_WORDS.items() if re.search(rf"\b{word}(e?s)?\b", low)})
    )
    zeros = bool(re.search(r"\bleading zeros?\b", low))
    suffixes = re.findall(r"(?<![\w/\\-])([/\\-][A-Za-z0-9]+)\b", text) if "suffix" in low else []
    if not (seps or zeros or suffixes):
        raise RuleNotFound(f"cannot read the invoice-number normalisation from: {text!r}")
    return Normalisation(seps, zeros, suffixes)


def calculate(inp: DuplicateInput, rules: Rules) -> CalcResult:
    cfg = config("duplicate")
    r_norm = rule(rules, cfg, "normalisation", inp.client)
    r_match = rule(rules, cfg, "match", inp.client)
    res = CalcResult(family="duplicate", decision="", passed=None)
    res.cite(r_norm)
    res.cite(r_match)
    norm = read_normalisation(str(r_norm.value.get("text") or r_norm.statement))
    a, b = norm.apply(inp.invoice_number), norm.apply(inp.other_invoice_number)
    same = a == b
    res.working = [
        Step("Normalisation (rule in force)", str(r_norm.value.get("text") or r_norm.statement)),
        Step(f"{inp.invoice_number} normalised", a),
        Step(f"{inp.other_invoice_number} normalised", b),
        Step("Normalised numbers match?", "Yes" if same else "No"),
    ]
    criteria = str(r_match.value.get("text") or r_match.statement)
    res.notes = [f"Suspected duplicate when: {criteria}"]
    if same:
        res.passed = False
        res.decision = (
            "Suspected duplicate — the normalised numbers match; for the same supplier, "
            f"raise {cfg['exception']}"
        )
        res.exception_code = cfg["exception"]
        res.next_owner = cfg.get("next_owner")
    else:
        res.passed = True
        res.decision = (
            "Not the same invoice number once normalised; still a suspected duplicate if the "
            "other test in the rule matches"
        )
    res.result = {"normalised": [a, b], "match": same}
    return res
