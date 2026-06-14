"""Enrich the real manifest's empty declared fields from vision transcriptions.

The COLA scrape captured brand_name / class_type but left alcohol_content and net_contents
empty, which made the verifier escalate on every label for lack of anything to compare.
declared_vision.jsonl holds those two fields read straight off the combined label images
by a vision model — i.e. ground-truth DECLARED values for a compliant application. The
verifier still has to OCR the label itself to FIND them, so this is not circular.

We only fill fields the manifest left empty, never overwrite the scraped brand/class, and
we tag provenance (declared_source) plus keep the verbatim ABV string (alcohol_content_raw).

ABV canonicalisation: labels print the statement many ways, sometimes proof FIRST
("93% PROOF (46.5% ALC. BY VOL)"). The declared alcohol content is the alcohol percentage,
never the proof — so we take the first percentage that is NOT immediately a proof figure,
normalise a European comma decimal ("8,5%"), and store "<n>% Alc./Vol.".

The original manifest is backed up to manifest.fetched.jsonl before rewriting.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REAL = Path(__file__).resolve().parent.parent / "real"
MANIFEST = REAL / "manifest.jsonl"
BACKUP = REAL / "manifest.fetched.jsonl"
VISION = REAL / "combined" / "declared_vision.jsonl"

_PCT_NOT_PROOF = re.compile(r"(\d+(?:\.\d+)?)\s*%(?!\s*proof)", re.IGNORECASE)
_NET_PREFIX = re.compile(r"^\s*net\s+cont(?:ents?|\.?)\s*", re.IGNORECASE)


def canon_abv(raw: str) -> str:
    """First alcohol percentage (not proof) -> '<n>% Alc./Vol.'; '' if none."""
    if not raw:
        return ""
    s = re.sub(r"(\d),(\d)", r"\1.\2", raw)  # 8,5% -> 8.5%
    m = _PCT_NOT_PROOF.search(s)
    return f"{m.group(1)}% Alc./Vol." if m else ""


def clean_net(raw: str) -> str:
    """Drop a leading 'NET CONTENTS'/'NET CONT.' label and a trailing 'e' estimator mark."""
    s = _NET_PREFIX.sub("", raw).strip()
    return re.sub(r"\s+e$", "", s).strip()


def main() -> None:
    vision = {r["ttbid"]: r for r in map(json.loads, VISION.read_text().splitlines())}
    records = [json.loads(ln) for ln in MANIFEST.read_text().splitlines()]

    if not BACKUP.exists():  # preserve the as-fetched manifest once
        BACKUP.write_text(MANIFEST.read_text())

    filled_abv = filled_net = 0
    out: list[str] = []
    for rec in records:
        v = vision.get(rec["ttbid"])
        if v:
            abv = canon_abv(v.get("alcohol_content", ""))
            net = clean_net(v.get("net_contents", ""))
            if abv and not rec.get("alcohol_content"):
                rec["alcohol_content"] = abv
                rec["alcohol_content_raw"] = v["alcohol_content"]
                filled_abv += 1
            if net and not rec.get("net_contents"):
                rec["net_contents"] = net
                filled_net += 1
            if abv or net:
                rec["declared_source"] = "label_vision"
        out.append(json.dumps(rec))

    MANIFEST.write_text("\n".join(out) + "\n")
    print(f"records: {len(records)}  filled ABV: {filled_abv}  filled net: {filled_net}")
    print(f"backup: {BACKUP}")


if __name__ == "__main__":
    main()
