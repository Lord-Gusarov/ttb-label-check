"""Sweep the real COLA corpus and measure what the LOCAL tiers actually need.

For every image in corpus/real/: full-image OCR, then the Tier-0 anchored warning
re-read; when the warning is still imperfect, try each rotation angle (±2°, ±5°, ±10°)
separately and record whether ANY angle improves token recovery. This answers, with
real labels instead of our synthetic art:
  - how often the warning resolves at Tier 0,
  - whether the Tier-1 rotation sweep ever helps real (flat, horizontal) artwork,
  - which angles (if any) earn their place in ROTATION_ANGLES.

Also despace-matches the manifest's declared brand / net contents / ABV against the
full-image text as a cheap field-level readability signal. Output: JSONL + summary.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from app.readers import build_reader
from app.readers.preprocess import load_image
from app.rules.spec.government_warning import missing_canonical_tokens
from app.rules.warning_region import _anchor_boxes, reread_warning

REAL = Path(__file__).resolve().parent.parent / "real"
OUT = REAL / "eval.jsonl"
ANGLES = (2, -2, 5, -5, 10, -10)
SCALES = (1.5, 2.5)


def _despace(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> None:
    reader = build_reader()
    records = [json.loads(ln) for ln in (REAL / "manifest.jsonl").read_text().splitlines()]
    n_img = 0
    with OUT.open("w") as f:
        for rec in records:
            for im in rec["images"]:
                path = REAL / "images" / im["file"]
                if not path.exists():
                    continue
                n_img += 1
                row: dict = {"ttbid": rec["ttbid"], "file": im["file"], "imgtype": im["type"],
                             "brand": rec["brand_name"], "commodity": rec["commodity"]}
                try:
                    img = load_image(str(path))
                except Exception as e:  # noqa: BLE001
                    row["error"] = f"load: {e}"
                    f.write(json.dumps(row) + "\n")
                    f.flush()
                    continue
                h, w = img.shape[:2]
                row["dims"] = [w, h]

                t = time.time()
                read = reader.extract(img)
                row["t_full"] = round(time.time() - t, 2)
                full = _despace(read.text)
                row["found_brand"] = _despace(rec["brand_name"]) in full if rec["brand_name"] else None
                row["found_net"] = _despace(rec["net_contents"]) in full if rec["net_contents"] else None
                abv = rec.get("alcohol_content", "")
                row["found_abv"] = (_despace(abv) in full or abv.strip() in read.text) if abv else None

                anchors = _anchor_boxes(read.words)
                row["warning_anchor"] = bool(anchors)
                if anchors:
                    t = time.time()
                    t0 = reread_warning(img, read.words, reader)
                    row["t_t0"] = round(time.time() - t, 2)
                    miss0 = len(missing_canonical_tokens(t0.text)) if t0 else 99
                    row["t0_missing"] = miss0
                    if miss0 > 0:
                        per_angle: dict[str, int] = {}
                        for a in ANGLES:
                            r = reread_warning(img, read.words, reader, angles=(a,), scales=SCALES)
                            per_angle[str(a)] = len(missing_canonical_tokens(r.text)) if r else 99
                        row["angle_missing"] = per_angle
                        row["best_angle_helps"] = min(per_angle.values()) < miss0
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(f"[{n_img}] {im['file'][:44]:44} anchor={row.get('warning_anchor')} "
                      f"t0_miss={row.get('t0_missing', '-')} rot_helps={row.get('best_angle_helps', '-')}")

    # ---- summary ------------------------------------------------------------------
    rows = [json.loads(ln) for ln in OUT.read_text().splitlines()]
    with_anchor = [r for r in rows if r.get("warning_anchor")]
    perfect_t0 = [r for r in with_anchor if r.get("t0_missing") == 0]
    imperfect = [r for r in with_anchor if r.get("t0_missing", 0) > 0]
    helped = [r for r in imperfect if r.get("best_angle_helps")]
    print(f"\nimages: {len(rows)}  warning-anchored: {len(with_anchor)}  "
          f"T0-perfect: {len(perfect_t0)}  T0-imperfect: {len(imperfect)}  rotation-helped: {len(helped)}")
    for r in imperfect:
        print(f"  {r['file'][:40]:40} t0_miss={r['t0_missing']:>2} angles={r.get('angle_missing')}")


if __name__ == "__main__":
    main()
