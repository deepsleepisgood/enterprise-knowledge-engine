"""Run the evaluation (TEST_PLAN levels 5-6): answer, grade, measure, report."""

from __future__ import annotations

import csv
import json
import re
import statistics
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from pathlib import Path
from typing import Any

from evaluation import scenario as sc
from evaluation.dataset import Question
from evaluation.judge import answer_text, judge
from evaluation.metrics import citation_correct, current_text, outdated

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
CAUSES = (
    "retrieval miss",
    "wrong authority",
    "calculator",
    "routing",
    "extraction",
    "generation",
    "verifier",
    "citation only",
)


@dataclass
class Options:
    config: str = "D"  # A | B | C | D
    use_judge: bool = True
    today: date = date(2026, 11, 7)
    workers: int = 3
    tenant: str | None = None


def _structured(thinking: bool = False) -> Callable[..., Any]:
    from app.core.llm import structured

    return partial(structured, thinking=False) if not thinking else structured


def _answer(q: Question, opt: Options) -> dict[str, Any]:
    if opt.config == "D":
        from app.answer.pipeline import ask

        return ask(
            q.question, today=opt.today, viewer="eval", user_id=f"eval-{uuid.uuid4().hex[:8]}"
        )
    from evaluation.baselines import answer

    return answer(opt.config, q.question, _structured())


def _nums_in(text: str) -> set[float]:
    from app.answer.verify import numbers

    return numbers(text)


def grade_scenario_text(exp: sc.Expected, card: dict[str, Any]) -> bool:
    """Scenario grading when no calculator ran: every expected figure in the current-rule text,
    and the verdict / code / decision named."""
    t = current_text(card)
    tl = t.lower()
    nums = _nums_in(t)
    for k, v in exp.fields.items():
        if isinstance(v, float) and v not in nums:
            return False
        if k == "exception" and v and v not in t:
            return False
        if k == "decision" and v.lower() not in tl:
            return False
        if k in ("due_date", "run_date"):
            d = datetime.fromisoformat(v)
            if f"{d.day} {d.strftime('%B')}" not in t and f"{d.day} {d.strftime('%b')}" not in t:
                return False
        if k == "section" and v not in t:
            return False
        if k == "passed":
            no = re.search(r"\b(no|not|cannot|fails?|hold|exceeds?|above)\b", tl) is not None
            if v == no:
                return False
    return True


def cause_of(r: dict[str, Any], card: dict[str, Any]) -> str:
    diag = card.get("diagnostics") or {}
    if card.get("status") == "unverified":
        return "verifier"
    if card.get("status") == "unsupported":
        return "retrieval miss" if diag.get("abstained") else "generation"
    if r["outdated"]:
        return "wrong authority"
    if r["correct"] and not r["cite_strict"]:
        return "citation only"
    if r["type"] == "scenario":
        if diag.get("calculator_error"):
            return "extraction"
        if not str(card.get("route", "")).startswith("calculator:"):
            return "routing"
        return "calculator"
    if r["correct"] and not r["cite_strict"]:
        return "citation only"
    return "generation"


