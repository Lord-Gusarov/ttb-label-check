"""On-demand VLM faithfulness eval for the government-warning read.

Direct-to-model (Tier 1 absent): degrade warning crops/renders with KNOWN removed tokens,
transcribe each with a declared-blind warning prompt, and measure completeness (recall) and
hallucination (fabricated = model emits a removed token). Not part of the default test suite.

Usage:  python corpus/tools/eval_vlm.py
"""

from __future__ import annotations

import re

import cv2
import numpy as np

from app.escalation import _chat_json, judge_warning_bold
from corpus.tools.degrade import render_warning


def _tok(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def fabricated_tokens(output: str, removed: list[str]) -> list[str]:
    """Removed tokens that nonetheless appear in the model output (= hallucinated)."""
    out = set(_tok(output))
    return [t for t in removed if t.lower() in out]


def recall(output: str, visible: list[str]) -> float:
    """Fraction of visible ground-truth tokens present in the output."""
    if not visible:
        return 1.0
    out = set(_tok(output))
    return sum(1 for t in visible if t.lower() in out) / len(visible)


def bold_accuracy(cases: list[tuple[str | None, bool]]) -> dict[str, int]:
    """Score (vote, is_actually_bold) pairs. correct = vote matches truth ('yes'==bold,
    'no'==not bold); false_yes = vote 'yes' on a non-bold prefix (the dangerous error)."""
    correct = false_yes = 0
    for vote, truth in cases:
        if (vote == "yes" and truth) or (vote == "no" and not truth):
            correct += 1
        if vote == "yes" and not truth:
            false_yes += 1
    return {"n": len(cases), "correct": correct, "false_yes": false_yes}


_WARNING_PROMPT = (
    "Transcribe the GOVERNMENT WARNING in this cropped image EXACTLY as printed. Do not infer, "
    "complete, or correct anything; if a word is missing or unreadable, leave it out. Use an empty "
    "string if no warning is present. Return ONLY JSON: {\"government_warning\": \"...\"}."
)


def transcribe_warning(crop: np.ndarray, model: str = "gpt-5.4-mini") -> str:
    data = _chat_json(crop, model, _WARNING_PROMPT)
    return str((data or {}).get("government_warning", ""))


def _prefix_crop(thickness: int) -> np.ndarray:
    img = np.full((120, 600, 3), 255, dtype=np.uint8)
    cv2.putText(img, "GOVERNMENT WARNING", (15, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), thickness, cv2.LINE_AA)
    cv2.putText(img, "according to the surgeon general consumption", (15, 95),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    return img


def run_bold_slice() -> dict[str, int]:
    cases = [(judge_warning_bold(_prefix_crop(5)), True), (judge_warning_bold(_prefix_crop(1)), False)]
    return bold_accuracy(cases)


def main() -> None:
    # Missing-words family (synthetic, exact GT): omit one required token at a time.
    cases = [render_warning(omit=[w]) for w in ("not", "pregnancy", "health")]
    fabrications = 0
    for img, removed in cases:
        out = transcribe_warning(img)
        fab = fabricated_tokens(out, removed)
        fabrications += bool(fab)
        print(f"removed={removed} fabricated={fab} :: {out[:80]!r}")
    n = len(cases)
    print(f"\nmissing-words cases: {n}  fabrication-rate: {fabrications}/{n} = {fabrications / n:.0%}")

    slice_ = run_bold_slice()
    print(f"bold-judge: {slice_['correct']}/{slice_['n']} correct, false-yes={slice_['false_yes']}")


if __name__ == "__main__":
    main()
