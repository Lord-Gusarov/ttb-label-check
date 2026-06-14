"""On-demand VLM faithfulness eval for the government-warning read.

Direct-to-model (Tier 1 absent): degrade warning crops/renders with KNOWN removed tokens,
transcribe each with a declared-blind warning prompt, and measure completeness (recall) and
hallucination (fabricated = model emits a removed token). Not part of the default test suite.

Usage:  python corpus/tools/eval_vlm.py
"""

from __future__ import annotations

import re

import numpy as np

from app.escalation import _chat_json
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


_WARNING_PROMPT = (
    "Transcribe the GOVERNMENT WARNING in this cropped image EXACTLY as printed. Do not infer, "
    "complete, or correct anything; if a word is missing or unreadable, leave it out. Use an empty "
    "string if no warning is present. Return ONLY JSON: {\"government_warning\": \"...\"}."
)


def transcribe_warning(crop: np.ndarray, model: str = "gpt-5.4-mini") -> str:
    data = _chat_json(crop, model, _WARNING_PROMPT)
    return str((data or {}).get("government_warning", ""))


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


if __name__ == "__main__":
    main()
