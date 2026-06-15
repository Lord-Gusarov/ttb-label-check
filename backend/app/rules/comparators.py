"""Field comparators — the per-field matching strategies.

Each comparator answers: does the LABEL (OCR text) match the APPLICATION's declared
value, under this field's rules? Returns `(verdict, found, detail)`. They follow the
exact-first cascade: normalized-exact → bounded fuzzy → fail, with field-appropriate
strictness (brand is tolerant; ABV is numeric+tolerance; net contents is presence).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.rules.normalize import despace, fold
from app.rules.result import Verdict
from app.rules.spec.tolerances import ABV_TOLERANCE_PCT

# TTB (27 CFR 5.65) states alcohol content as a percentage by volume, and blesses three
# interchangeable word orders ("Alcohol __ percent by volume", "__ percent alcohol by
# volume", "Alcohol by volume __ percent"). What they all share is a number bound to the
# percent unit, so anchoring on number+unit makes word order irrelevant. The unit may be
# the % glyph or the spelled-out "percent"/"pct" — OCR also frequently drops the % glyph.
_ABV_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent|pct)", re.IGNORECASE)
_PROOF_RE = re.compile(r"(\d+(?:\.\d+)?)\s*proof", re.IGNORECASE)
_FLOAT_RE = re.compile(r"\d+(?:\.\d+)?")

# The mandatory statement is the percentage *presented as alcohol by volume* — the number
# alone is not compliant. We require both an alcohol word (alc/alcohol) and a volume word
# (vol/volume/by) near the matched percentage; proximity (not order) covers all three TTB
# word orders. "ABV" is recognized but is NOT a TTB-sanctioned abbreviation, so it is flagged.
_ALC_RE = re.compile(r"alc(?:ohol)?", re.IGNORECASE)
_VOL_RE = re.compile(r"vol(?:ume)?|\bby\b", re.IGNORECASE)
_ABV_ABBR_RE = re.compile(r"\babv\b", re.IGNORECASE)
_NOMEN_WINDOW = 40  # chars on each side of the matched percentage to scan for the wording


def _best_fuzzy(exp: str, label_folded: str) -> tuple[float, str | None]:
    """Best SequenceMatcher ratio of `exp` against same-length token windows of label."""
    exp_tokens = exp.split()
    lab_tokens = label_folded.split()
    if not exp_tokens or not lab_tokens:
        return 0.0, None
    n = len(exp_tokens)
    best: tuple[float, str | None] = (0.0, None)
    for i in range(0, max(1, len(lab_tokens) - n + 1)):
        window = " ".join(lab_tokens[i : i + n])
        ratio = SequenceMatcher(None, exp, window).ratio()
        if ratio > best[0]:
            best = (ratio, window)
    return best


def match_text(
    expected: str | None,
    label_text: str,
    *,
    fuzzy_threshold: float = 0.85,
    absent_verdict: Verdict = Verdict.NEEDS_REVIEW,
    **_: object,
) -> tuple[Verdict, str | None, str]:
    """Normalized-exact then bounded-fuzzy presence match (brand, class/type)."""
    if not expected:
        return Verdict.NEEDS_REVIEW, None, "no value in application"

    exp = fold(expected)
    lab = fold(label_text)
    if exp and exp in lab:
        return Verdict.PASS, expected, "exact match (normalized)"

    # OCR engines often merge or split words (e.g. "OLD TOM DISTILLERY" read as
    # "OLDTOMDISTILLERY"). A de-spaced containment check is robust to that.
    exp_ds = despace(expected)
    if exp_ds and exp_ds in despace(label_text):
        return Verdict.PASS, expected, "match (spacing-normalized)"

    ratio, snippet = _best_fuzzy(exp, lab)
    if ratio >= 0.97:
        return Verdict.PASS, snippet, f"normalized match (similarity {ratio:.2f})"
    if ratio >= fuzzy_threshold:
        return Verdict.WARN, snippet, f"close match (similarity {ratio:.2f}) — review"
    return absent_verdict, snippet, f"not found on label (best similarity {ratio:.2f})"


def match_abv(
    expected: str | None,
    label_text: str,
    *,
    tolerance: float = 0.3,
    **_: object,
) -> tuple[Verdict, str | None, str]:
    """Compare the label's alcohol-by-volume statement to the application.

    Two dimensions: the *value* (number within ±tolerance) AND the *nomenclature* (the
    number must be presented as "alcohol by volume", 27 CFR 5.65). A bare or unrelated
    "N%" (e.g. "40% off") never stands in for the mandatory statement — it is NEEDS_REVIEW.
    """
    if not expected:
        return Verdict.NEEDS_REVIEW, None, "no alcohol content in application"
    exp_match = _FLOAT_RE.search(expected)
    if not exp_match:
        return Verdict.NEEDS_REVIEW, None, "could not parse application ABV"
    exp_num = float(exp_match.group())

    def _nomenclature(span: tuple[int, int]) -> str:
        s, e = span
        window = label_text[max(0, s - _NOMEN_WINDOW) : e + _NOMEN_WINDOW]
        if _ALC_RE.search(window) and _VOL_RE.search(window):
            return "ok"
        if _ABV_ABBR_RE.search(window):
            return "abv"
        return "none"

    matches = [(float(m.group(1)), _nomenclature(m.span())) for m in _ABV_RE.finditer(label_text)]
    if not matches:
        return Verdict.NEEDS_REVIEW, None, "no ABV (%) found on label"

    # Prefer a percentage stated as alcohol by volume over a bare/unrelated "N%" distractor.
    pool = [m for m in matches if m[1] == "ok"] or matches
    best, best_nom = min(pool, key=lambda c: abs(c[0] - exp_num))
    diff = abs(best - exp_num)

    proof_note = ""
    proof_match = _PROOF_RE.search(label_text)
    if proof_match:
        proof = float(proof_match.group(1))
        if abs(proof - 2 * best) > 1.0:
            proof_note = f"; proof {proof:g} ≠ 2×{best:g} ABV"

    label_abv = f"{best:g}%"
    if diff > tolerance:
        return (
            Verdict.NEEDS_REVIEW,
            label_abv,
            f"off by {diff:.1f} pts (> ±{tolerance:g}); label {best:g}% vs app {exp_num:g}%"
            + proof_note,
        )
    if best_nom == "ok":
        return (
            Verdict.PASS,
            label_abv,
            f"within ±{tolerance:g} (label {best:g}% vs app {exp_num:g}%)" + proof_note,
        )
    if best_nom == "abv":
        return (
            Verdict.NEEDS_REVIEW,
            label_abv,
            f"{best:g}% matches, but 'ABV' is not a TTB-sanctioned abbreviation for the "
            "alcohol content statement — use 'alcohol by volume' (alc/vol)" + proof_note,
        )
    return (
        Verdict.NEEDS_REVIEW,
        label_abv,
        f"{best:g}% found but not stated as 'alcohol by volume' — review wording" + proof_note,
    )


def match_net_contents(
    expected: str | None,
    label_text: str,
    **_: object,
) -> tuple[Verdict, str | None, str]:
    """Presence of the declared net contents, tolerant of spacing (750 mL ~ 750mL)."""
    if not expected:
        return Verdict.NEEDS_REVIEW, None, "no net contents in application"
    exp_ds = despace(expected)
    lab_ds = despace(label_text)
    if exp_ds and exp_ds in lab_ds:
        return Verdict.PASS, expected, "found on label"

    qty = re.search(r"\d+", exp_ds)
    if qty and qty.group() in lab_ds:
        return Verdict.WARN, qty.group(), "quantity present but unit/format differs — review"
    return Verdict.NEEDS_REVIEW, None, "net contents not found on label"


def match_abv_wine(
    expected: str | None,
    label_text: str,
    **_: object,
) -> tuple[Verdict, str | None, str]:
    """Wine ABV (27 CFR 4.36): banded tolerance — ±1.5 pts at ≤14% ABV, ±1.0 above —
    and tolerance may NEVER be used to cross the 14% tax/class line: a label and an
    application on opposite sides of 14% is a class change, not a rounding error."""
    if not expected:
        return Verdict.NEEDS_REVIEW, None, "no alcohol content in application"
    exp_match = _FLOAT_RE.search(expected)
    if not exp_match:
        return Verdict.NEEDS_REVIEW, None, "could not parse application ABV"
    exp_num = float(exp_match.group())

    band = ABV_TOLERANCE_PCT["wine_le_14" if exp_num <= 14 else "wine_gt_14"]
    verdict, found, detail = match_abv(expected, label_text, tolerance=band)
    if verdict is Verdict.PASS and found:
        label_num = float(_FLOAT_RE.search(found).group())  # type: ignore[union-attr]
        if (exp_num <= 14) != (label_num <= 14):
            return (
                Verdict.NEEDS_REVIEW,
                found,
                f"label {label_num:g}% and application {exp_num:g}% sit on opposite "
                "sides of the 14% class line — tolerance may not cross it (27 CFR 4.36)",
            )
    return verdict, found, detail


def require_phrase(
    expected: str | None,  # unused — presence checks have no application field
    label_text: str,
    *,
    phrase: str,
    absent_verdict: Verdict = Verdict.WARN,
    **_: object,
) -> tuple[Verdict, str | None, str]:
    """Presence of a required phrase on the label (e.g. wine's sulfite declaration),
    spacing- and case-tolerant. Absence is ``absent_verdict`` (not FAIL: some products
    are legitimately exempt — e.g. <10ppm sulfites — which only a human can confirm)."""
    del expected
    if despace(phrase) in despace(label_text):
        return Verdict.PASS, phrase, "found on label"
    return absent_verdict, None, f"'{phrase}' not found on label — confirm exemption"


# Standard "responsible party" lead-ins (27 CFR 5.66/4.35/7.65). Fold-normalized: lowercase,
# punctuation→space. A compliant label carries one of these + the firm's name & place.
_RESP_ANCHORS = (
    "bottled by", "produced by", "produced and bottled by", "distilled by", "imported by",
    "manufactured by", "packed by", "brewed by", "vinted by", "blended by", "prepared by",
)
# Country-of-origin lead-ins for imports (27 CFR 5.69 etc.).
_ORIGIN_ANCHORS = ("product of", "produce of", "produced in", "made in", "imported from", "vinted in")


def match_responsible_party(
    expected: str | None,
    label_text: str,
    **_: object,
) -> tuple[Verdict, str | None, str]:
    """Presence of the bottler/producer name & address: a responsible-party anchor
    ('bottled by'/'produced by'/…) AND the declared firm name on the label. Presence-level,
    not an adequacy judge — anything short of both is NEEDS_REVIEW for the agent."""
    if not expected:
        return Verdict.NEEDS_REVIEW, None, "no responsible party in application"
    lab_fold = fold(label_text)
    anchor = next((a for a in _RESP_ANCHORS if a in lab_fold), None)
    name = expected.split(",")[0].strip()  # the firm name precedes the address
    name_found = bool(name) and (despace(name) in despace(label_text) or fold(name) in lab_fold)
    if anchor and name_found:
        return Verdict.PASS, name, f"responsible party present ('{anchor}') and name matches"
    if name_found:
        return Verdict.NEEDS_REVIEW, name, "name present but no 'bottled/produced/imported by' statement — review"
    if anchor:
        return Verdict.NEEDS_REVIEW, anchor, f"'{anchor}' present but declared name not found — review"
    return Verdict.NEEDS_REVIEW, None, "responsible-party statement not found on label — review"


def match_country_of_origin(
    expected: str | None,
    label_text: str,
    **_: object,
) -> tuple[Verdict, str | None, str]:
    """Presence of the country of origin (imports). PASS when the declared country appears on the
    label; if only an origin lead-in is present without the declared country, flag for review."""
    if not expected:
        return Verdict.NEEDS_REVIEW, None, "no country of origin in application"
    country = expected.strip()
    if despace(country) in despace(label_text):
        return Verdict.PASS, country, f"country of origin '{country}' found on label"
    anchor = next((a for a in _ORIGIN_ANCHORS if a in fold(label_text)), None)
    if anchor:
        return (
            Verdict.NEEDS_REVIEW,
            anchor,
            f"origin statement ('{anchor}') present but '{country}' not matched — review",
        )
    return Verdict.NEEDS_REVIEW, None, f"country of origin '{country}' not found on label — review"
