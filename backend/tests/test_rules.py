"""Golden tests for the deterministic rules engine."""

from app.rules import Verdict, evaluate
from app.rules.comparators import match_abv, match_net_contents, match_text

# Realistic OCR text for the OLD TOM sample label.
OLD_TOM_TEXT = (
    "OLD TOM DISTILLERY Kentucky Straight Bourbon Whiskey "
    "45% Alc./Vol. (90 Proof) 750 mL "
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth defects. "
    "Bottled by Old Tom Distillery, Louisville, KY"
)

OLD_TOM_APP = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
    "responsible_party": "Old Tom Distillery, Louisville, KY",
    "source": "domestic",  # gating input (not a checked field); skips country-of-origin
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


def test_brand_absent_uses_absent_verdict():
    v, _, _ = match_text("Nonexistent Brand", OLD_TOM_TEXT, absent_verdict=Verdict.NEEDS_REVIEW)
    assert v is Verdict.NEEDS_REVIEW


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


def test_abv_out_of_tolerance_needs_review():
    v, _, detail = match_abv("45%", "46% Alc./Vol.", tolerance=0.3)
    assert v is Verdict.NEEDS_REVIEW and "off by" in detail


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


def test_net_contents_absent_needs_review():
    v, _, _ = match_net_contents("750 mL", "no volume stated")
    assert v is Verdict.NEEDS_REVIEW


# --- end-to-end engine --------------------------------------------------------
def test_evaluate_clean_label_all_pass():
    result = evaluate("distilled_spirits", OLD_TOM_APP, OLD_TOM_TEXT)
    assert result.overall is Verdict.PASS
    assert {f.field for f in result.fields} == {
        "brand_name", "class_type", "alcohol_content", "net_contents", "responsible_party",
    }  # country_of_origin is skipped for a domestic product; "source" gates, it isn't a field
    assert all(f.verdict is Verdict.PASS for f in result.fields)


def test_evaluate_rolls_up_worst_verdict():
    app = dict(OLD_TOM_APP, alcohol_content="50% Alc./Vol.")  # mismatch vs label's 45%
    result = evaluate("distilled_spirits", app, OLD_TOM_TEXT)
    # Worst rolls up to NEEDS_REVIEW (automated checks never terminal-FAIL).
    assert result.overall is Verdict.NEEDS_REVIEW
    abv = next(f for f in result.fields if f.field == "alcohol_content")
    assert abv.verdict is Verdict.NEEDS_REVIEW


def test_evaluate_missing_application_field_needs_review():
    app = {k: v for k, v in OLD_TOM_APP.items() if k != "net_contents"}
    result = evaluate("distilled_spirits", app, OLD_TOM_TEXT)
    net = next(f for f in result.fields if f.field == "net_contents")
    assert net.verdict is Verdict.NEEDS_REVIEW


# --- missing_canonical_tokens: cursor-teleport regression (real-corpus finding) ------


def test_stray_digit_after_warning_does_not_cascade():
    # (1) misread as (I), and the label's ABV text AFTER the warning contains a stray
    # '1' (Alc. 11%). The matcher must not teleport its cursor to that late '1' and
    # report everything in between as missing — only the genuinely-unreadable '1'.
    from app.rules.spec.government_warning import CANONICAL_WARNING, missing_canonical_tokens

    # '(1)' dropped entirely (not a homoglyph case), and a stray '1' appears later in
    # the ABV text — the matcher must report just the one miss, not teleport-cascade.
    candidate = CANONICAL_WARNING.replace("(1)", "()") + " Alc. 11% by VOL 750 ML"
    assert missing_canonical_tokens(candidate) == ["1"]


def test_dropped_line_is_reported_but_matching_resyncs_after_it():
    # A whole dropped phrase reports its own tokens missing, but matching RESYNCS on
    # the next long token, so the rest of the warning still counts as present.
    from app.rules.spec.government_warning import CANONICAL_WARNING, missing_canonical_tokens

    candidate = CANONICAL_WARNING.replace(
        "women should not drink alcoholic beverages during pregnancy ", ""
    )
    missing = missing_canonical_tokens(candidate)
    assert "women" in missing and "pregnancy" in missing
    assert "machinery" not in missing and "health" not in missing  # resynced tail


# --- scoped homoglyph equivalence: verify the LABEL, not the OCR engine --------------
# '1'/'I'/'l' (and '2'/'Z') are visually identical glyphs at print size — the pixels
# carry no distinction, so treating them as different verified our OCR, not the label.
# Scoped to the digit clause-markers only; every WORD change still fails exactly.


def test_clause_digit_accepts_visual_twin_glyphs():
    from app.rules.spec.government_warning import CANONICAL_WARNING, missing_canonical_tokens

    assert missing_canonical_tokens(CANONICAL_WARNING.replace("(1)", "(I)")) == []
    assert missing_canonical_tokens(CANONICAL_WARNING.replace("(1)", "(l)")) == []
    assert missing_canonical_tokens(CANONICAL_WARNING.replace("(2)", "(Z)")) == []


