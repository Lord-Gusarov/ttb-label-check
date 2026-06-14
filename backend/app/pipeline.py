"""End-to-end verification pipeline: read the label, then apply the rules.

Ties the two halves together — the pluggable reader (step 2) extracts text; the
deterministic engine (step 3) renders the verdict. The HTTP layer (step 5) and batch
runner (step 6) both call `verify_label`.

Reading escalates through two tiers; the second only runs when the first left a field
*unverified* (NEEDS_REVIEW / FAIL):

    Tier 1  LOCAL reading — RapidOCR two-pass with scale search, plus measured geometry
            rescues (ink-profile deskew; 90° re-read for sidebar/keg-collar warnings).
            ~1.4s typical. No egress: this tier alone is the air-gapped configuration.
    Tier 2  MODEL reader (cloud or local enclave), env-gated, ~3s — blur / hostile type.

The model runs before the local geometry rescues on the hot path (it fixes recognition
as well as geometry); the rescues still run whenever the model is off, unavailable, or
didn't resolve the warning — so the reported tier is 2 only when a model read was
actually adopted, and 1 for everything resolved locally.

Every tier is best-effort and FAIL-SAFE: any failure (rotation error, model unavailable,
no key, network/API error) is swallowed and the pipeline keeps the best result it has —
so it degrades to a human review, never to a crash or a block. The model only ever READS;
the deterministic checks always render the verdict.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import numpy as np

from app.escalation import escalate_label_read
from app.readers import ReadResult, build_reader
from app.rules import LabelResult, evaluate
from app.rules.result import FieldResult, Verdict, severity, worst
from app.rules.warning import evaluate_warning
from app.rules.warning_region import deskew_reread, reread_warning, vertical_reread

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


@dataclass(frozen=True)
class VerificationResult:
    commodity: str
    result: LabelResult
    read: ReadResult
    warning_tier: int = 1  # 1 = read locally, 2 = model-assisted


def _safe(fn: Callable[[], _T], what: str) -> _T | None:
    """Run an escalation step; on ANY failure keep going (degrade to human review)."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 — a tier failing must never break verification
        logger.warning("%s failed; keeping current result", what, exc_info=True)
        return None


def _warning_text(fields: list[FieldResult]) -> FieldResult | None:
    return next((f for f in fields if f.field == "warning_text"), None)


def _verified(fields: list[FieldResult]) -> bool:
    f = _warning_text(fields)
    return f is not None and f.verdict is Verdict.PASS


def _wt_severity(fields: list[FieldResult]) -> int:
    f = _warning_text(fields)
    return severity(f.verdict) if f else severity(Verdict.FAIL)


def _merge_better(
    current: list[FieldResult], candidate: list[FieldResult]
) -> list[FieldResult]:
    """Adopt a candidate (model-read) field only when it IMPROVES the local verdict (lower
    severity); never downgrade. A model misread can therefore only flag, never falsely clear,
    and a field the local read already passed can't be made worse by escalation."""
    by_field = {f.field: f for f in candidate}
    out: list[FieldResult] = []
    for f in current:
        c = by_field.get(f.field)
        out.append(c if c is not None and severity(c.verdict) < severity(f.verdict) else f)
    return out


def _model_field_results(
    commodity: str, application: dict, model: dict[str, str], image: np.ndarray,
    warning_words: list | None = None,
) -> list[FieldResult]:
    """Deterministically re-check every field against the MODEL's transcription. The model
    read the image only — never the declared values — so the same comparators/checks render
    the verdict; the model just supplies cleaner text. Bold is a visual check and requires
    word boxes to locate the prefix, so local OCR boxes are threaded in via warning_words."""
    text = " ".join(
        model.get(k, "")
        for k in ("brand_name", "class_type", "alcohol_content", "net_contents")
    )
    field_results = list(evaluate(commodity, application, text).fields)
    warning_results = list(evaluate_warning(image, model.get("government_warning", ""), warning_words or [], None))
    return field_results + warning_results


def verify_label(
    image: np.ndarray,
    commodity: str,
    application: dict,
    *,
    timings: dict[str, float] | None = None,
) -> VerificationResult:
    """Read `image` with the configured reader, then evaluate against the ruleset.

    Pass a ``timings`` dict to have per-stage wall-clock seconds recorded into it
    (``ocr``, ``tier1_reread``, ``tier2_model``, ``tier1_rescues``) — purely observational,
    it does not change behaviour and stays empty for stages that don't run."""

    def _timed(key: str, fn: Callable[[], _T]) -> _T:
        if timings is None:
            return fn()
        t = time.perf_counter()
        try:
            return fn()
        finally:
            timings[key] = timings.get(key, 0.0) + (time.perf_counter() - t)

    reader = build_reader()
    read = _timed("ocr", lambda: reader.extract(image))
    field_result = evaluate(commodity, application, read.text)

    # Tier 1 — anchored re-read with scale search (cheap; clears clean + most labels).
    region = _timed(
        "tier1_reread",
        lambda: _safe(lambda: reread_warning(image, read.words, reader), "tier-1 re-read"),
    )
    warning_fields = evaluate_warning(image, read.text, read.words, region)
    tier = 1

    fields = list(field_result.fields) + warning_fields

    # Tier 2 — label-level model escalation, only if ANY field (or the warning) is still
    # unverified. Runs BEFORE the local rotation sweep: measured, the model resolves the
    # same labels in ~3s that the sweep burns up to ~10s failing to fix (rotation only
    # helps geometry; the model helps geometry AND recognition). One declared-blind
    # transcription of the whole label; the engine re-checks every field against it and
    # adopts only per-field improvements. Env-gated + fail-safe: returns None when
    # disabled/unavailable, and we fall through to the local tiers.
    if any(f.verdict is not Verdict.PASS for f in fields):
        model = _timed(
            "tier2_model", lambda: _safe(lambda: escalate_label_read(image), "tier-2 label read")
        )
        if model:
            candidate = _model_field_results(commodity, application, model, image, warning_words=read.words)
            merged_fields = _merge_better(fields, candidate)
            if merged_fields != fields:  # adopted at least one improvement
                fields, tier = merged_fields, 2

    # Tier 1 (continued) — LOCAL geometry rescues when the warning is still unverified (model off /
    # unavailable / didn't fix it). No egress: this is the air-gapped path. Each attempt
    # is one measured correction + one re-read (no blind sweeps), adopted only if it
    # improves the warning verdict:
    #   deskew    — measure the band's skew from the ink profile, re-read once corrected
    #   vertical  — sidebar/keg-collar warnings printed 90° to the label, re-read upright
    def _rescues() -> list[FieldResult]:
        out = fields
        for what, attempt in (
            ("local deskew", lambda: deskew_reread(image, read.words, reader)),
            ("local vertical re-read", lambda: vertical_reread(image, reader, read.words)),
        ):
            current = [f for f in out if f.field == "warning_text"]
            if _verified(current):
                break
            region1 = _safe(attempt, what)
            if region1 is not None:
                f1 = evaluate_warning(image, read.text, read.words, region1)
                if _wt_severity(f1) < _wt_severity(current):
                    by_field = {f.field: f for f in f1}
                    out = [by_field.get(f.field, f) for f in out]
        return out

    fields = _timed("tier1_rescues", _rescues)

    overall = worst([f.verdict for f in fields])
    merged = LabelResult(commodity=commodity, overall=overall, fields=fields)
    return VerificationResult(commodity=commodity, result=merged, read=read, warning_tier=tier)
