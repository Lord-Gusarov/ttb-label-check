"""Degradation helpers produce exact removed-token ground truth."""

from __future__ import annotations

import os

import numpy as np
import pytest

from app.readers.types import WordBox
from corpus.tools.degrade import truncate, occlude_boxes, render_warning


def _wb(text, x1, y1, x2, y2):
    return WordBox(text=text, confidence=1.0, bbox=(x1, y1, x2, y2))


def test_truncate_removes_tail_tokens():
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    words = [_wb("alpha", 0, 0, 40, 20), _wb("beta", 0, 40, 40, 60), _wb("gamma", 0, 70, 40, 90)]
    cropped, removed = truncate(img, words, at_y=65)
    assert cropped.shape[0] == 65
    assert removed == ["gamma"]


def test_occlude_boxes_removes_covered_tokens():
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    words = [_wb("alpha", 0, 0, 40, 20), _wb("beta", 50, 0, 90, 20)]
    out, removed = occlude_boxes(img, words, [1])
    assert removed == ["beta"]
    assert (out[0:20, 50:90] == 0).all()  # covered region blacked out
    assert (out[0:20, 0:40] == 255).all()  # untouched word intact


def test_render_warning_omits_tokens_and_reports_them():
    img, removed = render_warning(omit=["not"])
    assert removed == ["not"]
    assert img.ndim == 3 and img.shape[2] == 3


from corpus.tools.eval_vlm import fabricated_tokens, recall


def test_fabricated_tokens_flags_emitted_removed_token():
    # model output contains 'pregnancy' which was removed -> fabrication
    assert fabricated_tokens("during pregnancy because", ["pregnancy"]) == ["pregnancy"]


def test_fabricated_tokens_none_when_absent():
    assert fabricated_tokens("according to the surgeon general", ["pregnancy"]) == []


def test_recall_counts_visible_tokens_found():
    assert recall("alpha beta", ["alpha", "beta", "gamma"]) == 2 / 3


@pytest.mark.vlm
@pytest.mark.skipif(
    not os.environ.get("RUN_VLM_EVAL"),
    reason="live VLM eval is opt-in: set RUN_VLM_EVAL=1 (and a model key) to run",
)
def test_vlm_does_not_fabricate_omitted_word():
    from corpus.tools.degrade import render_warning
    from corpus.tools.eval_vlm import fabricated_tokens, transcribe_warning

    img, removed = render_warning(omit=["pregnancy"])
    out = transcribe_warning(img)
    assert fabricated_tokens(out, removed) == [], f"model recited removed word: {out!r}"
