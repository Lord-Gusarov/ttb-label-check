"""Generate *realistic* hard-case labels for the reader bake-off.

The base ``generate.py`` only applies UNIFORM whole-panel transforms (rotate / dim /
glare the entire label as one rigid block). That flatters classical OCR: a single
deskew fixes every field at once. Real cans / wine / spirits labels instead have
*intra-label* variation — the brand is arced or tilted while the warning stays
straight, text runs vertically up the side, type is condensed or stretched, the panel
is perspective-warped by the bottle's curve, and the warning lives on a separate back
panel. This module composites each text element on its OWN layer so elements can be
transformed independently, then APPENDS the resulting variants to the SAME
``manifest.json`` the base generator writes.

Ground truth is preserved exactly: however a field is bent or rotated, the underlying
words are still the canonical field values, so accuracy stays measurable.

Everything is deterministic (seeded) and offline (PIL + cv2 + numpy only).

    python eval/generate.py        # writes the base 5 + manifest
    python eval/generate.py_rich   # APPENDS the rich variants

Run order matters: ``generate`` writes a fresh manifest; ``generate_rich`` reads it,
appends, and rewrites it. Running ``generate_rich`` twice is idempotent (it replaces
its own previously-appended entries by id).
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.rules.spec.government_warning import CANONICAL_WARNING, WARNING_PREFIX

HERE = Path(__file__).parent
IMAGES_DIR = HERE / "data" / "images"
MANIFEST = HERE / "data" / "manifest.json"

FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_NARROW = "/System/Library/Fonts/Supplemental/Arial Narrow.ttf"

# Two commodities for variety: the assignment spirit + a wine.
OLD_TOM = {
    "commodity": "distilled_spirits",
    "fields": {
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "alcohol_content": "45% Alc./Vol. (90 Proof)",
        "net_contents": "750 mL",
        "warning_present": True,
    },
}

CEDAR_RIDGE = {
    "commodity": "wine",
    "fields": {
        "brand_name": "CEDAR RIDGE VINEYARDS",
        "class_type": "Napa Valley Cabernet Sauvignon",
        "alcohol_content": "13.5% Alc./Vol.",
        "net_contents": "750 mL",
        "warning_present": True,
    },
}

INK = "#1a1208"
INK_SOFT = "#3a2c14"
RULE = "#6b4f1d"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


# --- low-level layer helpers --------------------------------------------------
def _text_layer(
    text: str, font: ImageFont.FreeTypeFont, fill: str = INK, pad: int = 6
) -> Image.Image:
    """Render text onto its own tight transparent RGBA layer."""
    tmp = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    box = d.textbbox((0, 0), text, font=font)
    w = (box[2] - box[0]) + 2 * pad
    h = (box[3] - box[1]) + 2 * pad
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((pad - box[0], pad - box[1]), text, font=font, fill=fill)
    return layer


def _warning_layer(
    width: int,
    font_reg: ImageFont.FreeTypeFont,
    font_bold: ImageFont.FreeTypeFont,
    fill: str = INK,
    line_h: int | None = None,
) -> Image.Image:
    """Render the canonical warning, wrapped to ``width``, with the
    'GOVERNMENT WARNING:' prefix in BOLD and the remainder regular.

    A later bold-detector depends on the prefix actually being heavier strokes, so we
    use a real bold font for those two words rather than faking weight.
    """
    if line_h is None:
        line_h = font_reg.size + 7
    space_w = font_reg.size  # generous; recomputed per-font below
    layer = Image.new("RGBA", (width, 4000), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    prefix_words = set(WARNING_PREFIX.split(" "))

    x = y = 8
    max_x = width - 8
    space_reg = d.textlength(" ", font=font_reg)
    space_w = space_reg
    for word in CANONICAL_WARNING.split(" "):
        bold = word in prefix_words
        font = font_bold if bold else font_reg
        ww = d.textlength(word, font=font)
        if x + ww > max_x:
            x = 8
            y += line_h
        d.text((x, y), word, font=font, fill=fill)
        x += ww + space_w
    # Crop to used height.
    used_h = y + line_h + 8
    return layer.crop((0, 0, width, used_h))


def _arc_text_layer(
    text: str,
    font: ImageFont.FreeTypeFont,
    radius: float,
    fill: str = INK,
) -> Image.Image:
    """Lay out ``text`` glyph-by-glyph along a circular arc (banner curve).

    Each glyph is rotated to be tangent to the arc, so the brand name curves like a
    banner across the top of the label — a deskew can't straighten it because every
    letter sits at a different angle.
    """
    tmp = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    widths = [d.textlength(c, font=font) for c in text]
    total_w = sum(widths)
    total_angle = total_w / radius  # radians spanned along the arc

    asc, desc = font.getmetrics()
    glyph_h = asc + desc
    # Canvas big enough for the arc bulge.
    size = int(2 * radius + 4 * glyph_h)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx, cy = size / 2, size / 2 + radius  # arc center below the canvas middle

    # Walk from the left end of the arc to the right.
    ang = -total_angle / 2
    for ch, w in zip(text, widths):
        ang_mid = ang + (w / radius) / 2
        # Position on the circle (top of arc), then rotate glyph to be tangent.
        gx = cx + radius * math.sin(ang_mid)
        gy = cy - radius * math.cos(ang_mid)
        glyph = _text_layer(ch, font, fill=fill, pad=2)
        rot = glyph.rotate(
            -math.degrees(ang_mid), expand=True, resample=Image.BICUBIC
        )
        layer.alpha_composite(rot, (int(gx - rot.width / 2), int(gy - rot.height / 2)))
        ang += w / radius
    return _autocrop(layer)


def _autocrop(layer: Image.Image, pad: int = 4) -> Image.Image:
    bbox = layer.getbbox()
    if not bbox:
        return layer
    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(layer.width, x1 + pad)
    y1 = min(layer.height, y1 + pad)
    return layer.crop((x0, y0, x1, y1))


def _rotated(layer: Image.Image, deg: float) -> Image.Image:
    return layer.rotate(deg, expand=True, resample=Image.BICUBIC)


def _tilt(rng: random.Random, lo: float, hi: float) -> float:
    """A guaranteed-non-trivial tilt of magnitude in [lo, hi], random sign."""
    return rng.choice((-1, 1)) * rng.uniform(lo, hi)


def _scaled(layer: Image.Image, sx: float, sy: float) -> Image.Image:
    return layer.resize(
        (max(1, int(layer.width * sx)), max(1, int(layer.height * sy))),
        Image.LANCZOS,
    )


def _paste(canvas: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    canvas.alpha_composite(layer, (int(x), int(y)))


# --- backgrounds & photo realism ---------------------------------------------
def _paper_bg(w: int, h: int, rng: random.Random, base=(244, 234, 213)) -> Image.Image:
    """A non-flat, faintly mottled paper background."""
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[:] = base
    # Low-frequency vignette / lighting gradient.
    yy, xx = np.mgrid[0:h, 0:w]
    gx = (xx / w - rng.uniform(0.3, 0.7)) ** 2
    gy = (yy / h - rng.uniform(0.3, 0.7)) ** 2
    grad = 1.0 - 0.18 * (gx + gy)
    arr *= grad[..., None]
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return img.convert("RGBA")


def _add_noise(img: Image.Image, rng: random.Random, sigma: float = 6.0) -> Image.Image:
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    noise = np.asarray(
        [rng.gauss(0, sigma) for _ in range(arr.size)], dtype=np.float32
    ).reshape(arr.shape)
    out = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def _perspective_warp(
    img: Image.Image, rng: random.Random, strength: float = 0.10
) -> Image.Image:
    """Warp the whole composited label to mimic the curve/tilt of a bottle."""
    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    s = strength
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    # Pinch the right edge inward + bow the verticals — barrel-ish bottle curve.
    dx = w * s
    dy = h * s * 0.5
    dst = np.float32(
        [
            [dx * rng.uniform(0.6, 1.0), dy * rng.uniform(0.4, 0.9)],
            [w - dx * rng.uniform(0.6, 1.0), dy * rng.uniform(0.2, 0.6)],
            [w - dx * rng.uniform(0.3, 0.7), h - dy * rng.uniform(0.4, 0.9)],
            [dx * rng.uniform(0.3, 0.7), h - dy * rng.uniform(0.2, 0.6)],
        ]
    )
    m = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(
        rgb, m, (w, h), borderValue=(216, 201, 168), flags=cv2.INTER_CUBIC
    )
    return Image.fromarray(warped, "RGB")


def _finish(
    img: Image.Image,
    rng: random.Random,
    blur: float = 0.6,
    sigma: float = 5.0,
) -> Image.Image:
    out = img.convert("RGB")
    if blur:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    return _add_noise(out, rng, sigma)


# --- panel builders -----------------------------------------------------------
def _front_panel(
    spec: dict,
    rng: random.Random,
    w: int,
    h: int,
    *,
    arc_brand: bool = False,
    rotate_elements: bool = False,
    condensed: bool = False,
    vertical_side: bool = False,
    include_warning: bool = True,
    off_center: bool = False,
) -> Image.Image:
    """Composite a front panel with independently-transformed elements."""
    f = spec["fields"]
    panel = _paper_bg(w, h, rng)
    d = ImageDraw.Draw(panel)
    d.rectangle([14, 14, w - 14, h - 14], outline=RULE, width=4)

    cx = w / 2

    def jitter(base: float) -> float:
        return base + (rng.uniform(-14, 14) if off_center else 0)

    # Brand name: arced banner, tilted, condensed, or straight.
    if arc_brand:
        # Radius scaled to text width so the arc visibly bows regardless of length.
        bw = ImageDraw.Draw(panel).textlength(f["brand_name"], font=_font(FONT_BOLD, 44))
        brand = _arc_text_layer(
            f["brand_name"], _font(FONT_BOLD, 44), radius=bw * rng.uniform(0.62, 0.78)
        )
        _paste(panel, brand, jitter(cx - brand.width / 2), 40)
        brand_bottom = 40 + brand.height
    else:
        font = _font(FONT_NARROW, 60) if condensed else _font(FONT_BOLD, 50)
        brand = _text_layer(f["brand_name"], font)
        if condensed:
            brand = _scaled(brand, 0.58, 1.32)  # squeeze horizontally, stretch tall
        # Keep the brand inside the panel (narrow multi-panel fronts are tight).
        if brand.width > w - 50:
            sf = (w - 50) / brand.width
            brand = _scaled(brand, sf, 1.0)
        if rotate_elements:
            brand = _rotated(brand, _tilt(rng, 5, 12))
        _paste(panel, brand, jitter(cx - brand.width / 2), 60)
        brand_bottom = 60 + brand.height

    # Class / type.
    ct_font = _font(FONT_NARROW, 34) if condensed else _font(FONT_REGULAR, 30)
    ct = _text_layer(f["class_type"], ct_font, fill=INK_SOFT)
    if condensed:
        ct = _scaled(ct, 0.66, 1.18)
    if rotate_elements:
        ct = _rotated(ct, _tilt(rng, 3, 7))
    cty = brand_bottom + 24
    _paste(panel, ct, jitter(cx - ct.width / 2), cty)

    d.line([70, cty + ct.height + 18, w - 70, cty + ct.height + 18], fill=RULE, width=2)

    # ABV — sometimes rotated independently.
    abv = _text_layer(f["alcohol_content"], _font(FONT_BOLD, 32))
    if rotate_elements:
        abv = _rotated(abv, _tilt(rng, 6, 12))
    abvy = int(h * 0.42)
    _paste(panel, abv, jitter(cx - abv.width / 2), abvy)

    # Net contents — vertical up the right side, or centered below ABV.
    if vertical_side:
        nc = _text_layer(f["net_contents"], _font(FONT_BOLD, 30))
        nc = _rotated(nc, 90)  # reads bottom-to-top up the side
        _paste(panel, nc, w - nc.width - 26, int(h * 0.5))
    else:
        nc = _text_layer(f["net_contents"], _font(FONT_REGULAR, 30), fill=INK_SOFT)
        if rotate_elements:
            nc = _rotated(nc, _tilt(rng, 4, 8))
        _paste(panel, nc, jitter(cx - nc.width / 2), abvy + abv.height + 30)

    if include_warning:
        warn = _warning_layer(
            w - 110, _font(FONT_REGULAR, 18), _font(FONT_BOLD, 18)
        )
        _paste(panel, warn, 55, h - warn.height - 36)

    return panel


def _back_panel(spec: dict, rng: random.Random, w: int, h: int) -> Image.Image:
    """A back panel that carries the government warning (multi-panel layouts)."""
    panel = _paper_bg(w, h, rng, base=(238, 228, 206))
    d = ImageDraw.Draw(panel)
    d.rectangle([14, 14, w - 14, h - 14], outline=RULE, width=3)

    title = _text_layer(spec["fields"]["brand_name"], _font(FONT_BOLD, 30))
    title = _scaled(title, 0.8, 1.0)
    _paste(panel, title, (w - title.width) / 2, 50)

    warn = _warning_layer(w - 90, _font(FONT_REGULAR, 19), _font(FONT_BOLD, 19))
    _paste(panel, warn, 45, int(h * 0.30))
    # A bit of back-label boilerplate as visual clutter.
    bp = _text_layer(
        "Bottled by the producer. Imported / distributed nationwide.",
        _font(FONT_REGULAR, 16),
        fill=INK_SOFT,
    )
    _paste(panel, bp, 45, h - bp.height - 50)
    return panel


def _on_scene(panel: Image.Image, rng: random.Random, margin: int = 70) -> Image.Image:
    """Drop a panel onto a darker scene background (shelf/table proxy)."""
    pw, ph = panel.size
    scene = Image.new("RGBA", (pw + 2 * margin, ph + 2 * margin), (34, 31, 28, 255))
    sd = ImageDraw.Draw(scene)
    for _ in range(24):
        x0 = rng.randint(0, scene.width)
        y0 = rng.randint(0, scene.height)
        shade = rng.randint(24, 70)
        sd.rectangle(
            [x0, y0, x0 + rng.randint(30, 160), y0 + rng.randint(30, 160)],
            fill=(shade, shade - 4, shade - 8, 255),
        )
    scene.alpha_composite(panel.convert("RGBA"), (margin, margin))
    return scene


# --- variant builders ---------------------------------------------------------
def build_arc(rng: random.Random) -> Image.Image:
    p = _front_panel(OLD_TOM, rng, 760, 1000, arc_brand=True)
    return _finish(p, rng, blur=0.5, sigma=4)


def build_per_element_rotation(rng: random.Random) -> Image.Image:
    p = _front_panel(OLD_TOM, rng, 760, 1000, rotate_elements=True, off_center=True)
    return _finish(p, rng, blur=0.5, sigma=5)


def build_vertical(rng: random.Random) -> Image.Image:
    p = _front_panel(OLD_TOM, rng, 760, 1000, vertical_side=True, rotate_elements=True)
    return _finish(p, rng, blur=0.5, sigma=4)


def build_condensed(rng: random.Random) -> Image.Image:
    p = _front_panel(OLD_TOM, rng, 760, 1000, condensed=True)
    return _finish(p, rng, blur=0.5, sigma=4)


def build_perspective(rng: random.Random) -> Image.Image:
    p = _front_panel(OLD_TOM, rng, 760, 1000, rotate_elements=True)
    warped = _perspective_warp(p, rng, strength=0.11)
    return _finish(warped, rng, blur=0.7, sigma=5)


def build_multipanel(rng: random.Random) -> Image.Image:
    pw, ph = 520, 920
    front = _front_panel(OLD_TOM, rng, pw, ph, include_warning=False, vertical_side=True)
    back = _back_panel(OLD_TOM, rng, pw, ph)
    gap = 40
    combined = Image.new(
        "RGBA", (pw * 2 + gap * 3, ph + gap * 2), (210, 196, 165, 255)
    )
    combined.alpha_composite(front, (gap, gap))
    combined.alpha_composite(back, (pw + gap * 2, gap))
    return _finish(combined, rng, blur=0.6, sigma=5)


def build_blur_noise(rng: random.Random) -> Image.Image:
    p = _front_panel(OLD_TOM, rng, 760, 1000, off_center=True)
    scene = _on_scene(p, rng)
    return _finish(scene, rng, blur=1.4, sigma=11)


def build_wine_arc_perspective(rng: random.Random) -> Image.Image:
    p = _front_panel(CEDAR_RIDGE, rng, 760, 1000, arc_brand=True, rotate_elements=True)
    warped = _perspective_warp(p, rng, strength=0.09)
    return _finish(warped, rng, blur=0.6, sigma=5)


def build_wine_multipanel(rng: random.Random) -> Image.Image:
    pw, ph = 520, 920
    front = _front_panel(
        CEDAR_RIDGE, rng, pw, ph, include_warning=False, condensed=True
    )
    back = _back_panel(CEDAR_RIDGE, rng, pw, ph)
    gap = 40
    combined = Image.new(
        "RGBA", (pw * 2 + gap * 3, ph + gap * 2), (206, 192, 162, 255)
    )
    combined.alpha_composite(front, (gap, gap))
    combined.alpha_composite(back, (pw + gap * 2, gap))
    return _finish(combined, rng, blur=0.6, sigma=5)


# (id, variant, commodity-spec, builder, seed)
RICH_VARIANTS = [
    ("old_tom_rich_arc", "rich_arc_brand", OLD_TOM, build_arc, 101),
    (
        "old_tom_rich_perelement",
        "rich_per_element_rotation",
        OLD_TOM,
        build_per_element_rotation,
        102,
    ),
    ("old_tom_rich_vertical", "rich_vertical_text", OLD_TOM, build_vertical, 103),
    ("old_tom_rich_condensed", "rich_condensed", OLD_TOM, build_condensed, 104),
    ("old_tom_rich_perspective", "rich_perspective", OLD_TOM, build_perspective, 105),
    ("old_tom_rich_multipanel", "rich_multipanel", OLD_TOM, build_multipanel, 106),
    ("old_tom_rich_blurnoise", "rich_blur_noise", OLD_TOM, build_blur_noise, 107),
    (
        "cedar_ridge_rich_arc_persp",
        "rich_wine_arc_perspective",
        CEDAR_RIDGE,
        build_wine_arc_perspective,
        108,
    ),
    (
        "cedar_ridge_rich_multipanel",
        "rich_wine_multipanel",
        CEDAR_RIDGE,
        build_wine_multipanel,
        109,
    ),
]


def main() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.exists():
        raise SystemExit(
            "manifest.json not found — run `python eval/generate.py` first."
        )
    manifest = json.loads(MANIFEST.read_text())
    labels = manifest["labels"]

    rich_ids = {vid for vid, *_ in RICH_VARIANTS}
    # Idempotent: drop any rich entries we previously appended, keep the base ones.
    labels = [lab for lab in labels if lab["id"] not in rich_ids]

    for vid, variant, spec, builder, seed in RICH_VARIANTS:
        rng = random.Random(seed)
        img = builder(rng).convert("RGB")
        name = f"{vid}.png"
        img.save(IMAGES_DIR / name)
        labels.append(
            {
                "id": vid,
                "image": f"images/{name}",
                "variant": variant,
                "commodity": spec["commodity"],
                "fields": spec["fields"],
            }
        )

    manifest["labels"] = labels
    manifest["description"] = (
        "Synthetic seed corpus for the reader bake-off: the original uniform-transform "
        "spirits labels PLUS realistic hard cases with intra-label variation "
        "(arc/vertical/condensed text, per-element rotation, perspective warp, "
        "multi-panel front+back, blur+noise) across spirits and wine."
    )
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(
        f"appended {len(RICH_VARIANTS)} rich variants; manifest now has "
        f"{len(labels)} labels."
    )


if __name__ == "__main__":
    main()