def run_question(q: Question, opt: Options, run_id: str) -> dict[str, Any]:
    from app.core.llm import trace

    started = time.perf_counter()
    err = None
    with trace(f"{run_id}:{q.id}"):
        try:
            card = _answer(q, opt)
        except Exception as exc:  # recorded, never fatal for the run
            card, err = {"status": "error", "rule": {"text": "", "citations": []}}, repr(exc)
        latency = time.perf_counter() - started
        r: dict[str, Any] = {
            "id": q.id,
            "split": q.split,
            "type": q.type,
            "difficulty": q.difficulty,
            "question": q.question,
            "gold": q.gold,
            "config": opt.config,
            "status": card.get("status"),
            "route": card.get("route"),
            "latency_s": round(latency, 2),
            "error": err,
            "answer_text": answer_text(card),
            "verified": ((card.get("diagnostics") or {}).get("verifier") or {}).get("verified"),
        }
        r["cite_strict"] = citation_correct(card, q.gold_file, q.gold_section, q.also_valid)
        r["cite_lenient"] = citation_correct(
            card, q.gold_file, q.gold_section, q.also_valid, lenient=True
        )
        r["outdated"] = outdated(card, q.must_not_say)
        r["has_must_not_say"] = bool(q.must_not_say)
        verdict, reason = "wrong", ""
        if q.type == "scenario":
            exp = sc.expected_from_gold(q.gold_section, q.gold)
            fam, got = sc.from_card(card)
            if fam == exp.family and got:
                ok = sc.same(exp.fields, got)
                reason = f"expected {exp.fields}; calculator {fam}: {got}"
            else:
                # No calculator: every figure must be in the text AND the judge, who sees the
                # gold working, must agree (figures can appear in the wrong role).
                ok = grade_scenario_text(exp, card)
                reason = f"expected {exp.fields}; graded from text"
                if ok and opt.use_judge and not err:
                    v = judge(q.question, q.gold, q.type, card, _structured())
                    ok = v.verdict == "correct"
                    reason += f"; judge: {v.verdict} {v.reason}"
            verdict = "correct" if ok else "wrong"
        elif opt.use_judge and not err:
            v = judge(q.question, q.gold, q.type, card, _structured())
            verdict, reason = v.verdict, v.reason + (f" Missing: {v.missing}" if v.missing else "")
        r["verdict"] = verdict
        r["correct"] = verdict == "correct"
        r["judge_reason"] = reason
        r["cause"] = "" if r["correct"] and r["cite_strict"] else cause_of(r, card)
    r["card"] = card
    return r


def attach_usage(results: list[dict[str, Any]], run_id: str, log: Path) -> None:
    """Tokens, LLM calls and cost per question, from the traced call log."""
    use: dict[str, dict[str, float]] = defaultdict(lambda: Counter())
    if log.exists():
        for line in log.open(encoding="utf-8"):
            if run_id not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            qid = str(rec.get("trace", "")).split(":", 1)[-1]
            u = use[qid]
            u["calls"] += 1
            u["cached"] += bool(rec.get("cached"))
            u["input_tokens"] += rec.get("input_tokens") or 0
            u["output_tokens"] += rec.get("output_tokens") or 0
            u["cost_usd"] += rec.get("cost_usd") or 0.0
    for r in results:
        u = use.get(r["id"], Counter())
        for k in ("calls", "cached", "input_tokens", "output_tokens"):
            r[k] = int(u.get(k, 0))
        r["cost_usd"] = round(float(u.get("cost_usd", 0.0)), 5)


def evaluate(questions: list[Question], opt: Options, progress: bool = True) -> list[dict]:
    from app.core.config import get_settings
    from app.store.base import use_tenant

    run_id = f"eval-{datetime.now():%Y%m%d%H%M%S}-{opt.config}"

    def one(q: Question) -> dict[str, Any]:
        if opt.tenant:
            with use_tenant(opt.tenant):
                r = run_question(q, opt, run_id)
        else:
            r = run_question(q, opt, run_id)
        if progress:
            mark = "ok" if r["correct"] else r["verdict"]
            print(
                f"  {r['id']:<5} {opt.config} {mark:<8} {r['latency_s']:>6.1f}s {r['cause']}",
                flush=True,
            )
        return r

    with ThreadPoolExecutor(max_workers=opt.workers) as pool:
        results = list(pool.map(one, questions))
    attach_usage(results, run_id, get_settings().log_dir / "llm_calls.jsonl")
    return results


# ---------------------------------------------------------------- metrics and reports


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}% ({n}/{d})" if d else "n/a"


def summarise(rs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rs)
    lat = sorted(r["latency_s"] for r in rs) or [0.0]
    conflict = [r for r in rs if r["type"] == "conflict"]
    mns = [r for r in rs if r["has_must_not_say"]]
    return {
        "n": n,
        "accuracy": _pct(sum(r["correct"] for r in rs), n),
        "partial": _pct(sum(r["verdict"] == "partial" for r in rs), n),
        "citation_strict": _pct(sum(r["cite_strict"] for r in rs), n),
        "citation_lenient": _pct(sum(r["cite_lenient"] for r in rs), n),
        "outdated_conflict": _pct(sum(r["outdated"] for r in conflict), len(conflict)),
        "outdated_must_not_say": _pct(sum(r["outdated"] for r in mns), len(mns)),
        "abstained": _pct(sum(r["status"] == "unsupported" for r in rs), n),
        "unverified": _pct(sum(r["status"] == "unverified" for r in rs), n),
        "errors": sum(bool(r["error"]) for r in rs),
        "latency_p50_s": round(statistics.median(lat), 1),
        "latency_p95_s": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 1),
        "llm_calls": sum(r.get("calls", 0) for r in rs),
        "tokens_in": sum(r.get("input_tokens", 0) for r in rs),
        "tokens_out": sum(r.get("output_tokens", 0) for r in rs),
        "cost_usd": round(sum(r.get("cost_usd", 0.0) for r in rs), 4),
    }


