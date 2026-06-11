"""Tests for the relative stroke-width bold detector.

Hermetic: warning crops are rendered inline (no dependency on the shared corpus), so
these are stable regardless of corpus regeneration.
"""

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.bold import detect_warning_bold

ARIAL = "/System/Library/Fonts/Supplemental/Arial.ttf"
ARIAL_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

_BODY = [
    "(1) According to the Surgeon General, women should not",
    "drink alcoholic beverages during pregnancy because of the",
    "risk of birth defects. (2) Consumption of alcoholic beverages",
    "impairs your ability to drive a car or operate machinery.",
]


def render_warning(bold_prefix: bool, prefix: str = "GOVERNMENT WARNING:") -> np.ndarray:
    img = Image.new("RGB", (760, 250), "white")
    draw = ImageDraw.Draw(img)
    reg = ImageFont.truetype(ARIAL, 22)
    bold = ImageFont.truetype(ARIAL_BOLD, 22)
    pf = bold if bold_prefix else reg
    draw.text((20, 18), prefix, font=pf, fill="black")
    px = 26 + draw.textlength(prefix, font=pf)
    draw.text((px, 18), _BODY[0].split(") ", 1)[0] + ")", font=reg, fill="black")
    for i, line in enumerate(_BODY):
        draw.text((20, 56 + i * 34), line, font=reg, fill="black")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def test_bold_prefix_detected_as_bold():
    finding = detect_warning_bold(render_warning(bold_prefix=True))
    assert finding.is_bold is True
    assert finding.ratio is not None and finding.ratio >= 1.20


def test_regular_prefix_detected_as_not_bold():
    finding = detect_warning_bold(render_warning(bold_prefix=False))
    assert finding.is_bold is False


def test_thick_prefix_never_called_not_bold():
    # A title-case *bold* prefix is an odd combo (and a caps violation anyway). The
    # detector may call it bold or flag it for review, but must NOT wrongly say "not bold".
    finding = detect_warning_bold(render_warning(bold_prefix=True, prefix="Government Warning:"))
    assert finding.is_bold is not False


def test_no_text_cannot_determine():
    blank = np.full((200, 400, 3), 255, dtype=np.uint8)
    finding = detect_warning_bold(blank)
    assert finding.is_bold is None  # needs_review, not a guess


@pytest.mark.parametrize("bold_prefix,expected", [(True, True), (False, False)])
def test_separation_margin(bold_prefix, expected):
    finding = detect_warning_bold(render_warning(bold_prefix=bold_prefix))
    assert finding.is_bold is expected
