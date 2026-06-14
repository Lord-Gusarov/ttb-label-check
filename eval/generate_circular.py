"""Generate PRONOUNCED circular / curved-text label variants for the bake-off.

``generate_rich.py`` already adds a *subtle* whole-line arc (``old_tom_rich_arc``).
That barely bends the baseline, so a deskew still recovers it. Real spirit labels go
much further: the brand wraps the *entire* circumference of a round medallion/seal,
the producer line rides the bottom of that same circle upside-down-ish, and a maker's
mark sits in the middle. Classical line-based OCR (Tesseract) falls apart on this
because every glyph sits at its own tangent angle and there is no straight baseline to
find; angle-robust detectors (RapidOCR / Paddle / EasyOCR) and a VLM are the interesting
comparison.

This module renders three new variants and APPENDS them to the SAME ``manifest.json``
(idempotently, by id), keeping every existing entry untouched:

    old_tom_rich_circular    brand wrapped the full 360 deg around a circular seal
    old_tom_rich_semicircle  brand on the top half-arc, producer line on the bottom arc
    old_tom_rich_seal        text encircling a round wax-style medallion with a monogram

Ground truth is unchanged: however the glyphs are bent, the underlying words are still
the canonical OLD TOM field values and the canonical government warning (bold prefix).

    python eval/generate.py          # base manifest
    python eval/generate.py_rich      # rich variants
    python eval/generate.py_circular  # APPENDS the circular variants

Deterministic (seeded) and fully offline (PIL + numpy only).
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Reuse the rich generator's building blocks so style/ground-truth stay in lockstep.
from corpus.generate_rich import (
    FONT_BOLD,
    FONT_REGULAR,
    INK,
    INK_SOFT,
    OLD_TOM,
    RULE,
    _add_noise,
    _font,
    _paper_bg,
    _paste,
    _text_layer,
    _warning_layer,
)

HERE = Path(__file__).parent
IMAGES_DIR = HERE / "data" / "images"
MANIFEST = HERE / "data" / "manifest.json"

SEAL_INK = "#2a1d0c"


def _circular_text_layer(
    text: str,
    font: ImageFont.FreeTypeFont,
    radius: float,
    *,
    fill: str = SEAL_INK,
    start_angle: float = -90.0,
    direction: int = 1,
    spread: float | None = None,
    letter_spacing: float = 1.0,
) -> tuple[Image.Image, float]:
    """Lay ``text`` glyph-by-glyph around a circle of ``radius`` pixels.

    Each glyph is rotated to be tangent to the circle, so the word follows the rim like
    a coin/seal legend. ``start_angle`` is in degrees (0 = right, -90 = top, measured
    clockwise as screen-y grows downward). ``direction`` = +1 lays text clockwise
    (correct for the TOP of a seal), -1 lays it counter-clockwise.

    If ``spread`` (total degrees to fill) is given, inter-glyph spacing is stretched/
    compressed to fill exactly that arc; otherwise glyphs use their natural widths.

    Returns ``(layer, used_angle_deg)`` where the layer is a square RGBA canvas whose
    center is the circle center, so callers can paste multiple legends concentrically.
    """
    tmp = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    widths = [d.textlength(c, font=font) * letter_spacing for c in text]
    total_w = sum(widths)
    natural_angle = math.degrees(total_w / radius)
    if spread is not None and total_w > 0:
        scale = spread / natural_angle
        widths = [w * scale for w in widths]
        used_angle = spread
    else:
        used_angle = natural_angle

    asc, desc = font.getmetrics()
    glyph_h = asc + desc
    size = int(2 * (radius + glyph_h) + 8)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx = cy = size / 2

    ang = math.radians(start_angle)
    for ch, w in zip(text, widths):
        dphi = direction * (w / radius)
        ang_mid = ang + dphi / 2
        gx = cx + radius * math.cos(ang_mid)
        gy = cy + radius * math.sin(ang_mid)
        glyph = _text_layer(ch, font, fill=fill, pad=2)
        # Tangent rotation. For text along the TOP arc reading left->right the glyph's
        # up-vector points toward the circle center; for the BOTTOM arc (direction=-1
        # with a flipped baseline) it points outward.
        rot_deg = -(math.degrees(ang_mid) + (90 if direction > 0 else -90))
        rot = glyph.rotate(rot_deg, expand=True, resample=Image.BICUBIC)
        layer.alpha_composite(
            rot, (int(gx - rot.width / 2), int(gy - rot.height / 2))
        )
        ang += dphi
    return layer, used_angle


def _seal_disc(radius: int, rng: random.Random, *, rings: bool = True) -> Image.Image:
    """A round medallion/seal disc to sit text around (aged-paper / wax look)."""
    size = 2 * radius + 8
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(disc)
    c = size / 2
    # Filled disc with a faint tonal body.
    d.ellipse([c - radius, c - radius, c + radius, c + radius], fill=(228, 214, 182, 255))
    if rings:
        for rr, wdt in ((radius - 4, 5), (radius - 26, 3), (radius - 34, 2)):
            d.ellipse(
                [c - rr, c - rr, c + rr, c + rr], outline=RULE, width=wdt
            )
    return disc


def _monogram(radius: int, text: str = "OT") -> Image.Image:
    """Center maker's-mark monogram for the seal."""
    layer = _text_layer(text, _font(FONT_BOLD, int(radius * 0.9)), fill=SEAL_INK)
    return layer


