"""Verdict + result types for the rules engine.

Kept dependency-free so comparators, rulesets, and the engine can all import these
without import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    """Outcome of a single check or the whole label.

    Severity order (low → high): PASS < WARN < NEEDS_REVIEW < FAIL.
    We hard-FAIL only what we're certain of; anything we can't determine confidently
    is NEEDS_REVIEW — a human decides. (Avoids false-fails that erode agent trust.)
    """

    PASS = "pass"
    WARN = "warn"
    NEEDS_REVIEW = "needs_review"
    FAIL = "fail"


_SEVERITY = {Verdict.PASS: 0, Verdict.WARN: 1, Verdict.NEEDS_REVIEW: 2, Verdict.FAIL: 3}


def severity(v: Verdict) -> int:
    return _SEVERITY[v]


def worst(verdicts: list[Verdict]) -> Verdict:
    """The most severe verdict in the list (label-level rollup)."""
    return max(verdicts, key=severity) if verdicts else Verdict.NEEDS_REVIEW


@dataclass(frozen=True)
class FieldResult:
    """Result of checking one field, with the evidence an agent needs to act."""

    field: str  # application key, e.g. "brand_name"
    label: str  # human label, e.g. "Brand name"
    verdict: Verdict
    expected: str | None  # value from the application
    found: str | None  # what we matched on the label (if anything)
    detail: str  # plain-language explanation of the verdict


@dataclass(frozen=True)
class LabelResult:
    """Aggregated result for a whole label."""

    commodity: str
    overall: Verdict
    fields: list[FieldResult] = field(default_factory=list)

    @classmethod
    def from_fields(cls, commodity: str, fields: list[FieldResult]) -> "LabelResult":
        """The single place a label verdict is derived: overall = the worst field verdict.

        Building results through this factory makes it impossible for `overall` to disagree
        with `fields`. `worst([])` is NEEDS_REVIEW, so an empty field list rolls up safely.
        """
        return cls(commodity=commodity, overall=worst([f.verdict for f in fields]), fields=fields)
