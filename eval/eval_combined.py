"""Run the REAL verification pipeline over the combined single-image corpus and report
tier resolution + per-stage latencies.

Each application is one combined image (front/back/neck stacked — see combine_panels.py),
matching the single-image submit flow. For every one we call the production
``verify_label`` with declared fields from the manifest, capturing per-stage wall-clock:

    ocr            Tier-1 base RapidOCR read of the whole image
    tier1_reread   Tier-1 anchored government-warning re-read (scale search)
    tier1_rescues  Tier-1 local geometry rescues (deskew / 90° vertical), if attempted
    tier2_model    Tier-2 model re-read (gpt-5.4-mini), if escalation fired

The cascade's target is the government warning, so resolution is reported on warning_text:
resolved at Tier 1 = warning PASS with no adopted model read (warning_tier == 1); escalated
to Tier 2 = a model read was adopted (warning_tier == 2).

Usage:  python corpus/tools/eval_combined.py [N]   # N = optional cap for a smoke test
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from app.pipeline import verify_label
from app.readers.preprocess import load_image
from app.rules.result import Verdict

REAL = Path(__file__).resolve().parent.parent / "real"
COMBINED = REAL / "combined"
OUT = COMBINED / "eval_pipeline.jsonl"


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return s[i]


def _stat_line(name: str, values: list[float]) -> str:
    if not values:
        return f"  {name:14} (none)"
    return (
        f"  {name:14} n={len(values):3d}  mean={sum(values) / len(values):5.2f}s  "
        f"median={_pct(values, 50):5.2f}s  p95={_pct(values, 95):5.2f}s  max={max(values):5.2f}s"
    )


def main() -> None:
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    manifest = {
        r["ttbid"]: r
        for r in map(json.loads, (REAL / "manifest.jsonl").read_text().splitlines())
    }
    images = sorted(COMBINED.glob("*.png"))
    if cap:
        images = images[:cap]

    rows: list[dict] = []
    with OUT.open("w") as f:
        for n, path in enumerate(images, 1):
            ttbid = path.stem
            rec = manifest.get(ttbid, {})
            app = {
                "brand_name": rec.get("brand_name", ""),
                "class_type": rec.get("class_type", ""),
                "alcohol_content": rec.get("alcohol_content", ""),
                "net_contents": rec.get("net_contents", ""),
            }
            commodity = rec.get("commodity", "distilled_spirits")

            timings: dict[str, float] = {}
            t0 = time.perf_counter()
            try:
                out = verify_label(load_image(str(path)), commodity, app, timings=timings)
            except Exception as e:  # noqa: BLE001
                print(f"[{n}/{len(images)}] {ttbid} ERROR: {e}")
                continue
            total = time.perf_counter() - t0

            warn = next((x for x in out.result.fields if x.field == "warning_text"), None)
            warn_verdict = warn.verdict.value if warn else "absent"
            # Local Tier-1 cost = everything except the model — the air-gapped latency.
            t_local = sum(
                timings.get(k, 0.0) for k in ("ocr", "tier1_reread", "tier1_rescues")
            )
            row = {
                "ttbid": ttbid,
                "panels": len(rec.get("images", [])) or 1,
                "warning_tier": out.warning_tier,
                "warning_verdict": warn_verdict,
                "overall": out.result.overall.value,
                "model_invoked": "tier2_model" in timings,
                "t_total": round(total, 2),
                "t_local": round(t_local, 2),
                **{f"t_{k}": round(v, 2) for k, v in timings.items()},
            }
            rows.append(row)
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(
                f"[{n}/{len(images)}] {ttbid:18} tier={out.warning_tier} "
                f"warn={warn_verdict:12} total={total:5.2f}s "
                f"(ocr={timings.get('ocr', 0):.2f} reread={timings.get('tier1_reread', 0):.2f} "
                f"rescue={timings.get('tier1_rescues', 0):.2f} model={timings.get('tier2_model', 0):.2f})"
            )

    # ---- summary ----------------------------------------------------------------------
    n = len(rows)
    t1 = [r for r in rows if r["warning_tier"] == 1]
    t2 = [r for r in rows if r["warning_tier"] == 2]
    warn_pass = [r for r in rows if r["warning_verdict"] == Verdict.PASS.value]
    t1_resolved = [r for r in t1 if r["warning_verdict"] == Verdict.PASS.value]
    invoked = [r for r in rows if r["model_invoked"]]

    print("\n" + "=" * 78)
    print(f"applications: {n}   (multi-panel: {sum(1 for r in rows if r['panels'] > 1)})")
    print("\n-- government-warning resolution --")
    print(f"  warning PASS overall:        {len(warn_pass):3d}/{n}")
    print(f"  resolved at Tier 1 (local):  {len(t1_resolved):3d}/{n}")
    print(f"  escalated to Tier 2 (model): {len(t2):3d}/{n}  (model adopted)")
    print(f"  model invoked (any field):   {len(invoked):3d}/{n}")
    print(f"  unresolved (warning != PASS):{n - len(warn_pass):3d}/{n}")

    print("\n-- latency per stage --")
    print(_stat_line("ocr", [r["t_ocr"] for r in rows if "t_ocr" in r]))
    print(_stat_line("tier1_reread", [r["t_tier1_reread"] for r in rows if "t_tier1_reread" in r]))
    print(_stat_line("tier1_rescues", [r["t_tier1_rescues"] for r in rows if "t_tier1_rescues" in r]))
    print(_stat_line("tier2_model", [r["t_tier2_model"] for r in rows if "t_tier2_model" in r]))
    print(_stat_line("LOCAL (T1 only)", [r["t_local"] for r in rows]))
    print(_stat_line("TOTAL (w/ model)", [r["t_total"] for r in rows]))
    print("\n  LOCAL = ocr+reread+rescues = the air-gapped Tier-1 latency (escalation off).")
    print("  TOTAL includes the Tier-2 model call, which here fires on nearly every label")
    print("  because the manifest lacks declared ABV/net-contents to compare against.")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
