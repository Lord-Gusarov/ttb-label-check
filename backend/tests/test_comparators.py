"""Comparators flag problems as NEEDS_REVIEW — never a terminal FAIL. Only the agent's
decision rejects; the automated checks recommend/flag."""

from __future__ import annotations

from app.rules.comparators import match_abv, match_net_contents, match_text
from app.rules.result import Verdict


def test_abv_mismatch_is_needs_review():
    # Off by 5 points — clearly wrong, but the automated check flags it, doesn't FAIL.
    v, _, _ = match_abv("45% Alc./Vol.", "ALC 40% BY VOL")
    assert v is Verdict.NEEDS_REVIEW


def test_net_contents_absent_is_needs_review():
    v, _, _ = match_net_contents("750 mL", "OLD TOM DISTILLERY BOURBON")
    assert v is Verdict.NEEDS_REVIEW


def test_brand_absent_is_needs_review():
    v, _, _ = match_text("STONE'S THROW", "completely different label text")
    assert v is Verdict.NEEDS_REVIEW


def test_abv_match_still_passes():
    v, _, _ = match_abv("45% Alc./Vol.", "45% ALC/VOL")
    assert v is Verdict.PASS  # guard: we didn't break the happy path


# TTB (27 CFR 5.65) blesses three interchangeable word orders for the alcohol-content
# statement, and they spell out "percent" rather than using the % glyph. All three must
# parse — the unit is "percent", whether written as %, the word, or "pct".
def test_abv_format_percent_alcohol_by_volume():
    # "__ percent alcohol by volume"
    v, found, _ = match_abv("45% Alc./Vol.", "45 PERCENT ALCOHOL BY VOLUME")
    assert v is Verdict.PASS
    assert found == "45%"


def test_abv_format_alcohol_percent_by_volume():
    # "Alcohol __ percent by volume"
    v, found, _ = match_abv("45% Alc./Vol.", "ALCOHOL 45 PERCENT BY VOLUME")
    assert v is Verdict.PASS
    assert found == "45%"


def test_abv_format_alcohol_by_volume_percent():
    # "Alcohol by volume __ percent"
    v, found, _ = match_abv("45% Alc./Vol.", "ALCOHOL BY VOLUME 45 PERCENT")
    assert v is Verdict.PASS
    assert found == "45%"


def test_abv_pct_abbreviation():
    v, _, _ = match_abv("45% Alc./Vol.", "ALC. 45 PCT BY VOL.")
    assert v is Verdict.PASS


# The number alone is not a compliant alcohol-content statement: it must be presented as
# "alcohol by volume" (27 CFR 5.65). A matching percentage WITHOUT the alc/vol nomenclature
# nearby must not silently PASS — it is NEEDS_REVIEW.
def test_abv_bare_percentage_without_nomenclature_is_needs_review():
    v, _, detail = match_abv("40% Alc./Vol.", "40% OFF EVERYTHING MUST GO")
    assert v is Verdict.NEEDS_REVIEW
    assert "volume" in detail.lower()


def test_abv_unrelated_percentage_is_needs_review():
    v, _, _ = match_abv("40% Alc./Vol.", "contains 40% real fruit juice")
    assert v is Verdict.NEEDS_REVIEW


def test_abv_abbreviation_not_sanctioned_is_needs_review():
    # 'ABV' is not a TTB-sanctioned abbreviation for the mandatory statement (strict).
    v, _, detail = match_abv("5.6% Alc./Vol.", "5.6% ABV")
    assert v is Verdict.NEEDS_REVIEW
    assert "abv" in detail.lower()


def test_abv_prefers_nomenclature_candidate_over_distractor():
    # A bare matching % distractor must not steal the verdict from the real alc/vol value.
    v, found, _ = match_abv("40% Alc./Vol.", "40% off — ALC 40% BY VOL")
    assert v is Verdict.PASS
    assert found == "40%"


def test_abv_all_three_word_orders_pass():
    for label in (
        "40% ALC/VOL 80 PROOF",
        "Alcohol 40 percent by volume",
        "40 percent alcohol by volume",
        "Alcohol by volume 40 percent",
    ):
        v, _, _ = match_abv("40% Alc./Vol.", label)
        assert v is Verdict.PASS, label
