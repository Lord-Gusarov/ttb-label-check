"""ABV tolerance table (data, not code).

Percentage-point tolerances allowed between the labeled alcohol content and the
application, by commodity. Sources: distilled spirits 27 CFR 5.65 (±0.3); wine
27 CFR 4.36 (±1.5 for ≤14% ABV, ±1.0 for >14%); malt beverages 27 CFR part 7 (±0.3).

Wine has two bands because the tolerance depends on the wine's own ABV; callers pick
the band from the application's stated ABV. Tolerance may never be used to cross the
14% (or 7%) class/tax line — enforced separately when wine is wired in (step 7).
"""

from __future__ import annotations

ABV_TOLERANCE_PCT: dict[str, float] = {
    "distilled_spirits": 0.3,
    "malt_beverage": 0.3,
    "wine_le_14": 1.5,
    "wine_gt_14": 1.0,
}
