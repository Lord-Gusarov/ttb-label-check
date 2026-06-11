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

_ABV_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PROOF_RE = re.compile(r"(\d+(?:\.\d+)?)\s*proof", re.IGNORECASE)
_FLOAT_RE = re.compile(r"\d+(?:\.\d+)?")


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
    absent_verdict: Verdict = Verdict.FAIL,
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
    """Parse the ABV number and compare to the application within ±tolerance points."""
    if not expected:
        return Verdict.NEEDS_REVIEW, None, "no alcohol content in application"
    exp_match = _FLOAT_RE.search(expected)
    if not exp_match:
        return Verdict.NEEDS_REVIEW, None, "could not parse application ABV"
    exp_num = float(exp_match.group())

    candidates = [float(x) for x in _ABV_RE.findall(label_text)]
    if not candidates:
        return Verdict.NEEDS_REVIEW, None, "no ABV (%) found on label"

    best = min(candidates, key=lambda c: abs(c - exp_num))
    diff = abs(best - exp_num)

    proof_note = ""
    proof_match = _PROOF_RE.search(label_text)
    if proof_match:
        proof = float(proof_match.group(1))
        if abs(proof - 2 * best) > 1.0:
            proof_note = f"; proof {proof:g} ≠ 2×{best:g} ABV"

    label_abv = f"{best:g}%"
    if diff <= tolerance:
        return (
            Verdict.PASS,
            label_abv,
            f"within ±{tolerance:g} (label {best:g}% vs app {exp_num:g}%)" + proof_note,
        )
    return (
        Verdict.FAIL,
        label_abv,
        f"off by {diff:.1f} pts (> ±{tolerance:g}); label {best:g}% vs app {exp_num:g}%"
        + proof_note,
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
    return Verdict.FAIL, None, "net contents not found on label"
