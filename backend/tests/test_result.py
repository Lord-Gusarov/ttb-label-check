from app.rules.result import FieldResult, LabelResult, Verdict


def _fr(verdict: Verdict) -> FieldResult:
    return FieldResult("f", "F", verdict, expected=None, found=None, detail="")


def test_from_fields_overall_is_worst():
    fields = [_fr(Verdict.PASS), _fr(Verdict.NEEDS_REVIEW), _fr(Verdict.WARN)]
    lr = LabelResult.from_fields("distilled_spirits", fields)
    assert lr.overall is Verdict.NEEDS_REVIEW
    assert lr.fields == fields
    assert lr.commodity == "distilled_spirits"


def test_from_fields_empty_is_needs_review():
    assert LabelResult.from_fields("wine", []).overall is Verdict.NEEDS_REVIEW
