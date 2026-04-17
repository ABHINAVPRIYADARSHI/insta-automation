"""
renderer.py
===========
Renders approved carousel text into JPG slides.
White Poppins Bold text on black background, 1080x1080 (Instagram square).

Output structure:
  outputs/
    YYMMDDHHMMSS_rand_slide.jpg

Imported by bot.py and instagram.py.
"""

import secrets
import textwrap
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import FONT_PATH, OUTPUT_DIR

CANVAS = (1080, 1080)
BG = (0, 0, 0)
FG = (255, 255, 255)
MUTED = (140, 140, 140)
PADDING = 108
DOT_AREA = 60
MAX_SIZE = 80
MIN_SIZE = 28
LINE_SPACE = 1.45


def _font(size: int) -> ImageFont.FreeTypeFont:
    if FONT_PATH.exists():
        return ImageFont.truetype(str(FONT_PATH), size)
    return ImageFont.load_default(size=size)


def _fit(draw: ImageDraw, text: str, max_w: int, max_h: int):
    for size in range(MAX_SIZE, MIN_SIZE - 1, -2):
        font = _font(size)
        cpl = max(10, int(max_w / (size * 0.56)))
        lines = textwrap.wrap(text, width=cpl) or [text]
        total_h = size * LINE_SPACE * len(lines)
        max_lw = max(draw.textlength(l, font=font) for l in lines)
        if max_lw <= max_w and total_h <= max_h:
            return font, lines
    font = _font(MIN_SIZE)
    lines = textwrap.wrap(text, width=30) or [text]
    return font, lines


def _render_slide(text: str, slide_type: str, slide_num: int, total: int, out_path: Path) -> None:
    img = Image.new("RGB", CANVAS, BG)
    draw = ImageDraw.Draw(img)

    usable_w = CANVAS[0] - PADDING * 2
    usable_h = CANVAS[1] - PADDING * 2 - DOT_AREA

    font, lines = _fit(draw, text, usable_w, usable_h)
    line_h = font.size * LINE_SPACE
    block_h = line_h * len(lines)
    start_y = (CANVAS[1] - block_h - DOT_AREA) / 2

    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        x = (CANVAS[0] - lw) / 2
        y = start_y + i * line_h
        draw.text((x, y), line, font=font, fill=FG)

    dot_r = 5
    spacing = 20
    total_dw = total * dot_r * 2 + (total - 1) * (spacing - dot_r * 2)
    sx = (CANVAS[0] - total_dw) / 2
    dy = CANVAS[1] - PADDING // 2

    for i in range(total):
        cx = sx + i * spacing
        color = FG if i == slide_num - 1 else MUTED
        draw.ellipse([cx - dot_r, dy - dot_r, cx + dot_r, dy + dot_r], fill=color)

    label_font = _font(24)
    label = f"{slide_num:02d}"
    lw = draw.textlength(label, font=label_font)
    draw.text((CANVAS[0] - PADDING - lw, PADDING // 2 - 12), label, font=label_font, fill=MUTED)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "JPEG", quality=92, optimize=True)


def _run_prefix() -> str:
    ts = datetime.now().strftime("%y%m%d%H%M%S")
    rand = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(4))
    return f"{ts}_{rand}"


def render_carousel(carousel: dict, date_str: str, carousel_index: int) -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prefix = _run_prefix()
    all_texts = [carousel["hook"]] + carousel["slides"] + [carousel["cta"]]
    total = len(all_texts)
    paths = []

    for idx, text in enumerate(all_texts, 1):
        if idx == 1:
            slide_type = "hook"
        elif idx == total:
            slide_type = "cta"
        else:
            slide_type = "body"

        out_path = OUTPUT_DIR / f"{prefix}_{idx:02d}.jpg"
        _render_slide(text, slide_type, idx, total, out_path)
        paths.append(out_path)

    return paths


def delete_paths(paths: list[Path]) -> None:
    for p in paths:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def delete_carousel(date_str: str, carousel_index: int) -> None:
    """
    Backward-compatible no-op for older call sites.
    Use delete_paths(paths) for precise cleanup.
    """
    return None


if __name__ == "__main__":
    SAMPLE = {
        "hook": "You don't have a productivity problem.",
        "slides": [
            "You have a clarity problem.",
            "Most people confuse being busy with making progress.",
            "The fix is a daily 10-minute review.",
            "Ask: what one thing moves the needle today?",
            "Do that first. Everything else is noise.",
        ],
        "cta": "Save this. Read it every morning.",
        "caption": "Test caption.",
        "hashtags": ["productivity", "systems", "deepwork"],
        "virality_score": 9,
        "content_pillar": "systems",
    }

    date_str = datetime.now().strftime("%Y-%m-%d")
    print("Rendering sample carousel -> outputs/")

    paths = render_carousel(SAMPLE, date_str, 1)

    print(f"Rendered {len(paths)} slides:")
    for p in paths:
        size_kb = p.stat().st_size // 1024
        print(f"  {p.name} ({size_kb} KB)")

    print("\nTesting delete_paths()...")
    delete_paths(paths)
    print(f"Deleted all files: {all(not p.exists() for p in paths)}")
