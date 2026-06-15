"""Runtime configuration (env-overridable).

Defaults encode the bake-off outcome: RapidOCR on the hot path, with an optional local
VLM as the low-confidence fallback. Change `LABELCHECK_READER` to swap engines without
touching code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").lower() not in ("0", "false", "no")


@dataclass(frozen=True)
class Settings:
    #: Hot-path reader. Bake-off on the realistic corpus picked RapidOCR: 91% vs
    #: Tesseract's 77%, robust to angle/perspective, ~417ms (well under the 5s budget).
    #: (Tesseract reads rotated text confidently-but-wrong, so it can't be a safe
    #: primary; swap to it via this env var only when inputs are known-clean flat art.)
    default_reader: str = os.getenv("LABELCHECK_READER", "rapidocr")
    #: Reader tried when the primary read is low-confidence (e.g. arced brand text).
    fallback_reader: str = os.getenv("LABELCHECK_FALLBACK_READER", "vlm")
    #: Mean-confidence threshold below which the fallback is invoked.
    fallback_confidence: float = float(os.getenv("LABELCHECK_FALLBACK_CONFIDENCE", "0.55"))
    #: Whether the confidence-gated fallback is enabled at all.
    enable_fallback: bool = _flag("LABELCHECK_ENABLE_FALLBACK", True)


settings = Settings()
