"""Tests for the government-warning text + caps checks (string-based, hermetic)."""

from app.rules.result import Verdict
from app.rules.spec.government_warning import CANONICAL_WARNING
from app.rules.warning import check_warning_caps, check_warning_text


# --- all-caps check -----------------------------------------------------------
def test_caps_all_uppercase_passes():
    r = check_warning_caps("... GOVERNMENT WARNING: (1) According ...")
    assert r.verdict is Verdict.PASS


def test_caps_title_case_needs_review():
    # Jenny's real rejection case: "Government Warning" in title case. The automated check
    # flags it (NEEDS_REVIEW with the reason) — it never issues a terminal FAIL; the agent
    # makes the reject call.
    r = check_warning_caps("... Government Warning: (1) According ...")
    assert r.verdict is Verdict.NEEDS_REVIEW
    assert "ALL CAPS" in r.detail


def test_caps_merged_uppercase_passes():
    # RapidOCR drops the space: "GOVERNMENTWARNING:".
    r = check_warning_caps("... GOVERNMENTWARNING:(1) According ...")
    assert r.verdict is Verdict.PASS


def test_caps_prefix_absent_needs_review():
    r = check_warning_caps("no warning prefix anywhere here")
    assert r.verdict is Verdict.NEEDS_REVIEW


# --- exact-wording check ------------------------------------------------------
def test_text_exact_passes():
    r = check_warning_text("OLD TOM 45% Alc./Vol. " + CANONICAL_WARNING)
    assert r.verdict is Verdict.PASS


def test_text_missing_needs_review():
    # No warning found at all — still NEEDS_REVIEW (flag for the agent), not a terminal FAIL.
    r = check_warning_text("OLD TOM DISTILLERY 45% Alc./Vol. 750 mL")
    assert r.verdict is Verdict.NEEDS_REVIEW


def test_text_reworded_flagged():
    reworded = "GOVERNMENT WARNING: Drinking alcohol may be bad for you. Be careful."
    r = check_warning_text("BRAND " + reworded)
    assert r.verdict is Verdict.NEEDS_REVIEW


def test_text_minor_ocr_noise_not_hard_fail():
    # A couple of dropped/garbled words (typical OCR) should not hard-FAIL a real warning.
    noisy = CANONICAL_WARNING.replace("Surgeon General", "Surgon Genera").replace(
        "machinery", "machinry"
    )
    r = check_warning_text("BRAND " + noisy)
    assert r.verdict in (Verdict.PASS, Verdict.NEEDS_REVIEW)


def test_text_joined_words_still_pass():
    # OCR commonly drops spaces; the legal content is intact, so this must still PASS.
    joined = CANONICAL_WARNING.replace("health problems", "healthproblems").replace(
        "GOVERNMENT WARNING", "GOVERNMENTWARNING"
    )
    r = check_warning_text("BRAND " + joined)
    assert r.verdict is Verdict.PASS


def test_text_dropped_negation_is_not_pass():
    # The legally critical case: "should not drink" -> "should drink" INVERTS the warning.
    # A similarity ratio scores this ~0.98 and would wave it through; token alignment must
    # NOT return PASS — the missing 'not' is caught and flagged for review.
    inverted = CANONICAL_WARNING.replace("should not drink", "should drink")
    r = check_warning_text("BRAND " + inverted)
    assert r.verdict is not Verdict.PASS
    assert "not" in r.detail  # the missing word is surfaced to the agent


def test_text_dropped_clause_needs_review():
    # Whole second clause missing -> present (prefix found) but unverifiable -> review.
    clause1_only = (
        "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
        "drink alcoholic beverages during pregnancy because of the risk of birth defects."
    )
    r = check_warning_text("BRAND " + clause1_only)
    assert r.verdict is Verdict.NEEDS_REVIEW
