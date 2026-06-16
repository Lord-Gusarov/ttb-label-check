"""Generate a small, reproducible seed corpus of synthetic spirit labels.

Why synthetic: we get exact ground truth and full control over the *hard cases*
(rotation, glare, low light, busy layout) without depending on external image-gen or
network. Step 8 expands this with realistic AI-generated labels; this seed is enough
to drive the reader bake-off and the golden tests.

Run once locally; the generated PNGs + manifest.json are committed so the bench is
reproducible without regenerating. Bold prefix is rendered with a real bold font so
the same corpus also feeds the step-4 bold detector.

    uv run python -m corpus.generate
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from app.rules.spec.government_warning import CANONICAL_WARNING

HERE = Path(__file__).parent
IMAGES_DIR = HERE / "data" / "images"
MANIFEST = HERE / "data" / "manifest.json"

FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

# The assignment's sample distilled-spirits label.
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

W, H = 760, 1000


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _draw_centered(draw, y, text, font, fill="#1a1208"):
    w = draw.textlength(text, font=font)
    draw.text(((W - w) / 2, y), text, font=font, fill=fill)


def _draw_wrapped_rich(draw, x, y, tokens, font_reg, font_bold, max_w, line_h, fill):
    """Word-wrap a list of (word, is_bold) tokens; bold words use the bold font.

    Lets us render 'GOVERNMENT WARNING:' bold and the remainder regular, exactly as
    the regulation requires — which the bold detector later has to verify.
    """
    cx, cy = x, y
    space = draw.textlength(" ", font=font_reg)
    for word, is_bold in tokens:
        font = font_bold if is_bold else font_reg
        ww = draw.textlength(word, font=font)
        if cx + ww > x + max_w:
            cx = x
            cy += line_h
        draw.text((cx, cy), word, font=font, fill=fill)
        cx += ww + space
    return cy + line_h


def _warning_tokens() -> list[tuple[str, bool]]:
    """Bold = the 'GOVERNMENT WARNING:' prefix; everything after is regular."""
    tokens: list[tuple[str, bool]] = []
    for word in CANONICAL_WARNING.split(" "):
        bold = word in ("GOVERNMENT", "WARNING:")
        tokens.append((word, bold))
    return tokens


def build_clean_label(spec: dict) -> Image.Image:
    """Render a straight, well-lit label on a cream background."""
    img = Image.new("RGB", (W, H), "#f4ead5")
    draw = ImageDraw.Draw(img)
    f = spec["fields"]

    # Decorative border.
    draw.rectangle([18, 18, W - 18, H - 18], outline="#6b4f1d", width=4)

    _draw_centered(draw, 70, f["brand_name"], _font(FONT_BOLD, 52))
    _draw_centered(draw, 150, f["class_type"], _font(FONT_REGULAR, 30), fill="#3a2c14")

    draw.line([90, 230, W - 90, 230], fill="#6b4f1d", width=2)

    _draw_centered(draw, 300, f["alcohol_content"], _font(FONT_BOLD, 34))
    _draw_centered(draw, 380, f["net_contents"], _font(FONT_REGULAR, 30), fill="#3a2c14")

    # Government warning block near the bottom.
    _draw_wrapped_rich(
        draw,
        x=70,
        y=760,
        tokens=_warning_tokens(),
        font_reg=_font(FONT_REGULAR, 19),
        font_bold=_font(FONT_BOLD, 19),
        max_w=W - 140,
        line_h=26,
        fill="#1a1208",
    )
    return img


# --- Hard-case transforms -----------------------------------------------------
def t_clean(img: Image.Image) -> Image.Image:
    return img


def t_rotated(img: Image.Image) -> Image.Image:
    return img.rotate(-12, expand=True, fillcolor="#d8c9a8", resample=Image.BICUBIC)


def t_lowlight(img: Image.Image) -> Image.Image:
    img = ImageEnhance.Brightness(img).enhance(0.45)
    return ImageEnhance.Contrast(img).enhance(0.7)


def t_glare(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    overlay = Image.new("RGB", img.size, "#000000")
    od = ImageDraw.Draw(overlay)
    cx, cy = int(W * 0.62), int(H * 0.32)
    for r in range(220, 0, -8):
        v = int(255 * (1 - r / 220))
        od.ellipse([cx - r, cy - r // 2, cx + r, cy + r // 2], fill=(v, v, v))
    return Image.blend(img, overlay, 0.45)


def t_busy(img: Image.Image) -> Image.Image:
    """Place the label over a noisy multicolor background (creative-layout proxy)."""
    rng = random.Random(7)
    canvas = Image.new("RGB", (W + 120, H + 120), "#222233")
    cd = ImageDraw.Draw(canvas)
    palette = ["#7a2d2d", "#2d557a", "#2d7a4f", "#7a6b2d", "#5a2d7a"]
    for _ in range(40):
        x0 = rng.randint(0, W + 120)
        y0 = rng.randint(0, H + 120)
        cd.rectangle(
            [x0, y0, x0 + rng.randint(40, 200), y0 + rng.randint(40, 200)],
            fill=rng.choice(palette),
        )
    canvas.paste(img, (60, 60))
    return canvas


TRANSFORMS = {
    "clean": t_clean,
    "rotated": t_rotated,
    "lowlight": t_lowlight,
    "glare": t_glare,
    "busy": t_busy,
}


def main() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    base = build_clean_label(OLD_TOM)

    labels = []
    for variant, transform in TRANSFORMS.items():
        out = transform(base)
        name = f"old_tom_{variant}.png"
        out.save(IMAGES_DIR / name)
        labels.append(
            {
                "id": f"old_tom_{variant}",
                "image": f"images/{name}",
                "variant": variant,
                "commodity": OLD_TOM["commodity"],
                "fields": OLD_TOM["fields"],
            }
        )

    manifest = {
        "description": "Synthetic seed corpus for the reader bake-off (distilled spirits).",
        "canonical_warning": CANONICAL_WARNING,
        "labels": labels,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"wrote {len(labels)} labels to {IMAGES_DIR} and {MANIFEST.name}")


if __name__ == "__main__":
    main()