def _finish_simple(img: Image.Image, rng: random.Random, sigma: float = 3.5):
    return _add_noise(img.convert("RGB"), rng, sigma)


# --- variant builders ---------------------------------------------------------
def build_circular(rng: random.Random) -> Image.Image:
    """Brand wrapped the FULL way around a circular seal (top arc + bottom arc),
    with the maker's monogram in the center and the warning straight at the bottom."""
    w, h = 820, 1060
    panel = _paper_bg(w, h, rng)
    d = ImageDraw.Draw(panel)
    d.rectangle([14, 14, w - 14, h - 14], outline=RULE, width=4)
    cx = w / 2
    seal_cy = int(h * 0.34)

    radius = 210
    disc = _seal_disc(radius, rng)
    _paste(panel, disc, cx - disc.width / 2, seal_cy - disc.height / 2)

    brand_font = _font(FONT_BOLD, 40)
    # "OLD TOM" across the top arc, "DISTILLERY" across the bottom arc.
    top_words = "OLD TOM"
    bot_word = "DISTILLERY"

    top_layer, _ = _circular_text_layer(
        top_words, brand_font, radius - 18,
        start_angle=-150, direction=1, spread=120,
    )
    _paste(panel, top_layer, cx - top_layer.width / 2, seal_cy - top_layer.height / 2)

    # Bottom arc: read left->right along the bottom, glyphs upright relative to viewer.
    bot_layer, _ = _circular_text_layer(
        bot_word, brand_font, radius - 18,
        start_angle=150, direction=-1, spread=130,
    )
    _paste(panel, bot_layer, cx - bot_layer.width / 2, seal_cy - bot_layer.height / 2)

    mono = _monogram(int(radius * 0.5), "OT")
    _paste(panel, mono, cx - mono.width / 2, seal_cy - mono.height / 2)

    # Straight supporting fields below the seal.
    y = seal_cy + radius + 40
    ct = _text_layer(OLD_TOM["fields"]["class_type"], _font(FONT_REGULAR, 30), fill=INK_SOFT)
    _paste(panel, ct, cx - ct.width / 2, y)
    y += ct.height + 16
    d.line([90, y, w - 90, y], fill=RULE, width=2)
    y += 18
    abv = _text_layer(OLD_TOM["fields"]["alcohol_content"], _font(FONT_BOLD, 30))
    _paste(panel, abv, cx - abv.width / 2, y)
    y += abv.height + 14
    nc = _text_layer(OLD_TOM["fields"]["net_contents"], _font(FONT_REGULAR, 28), fill=INK_SOFT)
    _paste(panel, nc, cx - nc.width / 2, y)

    warn = _warning_layer(w - 120, _font(FONT_REGULAR, 18), _font(FONT_BOLD, 18))
    _paste(panel, warn, 60, h - warn.height - 34)
    return _finish_simple(panel, rng, sigma=3)


def build_semicircle(rng: random.Random) -> Image.Image:
    """Brand on a pronounced TOP half-arc (a wide semicircle banner) with the producer
    line riding the matching BOTTOM half-arc — no straight baseline anywhere on the
    brand. Supporting fields stay straight underneath."""
    w, h = 860, 1040
    panel = _paper_bg(w, h, rng)
    d = ImageDraw.Draw(panel)
    d.rectangle([14, 14, w - 14, h - 14], outline=RULE, width=4)
    cx = w / 2
    arc_cy = int(h * 0.40)
    radius = 290

    # Faint guide arcs so the curve reads as intentional design, not warp.
    d.arc(
        [cx - radius - 30, arc_cy - radius - 30, cx + radius + 30, arc_cy + radius + 30],
        start=200, end=340, fill=RULE, width=2,
    )

    top, _ = _circular_text_layer(
        "OLD TOM DISTILLERY", _font(FONT_BOLD, 46), radius,
        start_angle=-160, direction=1, spread=140,
    )
    _paste(panel, top, cx - top.width / 2, arc_cy - top.height / 2)

    bot, _ = _circular_text_layer(
        "KENTUCKY STRAIGHT BOURBON", _font(FONT_REGULAR, 30), radius - 8,
        start_angle=158, direction=-1, spread=150, fill=INK_SOFT,
    )
    _paste(panel, bot, cx - bot.width / 2, arc_cy - bot.height / 2)

    # Center fields inside the semicircle.
    cy_text = arc_cy
    wh = _text_layer("WHISKEY", _font(FONT_BOLD, 34), fill=INK)
    _paste(panel, wh, cx - wh.width / 2, cy_text - wh.height / 2)

    y = arc_cy + radius + 30
    abv = _text_layer(OLD_TOM["fields"]["alcohol_content"], _font(FONT_BOLD, 30))
    _paste(panel, abv, cx - abv.width / 2, y)
    y += abv.height + 16
    nc = _text_layer(OLD_TOM["fields"]["net_contents"], _font(FONT_REGULAR, 28), fill=INK_SOFT)
    _paste(panel, nc, cx - nc.width / 2, y)

    warn = _warning_layer(w - 120, _font(FONT_REGULAR, 18), _font(FONT_BOLD, 18))
    _paste(panel, warn, 60, h - warn.height - 34)
    return _finish_simple(panel, rng, sigma=3)


