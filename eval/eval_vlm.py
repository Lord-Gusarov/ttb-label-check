"""On-demand VLM faithfulness eval for the government-warning read.

Direct-to-model (Tier 1 absent): degrade warning crops/renders with KNOWN removed tokens,
transcribe each with a declared-blind warning prompt, and measure completeness (recall) and
hallucination (fabricated = model emits a removed token). Not part of the default test suite.

Usage:  python eval/eval_vlm.py
"""

from __future__ import annotations

import re

import cv2
import numpy as np

from app.escalation import _chat_json, escalate_label_read
from app.rules.spec.government_warning import CANONICAL_WARNING
from degrade import render_label, render_warning


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


def _bold_label(thickness: int) -> np.ndarray:
    """A minimal full label whose 'GOVERNMENT WARNING' prefix is drawn at `thickness` (5=bold,
    1=not) so the PRODUCTION label-read's bold judgment can be scored — bold now rides on the
    same label-read call, so there is no separate bold prompt to test."""
    img = np.full((420, 820, 3), 255, dtype=np.uint8)
    f = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, "OLD TOM DISTILLERY", (40, 60), f, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(img, "40% ALC/VOL  750 mL", (40, 110), f, 0.7, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(img, "GOVERNMENT WARNING:", (40, 210), f, 0.8, (0, 0, 0), thickness, cv2.LINE_AA)
    cv2.putText(img, "(1) According to the Surgeon General, women should not drink", (40, 250),
                f, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    return img


def run_bold_slice() -> dict[str, int]:
    """Score the production label-read's bold judgment: a bold prefix should vote 'yes', a
    not-bold one should not. `false_yes` (calling not-bold "bold") is the dangerous error."""
    def vote(thick: int) -> str:
        return (escalate_label_read(_bold_label(thick)) or {}).get("government_warning_bold", "")
    return bold_accuracy([(vote(5), True), (vote(1), False)])


def label_field_report(result: dict, values: dict, omitted: str) -> dict:
    """Score one full-label read against ground truth: per field, recall when present, or
    the fabricated tokens when that field was omitted from the image (= hallucination)."""
    report: dict = {}
    for field, value in values.items():
        toks = _tok(value)
        if field == omitted:
            report[field] = {"omitted": True, "fabricated": fabricated_tokens(result.get(field) or "", toks)}
        else:
            report[field] = {"omitted": False, "recall": recall(result.get(field) or "", toks)}
    return report


#: A synthetic but realistic full label for evaluating the PRODUCTION reader (escalate_label_read).
_SYNTH_LABEL = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "KENTUCKY STRAIGHT BOURBON WHISKEY",
    "alcohol_content": "40% ALC/VOL",
    "net_contents": "750 mL",
    "government_warning": CANONICAL_WARNING,
}


def run_label_eval(values: dict | None = None) -> list[tuple[str, dict]]:
    """Run the ACTUAL production reader (escalate_label_read / _LABEL_PROMPT) on a clean
    synthetic label and on variants with one field omitted; report per-field recall and,
    for the omitted field, whether the reader invented it from memory."""
    values = values or _SYNTH_LABEL
    out: list[tuple[str, dict]] = []
    for omitted in ("", "alcohol_content", "net_contents", "government_warning"):
        img, _ = render_label(values, omit=[omitted] if omitted else [])
        result = escalate_label_read(img) or {}
        out.append((omitted or "(clean)", label_field_report(result, values, omitted)))
    return out


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

    # Production reader (full _LABEL_PROMPT, all five fields) — accuracy + per-field hallucination.
    print("\n-- production reader (escalate_label_read) --")
    for omitted, report in run_label_eval():
        parts = []
        for field, r in report.items():
            if r["omitted"]:
                parts.append(f"{field}=OMITTED{' FABRICATED' + str(r['fabricated']) if r['fabricated'] else ' ok'}")
            else:
                parts.append(f"{field} recall={r['recall']:.2f}")
        print(f"  omit={omitted:18} " + "  ".join(parts))


if __name__ == "__main__":
    main()
