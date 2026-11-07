"""File-type detection by content signature (libmagic when present), never by extension alone.

Returns one of: docx, xlsx, pptx, pdf, html, markdown, text, eml, vtt, srt, json, csv,
legacy_office, odf, rtf, image, zip, audio, video, unknown.
"""

from __future__ import annotations

import io
import json
import re
import zipfile


def _magic_mime(data: bytes) -> str | None:
    try:
        import magic  # python-magic / python-magic-bin

        return magic.from_buffer(data[:8192], mime=True)
    except Exception:  # libmagic missing or failing: fall back to our own signatures
        return None


def _zip_kind(data: bytes) -> str:
    try:
        names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    except zipfile.BadZipFile:
        return "unknown"
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    if "ppt/presentation.xml" in names:
        return "pptx"
    if "mimetype" in names:
        return "odf"
    return "zip"


_RFC822_HEADERS = re.compile(
    rb"^(?:From|To|Subject|Date|Message-ID|Received|Return-Path|MIME-Version):", re.I | re.M
)


def _text_kind(head: str, filename: str) -> str:
    stripped = head.lstrip("﻿ \r\n\t")
    if stripped.startswith("WEBVTT"):
        return "vtt"
    if re.match(r"^\d+\s*\r?\n\d{2}:\d{2}:\d{2}[,.]\d{3} -->", stripped):
        return "srt"
    if stripped[:1] in "{[":
        try:
            json.loads(head)
            return "json"
        except ValueError:
            pass
    low = stripped[:2000].lower()
    if (
        low.startswith("<!doctype html")
        or "<html" in low
        or re.search(r"<(body|p|h[1-6]|div)\b", low)
    ):
        return "html"
    if len(_RFC822_HEADERS.findall(head[:3000].encode("utf-8", "ignore"))) >= 3:
        return "eml"
    if re.search(r"^#{1,6} \S", stripped, re.M) or re.search(
        r"^\|.+\|\s*$\n^\|[ :\-|]+\|", stripped, re.M
    ):
        return "markdown"
    lines = [ln for ln in stripped.splitlines()[:20] if ln.strip()]
    if (
        len(lines) >= 2
        and all(ln.count(",") >= 1 for ln in lines)
        and len({ln.count(",") for ln in lines}) == 1
    ):
        return "csv"
    if filename.lower().endswith((".md", ".markdown")):
        return "markdown"
    return "text"


def detect(data: bytes, filename: str = "") -> tuple[str, str]:
    """(kind, mime) for raw bytes."""
    if data.startswith(b"%PDF"):
        return "pdf", "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        kind = _zip_kind(data)
        mimes = {
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "odf": "application/vnd.oasis.opendocument",
            "zip": "application/zip",
        }
        return kind, mimes.get(kind, "application/octet-stream")
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "legacy_office", "application/x-ole-storage"
    if data.startswith(b"{\\rtf"):
        return "rtf", "application/rtf"
    if (
        data[:8].startswith(b"\x89PNG")
        or data[:3] == b"\xff\xd8\xff"
        or data[:4]
        in (
            b"II*\x00",
            b"MM\x00*",
        )
        or data[:6] in (b"GIF87a", b"GIF89a")
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    ):
        return "image", _magic_mime(data) or "image/*"
    mime = _magic_mime(data) or ""
    if mime.startswith("audio/"):
        return "audio", mime
    if mime.startswith("video/"):
        return "video", mime
    try:
        head = data[:20000].decode("utf-8")
    except UnicodeDecodeError:
        try:
            head = data[:20000].decode("cp1252")
        except UnicodeDecodeError:
            return "unknown", mime or "application/octet-stream"
    if "\x00" in head:
        return "unknown", mime or "application/octet-stream"
    kind = _text_kind(head, filename)
    text_mimes = {
        "vtt": "text/vtt",
        "srt": "application/x-subrip",
        "json": "application/json",
        "html": "text/html",
        "eml": "message/rfc822",
        "markdown": "text/markdown",
        "csv": "text/csv",
        "text": "text/plain",
    }
    return kind, text_mimes[kind]
