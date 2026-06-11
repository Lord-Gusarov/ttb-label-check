"""Detect whether 'GOVERNMENT WARNING' is bold — by RELATIVE stroke width.

27 CFR 16.21 requires the words 'GOVERNMENT WARNING' to be in bold type and the
remainder of the statement NOT bold. OCR doesn't reliably report font weight, so we
measure it from pixels: compare the stroke thickness of the GOVERNMENT/WARNING words
against the regular-weight body text of the same warning, on the same image at the same
scale. Bold is RELATIVE — this sidesteps absolute font/DPI calibration entirely.

Word boxes come from Tesseract (run here regardless of the primary reader): it gives
word-level boxes — which the line-level engines don't — and the warning sits on flat
artwork where Tesseract is reliable. If it can't locate the words, we return
`needs_review` rather than guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

from app.readers.preprocess import to_grayscale

# Stroke-width ratio (GW / body) thresholds. Calibrated on the corpus; relative, so
# robust to font/size. Anything ambiguous degrades to needs_review (human decides).
_BOLD_RATIO = 1.20
_AMBIGUOUS_RATIO = 1.08

_GW_WORDS = {"government", "warning"}


@dataclass(frozen=True)
class BoldFinding:
    is_bold: bool | None  # True / False / None (could not determine)
    ratio: float | None  # GW stroke width / body stroke width
    detail: str


def _word_thickness(gray: np.ndarray, box: tuple[int, int, int, int]) -> float | None:
    """Mean stroke width (px) of the text in a word box, via the distance transform.

    Raw stroke width (not height-normalized): the prefix and body of a warning are the
    same font size, differing only in weight, so a direct stroke-width comparison is the
    cleanest signal — and avoids a case artifact (lowercase boxes are taller, which would
    skew a height-normalized measure for a title-case prefix).
    """
    x1, y1, x2, y2 = box
    crop = gray[max(0, y1) : y2, max(0, x1) : x2]
    if crop.size == 0 or crop.shape[0] < 4 or crop.shape[1] < 4:
        return None
    # Text = dark on light -> invert so text pixels are foreground (255).
    _, mask = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    if not np.any(mask):
        return None
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    ridge = dist[dist > 0]
    if ridge.size == 0:
        return None
    return 2.0 * float(ridge.mean())  # approx stroke width in px


def tesseract_words(image: np.ndarray) -> list[tuple[str, tuple[int, int, int, int], int]]:
    """Return (text, bbox, top_y) for each confident word Tesseract finds.

    Public so the warning text/caps checks can share a single Tesseract pass with the
    bold detector (the warning is read with Tesseract for word-level fidelity regardless
    of the primary reader).
    """
    import pytesseract
    from pytesseract import Output

    gray = to_grayscale(image)
    data = pytesseract.image_to_data(gray, output_type=Output.DICT)
    words = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text or float(data["conf"][i]) < 0:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        words.append((text, (x, y, x + w, y + h), y))
    return words


def detect_warning_bold(
    image: np.ndarray,
    words: list[tuple[str, tuple[int, int, int, int], int]] | None = None,
) -> BoldFinding:
    """Assess whether the 'GOVERNMENT WARNING' prefix is bold relative to the body.

    `words` may be passed in to reuse a single Tesseract pass shared with the text/caps
    checks; if omitted, it's computed here.
    """
    gray = to_grayscale(image)
    if words is None:
        words = tesseract_words(image)

    gw_boxes = [b for (t, b, _) in words if re.sub(r"[^a-z]", "", t.lower()) in _GW_WORDS]
    if len(gw_boxes) < 2:
        return BoldFinding(None, None, "could not locate 'GOVERNMENT WARNING' to assess bold")

    gw_top = min(b[1] for b in gw_boxes)
    # Body baseline = regular-weight clause words in the warning block (below/at the GW
    # prefix), excluding the GW words themselves and short tokens/numbers.
    body_boxes = [
        b
        for (t, b, y) in words
        if y >= gw_top
        and re.sub(r"[^a-z]", "", t.lower()) not in _GW_WORDS
        and len(re.sub(r"[^a-z]", "", t.lower())) >= 4
    ]
    if not body_boxes:
        return BoldFinding(None, None, "no body text found to compare against")

    gw_vals = [v for b in gw_boxes if (v := _word_thickness(gray, b)) is not None]
    body_vals = [v for b in body_boxes if (v := _word_thickness(gray, b)) is not None]
    if not gw_vals or not body_vals:
        return BoldFinding(None, None, "could not measure stroke width")

    gw_thick = float(np.mean(gw_vals))
    body_thick = float(np.median(body_vals))
    if body_thick <= 0:
        return BoldFinding(None, None, "degenerate body stroke width")

    ratio = gw_thick / body_thick
    if ratio >= _BOLD_RATIO:
        return BoldFinding(True, ratio, f"'GOVERNMENT WARNING' is bold ({ratio:.2f}× body)")
    if ratio <= _AMBIGUOUS_RATIO:
        return BoldFinding(
            False, ratio, f"'GOVERNMENT WARNING' not bold ({ratio:.2f}× body)"
        )
    return BoldFinding(None, ratio, f"bold unclear ({ratio:.2f}× body) — review")
