"""Shared data types for the reading layer.

Every reader returns the SAME `ReadResult` shape, so the
rest of the pipeline — field extraction, rules engine, the annotation overlay — is
decoupled from which engine actually read the label.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WordBox:
    """A single recognized word with its location and confidence.

    bbox is pixel coordinates ``(x1, y1, x2, y2)`` in the input image's frame —
    used both for the UI overlay and for locating regions (e.g. the warning text)
    for the bold check.
    """

    text: str
    confidence: float  # 0.0 – 1.0
    bbox: tuple[int, int, int, int]


@dataclass(frozen=True)
class ReadResult:
    """The normalized output of any reader."""

    text: str  # full recognized text, in reading order
    words: list[WordBox]
    confidence: float  # mean word confidence, 0.0 – 1.0
    engine: str
    elapsed_ms: float
