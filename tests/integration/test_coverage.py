"""Locator coverage: every gold and also-valid source in the eval set exists as a passage.

This test may read the evaluation workbook because it is test code (CLAUDE.md rule 1
applies to app/, web/ and scripts/ingest_*). It reads only file and locator columns.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "eval" / "PS-07_qa_evaluation_set.xlsx"


def _norm(loc: str) -> str:
    return re.sub(r"\s+", " ", loc.replace("§", "")).strip()


def _references() -> set[tuple[str, str]]:
    q = pd.read_excel(EVAL, sheet_name="questions")
    refs: set[tuple[str, str]] = set()
    for f, s in zip(q["gold_source_file"], q["gold_source_section"], strict=True):
        refs.add((str(f).strip(), str(s).strip()))
    for cell in q["also_valid_sources"].dropna():
        for item in str(cell).split(";"):
            item = item.strip()
            if item:
                f, _, loc = item.partition(" ")
                refs.add((f, loc.strip()))
    return refs


def _matches(loc: str, passage_locs: set[str], part_aliases: set[str]) -> bool:
    """Strict match, plus 'Part C' for 'Part C (CM-INF-02)'; '8.2 and 11' needs both."""
    loc = _norm(loc)
    if " and " in loc:
        return all(_matches(x, passage_locs, part_aliases) for x in loc.split(" and "))
    return loc in passage_locs or loc in part_aliases


@pytest.mark.skipif(not EVAL.exists(), reason="eval workbook not present")
def test_every_eval_locator_exists_as_passage(pack, corpus) -> None:
    by_file: dict[str, tuple[set[str], set[str]]] = {}
    for p in corpus.passages:
        file = pack.sources[p.source_id].file
        locs, aliases = by_file.setdefault(file, (set(), set()))
        locs.add(_norm(p.locator))
        if "part" in p.meta:
            aliases.add(p.meta["part"])

    refs = _references()
    assert len(refs) >= 35
    missing = sorted(
        f"{f} :: {loc}" for f, loc in refs if not _matches(loc, *by_file.get(f, (set(), set())))
    )
    assert not missing, f"{len(missing)} eval locators have no passage: {missing}"
