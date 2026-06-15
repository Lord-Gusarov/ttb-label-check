"""The rules engine: run a commodity's FieldPolicy table against a label's OCR text.

Deterministic and explainable — every field yields a verdict + plain-language detail,
and the label-level verdict is just the most severe field verdict. The model already
read the label; here nothing but rules decide.
"""

from __future__ import annotations

from app.rules.result import FieldResult, LabelResult
from app.rules.rulesets import ruleset_for


def evaluate(commodity: str, application: dict, label_text: str) -> LabelResult:
    """Compare an application + label OCR text against the commodity's ruleset.

    Args:
        commodity: e.g. "distilled_spirits".
        application: declared field values, keyed by field name (brand_name, ...).
        label_text: full OCR text read from the label image.
    """
    policies = ruleset_for(commodity)
    results: list[FieldResult] = []

    for policy in policies:
        if policy.applies_when is not None and not policy.applies_when(application):
            continue  # conditional field not applicable (e.g. country-of-origin on a domestic product)
        expected = application.get(policy.field)
        verdict, found, detail = policy.comparator(
            expected, label_text, **policy.params
        )
        results.append(
            FieldResult(
                field=policy.field,
                label=policy.label,
                verdict=verdict,
                expected=str(expected) if expected is not None else None,
                found=found,
                detail=detail,
            )
        )

    return LabelResult.from_fields(commodity, results)
