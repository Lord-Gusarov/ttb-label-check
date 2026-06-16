"""The government health warning — the single source of truth.

Verbatim text and formatting rules from 27 CFR 16.21 / 16.22. Used by the rules
engine (to validate labels) AND by the corpus generator (to render test labels),
so the two can never drift apart.
"""

import re

from app.rules.normalize import despace

#: The first two words must appear in capital letters and bold type (16.21);
#: the remainder must NOT be bold.
WARNING_PREFIX = "GOVERNMENT WARNING:"

#: The exact required statement. Whitespace may wrap on the label; wording is exact.
CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)


def _tokens(text: str) -> list[str]:
    """Lowercase alphanumeric word tokens (drops punctuation/whitespace)."""
    return re.findall(r"[a-z0-9]+", text.lower())


#: The canonical warning as ordered word tokens — the legal content to verify.
CANONICAL_TOKENS = _tokens(CANONICAL_WARNING)

#: Scoped homoglyph equivalence for the digit clause-markers. '1'/'I'/'l' (and '2'/'Z')
#: are visually identical glyphs at print size — the pixels carry no distinction, so a
#: matcher that treats them as different is verifying the OCR engine, not the label
#: (and no human agent could tell them apart at the same resolution either). This is NOT
#: fuzzy matching: it applies to these glyph classes only, and every WORD change —
#: dropped, altered, reordered — still fails exactly.
_HOMOGLYPHS = {"1": ("1", "i", "l"), "2": ("2", "z")}


def missing_canonical_tokens(candidate: str) -> list[str]:
    """Canonical word tokens NOT found, in order, within ``candidate``.

    Matched against the *de-spaced* candidate so OCR space errors are forgiven: a joined
    "healthproblems" still contains "health" then "problems", and a split "ma chinery"
    still contains "machinery". A genuinely MISSING or changed word (e.g. dropping the
    legally critical "not" from "should not drink") is not recoverable this way and is
    reported — exactly the deletion a similarity ratio would wave through.

    Also used to *score* re-read candidates (fewer missing = better recovery).
    """
    despaced = despace(candidate, strip_accents=False)
    pos = 0
    missing: list[str] = []
    # A short token ('1', 'the', 'of') may spuriously occur far ahead — e.g. the '1' in
    # a post-warning "Alc. 11%" — and letting it teleport the cursor cascades one real
    # miss into dozens (real-corpus finding). Short tokens must match NEAR the cursor;
    # only long tokens are trusted to jump ahead (resync after a dropped phrase).
    near = 24  # chars of OCR junk tolerated between adjacent canonical tokens
    resync_len = 5
    for tok in CANONICAL_TOKENS:
        best: tuple[int, int] | None = None  # (index, matched length)
        for alt in _HOMOGLYPHS.get(tok, (tok,)):
            # A twin glyph ('i' for '1') also occurs INSIDE ordinary words, so it only
            # counts when it sits exactly where the digit belongs; the true token keeps
            # the normal junk tolerance (and long tokens may resync after a dropped run).
            gap = near if alt == tok else 2
            found = despaced.find(alt, pos)
            ok = found != -1 and (
                found - pos <= gap or (alt == tok and len(tok) >= resync_len)
            )
            if ok and (best is None or found < best[0]):
                best = (found, len(alt))
        if best is None:
            missing.append(tok)  # cursor stays put — the next token gets its fair shot
        else:
            pos = best[0] + best[1]  # require the next token to appear later (in order)
    return missing
