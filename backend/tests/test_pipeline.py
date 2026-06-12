"""Integration: reader + rules compose on a real corpus image."""

from pathlib import Path

import pytest

from app.pipeline import verify_label
from app.readers.preprocess import load_image
from app.rules import Verdict

CLEAN = Path(__file__).resolve().parents[1] / "corpus" / "images" / "old_tom_clean.png"

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
    assert abv.verdict is Verdict.FAIL
    assert out.result.overall is Verdict.FAIL
