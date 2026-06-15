"""Second-pass re-read of the government-warning region.

Pass 1 (full-image OCR) often drops, garbles, or only partly reads the small, dense,
sometimes curved warning text — the engine runs the whole image at one scale and skips
the fine print. So we anchor on the ``GOVERNMENT WARNING`` box that pass 1 *did* find,
crop from there to the bottom of the label, upscale, and re-OCR. On readable labels this
recovers the warning verbatim; on genuinely-distorted ones it still falls short and the
deterministic checks degrade to NEEDS_REVIEW (request a flatter image) rather than guess.

This is the hot-path fix: deterministic, ~0.7s extra, no model in the legal verdict.
When pass 1 found no warning anchor at all, we return None and the checks run on the
original full-image text (which will FAIL / flag a genuinely-missing warning).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.readers.base import Reader
from app.readers.types import WordBox
from app.rules.normalize import despace
from app.rules.spec.government_warning import missing_canonical_tokens

# Re-OCR the warning band at several upscales and keep the best read. No single scale
# wins: PP-OCR's detector resizes internally, so a given layout has an unpredictable
# "good" scale and a bad one nearby (e.g. 1.5x recovers a warning that 2.0x drops, and
# vice-versa for another label). Trying a few and scoring by canonical-token recovery is
# the robust fix. Readable labels recover on the first scale and short-circuit, so the
# extra passes only cost time on the genuinely hard labels.
_SCALES = (1.5, 2.0, 3.0)
_PAD_PX = 14  # a little headroom above the anchor so the prefix isn't clipped

#: Scales for the Tier-1 deskewed re-read — fewer than Tier 0's, to bound latency: Tier 0
#: already explored scales at 0°, so Tier 1 only varies the (measured) angle.
ROTATION_SCALES = (1.5, 2.5)


def _rotate(img: np.ndarray, angle: float) -> np.ndarray:
    """Rotate about center, expanding the canvas (white fill) so nothing is clipped."""
    if angle == 0:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += (nw - w) / 2
    m[1, 2] += (nh - h) / 2
    return cv2.warpAffine(img, m, (nw, nh), borderValue=(255, 255, 255))


@dataclass(frozen=True)
class WarningRegion:
    """Output of the warning re-read.

    ``words`` are in ``crop`` coordinates (so the bold detector can use them against
    ``crop`` directly); ``bbox`` is the re-read region in the ORIGINAL image frame, for
    the UI overlay (hover-highlight "this is where we read the warning").
    """

    text: str
    words: list[WordBox]
    crop: np.ndarray
    bbox: tuple[int, int, int, int]


def estimate_skew(image: np.ndarray, max_angle: float = 12.0, step: float = 0.5) -> float:
    """Measure the correction angle (degrees, for `_rotate`) that makes text horizontal.

    Projection-profile method: threshold the ink, then score candidate angles by how
    sharply the horizontal row-profile separates into text lines vs gaps (sum of squared
    adjacent-row differences — maximal when lines are dead horizontal). The search runs
    on a small BINARY raster, so ~50 candidates cost milliseconds total — unlike the old
    blind sweep, which paid a full OCR pass per candidate angle.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    h = gray.shape[0]
    if h > 400:  # downscale for speed; line structure survives easily
        gray = cv2.resize(gray, None, fx=400 / h, fy=400 / h, interpolation=cv2.INTER_AREA)
    ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    ink = ink.astype(np.float32)
    hh, ww = ink.shape
    center = (ww / 2, hh / 2)
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + step / 2, step):
        m = cv2.getRotationMatrix2D(center, float(angle), 1.0)
        profile = cv2.warpAffine(ink, m, (ww, hh)).sum(axis=1)
        score = float(((profile[1:] - profile[:-1]) ** 2).sum())
        if score > best_score:
            best_score, best_angle = score, float(angle)
    return best_angle


def deskew_reread(
    image: np.ndarray,
    words: list[WordBox],
    reader: Reader,
    scales: tuple[float, ...] = ROTATION_SCALES,
    min_angle: float = 0.75,
) -> WarningRegion | None:
    """Tier 1: MEASURE the warning band's skew, then re-read once at that exact angle.

    Replaces the blind preset-angle sweep (up to 8 OCR passes hoping the skew matches a
    preset) with one cheap measurement + one corrected re-read. Returns None when there is
    no anchor or the band is already straight (|angle| < min_angle — nothing to fix that
    Tier 0 didn't already try).
    """
    band = _band(image, words)
    if band is None:
        return None
    angle = estimate_skew(band)
    if abs(angle) < min_angle:
        return None
    return reread_warning(image, words, reader, angles=(angle,), scales=scales)


