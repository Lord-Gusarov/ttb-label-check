"""End-to-end verification pipeline: read the label, then apply the rules.

Ties the two halves together — the pluggable reader (step 2) extracts text; the
deterministic engine (step 3) renders the verdict. The HTTP layer (step 5) and batch
runner (step 6) both call `verify_label`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.readers import ReadResult, build_reader
from app.rules import LabelResult, evaluate
from app.rules.result import worst
from app.rules.warning import evaluate_warning


@dataclass(frozen=True)
class VerificationResult:
    commodity: str
    result: LabelResult
    read: ReadResult


def verify_label(
    image: np.ndarray, commodity: str, application: dict
) -> VerificationResult:
    """Read `image` with the configured reader, then evaluate against the ruleset."""
    reader = build_reader()
    read = reader.extract(image)

    field_result = evaluate(commodity, application, read.text)
    # Government warning is mandatory on every commodity, so it's checked separately.
    # It reads the warning with Tesseract internally (word-level, case-preserving),
    # so it doesn't depend on the primary reader's possibly-lossy long-text output.
    warning_fields = evaluate_warning(image)

    fields = list(field_result.fields) + warning_fields
    overall = worst([f.verdict for f in fields])
    merged = LabelResult(commodity=commodity, overall=overall, fields=fields)
    return VerificationResult(commodity=commodity, result=merged, read=read)
