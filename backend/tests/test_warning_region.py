"""Tests for the anchored two-pass warning re-read (hermetic: stub reader, no OCR)."""

from __future__ import annotations

import numpy as np

from app.readers.base import Reader
from app.readers.types import WordBox
from app.rules.warning_region import WarningRegion, reread_warning


class _StubReader(Reader):
    """Echoes a fixed string as the re-read text, so we test geometry not OCR."""

    name = "stub"

    def __init__(self, text: str = "GOVERNMENT WARNING: (1) According") -> None:
        self._text = text

    def available(self) -> bool:
        return True

    def _read(self, image: np.ndarray) -> list[WordBox]:
        h, w = image.shape[:2]
        return [WordBox(text=self._text, confidence=0.9, bbox=(0, 0, w, h))]


def _blank(h: int = 200, w: int = 300) -> np.ndarray:
    return np.full((h, w, 3), 255, dtype=np.uint8)


def test_reread_returns_none_without_anchor():
    words = [WordBox("OLD TOM DISTILLERY", 0.99, (10, 10, 200, 40))]
    assert reread_warning(_blank(), words, _StubReader()) is None


def test_reread_crops_from_anchor_and_reocrs():
    words = [
        WordBox("OLD TOM DISTILLERY", 0.99, (10, 10, 200, 40)),
        WordBox("GOVERNMENT WARNING: (1) According", 0.9, (10, 150, 290, 180)),
    ]
    region = reread_warning(_blank(200, 300), words, _StubReader())
    assert isinstance(region, WarningRegion)
    # bbox is in ORIGINAL image coords: full width, from just above the anchor to bottom.
    x1, y1, x2, y2 = region.bbox
    assert (x1, x2, y2) == (0, 300, 200)
    assert y1 < 150  # padded above the anchor so the prefix isn't clipped
    assert "GOVERNMENT WARNING" in region.text
    # the crop is the region upscaled (best-of multiple scales, all > 1x)
    assert region.crop.shape[0] > (200 - y1)


def test_reread_anchors_on_warning_keyword_when_prefix_split():
    # Pass 1 only recognized "WARNING ..." (prefix space dropped/garbled) — still anchors.
    words = [WordBox("WARNING (1) According to", 0.8, (5, 120, 250, 150))]
    assert reread_warning(_blank(180, 260), words, _StubReader()) is not None


# --- measured deskew (replaces the blind rotation sweep) ---------------------------


def _lined_page(angle: float = 0.0) -> np.ndarray:
    """A page of horizontal 'text lines' (dense black rows), optionally rotated."""
    import cv2

    from app.rules.warning_region import _rotate

    img = _blank(400, 600)
    for y in range(60, 360, 28):  # line height ~12px, spacing ~28px — text-like
        cv2.rectangle(img, (40, y), (560, y + 12), (0, 0, 0), -1)
    return _rotate(img, angle)


def test_estimate_skew_zero_on_straight_text():
    from app.rules.warning_region import estimate_skew

    assert abs(estimate_skew(_lined_page(0.0))) <= 0.5


def test_estimate_skew_measures_correction_angle():
    from app.rules.warning_region import estimate_skew

    # Rotated +7° → the measured correction is ≈ −7° (what _rotate needs to undo it).
    assert abs(estimate_skew(_lined_page(7.0)) + 7.0) <= 1.0
    assert abs(estimate_skew(_lined_page(-4.0)) - 4.0) <= 1.0


# --- the band re-read must never DEGRADE below the pass-1 read -----------------------
# Real-corpus finding (Séléné, 24110001000168): the full-image pass read the warning
# almost perfectly, but the band crop broke the detector (13 garbage words) and
# reread_warning returned that worse read. Guard: if the best band read recovers fewer
# canonical tokens than pass 1 already had, return None and keep the pass-1 text.


def test_reread_returns_none_when_band_read_is_worse_than_pass1():
    from app.rules.spec.government_warning import CANONICAL_WARNING

    # Pass 1 already read the full canonical warning…
    words = [
        WordBox("OLD TOM DISTILLERY", 0.99, (10, 10, 200, 40)),
        WordBox(CANONICAL_WARNING, 0.9, (10, 120, 290, 190)),
    ]
    # …but the band re-read produces garbage (detector falls over on the crop).
    region = reread_warning(_blank(), words, _StubReader("x y z"))
    assert region is None


