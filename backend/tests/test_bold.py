"""Tests for the relative stroke-width bold detector.

Hermetic: warning crops are rendered inline with PIL (no dependency on the shared corpus),
so these tests are stable regardless of corpus regeneration.

The detector signature is:
    detect_warning_bold(image: np.ndarray, words: list[WordBox]) -> BoldFinding

WordBox(text, confidence, bbox=(x1, y1, x2, y2)) comes from app.readers.types.

Key contract: the detector NEVER returns is_bold=False; unclear → is_bold=None.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.bold import detect_warning_bold
from app.readers.types import WordBox

ARIAL = "/System/Library/Fonts/Supplemental/Arial.ttf"
ARIAL_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

# The warning prefix that despace() will match as "governmentwarning"
PREFIX = "GOVERNMENT WARNING:"
# Body text that follows on the same line
BODY_SUFFIX = " (1) Women should not drink during pregnancy."

# Image dimensions chosen so the bold prefix ('GOVERNMENT WARNING:') fills
# approximately the left 18-25% of the image width at font-size 28.
# Rendered at W=900, prefix length ≈ 180-200 px → ~20% of width → sits in [0, 18%]
# prefix crop, and the body starts well past the 30% mark.
IMG_W = 900
IMG_H = 60
FONT_SIZE = 28


def _render_line(bold_prefix: bool) -> tuple[np.ndarray, WordBox]:
    """Render PREFIX + BODY_SUFFIX on a single line; return BGR array + WordBox."""
    img = Image.new("RGB", (IMG_W, IMG_H), "white")
    draw = ImageDraw.Draw(img)
    reg = ImageFont.truetype(ARIAL, FONT_SIZE)
    bold = ImageFont.truetype(ARIAL_BOLD, FONT_SIZE)
    pf_font = bold if bold_prefix else reg

    x, y = 10, 8
    draw.text((x, y), PREFIX, font=pf_font, fill="black")
    px = x + draw.textlength(PREFIX, font=pf_font)
    draw.text((px, y), BODY_SUFFIX, font=reg, fill="black")

    # Bounding box for the whole line of text
    full_text = PREFIX + BODY_SUFFIX
    bbox = (0, 0, IMG_W, IMG_H)
    word = WordBox(text=full_text, confidence=0.9, bbox=bbox)

    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    return bgr, word


def test_bold_prefix_detected_as_bold():
    image, word = _render_line(bold_prefix=True)
    finding = detect_warning_bold(image, [word])
    print(f"bold case ratio={finding.ratio}")
    assert finding.is_bold is True
    assert finding.ratio is not None and finding.ratio >= 1.20


def test_regular_prefix_not_detected_as_bold():
    """Regular (non-bold) prefix: detector returns is_bold=None (never False)."""
    image, word = _render_line(bold_prefix=False)
    finding = detect_warning_bold(image, [word])
    print(f"regular case ratio={finding.ratio}")
    # The detector never returns is_bold=False; unclear cases become None.
    assert finding.is_bold is None


def test_empty_words_returns_none():
    """No word boxes → detector cannot locate the warning → is_bold=None."""
    image, _ = _render_line(bold_prefix=True)
    finding = detect_warning_bold(image, [])
    assert finding.is_bold is None
    assert finding.ratio is None


def test_bold_ratio_exceeds_threshold():
    """The bold/regular ratio gap is detectable (bold ratio > non-bold ratio)."""
    img_bold, wb_bold = _render_line(bold_prefix=True)
    img_reg, wb_reg = _render_line(bold_prefix=False)
    f_bold = detect_warning_bold(img_bold, [wb_bold])
    f_reg = detect_warning_bold(img_reg, [wb_reg])
    # Bold should have a higher (or equal) ratio; regular must be below 1.20
    assert f_bold.ratio is not None
    assert f_bold.ratio >= 1.20
    if f_reg.ratio is not None:
        assert f_reg.ratio < 1.20
