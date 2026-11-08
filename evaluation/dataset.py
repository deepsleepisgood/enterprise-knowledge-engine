"""Eval questions and the dev / holdout split (TEST_PLAN section 3).

Identical questions are grouped first (the set repeats some verbatim), then groups are split
60/40, stratified by question type and gold section, with seed 7. The split is deterministic and
written to eval/split.csv so every run uses the same one.
"""

from __future__ import annotations

import csv
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "eval" / "PS-07_qa_evaluation_set.xlsx"
SPLIT_FILE = ROOT / "eval" / "split.csv"
SEED = 7
DEV_SHARE = 0.6


@dataclass
class Question:
    id: str
    question: str
    type: str
    difficulty: str
    gold: str
    gold_file: str
    gold_section: str
    also_valid: list[str] = field(default_factory=list)
    must_not_say: str | None = None
    split: str = ""


def _s(v: object) -> str:
    return "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()


def load(path: Path = WORKBOOK) -> list[Question]:
    import pandas as pd

    rows = pd.read_excel(path, sheet_name="questions").to_dict(orient="records")
    out = []
    for r in rows:
        out.append(
            Question(
                id=_s(r["question_id"]),
                question=_s(r["question"]),
                type=_s(r["question_type"]),
                difficulty=_s(r["difficulty"]),
                gold=_s(r["gold_answer"]),
                gold_file=_s(r["gold_source_file"]),
                gold_section=_s(r["gold_source_section"]),
                also_valid=[x.strip() for x in _s(r["also_valid_sources"]).split(";") if x.strip()],
                must_not_say=_s(r["must_not_say"]) or None,
            )
        )
    return out


def _norm_q(q: str) -> str:
    return re.sub(r"\s+", " ", q.lower()).strip()


def make_split(questions: list[Question], seed: int = SEED) -> dict[str, str]:
    """question id -> 'dev' | 'holdout'. Groups of identical questions never straddle."""
    groups: dict[str, list[Question]] = defaultdict(list)
    for q in questions:
        groups[_norm_q(q.question)].append(q)
    strata: dict[tuple[str, str], list[list[Question]]] = defaultdict(list)
    for g in groups.values():
        strata[(g[0].type, g[0].gold_section)].append(g)
    rng = random.Random(seed)
    out: dict[str, str] = {}
    carry = 0.0  # keeps small strata from all landing on one side
    for key in sorted(strata):
        gs = sorted(strata[key], key=lambda g: g[0].id)
        rng.shuffle(gs)
        want = len(gs) * DEV_SHARE + carry
        n_dev = int(want + 0.5)
        carry = want - n_dev
        for i, g in enumerate(gs):
            for q in g:
                out[q.id] = "dev" if i < n_dev else "holdout"
    return out


def with_split(questions: list[Question], path: Path = SPLIT_FILE) -> list[Question]:
    """Attach the saved split (creating it on first use)."""
    if path.exists():
        with path.open(encoding="utf-8") as f:
            split = {r["question_id"]: r["split"] for r in csv.DictReader(f)}
    else:
        split = make_split(questions)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["question_id", "split"])
            for q in questions:
                w.writerow([q.id, split[q.id]])
    for q in questions:
        q.split = split.get(q.id, "holdout")
    return questions


def select(questions: list[Question], split: str) -> list[Question]:
    return questions if split == "all" else [q for q in questions if q.split == split]
