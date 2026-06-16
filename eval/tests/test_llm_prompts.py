"""Gated live eval of the two production model prompts (_LABEL_PROMPT, _BOLD_PROMPT).

Makes REAL OpenAI calls — opt-in only: set RUN_LLM_EVAL=1 (and have a key). Skipped by
default so the normal suite stays offline/deterministic. Asserts the safety invariants the
prompts must hold; full per-field accuracy numbers come from eval/eval_model_prompts.py.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not os.environ.get("RUN_LLM_EVAL"),
        reason="live model-prompt eval is opt-in: set RUN_LLM_EVAL=1 (and a key) to run",
    ),
]

os.environ.setdefault("WARNING_ESCALATION_MODEL", os.environ.get("LLM_EVAL_MODEL", "openai:gpt-5.4-mini"))


def test_label_prompt_does_not_fabricate_omitted_fields():
    """Omit a field from the image — the model must return empty, never invent it."""
    from eval_vlm import run_label_eval
    offenders = {
        omitted: {f: r["fabricated"] for f, r in report.items() if r.get("omitted") and r.get("fabricated")}
        for omitted, report in run_label_eval()
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, f"model fabricated omitted fields: {offenders}"


def test_bold_prompt_no_false_yes():
    """The dangerous error — calling a NON-bold prefix 'bold' — must never happen."""
    from eval_vlm import run_bold_slice
    slice_ = run_bold_slice()
    assert slice_["false_yes"] == 0, slice_


@pytest.mark.parametrize("word", ["not", "pregnancy", "health"])
def test_warning_precision_no_reinsertion(word):
    """A legal word missing from the printed warning must NOT be re-inserted by the model."""
    from degrade import render_warning
    from eval_vlm import fabricated_tokens, transcribe_warning
    crop, removed = render_warning(omit=[word])
    reinserted = fabricated_tokens(transcribe_warning(crop), removed)
    assert not reinserted, f"model re-inserted dropped legal word(s): {reinserted}"


def test_synthetic_reads_are_accurate():
    """On the exact-truth synthetic Old Tom set, every field should read near-perfectly."""
    from eval_model_prompts import _truth_b, field_recall
    scores = field_recall(_truth_b())
    low = {f: round(sum(v) / len(v), 2) for f, v in scores.items() if sum(v) / len(v) < 0.95}
    assert not low, f"synthetic read recall below 0.95: {low}"
