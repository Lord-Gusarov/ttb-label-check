"""Runtime configuration (env-overridable).

Defaults encode the bake-off outcome: RapidOCR on the hot path. Change `LABELCHECK_READER`
to swap engines without touching code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    #: Hot-path reader. The bake-off picked RapidOCR — best field accuracy within the 5s
    #: budget and robust to angle/perspective (see docs/evaluation.md).
    default_reader: str = os.getenv("LABELCHECK_READER", "rapidocr")


settings = Settings()
