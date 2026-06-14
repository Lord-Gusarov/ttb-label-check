"""Deterministic warning-image degradations with exact removed-token ground truth.

Used by eval_vlm.py to probe the model reader for hallucination: each function returns
(image, removed_tokens) so a model that emits a removed token is provably fabricating.
"""

from __future__ import annotations

import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.readers.types import WordBox
from app.rules.spec.government_warning import CANONICAL_WARNING


def _tok(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def truncate(image: np.ndarray, words: list[WordBox], at_y: int) -> tuple[np.ndarray, list[str]]:
    """Crop off everything below `at_y`; removed = tokens of words starting at/after the cut."""
    removed: list[str] = []
    for w in words:
        if w.bbox[1] >= at_y:
            removed.extend(_tok(w.text))
    return image[:at_y].copy(), removed


def occlude_boxes(image: np.ndarray, words: list[WordBox], indices: list[int]) -> tuple[np.ndarray, list[str]]:
    """Black out the given word boxes; removed = their tokens."""
    out = image.copy()
    removed: list[str] = []
    for i in indices:
        x1, y1, x2, y2 = words[i].bbox
        out[max(0, y1):y2, max(0, x1):x2] = 0
        removed.extend(_tok(words[i].text))
    return out, removed


def render_warning(omit: list[str] | None = None, width: int = 900) -> tuple[np.ndarray, list[str]]:
    """Typeset the canonical warning with `omit` tokens removed; removed = those tokens."""
    omit = omit or []
    omit_set = {o.lower() for o in omit}
    kept_words = [w for w in CANONICAL_WARNING.split() if w.strip(".,():").lower() not in omit_set]
    text = " ".join(kept_words)

    img = Image.new("RGB", (width, 300), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    # naive word-wrap
    x, y, line = 10, 10, ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) > width - 20:
            draw.text((x, y), line, fill="black", font=font)
            y += 16
            line = word
        else:
            line = trial
    draw.text((x, y), line, fill="black", font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR), [o.lower() for o in omit]


_LABEL_FIELD_ORDER = (
    "brand_name", "class_type", "alcohol_content", "net_contents", "government_warning"
)


def render_label(
    values: dict[str, str], omit: list[str] | None = None, width: int = 1000
) -> tuple[np.ndarray, list[str]]:
    """Typeset a synthetic full label from `values` (the five reader fields); each field in
    `omit` is left OFF the image entirely. Returns (BGR image, removed_tokens) where removed
    is the alnum tokens of the omitted fields — exact GT for hallucination on the full reader."""
    omit_set = set(omit or [])
    removed: list[str] = []
    img = Image.new("RGB", (width, 700), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    y = 15
    for field in _LABEL_FIELD_ORDER:
        if field not in values:
            continue
        val = values[field]
        if field in omit_set:
            removed.extend(_tok(val))
            continue
        if field == "government_warning":  # wrap the long paragraph
            line = ""
            for word in val.split():
                trial = f"{line} {word}".strip()
                if draw.textlength(trial, font=font) > width - 20:
                    draw.text((10, y), line, fill="black", font=font)
                    y += 16
                    line = word
                else:
                    line = trial
            draw.text((10, y), line, fill="black", font=font)
            y += 16
        else:
            draw.text((10, y), val, fill="black", font=font)
            y += 26
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR), removed
