"""
imgbb.py
========
Uploads local PNG files to imgbb and returns their public URLs.

WHY THIS EXISTS
───────────────
Instagram's Graph API does not accept local file uploads or base64 images.
It requires a publicly accessible HTTPS URL per image.
imgbb provides free, permanent image hosting with a simple API.

GET YOUR FREE KEY
─────────────────
1. Visit https://api.imgbb.com/
2. Sign up (free, no credit card)
3. Copy your API key → set IMGBB_API_KEY in .env

LIMITS (free tier)
──────────────────
- No upload size limit documented (tested fine with 1080x1080 PNGs ~30KB each)
- No rate limit documented — we add a small delay between uploads to be safe
- Images are hosted permanently
- No account verification needed

Imported by instagram.py. Run as __main__ for standalone testing.
"""

import base64
import time
from pathlib import Path

import requests

from config import IMGBB_API_KEY

IMGBB_ENDPOINT = "https://api.imgbb.com/1/upload"
UPLOAD_DELAY   = 0.5   # seconds between uploads — gentle on free tier


# ── Core upload ───────────────────────────────────────────────────────────────

def upload_image(image_path: Path) -> str:
    """
    Upload a single PNG to imgbb.
    Returns the public HTTPS URL of the uploaded image.
    Raises RuntimeError on failure.
    """
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    resp = requests.post(
        IMGBB_ENDPOINT,
        data={"key": IMGBB_API_KEY, "image": b64},
        timeout=30,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"imgbb HTTP {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"imgbb upload failed: {data}")

    url = data["data"]["url"]
    return url


def upload_slides(slide_paths: list[Path]) -> list[str]:
    """
    Upload all slides for one carousel in order.
    Returns a list of public URLs in the same order as slide_paths.

    Adds a small delay between uploads to avoid hammering the free API.
    """
    urls = []
    for i, path in enumerate(slide_paths):
        url = upload_image(path)
        urls.append(url)
        if i < len(slide_paths) - 1:
            time.sleep(UPLOAD_DELAY)
    return urls


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from renderer import render_carousel
    from datetime import datetime

    print("imgbb.py — standalone test")
    print("=" * 40)

    # Check API key
    if not IMGBB_API_KEY:
        print("\n✗ IMGBB_API_KEY not set in .env")
        print("  → Get your free key at https://api.imgbb.com/")
        sys.exit(1)
    print(f"✓ IMGBB_API_KEY found (ends: ...{IMGBB_API_KEY[-4:]})")

    # Render a sample carousel to get real PNGs
    print("\n[1] Rendering 3-slide sample carousel...")
    sample = {
        "hook":            "Test upload — ignore this post.",
        "slides":          ["Slide 2 body text here.", "Slide 3 body text here."],
        "cta":             "This is a test CTA slide.",
        "caption":         "Test.",
        "hashtags":        [],
        "virality_score":  1,
        "content_pillar":  "systems",
    }
    date_str = datetime.now().strftime("%Y-%m-%d")
    paths    = render_carousel(sample, date_str, 99)
    print(f"    ✓ {len(paths)} slides rendered")

    # Upload all slides
    print(f"\n[2] Uploading {len(paths)} slides to imgbb...")
    try:
        urls = upload_slides(paths)
        print(f"    ✓ {len(urls)} uploads successful")
        for i, (path, url) in enumerate(zip(paths, urls), 1):
            print(f"    slide {i}: {url}")
    except Exception as e:
        print(f"    ✗ Upload failed: {e}")
        sys.exit(1)

    # Cleanup test renders
    from renderer import delete_carousel
    delete_carousel(date_str, 99)
    print(f"\n[3] Test PNGs cleaned up")

    print(f"\n✓ imgbb test passed — {len(urls)} public URLs ready for Instagram API")