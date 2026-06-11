"""Deterministic rules engine — the compliance spine.

The model reads; these rules decide. Public surface:
    evaluate(commodity, application, label_text) -> LabelResult
"""

from app.rules.engine import evaluate
from app.rules.result import FieldResult, LabelResult, Verdict
from app.rules.rulesets import FieldPolicy, RULESETS, ruleset_for

__all__ = [
    "evaluate",
    "Verdict",
    "FieldResult",
    "LabelResult",
    "FieldPolicy",
    "RULESETS",
    "ruleset_for",
]
