"""Approval level by invoice total (including GST); non-PO invoices add the budget owner."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.calc.base import CalcResult, Rules, Step, config, inr, rule


class ApprovalsInput(BaseModel):
    total_incl_gst: float = Field(ge=0)
    po_backed: bool = True
    client: str | None = None


def calculate(inp: ApprovalsInput, rules: Rules) -> CalcResult:
    cfg = config("approvals")
    roles = cfg["roles"]
    res = CalcResult(family="approvals", decision="", passed=None)
    r_ctl = res.cite(rule(rules, cfg, "controller_above", inp.client))
    r_cfo = res.cite(rule(rules, cfg, "cfo_above", inp.client))

    if inp.total_incl_gst > r_cfo.number:
        level, approver = "cfo", roles["cfo"]
    elif inp.total_incl_gst > r_ctl.number:
        level, approver = "controller", roles["controller"]
    else:
        level, approver = "none", roles["none"]
    approvers = [] if level == "none" else [approver]
    if not inp.po_backed:
        approvers.append(roles["non_po_extra"])

    res.working = [
        Step("Invoice total (incl. GST)", inr(inp.total_incl_gst)),
        Step(f"{roles['controller']} above", inr(r_ctl.number)),
        Step(f"{roles['cfo']} above", inr(r_cfo.number)),
        Step("PO-backed", "Yes" if inp.po_backed else "No"),
    ]
    res.decision = " + ".join(approvers) if approvers else roles["none"]
    res.next_owner = approvers[0] if approvers else None
    res.result = {"level": level, "approvers": approvers}
    return res
