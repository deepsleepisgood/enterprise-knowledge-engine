"""Hard rule 1: application code never touches the answer key."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"qa_evaluation_set|known_conflicts|gold_answer", re.I)
SKIP_DIRS = {"node_modules", ".next", "__pycache__", "test-results", "playwright-report"}
TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
}


def _files() -> list[Path]:
    out: list[Path] = []
    for base in (ROOT / "app", ROOT / "web", ROOT / "packs"):
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in TEXT_SUFFIXES and not SKIP_DIRS & set(p.parts):
                out.append(p)
    out.extend((ROOT / "scripts").glob("ingest_*.py"))
    return out


def test_scanned_some_files() -> None:
    assert len(_files()) > 10


def test_no_answer_key_references() -> None:
    offenders = [
        f"{p.relative_to(ROOT)}:{i}"
        for p in _files()
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
        if FORBIDDEN.search(line)
    ]
    assert not offenders, f"answer-key references in app code: {offenders}"
