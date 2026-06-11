"""Government health warning checks (27 CFR 16.21 / 16.22).

Three deterministic checks, each its own FieldResult:
  1. text  — exact wording (whitespace-normalized; tolerant of OCR noise via similarity)
  2. caps  — 'GOVERNMENT WARNING' must be ALL CAPS (catches Jenny's title-case reject)
  3. bold  — the prefix must be bold (relative stroke-width; see app.bold)

Exactness vs OCR noise: the regulation demands exact wording, but OCR drops/merges
words, so we never byte-compare. High similarity → PASS; a middling score is
NEEDS_REVIEW (could be OCR noise OR real rewording — a human decides), not a hard FAIL.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

import numpy as np

from app.bold.detector import detect_warning_bold, tesseract_words
from app.rules.result import FieldResult, Verdict
from app.rules.spec.government_warning import CANONICAL_WARNING

_WS = re.compile(r"\s+")
_PREFIX_RE = re.compile(r"government\s*warning", re.IGNORECASE)


def _collapse(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _despace(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def check_warning_text(label_text: str) -> FieldResult:
    """Exact-wording check, anchored on the warning prefix, tolerant of OCR noise."""
    norm = _collapse(label_text)
    match = _PREFIX_RE.search(norm)
    if not match:
        return FieldResult(
            "warning_text", "Government warning text", Verdict.FAIL,
            expected="(canonical warning)", found=None,
            detail="warning statement not found on label",
        )

    region = norm[match.start() :]
    canon = CANONICAL_WARNING
    # Compare both as collapsed-lowercase and fully de-spaced; take the better score
    # (OCR merges/splits spaces, so de-spaced is the fairer floor).
    ratio = max(
        SequenceMatcher(None, canon.lower(), region.lower()).ratio(),
        SequenceMatcher(None, _despace(canon), _despace(region)).ratio(),
    )
    if ratio >= 0.95:
        verdict, detail = Verdict.PASS, f"matches required wording (similarity {ratio:.2f})"
    elif ratio >= 0.80:
        verdict, detail = (
            Verdict.NEEDS_REVIEW,
            f"close to required wording (similarity {ratio:.2f}) — verify exact text / OCR",
        )
    else:
        verdict, detail = (
            Verdict.FAIL,
            f"wording differs from required statement (similarity {ratio:.2f})",
        )
    return FieldResult(
        "warning_text", "Government warning text", verdict,
        expected="(canonical warning)", found=region[:60] + "…", detail=detail,
    )


def check_warning_caps(raw_text: str) -> FieldResult:
    """'GOVERNMENT WARNING' must be in capital letters (case preserved by the reader)."""
    match = _PREFIX_RE.search(raw_text)
    if not match:
        return FieldResult(
            "warning_caps", "Warning prefix ALL-CAPS", Verdict.NEEDS_REVIEW,
            expected="GOVERNMENT WARNING", found=None,
            detail="could not locate the warning prefix to check capitalization",
        )
    found = match.group()
    letters = re.sub(r"[^A-Za-z]", "", found)
    if letters.isupper():
        return FieldResult(
            "warning_caps", "Warning prefix ALL-CAPS", Verdict.PASS,
            expected="GOVERNMENT WARNING", found=found, detail="in all capital letters",
        )
    return FieldResult(
        "warning_caps", "Warning prefix ALL-CAPS", Verdict.FAIL,
        expected="GOVERNMENT WARNING", found=found,
        detail=f"must be ALL CAPS — found '{found}'",
    )


def check_warning_bold(image: np.ndarray, words=None) -> FieldResult:
    """Bold check via relative stroke width (see app.bold.detector)."""
    finding = detect_warning_bold(image, words=words)
    if finding.is_bold is True:
        verdict = Verdict.PASS
    elif finding.is_bold is False:
        verdict = Verdict.FAIL
    else:
        verdict = Verdict.NEEDS_REVIEW
    found = f"{finding.ratio:.2f}× body" if finding.ratio is not None else None
    return FieldResult(
        "warning_bold", "Warning prefix bold", verdict,
        expected="bold", found=found, detail=finding.detail,
    )


def evaluate_warning(image: np.ndarray) -> list[FieldResult]:
    """All three warning checks off a single Tesseract pass of the image.

    The warning is read with Tesseract (word-level, case-preserving) regardless of the
    primary reader — it's small printed text on flat artwork where Tesseract is reliable,
    and the field-matching reader (e.g. RapidOCR) can be lossy on long text blocks.
    """
    words = tesseract_words(image)
    raw_text = " ".join(t for (t, _, _) in words)
    return [
        check_warning_text(raw_text),
        check_warning_caps(raw_text),
        check_warning_bold(image, words=words),
    ]
