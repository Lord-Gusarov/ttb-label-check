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

import numpy as np

from app.bold.detector import detect_warning_bold
from app.escalation import judge_warning_bold
from app.readers.types import WordBox
from app.rules.result import FieldResult, Verdict
from app.rules.spec.government_warning import CANONICAL_WARNING, missing_canonical_tokens
from app.rules.warning_region import WarningRegion

_WS = re.compile(r"\s+")
_PREFIX_RE = re.compile(r"government\s*warning", re.IGNORECASE)


def _collapse(text: str) -> str:
    return _WS.sub(" ", text).strip()


def check_warning_text(label_text: str) -> FieldResult:
    """Exact-wording check by ordered token alignment, anchored on the warning prefix.

    The regulation demands exact wording, but byte-comparison is hopeless against OCR
    noise. Instead we verify that every canonical word appears, in order, within a bounded
    window after the prefix (de-spaced, so OCR join/split errors are forgiven). PASS only
    when the full legal content is present; any missing/changed word is NEEDS_REVIEW (the
    agent reads it) — never a silent PASS. This deliberately catches material deletions
    (e.g. a dropped "not") that a similarity ratio would score ~0.98 and pass.
    """
    norm = _collapse(label_text)
    match = _PREFIX_RE.search(norm)
    if not match:
        return FieldResult(
            "warning_text", "Government warning text", Verdict.NEEDS_REVIEW,
            expected="(canonical warning)", found=None,
            detail="warning statement not found on label",
        )

    # Bound the candidate to a window starting at the prefix (~1.6x the canonical length)
    # so canonical tokens can't be "found" scattered across unrelated label text.
    window = norm[match.start() : match.start() + int(len(CANONICAL_WARNING) * 1.6)]
    missing = missing_canonical_tokens(window)
    if not missing:
        verdict, detail = Verdict.PASS, "matches the required wording"
    else:
        # Prefix present, so the warning IS on the label — but some required wording could
        # not be verified (OCR dropped it, or it's genuinely reworded). A human reads it.
        shown = ", ".join(f"'{m}'" for m in missing[:6])
        more = "…" if len(missing) > 6 else ""
        verdict, detail = (
            Verdict.NEEDS_REVIEW,
            f"warning present but wording not fully verified "
            f"({len(missing)} word(s) missing/garbled: {shown}{more}) — read it",
        )
    return FieldResult(
        "warning_text", "Government warning text", verdict,
        expected="(canonical warning)", found=window[:60] + "…", detail=detail,
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
        "warning_caps", "Warning prefix ALL-CAPS", Verdict.NEEDS_REVIEW,
        expected="GOVERNMENT WARNING", found=found,
        detail=f"must be ALL CAPS — found '{found}'",
    )


def check_warning_bold(
    image: np.ndarray, words: list[WordBox] | None, *, tiebreak: bool = False
) -> FieldResult:
    """Bold via relative stroke width (local, OCR-free). When the local measure is UNCLEAR and
    ``tiebreak`` is set, a fail-safe model adjudicates ONCE on the (upscaled) warning crop — the
    caller enables this only on the best crop so the model call isn't repeated across passes.
    Never a hard FAIL: confident bold -> PASS, else NEEDS_REVIEW."""
    finding = detect_warning_bold(image, words)
    verdict = Verdict.PASS if finding.is_bold is True else Verdict.NEEDS_REVIEW
    found = f"{finding.ratio:.2f}x body" if finding.ratio is not None else None
    detail = finding.detail
    if finding.is_bold is None and tiebreak:  # unclear -> model tiebreak (fail-safe; None when off)
        vote = judge_warning_bold(image)
        if vote == "yes":
            verdict, detail = Verdict.PASS, f"{detail}; model confirmed bold"
        elif vote in {"no", "unclear"}:
            detail = f"{detail}; model bold={vote}"
    return FieldResult(
        "warning_bold", "Warning prefix bold", verdict,
        expected="bold", found=found, detail=detail,
    )


def evaluate_warning(
    image: np.ndarray,
    text: str,
    words: list[WordBox],
    region: WarningRegion | None = None,
    *,
    bold_tiebreak: bool = False,
) -> list[FieldResult]:
    """All three warning checks. When a second-pass `region` is supplied (anchored crop,
    upscaled, re-OCR'd), the checks run on that cleaner output: text/caps on the re-read
    text, bold on the upscaled crop + its boxes. Otherwise they fall back to the primary
    full-image read. `bold_tiebreak` enables the one-shot model bold adjudication (the caller
    sets it only on the best/upscaled crop so it runs at most once per verification).
    """
    if region is not None:
        return [
            check_warning_text(region.text),
            check_warning_caps(region.text),
            check_warning_bold(region.crop, region.words, tiebreak=bold_tiebreak),
        ]
    return [
        check_warning_text(text),
        check_warning_caps(text),
        check_warning_bold(image, words, tiebreak=bold_tiebreak),
    ]
