"""Format invariance (TEST_PLAN level 15): the SOP in other formats gives the same graph.

Each variant in synthetic/variants/ (from scripts/render_variants.py) and the original .docx go
into fresh tenants that share the default tenant's schema and bindings. Per variant:

- Fact F1 against the docx tenant: a fact matches if subject, attribute, scope and value match
  after normalisation. The XLSX variant has tables only, so only facts it can contain count
  (recall over baseline facts whose passage is a table).
- Rule F1 (reported, not the pass mark): the same with the subject left out (attribute, scope,
  value). The extractor may file one rule under different subject entities ("194X" or "TDS
  rules") in different layouts; answers and calculators look rules up by attribute and scope.
- Passage recovery: share of baseline passages whose sentences (80%+) appear in the variant.
- Scenario stability: the 92 scenario questions' calculator decisions and numbers equal the
  docx tenant's (parameters are extracted once per question and reused).

    python scripts/run_format_invariance.py                     # gate A variants
    python scripts/run_format_invariance.py --variants md,html  # a subset
    python scripts/run_format_invariance.py --all               # plus pptx and scanned (gate B)

Every variant re-extracts its passages with the LLM; run it with a fast provider.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# The owner seeding or measuring the knowledge base: no approval step for these inputs.
os.environ.setdefault("GOVERNANCE", "false")

from app.core.db import session_scope  # noqa: E402
from app.store import episodes as estore  # noqa: E402
from app.store import facts as fstore  # noqa: E402
from app.store.base import use_tenant  # noqa: E402
from evaluation.tenants import clone_config, ingest  # noqa: E402

VARIANTS = ROOT / "synthetic" / "variants"
STEM = "PS-07_AP_SOP_v4.0_2026"
BASE = ROOT / "data" / "raw" / f"{STEM}.docx"
GATE_A = {
    "pdf": f"{STEM}.pdf",
    "md": f"{STEM}.md",
    "html": f"{STEM}.html",
    "xlsx": f"{STEM}_tables.xlsx",
    "eml": f"{STEM}.eml",
    "flat_docx": f"{STEM}_flat.docx",
}
GATE_B = {"pptx": f"{STEM}.pptx", "scanned": f"{STEM}_scanned.pdf"}
TARGET = {"scanned": 0.8}
# The XLSX variant holds the tables only. Calculators also need rules the SOP states in prose
# (for example the rate without a PAN, default payment terms), which it cannot contain, so its
# scenario stability is reported but is not part of its pass mark.
SCENARIOS_NOT_JUDGED = {"xlsx"}
TODAY = date(2026, 11, 7)
REPORTS = ROOT / "reports"


def norm_text(s: str) -> str:
    s = s.replace("₹", " rs ").replace("—", "-").replace("–", "-").lower()
    s = re.sub(r"\brs\.?\s*", "rs ", s)
    return re.sub(r"[^a-z0-9%.]+", " ", s).strip()


def fact_key(f: fstore.FactRow) -> tuple:
    v = f.value or {}
    val = v.get("number")
    val = round(float(val), 4) if val is not None else norm_text(str(v.get("text") or ""))
    client = (f.scope or {}).get("client") or "all"
    return (norm_text(f.subject_name or ""), f.attribute, client, val)


def graph(tenant: str) -> tuple[set[tuple], list[str], set[tuple]]:
    """(fact keys, passage texts, fact keys from table passages) of a tenant's live graph."""
    with use_tenant(tenant), session_scope() as s:
        rows = [f for f in fstore.get_facts(s) if not f.attribute.startswith("other:")]
        passages = estore.all_passages(s)
        table_ids = {p.id for p in passages if p.segment_kind in ("table", "table_row")}
        texts = [p.text for p in passages if p.segment_kind != "record"]
    keys = {fact_key(f) for f in rows}
    table_keys = {fact_key(f) for f in rows if f.passage_id in table_ids}
    return keys, texts, table_keys


def rule_keys(keys: set[tuple]) -> set[tuple]:
    return {k[1:] for k in keys}


def recovery(base_texts: list[str], variant_texts: list[str]) -> float:
    hay = " ".join(norm_text(t) for t in variant_texts)
    found = 0
    for t in base_texts:
        sents = [norm_text(x) for x in re.split(r"(?<=[.!?])\s+|\n+", t) if len(x.strip()) > 12]
        if not sents:
            continue
        hits = sum(1 for x in sents if x and x in hay)
        found += hits / len(sents) >= 0.8
    total = sum(1 for t in base_texts if any(len(x.strip()) > 12 for x in re.split(r"\n+", t)))
    return found / total if total else 0.0


