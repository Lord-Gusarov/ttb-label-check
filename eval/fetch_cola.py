"""Fetch real alcohol labels + their declared application fields from TTB's
Public COLA Registry (https://www.ttbonline.gov/colasonline/).

WHY: our hand-made corpus (old_tom_*, mb_liqours, BARENJAGER) is synthetic, so every
measurement fit to it — including the Tier-1 rotation angles — is biased to art we drew.
The COLA registry is the real input distribution TTB agents review: genuine approved US
labels, real government warnings (usually on the BACK label), authentic stylized/curved
typography, and the *declared* application fields (brand, fanciful, class/type, ABV, net
contents) right there on the printable form. Public government records; eval-only use.

This is a one-off acquisition tool, not product code. It writes:
  eval/data/real/images/<ttbid>__<n>_<imgtype>.<ext>   the label images
  eval/data/real/manifest.jsonl                         one record per COLA (fields + images)

Pipeline per COLA (proven by hand first):
  search (keyword + date range)  -> ttbids
  viewColaDetails publicFormDisplay -> declared fields + per-image (type, filename)
  publicViewAttachment?filename=.. -> the image bytes
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

# Homebrew Python ships without a system trust store; build one from certifi if available,
# else fall back to unverified — acceptable for this one-off tool hitting a known .gov host
# (curl already verified the certificate chain by hand).
try:
    import certifi

    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL = ssl._create_unverified_context()

BASE = "https://www.ttbonline.gov/colasonline"
OUT = Path(__file__).resolve().parent / "data" / "real"
IMG_DIR = OUT / "images"
MANIFEST = OUT / "manifest.jsonl"

# Keyword searches across the three commodities — diversity comes from varied product
# names. searchType=2 == "contains". Date window kept wide to surface plenty of hits.
SEARCHES = {
    "distilled_spirits": ["bourbon", "whiskey", "vodka", "gin", "rum", "tequila", "brandy"],
    "wine": ["cabernet", "pinot", "chardonnay", "merlot", "riesling", "zinfandel"],
    "malt_beverage": ["ale", "lager", "stout", "porter", "pilsner"],
}
PER_KEYWORD = 5          # ttbids to take from each keyword search
MAX_IMAGES_PER_COLA = 3  # front + back (+ neck) is plenty
# Keep the window <=2 years: a wider range exceeds a server result cap and silently
# falls back to an unfiltered default list. Recent years also carry the current warning.
DATE_FROM, DATE_TO = "01/01/2023", "12/31/2024"
DELAY = 0.35             # politeness between requests to a .gov server

_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(CookieJar()),
    urllib.request.HTTPSHandler(context=_SSL),
)
_opener.addheaders = [("User-Agent", "label-check-eval-corpus/1.0 (research; contact local)")]


def _get(url: str, data: dict | None = None) -> bytes:
    time.sleep(DELAY)
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    with _opener.open(url, data=body, timeout=30) as r:  # data set -> POST
        return r.read()


def _text(html: bytes) -> list[str]:
    t = re.sub(r"<[^>]+>", "\n", html.decode("utf-8", "replace"))
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    return [re.sub(r"\s+", " ", ln).strip() for ln in t.split("\n") if ln.strip()]


def search_ttbids(keyword: str) -> list[str]:
    params = {
        "searchCriteria.dateCompletedFrom": DATE_FROM,
        "searchCriteria.dateCompletedTo": DATE_TO,
        "searchCriteria.productOrFancifulName": keyword,
        "searchCriteria.productNameSearchType": "E",  # match brand OR fanciful name
        "searchCriteria.classTypeFrom": "",
        "searchCriteria.classTypeTo": "",
        "searchCriteria.originCode": "",
    }
    html = _get(f"{BASE}/publicSearchColasBasicProcess.do?action=search", data=params)
    ids = re.findall(r"viewColaDetails\.do\?action=\w+&ttbid=(\d+)", html.decode("utf-8", "replace"))
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out[:PER_KEYWORD]


def _value_after(lines: list[str], label_rx: str, stop_rx: str = r"^\d+[a-z]?\.\s|^PART |^TTB ") -> str:
    """Value of a numbered form field = first 'real' line after the label, skipping the
    parenthetical hint lines like '(Required)'/'(If any)'."""
    for i, ln in enumerate(lines):
        if re.search(label_rx, ln, re.I):
            for nxt in lines[i + 1 : i + 5]:
                if re.match(r"^\(", nxt):
                    continue
                if re.search(stop_rx, nxt):
                    return ""
                return nxt
    return ""


COMMODITY_KW = [
    ("wine", r"WINE|CHAMPAGNE|SPARKLING|VERMOUTH|SAKE|MEAD|CIDER|PORT|SHERRY|MOSCATO"),
    ("malt_beverage", r"\bALE\b|LAGER|\bBEER\b|STOUT|PORTER|PILSNER|MALT|\bIPA\b"),
    ("distilled_spirits", r"WHISK|VODKA|\bGIN\b|\bRUM\b|TEQUILA|BRANDY|CORDIAL|LIQUEUR|SPIRIT|BOURBON|SCOTCH|COGNAC"),
]


def _commodity(class_type: str, hint: str) -> str:
    for name, rx in COMMODITY_KW:
        if re.search(rx, class_type, re.I):
            return name
    return hint


def fetch_cola(ttbid: str, hint_commodity: str) -> dict | None:
    html = _get(f"{BASE}/viewColaDetails.do?action=publicFormDisplay&ttbid={ttbid}")
    lines = _text(html)
    class_type = _value_after(lines, r"CLASS/TYPE DESCRIPTION")
    rec = {
        "ttbid": ttbid,
        "source_url": f"{BASE}/viewColaDetails.do?action=publicFormDisplay&ttbid={ttbid}",
        # Item numbers differ across form revisions (brand is 5 on the 2005 form, 6 on
        # the current one; the current form has NO net-contents/ABV boxes at all), so
        # match on the label text, not the number.
        "brand_name": _value_after(lines, r"^\d+\.\s*BRAND NAME"),
        "fanciful_name": _value_after(lines, r"^\d+\.\s*FANCIFUL NAME"),
        "net_contents": _value_after(lines, r"^\d+\.\s*NET CONTENTS"),
        "alcohol_content": _value_after(lines, r"^\d+\.\s*ALCOHOL CONTENT"),
        "appellation": _value_after(lines, r"^\d+\.\s*WINE APPELLATION"),
        "vintage": _value_after(lines, r"^\d+\.\s*WINE VINTAGE"),
        "class_type": class_type,
        "commodity": _commodity(class_type, hint_commodity),
    }
    # Pair each "Image Type:" with the following type label and the attachment filenames
    # (which appear in document order in the raw HTML).
    raw = html.decode("utf-8", "replace")
    files = re.findall(r"publicViewAttachment\.do\?filename=([^&\"']+)&filetype=l", raw)
    types = re.findall(r"Image Type:\s*</[^>]+>\s*<[^>]+>\s*([^<]+)", raw)
    types = [re.sub(r"\s+", " ", t).strip() for t in types]

    images = []
    for n, fn in enumerate(dict.fromkeys(files)):  # dedup, keep order
        if n >= MAX_IMAGES_PER_COLA:
            break
        itype = types[n] if n < len(types) else f"img{n}"
        ext = Path(fn).suffix or ".png"
        slug = re.sub(r"[^a-z0-9]+", "_", itype.lower()).strip("_")[:12] or f"img{n}"
        dest = IMG_DIR / f"{ttbid}__{n}_{slug}{ext}"
        try:
            dest.write_bytes(_get(f"{BASE}/publicViewAttachment.do?filename={urllib.parse.quote(fn)}&filetype=l"))
        except Exception as e:  # noqa: BLE001 — one-off tool, skip a bad image
            print(f"  ! image {fn} failed: {e}", file=sys.stderr)
            continue
        if dest.stat().st_size < 800:  # empty/placeholder
            dest.unlink(missing_ok=True)
            continue
        images.append({"type": itype, "file": dest.name, "bytes": dest.stat().st_size})
    rec["images"] = images
    return rec if images else None


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    _get(f"{BASE}/publicSearchColasBasic.do")  # establish session cookies

    pool: list[tuple[str, str]] = []
    seen: set[str] = set()
    for commodity, keywords in SEARCHES.items():
        for kw in keywords:
            try:
                ids = search_ttbids(kw)
            except Exception as e:  # noqa: BLE001
                print(f"search {kw!r} failed: {e}", file=sys.stderr)
                continue
            new = [i for i in ids if i not in seen]
            seen.update(new)
            pool.extend((i, commodity) for i in new)
            print(f"search {commodity}/{kw!r}: +{len(new)} (pool={len(pool)})")

    pool = pool[:limit]
    records = []
    with MANIFEST.open("w") as mf:
        for n, (ttbid, commodity) in enumerate(pool, 1):
            try:
                rec = fetch_cola(ttbid, commodity)
            except Exception as e:  # noqa: BLE001
                print(f"[{n}/{len(pool)}] {ttbid} FAILED: {e}", file=sys.stderr)
                continue
            if not rec:
                print(f"[{n}/{len(pool)}] {ttbid}: no usable images, skipped")
                continue
            records.append(rec)
            mf.write(json.dumps(rec) + "\n")
            mf.flush()
            print(f"[{n}/{len(pool)}] {ttbid} {rec['commodity']:17} "
                  f"{(rec['fanciful_name'] or rec['brand_name'])[:28]:28} imgs={len(rec['images'])}")
    print(f"\nDONE: {len(records)} COLAs -> {MANIFEST}")


if __name__ == "__main__":
    main()
