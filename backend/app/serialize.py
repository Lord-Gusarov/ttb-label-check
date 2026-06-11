"""Serialize a VerificationResult into a JSON-able dict for the UI."""
from __future__ import annotations

import re

from app.pipeline import VerificationResult
from app.readers.types import ReadResult
from app.rules.result import FieldResult

# match = label must equal a declared value; present = mandatory element, no declared value.
FIELD_KIND: dict[str, str] = {
    "brand_name": "match",
    "class_type": "match",
    "alcohol_content": "match",
    "net_contents": "match",
    "warning_text": "present",
    "warning_caps": "present",
    "warning_bold": "present",
}

_WARNING_TOKENS = {"government", "warning"}


def _tokens(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _locate_boxes(field: FieldResult, read: ReadResult) -> list[list[int]]:
    """Best-effort: boxes of reader words that make up this field's value."""
    if field.field.startswith("warning"):
        wanted = _WARNING_TOKENS
    else:
        wanted = _tokens(field.found) or _tokens(field.expected)
    if not wanted:
        return []
    boxes = []
    for w in read.words:
        if _tokens(w.text) & wanted:
            boxes.append([int(c) for c in w.bbox])
    return boxes


def serialize_field(field: FieldResult, read: ReadResult) -> dict:
    return {
        "field": field.field,
        "label": field.label,
        "verdict": field.verdict.value,
        "kind": FIELD_KIND.get(field.field, "present"),
        "expected": field.expected,
        "found": field.found,
        "detail": field.detail,
        "boxes": _locate_boxes(field, read),
    }


def serialize_verification(vr: VerificationResult) -> dict:
    read = vr.read
    return {
        "overall": vr.result.overall.value,
        "engine": read.engine,
        "elapsed_ms": round(read.elapsed_ms, 1),
        "fields": [serialize_field(f, read) for f in vr.result.fields],
        "words": [{"text": w.text, "bbox": [int(c) for c in w.bbox]} for w in read.words],
    }