def vertical_reread(
    image: np.ndarray, reader: Reader, words: list[WordBox]
) -> WarningRegion | None:
    """Rescue warnings printed 90° to the label (can sidebars, keg collars' rims).

    Real-corpus layout class: the warning runs vertically, so the horizontal pass reads
    fragments at best. Re-extract the FULL image rotated upright both ways and keep the
    best warning read (anchored band re-read inside the rotated frame when possible,
    else the rotated full read). ``crop``/``words`` stay in the rotated (upright) frame —
    correct for the caps/bold checks — while ``bbox`` is mapped back to the original
    frame for the UI overlay. ``words`` is the horizontal pass-1 read: a rotated read is
    only returned when it strictly BEATS that baseline (same discipline as the band
    re-read — an upright label must come back None, never a worse read).
    """
    h, w = image.shape[:2]
    baseline = len(missing_canonical_tokens(" ".join(wd.text for wd in words)))
    best: WarningRegion | None = None
    best_missing: int | None = None
    for rot in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
        upright = cv2.rotate(image, rot)
        read = reader.extract(upright)
        if not _anchor_boxes(read.words):
            continue  # no warning in this orientation
        region = reread_warning(upright, read.words, reader)
        if region is not None:
            text, words_r, crop, (bx1, by1, bx2, by2) = (
                region.text, region.words, region.crop, region.bbox)
        else:  # band re-read didn't improve on the rotated full read — use that read
            text, words_r, crop = read.text, list(read.words), upright
            bx1, by1, bx2, by2 = 0, 0, upright.shape[1], upright.shape[0]
        n_missing = len(missing_canonical_tokens(text))
        if n_missing >= baseline or (best_missing is not None and n_missing >= best_missing):
            continue
        # Map the band rect from the upright frame back into the original frame.
        if rot == cv2.ROTATE_90_CLOCKWISE:  # upright (xr,yr) ← original (x,y)=(yr, h-xr)
            obox = (by1, max(0, h - bx2), by2, max(0, h - bx1))
        else:  # counter-clockwise: original (x,y) = (w - yr, xr)
            obox = (max(0, w - by2), bx1, max(0, w - by1), bx2)
        best = WarningRegion(text=text, words=words_r, crop=crop, bbox=obox)
        best_missing = n_missing
        if n_missing == 0:
            return best
    return best


def _band(image: np.ndarray, words: list[WordBox]) -> np.ndarray | None:
    """The anchored warning band (anchor top − pad → label bottom), or None."""
    anchors = _anchor_boxes(words)
    if not anchors:
        return None
    h, w = image.shape[:2]
    y_top = max(0, min(a.bbox[1] for a in anchors) - _PAD_PX)
    if y_top >= h:
        return None
    region = image[y_top:h, 0:w]
    return region if region.size else None


def _anchor_boxes(words: list[WordBox]) -> list[WordBox]:
    """Pass-1 boxes that mark the warning: the prefix, else distinctive warning tokens."""
    anchors = [w for w in words if "governmentwarning" in despace(w.text, keep_digits=False, strip_accents=False)]
    if not anchors:
        anchors = [
            w
            for w in words
            if "warning" in despace(w.text, keep_digits=False, strip_accents=False)
            or "surgeongeneral" in despace(w.text, keep_digits=False, strip_accents=False)
        ]
    return anchors


def reread_warning(
    image: np.ndarray,
    words: list[WordBox],
    reader: Reader,
    angles: tuple[float, ...] = (0,),
    scales: tuple[float, ...] = _SCALES,
) -> WarningRegion | None:
    """Locate the warning from pass-1 ``words``, crop + upscale it, and re-OCR.

    Searches angle × scale and keeps the read with the most canonical-warning tokens
    recovered, short-circuiting on a perfect read. ``angles=(0,)`` is the cheap default
    (scale search only); pass non-zero ``angles`` (e.g. a measured skew) to also search
    rotation.

    Returns None when no warning anchor is present (nothing to re-read) or the crop is
    degenerate. Any failure is non-fatal: callers fall back to the full-image text.
    """
    anchors = _anchor_boxes(words)
    if not anchors:
        return None

    h, w = image.shape[:2]
    y_top = max(0, min(a.bbox[1] for a in anchors) - _PAD_PX)
    if y_top >= h:
        return None

    region = image[y_top:h, 0:w]
    if region.size == 0:
        return None

    # Pass-1 baseline: the re-read must IMPROVE on what the full-image pass already
    # recovered. On some dense flat labels the band crop breaks the detector entirely
    # (real-corpus finding) — returning that worse read would replace a near-perfect
    # pass-1 warning with garbage. Worse-than-baseline → None → callers keep pass 1.
    baseline_missing = len(missing_canonical_tokens(" ".join(wd.text for wd in words)))

    best: WarningRegion | None = None
    best_missing: int | None = None
    for angle in angles:
        rotated = _rotate(region, angle)
        for scale in scales:
            crop = cv2.resize(rotated, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC)
            read = reader.extract(crop)
            n_missing = len(missing_canonical_tokens(read.text))
            if best_missing is None or n_missing < best_missing:
                best_missing = n_missing
                best = WarningRegion(
                    text=read.text, words=list(read.words), crop=crop,
                    bbox=(0, y_top, w, h),
                )
            if n_missing == 0:
                return best  # full warning recovered — stop searching
    if best_missing is not None and best_missing > baseline_missing:
        return None  # every band read was worse than pass 1 — don't adopt a regression
    return best
