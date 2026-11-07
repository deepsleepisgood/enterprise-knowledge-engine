"""CLAUDE.md: the core under app/ never mentions the first tenant's domain or imports plug-ins."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Company names, the first tenant's tax and regulatory terms, and the rupee sign.
DOMAIN = re.compile(r"Meridian|Arvana|\bTDS\b|GSTIN|\bMSME\b|₹|\blakh\b|\bcrore\b", re.I)
PLUGIN_IMPORT = re.compile(r"^\s*(from\s+plugins[\s.]|import\s+plugins\b)", re.M)


def _core_files() -> list[Path]:
    return [p for p in (ROOT / "app").rglob("*.py") if "__pycache__" not in p.parts]


def test_scanned_core() -> None:
    assert len(_core_files()) > 10


def test_core_has_no_domain_terms() -> None:
    offenders = [
        f"{p.relative_to(ROOT)}:{i}: {line.strip()[:80]}"
        for p in _core_files()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if DOMAIN.search(line)
    ]
    assert not offenders, "domain terms in the core:\n" + "\n".join(offenders)


def test_core_never_imports_plugins() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in _core_files()
        if PLUGIN_IMPORT.search(p.read_text("utf-8"))
    ]
    assert not offenders, f"core imports plug-ins: {offenders}"
