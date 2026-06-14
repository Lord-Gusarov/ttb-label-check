"""Text normalization for field matching.

Two levels:
- `normalize`: light cleanup (Unicode NFKC, straighten curly quotes, collapse spaces) —
  preserves case, used where case matters (e.g. the warning's caps check, step 4).
- `fold`: aggressive fold for fuzzy field matching — lowercases, DROPS apostrophes
  (so "STONE'S" and "Stone's" both become "stones"), turns other punctuation into
  spaces, collapses. This is what makes Dave's "STONE'S THROW" vs "Stone's Throw" match.
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_APOS = re.compile(r"['`’‘]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return _WS.sub(" ", text).strip()


def _strip_diacritics(text: str) -> str:
    """é -> e, ü -> u: NFKD-decompose and drop the combining marks. OCR reads the plain
    glyph (and applicants type both forms), so accented and plain must fold together."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def fold(text: str) -> str:
    text = _strip_diacritics(normalize(text)).lower()
    text = _APOS.sub("", text)  # STONE'S -> STONES (no space)
    text = _NON_ALNUM.sub(" ", text)  # other punctuation -> space
    return _WS.sub(" ", text).strip()


def despace(text: str) -> str:
    """Lowercase, keep only [a-z0-9] — robust to spacing/granularity (750 mL ~ 750mL)."""
    return _NON_ALNUM.sub("", _strip_diacritics(text).lower())