def build_seal(rng: random.Random) -> Image.Image:
    """Text fully ENCIRCLING a round wax-style medallion: the brand runs around the
    top of the rim, the class/type around the bottom of the rim, a monogram in the
    middle — like the certification seal on many spirit labels."""
    w, h = 840, 1080
    panel = _paper_bg(w, h, rng, base=(240, 230, 209))
    d = ImageDraw.Draw(panel)
    d.rectangle([14, 14, w - 14, h - 14], outline=RULE, width=4)
    cx = w / 2
    seal_cy = int(h * 0.40)
    radius = 250

    disc = _seal_disc(radius, rng)
    _paste(panel, disc, cx - disc.width / 2, seal_cy - disc.height / 2)

    # Outer legend ring: brand around the top, producer/class around the bottom.
    top, _ = _circular_text_layer(
        "OLD TOM DISTILLERY", _font(FONT_BOLD, 36), radius - 24,
        start_angle=-165, direction=1, spread=150,
    )
    _paste(panel, top, cx - top.width / 2, seal_cy - top.height / 2)

    bot, _ = _circular_text_layer(
        "KENTUCKY STRAIGHT BOURBON WHISKEY", _font(FONT_REGULAR, 24), radius - 26,
        start_angle=155, direction=-1, spread=160, fill=INK_SOFT,
    )
    _paste(panel, bot, cx - bot.width / 2, seal_cy - bot.height / 2)

    # Inner ring stars + center monogram.
    star = _text_layer("* EST. 1887 *", _font(FONT_BOLD, 22), fill=SEAL_INK)
    _paste(panel, star, cx - star.width / 2, seal_cy - radius * 0.46 - star.height / 2)
    mono = _monogram(int(radius * 0.42), "OT")
    _paste(panel, mono, cx - mono.width / 2, seal_cy - mono.height / 2)

    # Straight fields below.
    y = seal_cy + radius + 36
    abv = _text_layer(OLD_TOM["fields"]["alcohol_content"], _font(FONT_BOLD, 30))
    _paste(panel, abv, cx - abv.width / 2, y)
    y += abv.height + 14
    nc = _text_layer(OLD_TOM["fields"]["net_contents"], _font(FONT_REGULAR, 28), fill=INK_SOFT)
    _paste(panel, nc, cx - nc.width / 2, y)

    warn = _warning_layer(w - 120, _font(FONT_REGULAR, 18), _font(FONT_BOLD, 18))
    _paste(panel, warn, 60, h - warn.height - 34)
    return _finish_simple(panel, rng, sigma=3)


# (id, variant, builder, seed)
CIRCULAR_VARIANTS = [
    ("old_tom_rich_circular", "rich_circular_brand", build_circular, 201),
    ("old_tom_rich_semicircle", "rich_semicircle_brand", build_semicircle, 202),
    ("old_tom_rich_seal", "rich_seal_medallion", build_seal, 203),
]


def main() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.exists():
        raise SystemExit(
            "manifest.json not found — run `python eval/generate.py` first."
        )
    manifest = json.loads(MANIFEST.read_text())
    labels = manifest["labels"]

    ids = {vid for vid, *_ in CIRCULAR_VARIANTS}
    labels = [lab for lab in labels if lab["id"] not in ids]

    for vid, variant, builder, seed in CIRCULAR_VARIANTS:
        rng = random.Random(seed)
        img = builder(rng).convert("RGB")
        name = f"{vid}.png"
        img.save(IMAGES_DIR / name)
        labels.append(
            {
                "id": vid,
                "image": f"images/{name}",
                "variant": variant,
                "commodity": OLD_TOM["commodity"],
                "fields": OLD_TOM["fields"],
            }
        )

    manifest["labels"] = labels
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(
        f"appended {len(CIRCULAR_VARIANTS)} circular variants; manifest now has "
        f"{len(labels)} labels."
    )


if __name__ == "__main__":
    main()