def _table(groups: dict[str, list[dict[str, Any]]], cols: list[str]) -> list[str]:
    head = "| group | " + " | ".join(cols) + " |"
    lines = [head, "|" + " --- |" * (len(cols) + 1)]
    for g, rs in groups.items():
        s = summarise(rs)
        lines.append(f"| {g} | " + " | ".join(str(s[c]) for c in cols) + " |")
    return lines


def write_report(
    results: dict[str, list[dict[str, Any]]], split: str, extra: dict[str, Any] | None = None
) -> Path:
    """results: config -> per-question rows. Writes Markdown and one CSV per config."""
    REPORTS.mkdir(exist_ok=True)
    stamp = f"{date.today():%Y%m%d}"
    md = REPORTS / f"eval_{stamp}_{split}.md"
    cols = [
        "n",
        "accuracy",
        "citation_strict",
        "citation_lenient",
        "outdated_conflict",
        "outdated_must_not_say",
        "abstained",
        "latency_p50_s",
        "latency_p95_s",
        "cost_usd",
    ]
    out = [f"# Evaluation — {split} split — {datetime.now():%d %b %Y %H:%M}", ""]
    if extra:
        out += [f"- {k}: {v}" for k, v in extra.items()] + [""]
    if len(results) > 1:
        out += ["## Ablation (TEST_PLAN level 6)", ""]
        out += _table({f"config {c}": rs for c, rs in results.items()}, cols) + [""]
    for config, rs in results.items():
        s = summarise(rs)
        out += [f"## Config {config}", ""]
        out += [f"- **{k}**: {v}" for k, v in s.items()] + [""]
        for title, key in (
            ("By split", "split"),
            ("By question type", "type"),
            ("By difficulty", "difficulty"),
        ):
            groups: dict[str, list] = defaultdict(list)
            for r in rs:
                groups[r[key]].append(r)
            out += [f"### {title}", ""] + _table(dict(sorted(groups.items())), cols[:7]) + [""]
        out += ["### Routes and statuses", ""]
        out.append(
            "- routes: "
            + ", ".join(
                f"{k} {v}"
                for k, v in Counter(str(r["route"]).split(".")[0] for r in rs).most_common()
            )
        )
        out.append(
            "- statuses: "
            + ", ".join(f"{k} {v}" for k, v in Counter(r["status"] for r in rs).most_common())
        )
        out.append(
            "- failure causes: "
            + ", ".join(
                f"{k} {v}" for k, v in Counter(r["cause"] for r in rs if r["cause"]).most_common()
            )
            + "\n"
        )
        worst = sorted(
            [r for r in rs if not (r["correct"] and r["cite_strict"])],
            key=lambda r: (r["correct"], r["verdict"] == "partial", not r["outdated"], r["id"]),
        )[:15]
        out += [
            "### 15 worst questions",
            "",
            "| id | type | verdict | cited | outdated | cause | why |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in worst:
            why = (r["error"] or r["judge_reason"] or "").replace("|", "/").replace("\n", " ")
            out.append(
                f"| {r['id']} | {r['type']} | {r['verdict']} | {r['cite_strict']} | "
                f"{r['outdated']} | {r['cause']} | {why[:160]} |"
            )
        out.append("")
        csv_path = REPORTS / f"eval_{stamp}_{split}_{config}.csv"
        fields = [k for k in rs[0] if k != "card"] if rs else []
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rs:
                w.writerow({k: r[k] for k in fields})
        (REPORTS / f"eval_{stamp}_{split}_{config}_cards.jsonl").write_text(
            "\n".join(
                json.dumps({"id": r["id"], "card": r["card"]}, ensure_ascii=False, default=str)
                for r in rs
            ),
            encoding="utf-8",
        )
        out.append(f"Per-question CSV: `{csv_path.relative_to(ROOT).as_posix()}`\n")
    md.write_text("\n".join(out), encoding="utf-8")
    return md
