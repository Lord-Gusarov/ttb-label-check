"""Serialize a VerificationResult into a JSON-able dict for the UI."""
from __future__ import annotations

import re

from app.pipeline import VerificationResult
from app.readers.types import ReadResult
from app.rules.normalize import despace
from app.rules.result import FieldResult
from app.rules.spec.government_warning import CANONICAL_TOKENS

_CANON_TOKEN_SET = set(CANONICAL_TOKENS)

# match = label must equal a declared value; present = mandatory element, no declared value.
FIELD_KIND: dict[str, str] = {
    "brand_name": "match",
    "class_type": "match",
    "alcohol_content": "match",
    "net_contents": "match",
    "responsible_party": "match",
    "country_of_origin": "match",
    "warning_text": "present",
    "warning_caps": "present",
    "warning_bold": "present",
}

def _tokens(text: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _is_warning_line(text: str) -> bool:
    """A reader line belongs to the warning if most of its words are canonical-warning
    vocabulary. Robust to OCR noise, and (unlike matching only "GOVERNMENT WARNING")
    it tags EVERY line of the multi-line warning, not just the prefix."""
    toks = _tokens(text)
    if len(toks) < 3:
        return False
    return sum(t in _CANON_TOKEN_SET for t in toks) / len(toks) >= 0.6


def _locate_boxes(field: FieldResult, read: ReadResult) -> list[list[int]]:
    """Best-effort: boxes of reader words that make up this field's value/region.

    Warning checks highlight the WHOLE warning (every recognized line). Other fields match
    on a de-spaced *substring* basis rather than exact token overlap, because OCR joins or
    splits the same value unpredictably (vertical/stylized text especially): the declared
    "750 mL" may come back as one word "750mL" or as "750" + "mL". A word's box belongs to
    the field if its de-spaced text sits inside the target value, or contains it — so
    recognition and highlighting can't silently disagree.
    """
    if field.field.startswith("warning"):
        return [[int(c) for c in w.bbox] for w in read.words if _is_warning_line(w.text)]

    target = despace(field.found or field.expected, strip_accents=False)
    if not target:
        return []
    boxes = []
    for w in read.words:
        wt = despace(w.text, strip_accents=False)
        if len(wt) >= 2 and (wt in target or target in wt):
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
        "warning_tier": vr.warning_tier,  # 0 plain, 1 rotation re-read, 2 model-assisted
        "text": read.text,  # full text the reader extracted, for the agent to eyeball
        "fields": [serialize_field(f, read) for f in vr.result.fields],
        "words": [{"text": w.text, "bbox": [int(c) for c in w.bbox]} for w in read.words],
    }
