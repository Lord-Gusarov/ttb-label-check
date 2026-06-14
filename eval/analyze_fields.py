"""Local-only (escalation OFF) per-FIELD breakdown over the combined corpus.

Answers two entangled questions the full eval can't separate: is the enriched manifest
right, and how good is local OCR? For every combined image we run the pipeline with the
model disabled and tally each field's verdict, printing every non-PASS field with its
declared value and the comparator detail (which carries what was found) — so a transcription
error in the manifest looks different from an OCR miss, and you can eyeball both.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

os.environ["WARNING_ESCALATION_MODEL"] = "off"  # local only — no model, no egress

from app.pipeline import verify_label  # noqa: E402
from app.readers.preprocess import load_image  # noqa: E402

REAL = Path(__file__).resolve().parent.parent / "real"
COMBINED = REAL / "combined"
FIELDS = ("brand_name", "class_type", "alcohol_content", "net_contents", "warning_text")


def main() -> None:
    manifest = {
        r["ttbid"]: r for r in map(json.loads, (REAL / "manifest.jsonl").read_text().splitlines())
    }
    images = sorted(COMBINED.glob("*.png"))
    per_field: dict[str, Counter] = {f: Counter() for f in FIELDS}
    misses: list[str] = []

    for path in images:
        ttbid = path.stem
        rec = manifest.get(ttbid, {})
        app = {k: rec.get(k, "") for k in ("brand_name", "class_type", "alcohol_content", "net_contents")}
        out = verify_label(load_image(str(path)), rec.get("commodity", "distilled_spirits"), app)
        by = {f.field: f for f in out.result.fields}
        for f in FIELDS:
            fr = by.get(f)
            if fr is None:
                continue
            per_field[f][fr.verdict.value] += 1
            if fr.verdict.value != "pass":
                declared = app.get(f, "—") or "—"
                misses.append(f"  {ttbid} [{f}] {fr.verdict.value}: declared={declared!r} :: {fr.detail}")

    n = len(images)
    print(f"local-only (escalation OFF) over {n} combined images\n")
    print(f"{'field':16} {'pass':>5} {'review':>7} {'fail':>5}  pass-rate")
    for f in FIELDS:
        c = per_field[f]
        p = c.get("pass", 0)
        print(f"{f:16} {p:>5} {c.get('needs_review', 0):>7} {c.get('fail', 0):>5}  {p / n:6.0%}")
    print("\nnon-PASS fields (declared value :: comparator detail):")
    print("\n".join(misses))


if __name__ == "__main__":
    main()
