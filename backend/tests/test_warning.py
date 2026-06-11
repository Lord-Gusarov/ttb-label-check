"""Tests for the government-warning text + caps checks (string-based, hermetic)."""

from app.rules.result import Verdict
from app.rules.spec.government_warning import CANONICAL_WARNING
from app.rules.warning import check_warning_caps, check_warning_text


# --- all-caps check -----------------------------------------------------------
def test_caps_all_uppercase_passes():
    r = check_warning_caps("... GOVERNMENT WARNING: (1) According ...")
    assert r.verdict is Verdict.PASS


def test_caps_title_case_fails():
    # Jenny's real rejection: "Government Warning" in title case.
    r = check_warning_caps("... Government Warning: (1) According ...")
    assert r.verdict is Verdict.FAIL
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


def test_text_missing_fails():
    r = check_warning_text("OLD TOM DISTILLERY 45% Alc./Vol. 750 mL")
    assert r.verdict is Verdict.FAIL


def test_text_reworded_flagged():
    reworded = "GOVERNMENT WARNING: Drinking alcohol may be bad for you. Be careful."
    r = check_warning_text("BRAND " + reworded)
    assert r.verdict in (Verdict.FAIL, Verdict.NEEDS_REVIEW)


def test_text_minor_ocr_noise_not_hard_fail():
    # A couple of dropped/garbled words (typical OCR) should not hard-FAIL a real warning.
    noisy = CANONICAL_WARNING.replace("Surgeon General", "Surgon Genera").replace(
        "machinery", "machinry"
    )
    r = check_warning_text("BRAND " + noisy)
    assert r.verdict in (Verdict.PASS, Verdict.NEEDS_REVIEW)
