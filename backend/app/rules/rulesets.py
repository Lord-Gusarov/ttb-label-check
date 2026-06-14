"""Per-commodity rulesets — the declarative FieldPolicy table.

This is the auditable spec: each field declares which comparator runs and with what
parameters. Adding a commodity (wine/malt, step 7) or a rule = editing data here, not
the engine. Distilled spirits is seeded deep (the assignment's sample label); wine and
malt are wired structurally in step 7.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Optional

from app.rules.comparators import (
    match_abv,
    match_abv_wine,
    match_net_contents,
    match_text,
    require_phrase,
)
from app.rules.result import Verdict
from app.rules.spec.tolerances import ABV_TOLERANCE_PCT

# A comparator: (expected, label_text, **params) -> (verdict, found, detail)
Comparator = Callable[..., tuple[Verdict, Optional[str], str]]


@dataclass(frozen=True)
class FieldPolicy:
    field: str  # key in the application dict
    label: str  # human-facing label
    comparator: Comparator
    params: dict = dc_field(default_factory=dict)


DISTILLED_SPIRITS: list[FieldPolicy] = [
    FieldPolicy(
        "brand_name",
        "Brand name",
        match_text,
        {"fuzzy_threshold": 0.85, "absent_verdict": Verdict.NEEDS_REVIEW},
    ),
    FieldPolicy(
        "class_type",
        "Class/type designation",
        match_text,
        {"fuzzy_threshold": 0.80, "absent_verdict": Verdict.WARN},
    ),
    FieldPolicy(
        "alcohol_content",
        "Alcohol content",
        match_abv,
        {"tolerance": ABV_TOLERANCE_PCT["distilled_spirits"]},
    ),
    FieldPolicy(
        "net_contents",
        "Net contents",
        match_net_contents,
        {},
    ),
]

# Wine (27 CFR part 4): banded ABV tolerance with the hard 14% class line, plus the
# sulfite declaration (presence-level — exemption under 10ppm is a human call).
WINE: list[FieldPolicy] = [
    FieldPolicy(
        "brand_name",
        "Brand name",
        match_text,
        {"fuzzy_threshold": 0.85, "absent_verdict": Verdict.NEEDS_REVIEW},
    ),
    FieldPolicy(
        "class_type",
        "Class/type designation",
        match_text,
        {"fuzzy_threshold": 0.80, "absent_verdict": Verdict.WARN},
    ),
    FieldPolicy("alcohol_content", "Alcohol content", match_abv_wine, {}),
    FieldPolicy("net_contents", "Net contents", match_net_contents, {}),
    FieldPolicy(
        "sulfite_declaration",
        "Sulfite declaration",
        require_phrase,
        {"phrase": "CONTAINS SULFITES", "absent_verdict": Verdict.WARN},
    ),
]

# Malt beverages (27 CFR part 7): structural — same mandatory fields as spirits with
# the malt ABV tolerance; the low/non-alcohol floors stay a human call at this depth.
MALT_BEVERAGE: list[FieldPolicy] = [
    FieldPolicy(
        "brand_name",
        "Brand name",
        match_text,
        {"fuzzy_threshold": 0.85, "absent_verdict": Verdict.NEEDS_REVIEW},
    ),
    FieldPolicy(
        "class_type",
        "Class/type designation",
        match_text,
        {"fuzzy_threshold": 0.80, "absent_verdict": Verdict.WARN},
    ),
    FieldPolicy(
        "alcohol_content",
        "Alcohol content",
        match_abv,
        {"tolerance": ABV_TOLERANCE_PCT["malt_beverage"]},
    ),
    FieldPolicy("net_contents", "Net contents", match_net_contents, {}),
]

RULESETS: dict[str, list[FieldPolicy]] = {
    "distilled_spirits": DISTILLED_SPIRITS,
    "wine": WINE,
    "malt_beverage": MALT_BEVERAGE,
}


def ruleset_for(commodity: str) -> list[FieldPolicy]:
    if commodity not in RULESETS:
        raise KeyError(
            f"no ruleset for commodity '{commodity}'. known: {sorted(RULESETS)}"
        )
    return RULESETS[commodity]
