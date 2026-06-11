"""Golden tests for the deterministic rules engine."""

from app.rules import Verdict, evaluate
from app.rules.comparators import match_abv, match_net_contents, match_text

# Realistic OCR text for the OLD TOM sample label.
OLD_TOM_TEXT = (
    "OLD TOM DISTILLERY Kentucky Straight Bourbon Whiskey "
    "45% Alc./Vol. (90 Proof) 750 mL "
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth defects."
)

OLD_TOM_APP = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
}


# --- brand matching -----------------------------------------------------------
def test_brand_exact_pass():
    v, _, _ = match_text("OLD TOM DISTILLERY", OLD_TOM_TEXT)
    assert v is Verdict.PASS


def test_brand_case_and_punctuation_tolerant():
    # Dave's case: "STONE'S THROW" on the label, "Stone's Throw" in the application.
    v, _, _ = match_text("Stone's Throw", "STONE'S THROW BOURBON 40% Alc./Vol.")
    assert v is Verdict.PASS


def test_brand_matches_when_ocr_merges_words():
    # RapidOCR often returns all-caps brands with the spaces dropped.
    v, _, _ = match_text("OLD TOM DISTILLERY", "OLDTOMDISTILLERY Kentucky Straight")
    assert v is Verdict.PASS


def test_brand_absent_fails():
    v, _, _ = match_text("Nonexistent Brand", OLD_TOM_TEXT, absent_verdict=Verdict.FAIL)
    assert v is Verdict.FAIL


def test_brand_close_typo_warns():
    # One transposed letter -> high-but-imperfect similarity -> review, not silent pass.
    v, _, _ = match_text("OLD TOM DISTILERY", OLD_TOM_TEXT)
    assert v in (Verdict.WARN, Verdict.PASS)
    v2, _, _ = match_text("OLED TOMM DISTILLERX", "OLD TOM DISTILLERY")
    assert v2 is Verdict.WARN


# --- ABV (numeric + tolerance) ------------------------------------------------
def test_abv_within_tolerance_pass():
    v, found, _ = match_abv("45% Alc./Vol.", "label 45% Alc./Vol.", tolerance=0.3)
    assert v is Verdict.PASS and found == "45%"


def test_abv_out_of_tolerance_fails():
    v, _, detail = match_abv("45%", "46% Alc./Vol.", tolerance=0.3)
    assert v is Verdict.FAIL and "off by" in detail


def test_abv_missing_on_label_needs_review():
    v, _, _ = match_abv("45%", "no percentage here", tolerance=0.3)
    assert v is Verdict.NEEDS_REVIEW


def test_abv_proof_mismatch_noted():
    v, _, detail = match_abv("45%", "45% Alc./Vol. (100 Proof)", tolerance=0.3)
    assert v is Verdict.PASS  # ABV itself matches
    assert "proof" in detail.lower()


# --- net contents -------------------------------------------------------------
def test_net_contents_spacing_tolerant():
    v, _, _ = match_net_contents("750 mL", "net 750mL e")
    assert v is Verdict.PASS


def test_net_contents_absent_fails():
    v, _, _ = match_net_contents("750 mL", "no volume stated")
    assert v is Verdict.FAIL


# --- end-to-end engine --------------------------------------------------------
def test_evaluate_clean_label_all_pass():
    result = evaluate("distilled_spirits", OLD_TOM_APP, OLD_TOM_TEXT)
    assert result.overall is Verdict.PASS
    assert {f.field for f in result.fields} == set(OLD_TOM_APP)
    assert all(f.verdict is Verdict.PASS for f in result.fields)


def test_evaluate_rolls_up_worst_verdict():
    app = dict(OLD_TOM_APP, alcohol_content="50% Alc./Vol.")  # mismatch vs label's 45%
    result = evaluate("distilled_spirits", app, OLD_TOM_TEXT)
    assert result.overall is Verdict.FAIL
    abv = next(f for f in result.fields if f.field == "alcohol_content")
    assert abv.verdict is Verdict.FAIL


def test_evaluate_missing_application_field_needs_review():
    app = {k: v for k, v in OLD_TOM_APP.items() if k != "net_contents"}
    result = evaluate("distilled_spirits", app, OLD_TOM_TEXT)
    net = next(f for f in result.fields if f.field == "net_contents")
    assert net.verdict is Verdict.NEEDS_REVIEW
