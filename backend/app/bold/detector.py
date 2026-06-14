"""Detect whether 'GOVERNMENT WARNING' is bold — OCR-free, by relative stroke width.

27 CFR 16.21 requires the words 'GOVERNMENT WARNING' to be in bold type. OCR engines don't
report font weight, so we measure it from pixels: locate the warning region from the primary
reader's boxes, then compare the stroke thickness of the **prefix** (left of the warning block,
where 'GOVERNMENT WARNING' sits) against the **body** of the warning. Bold is RELATIVE, so this
sidesteps absolute font/DPI calibration.

No Tesseract: the region comes from the primary reader's boxes; everything else is OpenCV. Bold
detection is inherently approximate (small/dense/curved text), so it is never a hard FAIL — a
confident measurement reads PASS, anything unclear is NEEDS_REVIEW for the agent to confirm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

from app.readers.preprocess import to_grayscale
from app.readers.types import WordBox

_BOLD_RATIO = 1.20      # prefix stroke width must exceed body by this factor to read as bold
_NOT_BOLD_RATIO = 1.00  # at/below this (with a confident measurement) reads as NOT bold
_MIN_GLYPH_H = 14       # below this prefix height, upscale + CLAHE before measuring
_BODY_BAND = 8          # search body words within this many prefix-heights below the prefix


@dataclass(frozen=True)
class BoldFinding:
    is_bold: bool | None  # True / False / None (could not determine)
    ratio: float | None  # prefix stroke width / body stroke width
    detail: str


def _despace(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def _stroke_width(gray_crop: np.ndarray) -> float | None:
    """Mean stroke width (px) of dark text in a crop, via the distance transform."""
    if gray_crop.size == 0 or gray_crop.shape[0] < 5 or gray_crop.shape[1] < 5:
        return None
    _, mask = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    if not np.any(mask):
        return None
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    ridge = dist[dist > 0]
    if ridge.size == 0:
        return None
    return 2.0 * float(ridge.mean())


def _prep(crop: np.ndarray, glyph_h: int) -> np.ndarray:
    """Upscale + contrast-normalize tiny/low-contrast crops so stroke width is measurable."""
    if glyph_h >= _MIN_GLYPH_H or crop.size == 0:
        return crop
    scale = max(1, round(_MIN_GLYPH_H / max(1, glyph_h)) + 1)
    up = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(up)


def _mean_stroke(gray: np.ndarray, boxes: list[WordBox]) -> float | None:
    """Mean stroke width across the given word boxes (each crop prepped if tiny)."""
    widths: list[float] = []
    for b in boxes:
        x1, y1, x2, y2 = b.bbox
        crop = gray[max(0, y1):y2, max(0, x1):x2]
        sw = _stroke_width(_prep(crop, y2 - y1))
        if sw is not None:
            widths.append(sw)
    return float(np.mean(widths)) if widths else None


def detect_warning_bold(image: np.ndarray, words: list[WordBox] | None) -> BoldFinding:
    """Assess whether 'GOVERNMENT WARNING' is bold relative to the warning body.

    Selects the prefix word boxes ('government'/'warning') and the body word boxes (the
    other warning-paragraph words in a band below the prefix), then compares their mean
    stroke widths. This is independent of line geometry, so justified/multi-line and
    own-line prefixes both work. Tiny/low-contrast crops are upscaled + CLAHE'd first.
    """
    gray = to_grayscale(image)
    words = words or []
    prefix = [w for w in words if "government" in _despace(w.text) or "warning" in _despace(w.text)]
    if not prefix:
        return BoldFinding(None, None, "could not locate the warning prefix to assess bold")

    anchor = min(prefix, key=lambda w: w.bbox[1])  # topmost prefix box
    ah = anchor.bbox[3] - anchor.bbox[1]
    band_bottom = anchor.bbox[1] + max(1, _BODY_BAND * ah)
    prefix_ids = {id(w) for w in prefix}
    body = [
        w for w in words
        if id(w) not in prefix_ids and anchor.bbox[1] - ah <= w.bbox[1] <= band_bottom
    ]
    if not body:
        return BoldFinding(None, None, "no body text near the warning prefix to compare against")

    pw, bw = _mean_stroke(gray, prefix), _mean_stroke(gray, body)
    if pw is None or bw is None or bw <= 0:
        return BoldFinding(None, None, "could not measure stroke width")

    ratio = pw / bw
    if ratio >= _BOLD_RATIO:
        return BoldFinding(True, ratio, f"'GOVERNMENT WARNING' is bold ({ratio:.2f}x body)")
    if ratio <= _NOT_BOLD_RATIO:
        return BoldFinding(False, ratio, f"prefix not heavier than body ({ratio:.2f}x) — verify")
    return BoldFinding(None, ratio, f"bold unclear ({ratio:.2f}x body) — verify the prefix is bold")