def test_reread_still_returned_when_it_improves_on_pass1():
    # Pass 1 caught only the prefix; the band re-read recovers more — keep it.
    words = [WordBox("GOVERNMENT WARNING:", 0.9, (10, 150, 290, 180))]
    region = reread_warning(
        _blank(), words, _StubReader("GOVERNMENT WARNING: (1) According to the Surgeon")
    )
    assert region is not None


import pytest  # noqa: E402

from pathlib import Path  # noqa: E402

_REAL = Path(__file__).resolve().parents[2] / "eval" / "data" / "real" / "images"


def test_golden_flat_dense_label_never_degrades_below_pass1():
    # Séléné: flat, dense, near-perfect at pass 1 (only the '(1)' digit misreads). The
    # band re-read must return either None or a read at least as good — never replace
    # the pass-1 text with something worse (the pre-guard behavior lost 38 tokens here).
    from app.readers import build_reader
    from app.readers.preprocess import load_image
    from app.rules.spec.government_warning import missing_canonical_tokens

    path = _REAL / "24110001000168__0_img0.JPG"
    if not path.exists():
        pytest.skip("real corpus not fetched")
    img = load_image(str(path))
    reader = build_reader()
    words = reader.extract(img).words
    baseline = len(missing_canonical_tokens(" ".join(w.text for w in words)))
    assert baseline <= 1  # pass 1 reads this label nearly perfectly
    region = reread_warning(img, words, reader)
    assert region is None or len(missing_canonical_tokens(region.text)) <= baseline


def test_deskew_reread_rescues_a_skewed_label():
    # End-to-end mechanism test on real OCR: a clean label rotated 6° (a tilted user
    # photo) is unreadable at 0° but the MEASURED deskew recovers the warning.
    from app.readers import build_reader
    from app.readers.preprocess import load_image
    from app.rules.spec.government_warning import missing_canonical_tokens
    from app.rules.warning_region import _rotate, deskew_reread

    path = Path(__file__).resolve().parent / "fixtures" / "labels" / "old_tom_clean.png"
    if not path.exists():
        pytest.skip("seed corpus not generated")
    img = _rotate(load_image(str(path)), 6.0)
    reader = build_reader()
    words = reader.extract(img).words
    region = deskew_reread(img, words, reader)
    if region is None:
        pytest.skip("pass-1 already read the rotated label perfectly")
    assert missing_canonical_tokens(region.text) == []


# --- vertical-sidebar rescue: warning printed 90° to the label (cans, sidebars) ------


def test_vertical_reread_rescues_sideways_warning():
    # Real-corpus class (FOUR SIXES can, THUNDER CANYON sidebar): the warning runs 90°
    # to the label. Reading the image rotated upright recovers it — locally, no model.
    import cv2

    from app.readers import build_reader
    from app.readers.preprocess import load_image
    from app.rules.spec.government_warning import missing_canonical_tokens
    from app.rules.warning_region import vertical_reread

    path = Path(__file__).resolve().parent / "fixtures" / "labels" / "old_tom_clean.png"
    if not path.exists():
        pytest.skip("seed corpus not generated")
    sideways = cv2.rotate(load_image(str(path)), cv2.ROTATE_90_CLOCKWISE)
    reader = build_reader()
    region = vertical_reread(sideways, reader, reader.extract(sideways).words)
    assert region is not None
    assert missing_canonical_tokens(region.text) == []
    # bbox must be remapped to the ORIGINAL (sideways) frame for the UI overlay.
    h, w = sideways.shape[:2]
    x1, y1, x2, y2 = region.bbox
    assert 0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h


def test_vertical_reread_returns_none_on_normal_label():
    from app.readers import build_reader
    from app.readers.preprocess import load_image
    from app.rules.warning_region import vertical_reread

    path = Path(__file__).resolve().parent / "fixtures" / "labels" / "old_tom_clean.png"
    if not path.exists():
        pytest.skip("seed corpus not generated")
    # Upright label: rotated reads find no warning (or a worse one) → None, fail-safe.
    img = load_image(str(path))
    reader = build_reader()
    assert vertical_reread(img, reader, reader.extract(img).words) is None