def test_genuinely_wrong_clause_digit_still_fails():
    from app.rules.spec.government_warning import CANONICAL_WARNING, missing_canonical_tokens

    assert "1" in missing_canonical_tokens(CANONICAL_WARNING.replace("(1)", "(3)"))


def test_word_changes_still_fail_exactly():
    # The equivalence is for glyphs, not words — dropping legally-critical wording fails.
    from app.rules.spec.government_warning import CANONICAL_WARNING, missing_canonical_tokens

    assert "not" in missing_canonical_tokens(CANONICAL_WARNING.replace("should not ", "should "))


# --- wine + malt rulesets (27 CFR 4.36 / part 7) -------------------------------------


def test_wine_abv_band_le_14_allows_1_5_points():
    from app.rules.comparators import match_abv_wine

    v, found, _ = match_abv_wine("12.5% by volume", "ALCOHOL 13.5% BY VOLUME")
    assert v is Verdict.PASS and found == "13.5%"


def test_wine_abv_band_gt_14_allows_only_1_point():
    from app.rules.comparators import match_abv_wine

    v, _, detail = match_abv_wine("15.5%", "ALCOHOL 16.8% BY VOLUME")
    assert v is Verdict.NEEDS_REVIEW
    assert "1" in detail  # off by 1.3 > ±1.0


def test_wine_abv_tolerance_never_crosses_the_14_line():
    from app.rules.comparators import match_abv_wine

    # 13.8 vs 14.4 is within ±1.5 — but tolerance may never cross the 14% tax/class
    # line (27 CFR 4.36), so this must be flagged, not passed.
    v, _, detail = match_abv_wine("13.8%", "ALC. 14.4% BY VOL")
    assert v is Verdict.NEEDS_REVIEW
    assert "14" in detail


def test_wine_sulfite_declaration_presence():
    from app.rules.comparators import require_phrase

    v, found, _ = require_phrase(None, "PRODUCT OF FRANCE — CONTAINS SULFITES",
                                 phrase="CONTAINS SULFITES")
    assert v is Verdict.PASS and found == "CONTAINS SULFITES"
    v, _, _ = require_phrase(None, "PRODUCT OF FRANCE", phrase="CONTAINS SULFITES",
                             absent_verdict=Verdict.WARN)
    assert v is Verdict.WARN


def test_wine_and_malt_rulesets_are_wired():
    from app.rules import evaluate

    wine = evaluate("wine", {"brand_name": "SÉLÉNÉ", "class_type": "Red Wine",
                             "alcohol_content": "11%", "net_contents": "750 ML"},
                    "SELENE French Red Wine ALC. 11% BY VOL 750 ML CONTAINS SULFITES")
    by = {f.field: f.verdict for f in wine.fields}
    assert by["brand_name"] is Verdict.PASS
    assert by["alcohol_content"] is Verdict.PASS
    assert by["sulfite_declaration"] is Verdict.PASS

    malt = evaluate("malt_beverage", {"brand_name": "FOUR SIXES", "class_type": "Pilsner",
                                      "alcohol_content": "5.3%", "net_contents": "12 FL OZ"},
                    "FOUR SIXES PILSNER 5.3% ALC/VOL 12 FL OZ (355ML)")
    by = {f.field: f.verdict for f in malt.fields}
    assert by["brand_name"] is Verdict.PASS
    assert by["alcohol_content"] is Verdict.PASS


def test_fold_strips_diacritics_for_brand_matching():
    # Wine brands are full of accents (Séléné, Château) and OCR reads the plain glyphs;
    # folding must treat the accented and plain forms as the same brand.
    from app.rules.normalize import fold

    assert fold("SÉLÉNÉ") == fold("SELENE")
    assert fold("Château Margaux") == fold("CHATEAU MARGAUX")


# --- Conditional fields: country-of-origin applies only to imports --------------------
def _fields(commodity, app, text):
    return {f.field for f in evaluate(commodity, app, text).fields}


def test_country_of_origin_skipped_for_domestic():
    app = {"brand_name": "X", "class_type": "Y", "alcohol_content": "40%",
           "net_contents": "750 mL", "source": "domestic"}
    fields = _fields("distilled_spirits", app, "X Y 40% 750 mL")
    assert "country_of_origin" not in fields       # not applicable for domestic
    assert "responsible_party" in fields           # always applies


def test_country_of_origin_present_for_imported():
    app = {"brand_name": "X", "class_type": "Y", "alcohol_content": "40%",
           "net_contents": "750 mL", "source": "imported", "country_of_origin": "France"}
    fields = _fields("wine", app, "X Y 13% 750 mL PRODUCT OF FRANCE CONTAINS SULFITES")
    assert "country_of_origin" in fields
