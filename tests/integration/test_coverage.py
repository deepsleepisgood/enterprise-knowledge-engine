"""Locator coverage: every gold and also-valid source in the eval set exists as a passage locator.

Test code, so it may read the evaluation workbook (only the file and locator columns). The
corpus goes through the generic parser and segmenter with no hand-written pack.

Matching (TEST_PLAN level 5 normalisation): "§4.2" = "4.2"; "Part C (CM-INF-02)" = "Part C";
"8.2 and 11" needs both; a label may carry extra words from the heading ("Interview 1 [02:30]"
matches "Expert interview 1 [02:30]") but numbers and timestamps must match exactly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from app.ingest.detect import detect
from app.ingest.parsers import parse
from app.ingest.segment import segment, split_documents

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "eval" / "PS-07_qa_evaluation_set.xlsx"


def norm(loc: str) -> str:
    loc = re.sub(r"\s*\([^)]*\)", "", loc.replace("§", ""))
    return re.sub(r"\s+", " ", loc).strip().lower()


def _split(loc: str) -> tuple[set[str], str]:
    """(label words, the numeric or time part) of a locator."""
    m = re.search(r"(\[?\d{1,2}:\d{2}\]?|\d+(?:\.\d+)*(?:, step \d+)?|step \d+)\s*$", loc)
    tail = m.group(1) if m else ""
    head = loc[: m.start()] if m else loc
    return set(re.findall(r"[a-z0-9]+", head)), tail


def matches(gold: str, ours: str) -> bool:
    g, o = norm(gold), norm(ours)
    if g == o:
        return True
    (gw, gt), (ow, ot) = _split(g), _split(o)
    return bool(gt) and gt == ot and gw <= ow and bool(gw) == bool(ow)


def references() -> set[tuple[str, str]]:
    q = pd.read_excel(EVAL, sheet_name="questions")
    refs = {
        (str(f).strip(), str(s).strip())
        for f, s in zip(q.gold_source_file, q.gold_source_section, strict=True)
    }
    for cell in q.also_valid_sources.dropna():
        for item in str(cell).split(";"):
            f, _, loc = item.strip().partition(" ")
            if f:
                refs.add((f, loc.strip()))
    return refs


def corpus_locators() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted((ROOT / "data" / "raw").glob("*")):
        data = f.read_bytes()
        result = parse(data, detect(data, f.name)[0])
        out[f.name] = {p.locator for doc in split_documents(result.blocks) for p in segment(doc)}
    return out


def test_matching_rules() -> None:
    assert matches("4.2", "4.2") and matches("§4.2", "4.2")
    assert matches("Part C (CM-INF-02)", "Part C")
    assert matches("Interview 1 [02:30]", "Expert interview 1 [02:30]")
    assert matches("Shadowing 10:05", "Shadowing notes 10:05")
    assert not matches("Interview 1 [02:30]", "Expert interview 2 [02:30]")
    assert not matches("Interview 1 [02:30]", "Expert interview 1 [02:31]")
    assert not matches("4.2", "4.3") and not matches("Part A, step 4", "Part A, step 5")


@pytest.mark.skipif(not EVAL.exists(), reason="eval workbook not present")
def test_every_eval_locator_exists_as_passage() -> None:
    locs = corpus_locators()
    refs = references()
    assert len(refs) >= 35
    missing = []
    for f, loc in sorted(refs):
        parts = [x.strip() for x in loc.split(" and ")] if " and " in loc else [loc]
        if not all(any(matches(p, o) for o in locs.get(f, set())) for p in parts):
            missing.append(f"{f} :: {loc}")
    assert not missing, f"{len(missing)} eval locators have no passage: {missing}"
