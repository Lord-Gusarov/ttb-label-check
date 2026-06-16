"""Per-FIELD accuracy + latency: local-only (LLM off) vs model-assisted (LLM on).

Runs the production ``verify_label`` over the hand-verified golden set (eval/golden.jsonl,
full ground truth for all fields) twice — escalation OFF, then ON — and compares per-field
PASS rate and latency. Because the declared values are all CORRECT, a right system should
PASS every field; more PASS = fewer spurious NEEDS_REVIEW. Flags any field the LLM makes worse.

The ON pass makes REAL OpenAI calls (key from $OPENAI_API_KEY or ~/.oai_key).

Usage:  cd backend && uv run python ../eval/eval_fields.py
        LLM_EVAL_MODEL=openai:gpt-4.1-mini  (override the on-model)
"""

from __future__ import annotations

import json
import os
import statistics as st
import time
from collections import defaultdict
from pathlib import Path

from app.pipeline import verify_label
from app.readers.preprocess import load_image

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden.jsonl"
COMBINED = HERE / "data" / "real" / "combined"
MODEL_ON = os.environ.get("LLM_EVAL_MODEL", "openai:gpt-5.4-mini")


def run(cases: list[dict], model_spec: str) -> list[dict]:
    os.environ["WARNING_ESCALATION_MODEL"] = model_spec
    out_rows: list[dict] = []
    for c in cases:
        img = load_image(str(COMBINED / f"{c['ttbid']}.png"))
        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        res = verify_label(img, c["commodity"], c["app"], timings=timings)
        total = time.perf_counter() - t0
        out_rows.append({
            "ttbid": c["ttbid"],
            "verdicts": {f.field: f.verdict.value for f in res.result.fields},
            "overall": res.result.overall.value,
            "tier": res.warning_tier,
            "model_fired": timings.get("tier2_model", 0) > 0.1,
            "total": total,
            "local": sum(timings.get(k, 0.0) for k in ("ocr", "tier1_reread", "tier1_rescues")),
        })
    return out_rows


def pass_counts(rows: list[dict]) -> tuple[dict, dict]:
    present: dict[str, int] = defaultdict(int)
    passed: dict[str, int] = defaultdict(int)
    for r in rows:
        for field, verdict in r["verdicts"].items():
            present[field] += 1
            passed[field] += verdict == "pass"
    return present, passed


def _lat(rows: list[dict], key: str) -> str:
    vs = [r[key] for r in rows]
    p95 = sorted(vs)[min(len(vs) - 1, int(round(0.95 * (len(vs) - 1))))]
    return f"median={st.median(vs):.2f}s  p95={p95:.2f}s  max={max(vs):.2f}s  mean={st.mean(vs):.2f}s"


def main() -> None:
    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    print(f"golden cases: {len(cases)}   model-on: {MODEL_ON}\n")

    off = run(cases, "off")
    on = run(cases, MODEL_ON)

    p_off, pass_off = pass_counts(off)
    p_on, pass_on = pass_counts(on)
    fields = sorted(set(p_off) | set(p_on))

    print("== per-field PASS (declared values are all correct, so PASS = good) ==")
    print(f"{'field':26} {'OFF':>8} {'ON':>8}   note")
    for f in fields:
        po, pn = f"{pass_off[f]}/{p_off[f]}", f"{pass_on[f]}/{p_on[f]}"
        delta = pass_on[f] - pass_off[f]
        note = "LLM WORSE" if delta < 0 else (f"+{delta} recovered by LLM" if delta > 0 else "")
        print(f"{f:26} {po:>8} {pn:>8}   {note}")

    opass = lambda rows: sum(r["overall"] == "pass" for r in rows)  # noqa: E731
    print(f"\noverall label PASS:  off {opass(off)}/{len(off)}   on {opass(on)}/{len(on)}")
    print(f"model actually fired (on): {sum(r['model_fired'] for r in on)}/{len(on)}")

    print(f"\nlatency  OFF (local air-gapped): {_lat(off, 'local')}")
    print(f"latency  ON  (total w/ model):  {_lat(on, 'total')}")

    print("\nper-case overall (off -> on):")
    on_by = {r["ttbid"]: r for r in on}
    for r in off:
        o = on_by[r["ttbid"]]
        print(f"  {r['ttbid']}  {r['overall']:12} -> {o['overall']:12}  "
              f"tier {r['tier']}->{o['tier']}  local {r['local']:5.1f}s -> total {o['total']:5.1f}s")


if __name__ == "__main__":
    main()
