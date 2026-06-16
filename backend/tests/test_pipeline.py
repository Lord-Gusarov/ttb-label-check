"""Integration: reader + rules compose on a real corpus image."""

from pathlib import Path

import pytest

from app.pipeline import _merge_better, verify_label
from app.readers.preprocess import load_image
from app.rules import Verdict
from app.rules.result import FieldResult


def _fr(field: str, verdict: Verdict) -> FieldResult:
    return FieldResult(field, field, verdict, None, None, "detail")


def test_merge_adopts_only_field_improvements():
    current = [_fr("brand_name", Verdict.NEEDS_REVIEW), _fr("alcohol_content", Verdict.PASS)]
    # The model fixed the brand but read the ABV worse than the local pass.
    candidate = [_fr("brand_name", Verdict.PASS), _fr("alcohol_content", Verdict.NEEDS_REVIEW)]
    merged = {f.field: f.verdict for f in _merge_better(current, candidate)}
    assert merged["brand_name"] is Verdict.PASS  # improved → adopted
    assert merged["alcohol_content"] is Verdict.PASS  # candidate worse → kept local

CORPUS = Path(__file__).resolve().parent / "fixtures" / "labels"
CLEAN = CORPUS / "old_tom_clean.png"
CIRCULAR = CORPUS / "old_tom_rich_circular.png"  # arc-laid-out warning → needs rotation

APP = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
}


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_verify_clean_label_runs_end_to_end():
    out = verify_label(load_image(CLEAN), "distilled_spirits", APP)
    # The reader actually produced text and the rules engine ran all fields.
    assert out.read.text
    fields_by_name = {f.field: f for f in out.result.fields}
    # All non-bold fields should pass on the clean reference label.
    for field in ("brand_name", "class_type", "alcohol_content", "net_contents"):
        assert fields_by_name[field].verdict is Verdict.PASS, (
            field, fields_by_name[field].detail
        )
    # The bold check on the corpus image may read as NEEDS_REVIEW (pixel-level
    # measurement is borderline); that is acceptable — the pipeline ran correctly.
    assert out.result.overall in (Verdict.PASS, Verdict.NEEDS_REVIEW)


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_verify_flags_wrong_abv_end_to_end():
    bad_app = dict(APP, alcohol_content="40% Alc./Vol.")  # label says 45%
    out = verify_label(load_image(CLEAN), "distilled_spirits", bad_app)
    abv = next(f for f in out.result.fields if f.field == "alcohol_content")
    # The mismatch is flagged for the agent, not auto-rejected — NEEDS_REVIEW, not FAIL.
    assert abv.verdict is Verdict.NEEDS_REVIEW
    assert out.result.overall is Verdict.NEEDS_REVIEW


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_automated_verdict_is_never_terminal_fail():
    # Automated checks never auto-reject: every verdict is one of the three review tiers.
    _ALLOWED = (Verdict.PASS, Verdict.WARN, Verdict.NEEDS_REVIEW)
    bad_app = dict(APP, alcohol_content="40% Alc./Vol.", brand_name="NOT THE BRAND")
    out = verify_label(load_image(CLEAN), "distilled_spirits", bad_app)
    assert out.result.overall in _ALLOWED
    assert all(f.verdict in _ALLOWED for f in out.result.fields)


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_clean_warning_resolves_locally_at_tier_1():
    out = verify_label(load_image(CLEAN), "distilled_spirits", APP)
    wt = next(f for f in out.result.fields if f.field == "warning_text")
    assert wt.verdict is Verdict.PASS
    assert out.warning_tier == 1  # no escalation needed on a clean label


@pytest.mark.skipif(not CIRCULAR.exists(), reason="seed corpus not generated")
def test_tier2_label_escalation_adopts_model_field_read(monkeypatch):
    # Circular "OT" monogram → brand unreadable locally (NEEDS_REVIEW). The (mocked) model
    # reads the real brand; the pipeline re-checks all fields against it and adopts the
    # improvement, recording tier 2. The model never sees the declared values.
    from app.rules.spec.government_warning import CANONICAL_WARNING
    monkeypatch.setattr("app.pipeline.escalate_label_read", lambda _img: {
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "alcohol_content": "45% Alc./Vol. (90 Proof)",
        "net_contents": "750 mL",
        "government_warning": CANONICAL_WARNING,
    })
    out = verify_label(load_image(CIRCULAR), "distilled_spirits", APP)
    brand = next(f for f in out.result.fields if f.field == "brand_name")
    assert brand.verdict is Verdict.PASS  # model read adopted (improvement)
    assert out.warning_tier == 2


