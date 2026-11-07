"""Load a domain pack (packs/<name>/*.yaml) into typed objects."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.core.config import get_settings

SOURCE_STATUSES = {
    "current",
    "superseded",
    "stale",
    "partly_outdated",
    "observation",
    "knowledge_capture",
}
SOURCE_KINDS = {
    "sop",
    "desk_instruction",
    "client_memo",
    "faq",
    "training_video",
    "shadowing",
    "interview",
    "email",
    "chat",
    "tacit",
}


class SourceSpec(BaseModel):
    id: str
    file: str
    part: str | None = None
    title: str
    label: str
    kind: str
    version: str | None = None
    dated: date | None = None
    valid_to: date | None = None
    status: str
    status_note: str | None = None
    owner: str | None = None
    authority_rank: int
    client_scope: str = "all"

    def model_post_init(self, _: Any) -> None:
        if self.status not in SOURCE_STATUSES:
            raise ValueError(f"source {self.id}: unknown status {self.status!r}")
        if self.kind not in SOURCE_KINDS:
            raise ValueError(f"source {self.id}: unknown kind {self.kind!r}")


class ClientSpec(BaseModel):
    name: str
    short: str


class DocumentSpec(BaseModel):
    file: str
    segmenter: str
    source: str | None = None
    row_sections: list[str] = Field(default_factory=list)
    heading_pattern: str | None = None
    parts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    question_speakers: list[str] = Field(default_factory=list)


class Pack(BaseModel):
    name: str
    title: str
    root: Path
    clients: dict[str, ClientSpec]
    skip_paragraphs: list[str]
    metadata_keys: list[str]
    documents: list[DocumentSpec]
    operations: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, SourceSpec]
    vocabulary: dict[str, Any]
    roles: dict[str, Any]
    authority: dict[str, Any]
    risk: dict[str, Any]
    extraction: dict[str, Any] = Field(default_factory=dict)

    def client_label(self, scope: str) -> str:
        if scope == "all":
            return "all clients"
        return f"{self.clients[scope].short} only"

    def client_key_for_name(self, name: str | None) -> str | None:
        if not name:
            return None
        for key, c in self.clients.items():
            if name.strip() in (c.name, c.short):
                return key
        return None


def _read(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_pack(pack_dir: Path) -> Pack:
    main = _read(pack_dir / "pack.yaml")
    sources_raw = _read(pack_dir / "sources.yaml")["sources"]
    sources = {k: SourceSpec(id=k, **v) for k, v in sources_raw.items()}
    pack = Pack(
        name=main["name"],
        title=main["title"],
        root=pack_dir,
        clients={k: ClientSpec(**v) for k, v in main["clients"].items()},
        skip_paragraphs=main.get("skip_paragraphs", []),
        metadata_keys=main.get("metadata_keys", []),
        documents=[DocumentSpec(**d) for d in main["documents"]],
        operations=main.get("operations", {}),
        sources=sources,
        vocabulary=_read(pack_dir / "vocabulary.yaml"),
        roles=_read(pack_dir / "roles.yaml"),
        authority=_read(pack_dir / "authority.yaml"),
        risk=_read(pack_dir / "risk.yaml"),
        extraction=_read(pack_dir / "extraction.yaml")
        if (pack_dir / "extraction.yaml").exists()
        else {},
    )
    for s in sources.values():
        if s.client_scope != "all" and s.client_scope not in pack.clients:
            raise ValueError(f"source {s.id}: unknown client scope {s.client_scope!r}")
    return pack


@lru_cache
def get_pack() -> Pack:
    return load_pack(get_settings().pack_dir)
