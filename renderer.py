"""
renderer.py
===========
Renders approved carousel text into PNG slides.
White Poppins Bold text on black background, 1080x1080 (Instagram square).

Output structure:
  outputs/YYYY-MM-DD/carousel_01/
    slide_01.png  ← hook
    slide_02.png  ← body
    ...
    slide_N.png   ← CTA

Imported by bot.py — not run directly in production.
Run as __main__ for local testing only.
"""

import shutil
import textwrap
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

from config import FONT_PATH, OUTPUT_DIR

# ── Constants ─────────────────────────────────────────────────────────────────

CANVAS      = (1080, 1080)
BG          = (0, 0, 0)
FG          = (255, 255, 255)
MUTED       = (140, 140, 140)
PADDING     = 108                # px from each edge
DOT_AREA    = 60                 # px reserved at bottom for dots
MAX_SIZE    = 80
MIN_SIZE    = 28
LINE_SPACE  = 1.45


# ── Font loader ───────────────────────────────────────────────────────────────

def _font(size: int) -> ImageFont.FreeTypeFont:
    if FONT_PATH.exists():
        return ImageFont.truetype(str(FONT_PATH), size)
    # fallback for environments without the font file
    return ImageFont.load_default(size=size)


# ── Text fitting ──────────────────────────────────────────────────────────────

def _fit(draw: ImageDraw, text: str, max_w: int, max_h: int):
    """
    Find largest font size where wrapped text fits within max_w x max_h.
    Returns (font, lines).
    """
    for size in range(MAX_SIZE, MIN_SIZE - 1, -2):
        font    = _font(size)
        # estimate chars per line from canvas width and char width
        cpl     = max(10, int(max_w / (size * 0.56)))
        lines   = textwrap.wrap(text, width=cpl)
        if not lines:
            lines = [text]
        total_h = size * LINE_SPACE * len(lines)
        max_lw  = max(draw.textlength(l, font=font) for l in lines)
        if max_lw <= max_w and total_h <= max_h:
            return font, lines
    font  = _font(MIN_SIZE)
    lines = textwrap.wrap(text, width=30) or [text]
    return font, lines


# ── Single slide renderer ─────────────────────────────────────────────────────

def _render_slide(text: str, slide_type: str,
                  slide_num: int, total: int,
                  out_path: Path) -> None:
    """
    Render one slide and save as PNG.
    slide_type: 'hook' | 'body' | 'cta'
    """
    img  = Image.new("RGB", CANVAS, BG)
    draw = ImageDraw.Draw(img)

    usable_w = CANVAS[0] - PADDING * 2
    usable_h = CANVAS[1] - PADDING * 2 - DOT_AREA

    font, lines = _fit(draw, text, usable_w, usable_h)
    line_h      = font.size * LINE_SPACE
    block_h     = line_h * len(lines)

    # vertically centre text block
    start_y = (CANVAS[1] - block_h - DOT_AREA) / 2

    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        x  = (CANVAS[0] - lw) / 2
        y  = start_y + i * line_h
        draw.text((x, y), line, font=font, fill=FG)

    # ── slide indicator dots ──────────────────────────────────────────────────
    dot_r    = 5
    spacing  = 20
    total_dw = total * dot_r * 2 + (total - 1) * (spacing - dot_r * 2)
    sx       = (CANVAS[0] - total_dw) / 2
    dy       = CANVAS[1] - PADDING // 2

    for i in range(total):
        cx    = sx + i * spacing
        color = FG if i == slide_num - 1 else MUTED
        draw.ellipse([cx - dot_r, dy - dot_r,
                      cx + dot_r, dy + dot_r], fill=color)

    # ── thin rule on hook slide ───────────────────────────────────────────────
    if slide_type == "hook":
        draw.line(
            [(PADDING, PADDING // 2), (CANVAS[0] - PADDING, PADDING // 2)],
            fill=MUTED, width=1
        )

    # ── slide type label (small, top-right, muted) ────────────────────────────
    label_font = _font(24)
    label      = {"hook": "01 / HOOK", "cta": f"{total:02d} / CTA"}.get(
                    slide_type, f"{slide_num:02d}")
    lw         = draw.textlength(label, font=label_font)
    draw.text((CANVAS[0] - PADDING - lw, PADDING // 2 - 12),
              label, font=label_font, fill=MUTED)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "PNG")


# ── Public API ────────────────────────────────────────────────────────────────

def render_carousel(carousel: dict, date_str: str, carousel_index: int) -> list[Path]:
    """
    Render all slides for one carousel. Returns ordered list of PNG paths.

    carousel schema:
      {
        hook:            str,
        slides:          list[str],
        cta:             str,
        caption:         str,
        hashtags:        list[str],
        virality_score:  int,
        content_pillar:  str
      }
    """
    out_dir   = OUTPUT_DIR / date_str / f"carousel_{carousel_index:02d}"
    all_texts = [carousel["hook"]] + carousel["slides"] + [carousel["cta"]]
    total     = len(all_texts)
    paths     = []

    for idx, text in enumerate(all_texts, 1):
        if idx == 1:
            slide_type = "hook"
        elif idx == total:
            slide_type = "cta"
        else:
            slide_type = "body"

        out_path = out_dir / f"slide_{idx:02d}.png"
        _render_slide(text, slide_type, idx, total, out_path)
        paths.append(out_path)

    return paths


def delete_carousel(date_str: str, carousel_index: int) -> None:
    """
    Delete the rendered PNG folder for a carousel after successful posting.
    Safe to call even if folder doesn't exist.
    """
    folder = OUTPUT_DIR / date_str / f"carousel_{carousel_index:02d}"
    if folder.exists():
        shutil.rmtree(folder)
        # remove parent date folder if now empty
        parent = OUTPUT_DIR / date_str
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    SAMPLE = {
        "hook":   "You don't have a productivity problem.",
        "slides": [
            "You have a clarity problem.",
            "Most people confuse being busy with making progress.",
            "The fix is a daily 10-minute review.",
            "Ask: what one thing moves the needle today?",
            "Do that first. Everything else is noise.",
        ],
        "cta":            "Save this. Read it every morning.",
        "caption":        "Test caption.",
        "hashtags":       ["productivity", "systems", "deepwork"],
        "virality_score": 9,
        "content_pillar": "systems",
    }

    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"Rendering sample carousel → outputs/{date_str}/carousel_01/")

    paths = render_carousel(SAMPLE, date_str, 1)

    print(f"✓ {len(paths)} slides rendered:")
    for p in paths:
        size_kb = p.stat().st_size // 1024
        print(f"  {p.name}  ({size_kb} KB)")

    # verify delete works
    print("\nTesting delete_carousel()...")
    delete_carousel(date_str, 1)
    folder = OUTPUT_DIR / date_str / "carousel_01"
    print(f"✓ Folder deleted: {not folder.exists()}")
    print(f"✓ outputs/ clean: {not (OUTPUT_DIR / date_str).exists()}")
