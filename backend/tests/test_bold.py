"""Bold detector: box-based prefix/body stroke-width measurement."""

from __future__ import annotations

import cv2
import numpy as np

from app.bold.detector import detect_warning_bold
from app.readers.types import WordBox


def _canvas(h=200, w=600):
    return np.full((h, w, 3), 255, dtype=np.uint8)


def _draw(img, text, org, scale, thickness):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness, cv2.LINE_AA)


def _wb(text, x1, y1, x2, y2):
    return WordBox(text=text, confidence=1.0, bbox=(x1, y1, x2, y2))


def test_bold_prefix_detected_across_separate_lines():
    # Prefix on its own line (thick), body on the next line (thin) — the old fixed
    # left/right slice could not handle this; box-based selection must.
    img = _canvas()
    _draw(img, "GOVERNMENT WARNING", (20, 50), 1.0, 5)   # bold prefix line
    _draw(img, "according to the surgeon general", (20, 120), 0.7, 1)  # thin body line
    words = [
        _wb("GOVERNMENT", 18, 25, 230, 60),
        _wb("WARNING", 240, 25, 400, 60),
        _wb("according to the surgeon general", 18, 95, 470, 130),
    ]
    finding = detect_warning_bold(img, words)
    assert finding.is_bold is True
    assert finding.ratio is not None and finding.ratio >= 1.2


def test_non_bold_prefix_is_not_true():
    img = _canvas()
    _draw(img, "GOVERNMENT WARNING", (20, 50), 0.7, 1)   # same weight as body
    _draw(img, "according to the surgeon general", (20, 120), 0.7, 1)
    words = [
        _wb("GOVERNMENT", 18, 30, 200, 60),
        _wb("WARNING", 210, 30, 360, 60),
        _wb("according to the surgeon general", 18, 95, 470, 130),
    ]
    finding = detect_warning_bold(img, words)
    assert finding.is_bold is not True  # False or None, never a confident bold
    assert finding.ratio is not None and finding.ratio < 1.2  # measured, below bold threshold


def test_no_prefix_box_returns_none():
    img = _canvas()
    finding = detect_warning_bold(img, [_wb("something else", 10, 10, 100, 30)])
    assert finding.is_bold is None
    assert "locate" in finding.detail


def test_tiny_glyphs_are_measured_via_upscale():
    # Glyphs well below _MIN_GLYPH_H must still be measurable (the _prep upscale path),
    # not crash on the CLAHE step and not silently return None for "could not measure".
    img = _canvas(h=80, w=400)
    _draw(img, "GOVERNMENT WARNING", (5, 18), 0.3, 2)            # tiny bold prefix
    _draw(img, "according to the surgeon general", (5, 40), 0.3, 1)  # tiny thin body
    words = [
        _wb("GOVERNMENT", 4, 8, 95, 22),
        _wb("WARNING", 100, 8, 165, 22),
        _wb("according to the surgeon general", 4, 30, 250, 44),
    ]
    finding = detect_warning_bold(img, words)
    assert finding.ratio is not None  # a measurement was produced, no crash