@pytest.mark.skipif(not CIRCULAR.exists(), reason="seed corpus not generated")
def test_arc_warning_degrades_gracefully_without_model():
    # Arc-laid-out warnings have NO single skew angle, so the measured deskew can't fix
    # them — and the real TTB corpus contains no arc warnings at all (synthetic-only
    # case). Air-gapped contract: degrade to NEEDS_REVIEW for a human, never crash and
    # never false-pass. With the model on, the arc resolves at Tier 2 (covered above).
    out = verify_label(load_image(CIRCULAR), "distilled_spirits", APP)
    wt = next(f for f in out.result.fields if f.field == "warning_text")
    assert wt.verdict is Verdict.NEEDS_REVIEW


# NOTE: no pipeline-level "deskew rescue" test — measured empirically, Tier 0's scale
# search already reads uniformly-rotated labels up to ~12°, so a rescue case cannot be
# honestly constructed from the seed corpus. The deskew mechanism itself is covered in
# test_warning_region (estimator units + band-level improvement on real OCR).


def test_model_path_runs_bold_on_local_boxes(monkeypatch):
    """When the model is adopted, bold must use the LOCAL boxes, not an empty list."""
    import numpy as np
    from app import pipeline
    seen = {}

    def _spy_bold(image, words):
        seen["words"] = words
        from app.rules.result import FieldResult, Verdict
        return FieldResult("warning_bold", "Warning prefix bold", Verdict.PASS,
                           expected="bold", found=None, detail="stub")

    monkeypatch.setattr(pipeline, "evaluate_warning",
                        lambda image, text, words, region=None: [_spy_bold(image, words)])
    sentinel = [object()]
    pipeline._model_field_results("distilled_spirits", {}, {"government_warning": "x"},
                                  np.zeros((10, 10, 3), dtype="uint8"), warning_words=sentinel)
    assert seen["words"] is sentinel


@pytest.mark.skipif(not CIRCULAR.exists(), reason="seed corpus not generated")
def test_model_runs_before_rotation_sweep(monkeypatch):
    # Latency, measured: the Tier-1 rotation sweep costs up to ~10s on busy labels while
    # the model reader resolves the same cases in ~3s. So when the model is available it
    # runs FIRST; the rotation sweep is the air-gapped fallback and must not be invoked
    # when the model already resolved the warning.
    from app.rules.spec.government_warning import CANONICAL_WARNING

    swept = []
    real = verify_label.__globals__["reread_warning"]

    def spy(image, words, reader, angles=(0,), **kw):
        if tuple(angles) != (0,):
            swept.append(angles)
        return real(image, words, reader, angles=angles, **kw)

    monkeypatch.setattr("app.pipeline.reread_warning", spy)
    monkeypatch.setattr("app.pipeline.escalate_label_read", lambda _img: {
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "alcohol_content": "45% Alc./Vol. (90 Proof)",
        "net_contents": "750 mL",
        "government_warning": CANONICAL_WARNING,
    })
    out = verify_label(load_image(CIRCULAR), "distilled_spirits", APP)
    wt = next(f for f in out.result.fields if f.field == "warning_text")
    assert wt.verdict is Verdict.PASS
    assert out.warning_tier == 2
    assert swept == []  # model resolved it → no rotation sweep spent


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_sideways_label_warning_rescued_locally_at_tier_1(monkeypatch):
    # A label submitted/printed sideways (vertical-sidebar class): the warning must be
    # verified locally via the 90° re-read — air-gapped, no model (escalation off here).
    import cv2

    sideways = cv2.rotate(load_image(CLEAN), cv2.ROTATE_90_CLOCKWISE)
    out = verify_label(sideways, "distilled_spirits", APP)
    wt = next(f for f in out.result.fields if f.field == "warning_text")
    assert wt.verdict is Verdict.PASS
    assert out.warning_tier == 1
