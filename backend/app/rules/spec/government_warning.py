"""The government health warning — the single source of truth.

Verbatim text and formatting rules from 27 CFR 16.21 / 16.22. Used by the rules
engine (to validate labels) AND by the corpus generator (to render test labels),
so the two can never drift apart.
"""

from __future__ import annotations

#: The first two words must appear in capital letters and bold type (16.21);
#: the remainder must NOT be bold.
WARNING_PREFIX = "GOVERNMENT WARNING:"

#: The exact required statement. Whitespace may wrap on the label; wording is exact.
CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)