def f1(base: set, got: set) -> tuple[float, float, float]:
    tp = len(base & got)
    p = tp / len(got) if got else 0.0
    r = tp / len(base) if base else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def scenario_answers(tenant: str, params: dict[str, object]) -> dict[str, object]:
    from app.graph.pipeline import active_ontology
    from app.plugins.calculate import calculate
    from evaluation.scenario import from_calc

    out = {}
    with use_tenant(tenant), session_scope() as s:
        onto = active_ontology(s)
        for qid, (family, inputs) in params.items():
            try:
                out[qid] = from_calc(family, calculate(s, onto, "ap", family, inputs, today=TODAY))
            except Exception as exc:  # a missing rule in this variant is a difference
                out[qid] = f"error: {type(exc).__name__}"
    return out


def scenario_params() -> dict[str, tuple[str, dict]]:
    from app.graph.pipeline import active_ontology
    from app.store import entities
    from evaluation.dataset import load
    from plugins.ap.calc.params import calculator_inputs, extract_params

    with session_scope() as s:
        clients = [e.name for e in entities.list_entities(s, "client")]
        onto = active_ontology(s)
    out = {}
    for q in [q for q in load() if q.type == "scenario"]:
        p = extract_params(q.question, clients)
        inputs = calculator_inputs(p, onto.units, clients, onto.base_currency)
        if inputs is not None:
            out[q.id] = (p.family, inputs)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", help="comma-separated names (default: gate A)")
    ap.add_argument("--all", action="store_true", help="gate A and gate B variants")
    ap.add_argument("--no-scenarios", action="store_true")
    args = ap.parse_args()
    pool = {**GATE_A, **GATE_B}
    names = args.variants.split(",") if args.variants else list(pool if args.all else GATE_A)
    clone_config("fmt_docx")
    ingest("fmt_docx", [BASE])
    base_keys, base_texts, base_tables = graph("fmt_docx")
    params = {} if args.no_scenarios else scenario_params()
    base_answers = scenario_answers("fmt_docx", params) if params else {}
    print(f"baseline: {len(base_keys)} facts, {len(base_texts)} passages")
    rows = []
    for name in names:
        tenant = f"fmt_{name}"
        clone_config(tenant)
        ingest(tenant, [VARIANTS / pool[name]])
        keys, texts, _ = graph(tenant)
        reference = base_tables if name == "xlsx" else base_keys
        p, r, f = f1(reference, keys)
        rule_f = f1(rule_keys(reference), rule_keys(keys))[2]
        rec = recovery(base_texts, texts)
        stable = None
        if params:
            got = scenario_answers(tenant, params)
            same = sum(got.get(q) == a for q, a in base_answers.items())
            stable = same / len(base_answers) if base_answers else None
        target = TARGET.get(name, 0.9)
        rows.append(
            {
                "variant": name,
                "facts": len(keys),
                "precision": p,
                "recall": r,
                "f1": f,
                "rule_f1": rule_f,
                "passage_recovery": rec,
                "scenario_stability": stable,
                "pass": f >= target
                and (stable is None or name in SCENARIOS_NOT_JUDGED or stable >= 0.95),
                "lost": sorted(reference - keys)[:15],
                "target": target,
            }
        )
        print(
            f"{name}: F1 {f:.2f} (P {p:.2f} R {r:.2f}), rule F1 {rule_f:.2f}, passages {rec:.0%}, "
            "scenarios "
            f"{'n/a' if stable is None else f'{stable:.0%}'}"
        )
    REPORTS.mkdir(exist_ok=True)
    lines = [
        f"# Format invariance — {datetime.now():%d %b %Y %H:%M}",
        "",
        f"Baseline: original .docx, {len(base_keys)} facts, {len(base_texts)} passages.",
        "",
        "| variant | F1 | precision | recall | rule F1 | passages | scenarios | target | pass |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        sc = "n/a" if r["scenario_stability"] is None else f"{r['scenario_stability']:.0%}"
        if r["variant"] in SCENARIOS_NOT_JUDGED and r["scenario_stability"] is not None:
            sc += " (not judged: tables only)"
        lines.append(
            f"| {r['variant']} | {r['f1']:.2f} | {r['precision']:.2f} | {r['recall']:.2f}"
            f" | {r['rule_f1']:.2f} | {r['passage_recovery']:.0%} | {sc} | F1 >= {r['target']} | "
            f"{'PASS' if r['pass'] else 'FAIL'} |"
        )
    for r in rows:
        if r["lost"]:
            lines += ["", f"## Facts lost or changed: {r['variant']} (first 15)", ""]
            lines += [f"- {k}" for k in r["lost"]]
    out = REPORTS / f"format_invariance_{date.today():%Y%m%d}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("report:", out)


if __name__ == "__main__":
    main()
