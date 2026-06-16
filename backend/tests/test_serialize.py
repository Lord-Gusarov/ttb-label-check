from app.readers.types import ReadResult, WordBox
from app.rules.result import FieldResult, LabelResult, Verdict
from app.pipeline import VerificationResult
from app.serialize import FIELD_KIND, _locate_boxes, serialize_verification


def _vr():
    words = [
        WordBox("OLD", 0.9, (10, 10, 40, 30)),
        WordBox("TOM", 0.9, (45, 10, 80, 30)),
        WordBox("45%", 0.9, (10, 50, 60, 70)),
    ]
    read = ReadResult(text="OLD TOM 45%", words=words, confidence=0.9,
                      engine="tesseract", elapsed_ms=12.3)
    fields = [
        FieldResult("brand_name", "Brand name", Verdict.PASS, "OLD TOM", "OLD TOM", "match"),
        FieldResult("warning_text", "Government warning text", Verdict.NEEDS_REVIEW,
                    "(canonical)", "GOVERNMENT WARNING…", "review"),
    ]
    result = LabelResult("distilled_spirits", Verdict.NEEDS_REVIEW, fields)
    return VerificationResult("distilled_spirits", result, read)


def test_serialize_shape_and_kinds():
    out = serialize_verification(_vr())
    assert out["overall"] == "needs_review"
    assert out["engine"] == "tesseract"
    brand = next(f for f in out["fields"] if f["field"] == "brand_name")
    assert brand["kind"] == "match"
    assert [10, 10, 40, 30] in brand["boxes"]
    assert FIELD_KIND["warning_text"] == "present"
    assert len(out["words"]) == 3


def test_serialize_handles_unlocatable_field():
    out = serialize_verification(_vr())
    warning = next(f for f in out["fields"] if f["field"] == "warning_text")
    assert warning["boxes"] == []


def _read_with(*texts: str) -> ReadResult:
    return ReadResult(
        text=" ".join(texts),
        words=[WordBox(t, 0.9, (i * 10, 0, i * 10 + 9, 9)) for i, t in enumerate(texts)],
        confidence=0.9, engine="x", elapsed_ms=1,
    )


def test_locate_boxes_tolerates_ocr_join_and_split():
    """OCR joins/splits the declared value unpredictably (vertical/stylized text); the
    box must still associate so recognition and highlighting can't silently disagree."""
    nc = FieldResult("net_contents", "Net contents", Verdict.PASS, "750 mL", "750 mL", "ok")
    # joined "750mL" (one token) — the case that used to yield NO box
    assert _locate_boxes(nc, _read_with("750mL")) == [[0, 0, 9, 9]]
    # split across two words
    assert _locate_boxes(nc, _read_with("750", "mL")) == [[0, 0, 9, 9], [10, 0, 19, 9]]
    # an unrelated word is not falsely highlighted
    assert _locate_boxes(nc, _read_with("OLD TOM", "750mL")) == [[10, 0, 19, 9]]


def test_locate_boxes_warning_spans_every_line():
    """Hovering a warning check highlights EVERY warning line, not just the prefix."""
    words = [
        WordBox("GOVERNMENT WARNING: (1) According to the Surgeon General, women", 0.9, (0, 0, 100, 10)),
        WordBox("should not drink alcoholic beverages during pregnancy because of the risk of", 0.9, (0, 12, 100, 22)),
        WordBox("birth defects. (2) Consumption of alcoholic beverages impairs your ability to", 0.9, (0, 24, 100, 34)),
        WordBox("OLD TOM DISTILLERY", 0.9, (0, 40, 100, 50)),  # not part of the warning
    ]
    read = ReadResult(text="…", words=words, confidence=0.9, engine="x", elapsed_ms=1)
    wt = FieldResult("warning_text", "Government warning text", Verdict.PASS,
                     "(canonical)", "GOVERNMENT WARNING…", "ok")
    boxes = _locate_boxes(wt, read)
    assert [0, 0, 100, 10] in boxes  # prefix line
    assert [0, 12, 100, 22] in boxes  # body line 1
    assert [0, 24, 100, 34] in boxes  # body line 2
    assert [0, 40, 100, 50] not in boxes  # brand line must NOT highlight
