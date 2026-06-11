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
def test_verify_clean_label_passes_end_to_end():
    out = verify_label(load_image(CLEAN), "distilled_spirits", APP)
    # The reader actually read the label and the rules engine cleared every field.
    assert out.read.text
    assert out.result.overall is Verdict.PASS, [
        (f.field, f.verdict, f.detail) for f in out.result.fields
    ]


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_verify_flags_wrong_abv_end_to_end():
    bad_app = dict(APP, alcohol_content="40% Alc./Vol.")  # label says 45%
    out = verify_label(load_image(CLEAN), "distilled_spirits", bad_app)
    abv = next(f for f in out.result.fields if f.field == "alcohol_content")
    assert abv.verdict is Verdict.FAIL
    assert out.result.overall is Verdict.FAIL
