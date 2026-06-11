from app.readers.types import ReadResult, WordBox
from app.rules.result import FieldResult, LabelResult, Verdict
from app.pipeline import VerificationResult
from app.serialize import FIELD_KIND, serialize_verification


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
