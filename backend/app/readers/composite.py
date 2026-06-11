"""Confidence-gated fallback reader.

Runs a fast primary reader; only if its mean confidence is below a threshold does it
pay for a second, more robust reader (RapidOCR or a local VLM) and keep whichever read
is more confident. This is how we honor BOTH the 5s budget (most labels = primary only)
and Jenny's messy-image wish (hard labels get the heavier engine).
"""

from __future__ import annotations

import numpy as np

from app.config import settings
from app.readers.base import Reader, get_reader
from app.readers.types import ReadResult


class FallbackReader(Reader):
    """Compose a primary + fallback reader, gated on the primary's confidence."""

    def __init__(self, primary: Reader, fallback: Reader, threshold: float) -> None:
        self.primary = primary
        self.fallback = fallback
        self.threshold = threshold
        self.name = f"{primary.name}+{fallback.name}"

    def available(self) -> bool:
        return self.primary.available()

    def _read(self, image: np.ndarray):  # pragma: no cover - composes timed reads
        raise NotImplementedError("FallbackReader composes extract(); _read is unused")

    def extract(self, image: np.ndarray) -> ReadResult:
        primary = self.primary.extract(image)
        if primary.confidence >= self.threshold or not self.fallback.available():
            return primary
        alt = self.fallback.extract(image)
        return alt if alt.confidence > primary.confidence else primary


def build_reader() -> Reader:
    """Construct the configured runtime reader (with fallback if enabled/available)."""
    primary = get_reader(settings.default_reader)
    if not settings.enable_fallback:
        return primary
    try:
        fallback = get_reader(settings.fallback_reader)
    except KeyError:
        return primary
    if not fallback.available() or fallback.name == primary.name:
        return primary
    return FallbackReader(primary, fallback, settings.fallback_confidence)
