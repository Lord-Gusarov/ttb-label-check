"""Combine each application's separate panels (front / back / neck) into ONE image.

Real COLA submissions arrive as several files per application — the manifest groups
them under a single ``ttbid`` with an ordered ``images`` array (img0, img1, img2…).
Our submit flow, though, takes a single image per application: the applicant is asked to
combine every panel into one document. This tool produces exactly that, so we can run the
verifier against realistic single-image inputs instead of isolated panels.

Panels are stacked vertically in manifest order, each padded (not scaled) to the group's
widest panel on a white background, with a thin separator between them — preserving every
panel's native resolution for OCR.

Output: corpus/real/combined/<ttbid>.png plus corpus/real/combined/manifest.jsonl, whose
records mirror the source manifest but point at the single combined file — so eval_real.py
runs over it unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

REAL = Path(__file__).resolve().parent.parent / "real"
SRC_IMAGES = REAL / "images"
OUT_DIR = REAL / "combined"
SEPARATOR_PX = 8  # white gap between stacked panels, keeps OCR lines from bleeding together


def stack_panels(panels: list[np.ndarray], *, separator_px: int = SEPARATOR_PX) -> np.ndarray:
    """Vertically stack BGR panels, padding each to the max width on white (no scaling)."""
    if not panels:
        raise ValueError("no panels to stack")
    width = max(p.shape[1] for p in panels)
    sep = np.full((separator_px, width, 3), 255, dtype=np.uint8)

    rows: list[np.ndarray] = []
    for i, p in enumerate(panels):
        pad = width - p.shape[1]
        left, right = pad // 2, pad - pad // 2
        padded = cv2.copyMakeBorder(
            p, 0, 0, left, right, cv2.BORDER_CONSTANT, value=(255, 255, 255)
        )
        if i:
            rows.append(sep)
        rows.append(padded)
    return np.vstack(rows)


def main() -> None:
    records = [json.loads(ln) for ln in (REAL / "manifest.jsonl").read_text().splitlines()]
    OUT_DIR.mkdir(exist_ok=True)
    out_manifest = OUT_DIR / "manifest.jsonl"

    written = 0
    with out_manifest.open("w") as mf:
        for rec in records:
            panels: list[np.ndarray] = []
            sources: list[str] = []
            for im in rec["images"]:
                path = SRC_IMAGES / im["file"]
                img = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
                if img is None:
                    print(f"  ! skip missing/unreadable: {im['file']}")
                    continue
                panels.append(img)
                sources.append(im["file"])
            if not panels:
                print(f"  ! no usable panels for {rec['ttbid']} — skipped")
                continue

            combined = stack_panels(panels)
            out_file = f"{rec['ttbid']}.png"
            cv2.imwrite(str(OUT_DIR / out_file), combined)
            written += 1

            out_rec = {k: v for k, v in rec.items() if k != "images"}
            out_rec["images"] = [{"type": "combined", "file": out_file}]
            out_rec["combined_from"] = sources
            mf.write(json.dumps(out_rec) + "\n")
            h, w = combined.shape[:2]
            print(f"[{written}] {out_file:24} {len(panels)} panel(s) -> {w}x{h}")

    print(f"\nwrote {written} combined images + manifest to {OUT_DIR}")


if __name__ == "__main__":
    main()
