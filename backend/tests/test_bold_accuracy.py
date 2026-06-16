"""Bold-detector accuracy guard.

The bold check is compliance-sensitive: a FALSE-bold (reading a non-bold prefix as bold) would
pass a non-compliant warning, and a FALSE-not-bold needlessly flags a compliant one. This locks
both directions against detector changes — including the caps-vs-lowercase equal-weight case that
a naive per-glyph upscale gets wrong (the prefix is ALL-CAPS / tall, the body lowercase / short).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.bold.detector import detect_warning_bold
from app.readers.types import WordBox

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_BODY = "according to the surgeon general women should not"


def _sample(prefix_thick: int, body_thick: int, body: str = _BODY, scale: float = 0.7):
    """Render a prefix + body line at the given stroke thicknesses; return (image, words)."""
    img = np.full((240, 760, 3), 255, np.uint8)
    (pw, ph), _ = cv2.getTextSize("GOVERNMENT WARNING", _FONT, scale, prefix_thick)
    (bw, bh), _ = cv2.getTextSize(body, _FONT, scale, body_thick)
    cv2.putText(img, "GOVERNMENT WARNING", (20, 70), _FONT, scale, (0, 0, 0), prefix_thick, cv2.LINE_AA)
    cv2.putText(img, body, (20, 150), _FONT, scale, (0, 0, 0), body_thick, cv2.LINE_AA)
    words = [
        WordBox("GOVERNMENT WARNING", 1.0, (18, 70 - ph - 4, 22 + pw, 76)),
        WordBox(body, 1.0, (18, 150 - bh - 4, 22 + bw, 156)),
    ]
    return img, words


# (prefix_thickness, body_thickness, expect_bold)
_NOT_BOLD = [(1, 1), (2, 2), (3, 3)]            # equal weight (incl. caps-vs-lowercase) -> never bold
_BOLD = [(3, 1), (4, 1), (4, 2)]                # clearly heavier prefix -> bold


@pytest.mark.parametrize("pt,bt", _NOT_BOLD)
def test_equal_weight_is_never_false_bold(pt, bt):
    img, words = _sample(pt, bt)
    finding = detect_warning_bold(img, words)
    assert finding.is_bold is not True, f"false-bold at ({pt},{bt}): ratio={finding.ratio}"


@pytest.mark.parametrize("pt,bt", _BOLD)
def test_heavier_prefix_is_detected_bold(pt, bt):
    img, words = _sample(pt, bt)
    finding = detect_warning_bold(img, words)
    assert finding.is_bold is True, f"missed bold at ({pt},{bt}): ratio={finding.ratio}"


CLEAN = Path(__file__).resolve().parent / "fixtures" / "labels" / "old_tom_clean.png"


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_clean_label_bold_resolves_on_base_read():
    """The clean sample is genuinely bold; it should be confidently detected on the BASE read,
    so the pipeline need not pay for an OCR re-read just to re-measure bold."""
    from app.readers import build_reader
    read = build_reader().extract(cv2.imread(str(CLEAN)))
    finding = detect_warning_bold(cv2.imread(str(CLEAN)), read.words)
    assert finding.is_bold is True, f"clean label bold not confident on base read: {finding.ratio} ({finding.detail})"
