"""Degradation helpers produce exact removed-token ground truth."""

from __future__ import annotations

import os

import numpy as np
import pytest

from app.readers.types import WordBox
from degrade import truncate, occlude_boxes, render_label, render_warning


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


def test_render_label_omits_field_tokens():
    img, removed = render_label(
        {"brand_name": "OLD TOM", "alcohol_content": "40% ALC/VOL"}, omit=["alcohol_content"]
    )
    assert removed == ["40", "alc", "vol"]  # tokens of the omitted field's value
    assert img.ndim == 3 and img.shape[2] == 3


from eval_vlm import bold_accuracy, fabricated_tokens, label_field_report, recall


def test_label_field_report_flags_fabricated_omitted_field():
    values = {"brand_name": "OLD TOM", "alcohol_content": "40% ALC/VOL"}
    result = {"brand_name": "OLD TOM", "alcohol_content": "40% ALC/VOL"}  # model recited omitted ABV
    rep = label_field_report(result, values, omitted="alcohol_content")
    assert rep["alcohol_content"]["omitted"] is True
    assert "40" in rep["alcohol_content"]["fabricated"]
    assert rep["brand_name"]["recall"] == 1.0


def test_label_field_report_no_fabrication_when_field_blank():
    values = {"alcohol_content": "40% ALC/VOL"}
    result = {"alcohol_content": ""}
    rep = label_field_report(result, values, omitted="alcohol_content")
    assert rep["alcohol_content"]["fabricated"] == []


def test_bold_accuracy_scores_votes_against_truth():
    cases = [("yes", True), ("no", False), ("yes", False), ("unclear", True)]
    acc = bold_accuracy(cases)
    assert acc["correct"] == 2          # (yes,True) and (no,False)
    assert acc["false_yes"] == 1        # (yes,False)
    assert acc["n"] == 4


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
    from degrade import render_warning
    from eval_vlm import fabricated_tokens, transcribe_warning

    img, removed = render_warning(omit=["pregnancy"])
    out = transcribe_warning(img)
    assert fabricated_tokens(out, removed) == [], f"model recited removed word: {out!r}"
