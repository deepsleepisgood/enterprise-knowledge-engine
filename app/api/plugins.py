"""Plug-ins through the API: what is installed, its bindings, direct calculator access, and the
plug-in's context hooks (invoice picker, vendor tips). The core names no plug-in: everything
here goes through the registry and the hooks a plug-in declares in plugin.yaml."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.api.deps import not_found, read_session, row, write_session
from app.core.db import snapshot_scope
from app.graph.pipeline import active_ontology
from app.graph.rules import RuleNotFound
from app.plugins import calculate as calc
from app.plugins import registry
from app.store import entities as ents
from app.store import facts as fstore
from app.store import kb
from app.store.base import tenant

router = APIRouter(tags=["plug-ins"])


def plugin_context(invoice_id: str | None = None, vendor_id: str | None = None) -> dict | None:
    """The first plug-in context hook that knows the invoice or vendor."""
    with snapshot_scope() as s:
        for _p, fn in registry.hooks("context"):
            ctx = fn(s, tenant(), invoice_id=invoice_id, vendor_id=vendor_id)
            if ctx:
                return ctx
    return None


@router.get("/plugins")
def plugins() -> list[dict[str, Any]]:
    out = []
    for p in registry.plugins():
        mod = calc.entry(p.name)
        desc = mod.describe() if hasattr(mod, "describe") else {}
        out.append(
            {
                "name": p.name,
                "title": p.title,
                "description": p.manifest.get("description", ""),
                "hooks": sorted((p.manifest.get("hooks") or {}).keys()),
                "calculators": [
                    {
                        "family": fam,
                        "description": desc.get(fam, fam),
                        "input_schema": model.model_json_schema(),
                    }
                    for fam, (model, _fn) in mod.CALCULATORS.items()
                ],
            }
        )
    return out


@router.get("/bindings")
def bindings(plugin: str | None = None, s: Session = Depends(read_session)) -> list[dict]:
    """Each calculator parameter and the schema attribute (and subject) it reads its rule from."""
    return [row(b) for b in kb.get_bindings(s, plugin)]


class BindingEdit(BaseModel):
    attribute_key: str
    subject_entity_id: str | None = None
    confirmed_by: str


@router.put("/bindings/{binding_id}")
def put_binding(
    binding_id: int, body: BindingEdit, s: Session = Depends(write_session)
) -> dict[str, Any]:
    """Owner correction of a binding; confirmed bindings are never re-bound automatically."""
    b = next((x for x in kb.get_bindings(s) if x.id == binding_id), None)
    if b is None:
        raise not_found("binding")
    onto = active_ontology(s)
    if onto is not None and body.attribute_key not in {a.key for a in onto.attributes}:
        raise HTTPException(422, f"{body.attribute_key!r} is not an attribute of the schema")
    if body.subject_entity_id and ents.get(s, body.subject_entity_id) is None:
        raise not_found("entity")
    kb.put_binding(
        s,
        b.plugin,
        b.param,
        attribute_key=body.attribute_key,
        subject_entity_id=body.subject_entity_id,
        confidence=1.0,
        confirmed_by=body.confirmed_by,
        meta={**(b.meta or {}), "method": "owner"},
    )
    return {"id": binding_id, "plugin": b.plugin, "param": b.param, **body.model_dump()}


class CalcIn(BaseModel):
    params: dict[str, Any]
    as_of: date | None = None
    today: date | None = None


@router.post("/calculate/{plugin}/{family}")
def calculate(plugin: str, family: str, body: CalcIn) -> dict[str, Any]:
    """Run a calculator directly. Every threshold it uses is a current fact read through the
    plug-in's bindings; a missing rule or binding is an error, never a default."""
    if registry.get(plugin) is None:
        raise not_found(f"plug-in {plugin!r}")
    if family not in calc.families(plugin):
        raise not_found(f"calculator {plugin}.{family}")
    with snapshot_scope() as s:
        onto = active_ontology(s)
        if onto is None:
            raise HTTPException(409, "No frozen schema yet: build the graph first.")
        try:
            out = calc.calculate(
                s, onto, plugin, family, body.params, today=body.today, as_of=body.as_of
            )
        except ValidationError as exc:
            raise HTTPException(422, jsonable_encoder(exc.errors())) from exc
        except RuleNotFound as exc:
            raise HTTPException(422, f"rule not found: {exc}") from exc
        return {"plugin": plugin, "family": family, "result": jsonable_encoder(out)}


@router.get("/context")
def context(invoice_id: str | None = None, vendor_id: str | None = None) -> dict[str, Any]:
    """Vendor tips and checks for an invoice or vendor, from the plug-in that knows it."""
    if not invoice_id and not vendor_id:
        raise HTTPException(422, "give invoice_id or vendor_id")
    ctx = plugin_context(invoice_id=invoice_id, vendor_id=vendor_id)
    if ctx is None:
        raise not_found("invoice or vendor")
    return ctx


@router.get("/invoices")
def invoices(q: str = "", limit: int = 20, s: Session = Depends(read_session)) -> list[dict]:
    """Search the operational invoices for the invoice picker (plug-in hook `invoice_search`)."""
    out: list[dict] = []
    for _p, fn in registry.hooks("invoice_search"):
        out += fn(s, tenant(), q=q, limit=min(max(limit, 1), 100))
    return out


@router.get("/scopes")
def scopes(s: Session = Depends(read_session)) -> list[dict[str, str]]:
    """Client scopes that rules in the graph are actually scoped to, for the composer's client
    chip ("all" first). Entities merely typed as clients do not make a scope."""
    values = fstore.scope_values(s, "client")
    return [{"key": "all", "label": "All clients"}] + [
        {"key": v, "label": v} for v in sorted(values)
    ]
