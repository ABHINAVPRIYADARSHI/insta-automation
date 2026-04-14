"""
instagram.py
============
Posts rendered carousels to Instagram via the Graph API.

FLOW (per carousel)
───────────────────
1. upload_slides()     → imgbb gives us public URLs for each slide PNG
2. create_image_container() × N  → one IG container ID per image
3. create_carousel_container()   → one container wrapping all image IDs
4. publish_container()           → makes the post live, returns media ID

PREREQUISITES — read carefully
──────────────────────────────
A. Facebook Developer account
   → https://developers.facebook.com

B. Create a Meta App
   → My Apps → Create App → Business type
   → Add product: Instagram Graph API

C. Instagram Professional account
   → Must be Creator or Business (not Personal)
   → Convert: Instagram app → Settings → Account type → Switch to Professional

D. Link Instagram to a Facebook Page
   → Facebook Page → Settings → Linked accounts → Instagram
   → (Create a dummy Facebook Page if you don't have one)

E. Get your IG User ID
   → Graph API Explorer → GET /me/accounts → find your Page ID
   → GET /{page_id}?fields=instagram_business_account
   → The id inside instagram_business_account is your IG_USER_ID

F. Get a Long-lived Access Token (valid 60 days)
   Step 1 — short-lived token from Graph API Explorer (valid 1 hour)
   Step 2 — exchange for long-lived:
     GET https://graph.facebook.com/v18.0/oauth/access_token
       ?grant_type=fb_exchange_token
       &client_id={APP_ID}
       &client_secret={APP_SECRET}
       &fb_exchange_token={SHORT_LIVED_TOKEN}
   Step 3 — copy the access_token from the response → set in .env

G. Set in .env:
   PROD_IG_USER_ID=numeric_id_from_step_E
   PROD_IG_ACCESS_TOKEN=token_from_step_F

NOTE: Tokens expire after 60 days. Re-run Step F to refresh.

Imported by bot.py. Run as __main__ for standalone testing.
"""

import time
from pathlib import Path

import requests

from config import CHANNELS
from imgbb import upload_slides

GRAPH_BASE   = "https://graph.facebook.com/v18.0"
ITEM_DELAY   = 1.5   # seconds between image container creation calls
PUBLISH_WAIT = 2.0   # seconds to wait before publishing carousel container


# ── Graph API helpers ─────────────────────────────────────────────────────────

def _post(endpoint: str, params: dict) -> dict:
    """
    POST to Graph API endpoint. Raises RuntimeError on failure.
    """
    resp = requests.post(
        f"{GRAPH_BASE}/{endpoint}",
        params=params,
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(
            f"Graph API error on /{endpoint}: "
            f"{data['error'].get('message', data['error'])}"
        )
    if "id" not in data:
        raise RuntimeError(f"Unexpected response from /{endpoint}: {data}")
    return data


# ── Instagram posting steps ───────────────────────────────────────────────────

def _create_image_container(ig_user_id: str, access_token: str,
                             image_url: str) -> str:
    """
    Step 2: Create an IG media container for one carousel image.
    Returns the container ID.
    """
    data = _post(
        f"{ig_user_id}/media",
        {
            "image_url":        image_url,
            "is_carousel_item": "true",
            "access_token":     access_token,
        }
    )
    return data["id"]


def _create_carousel_container(ig_user_id: str, access_token: str,
                                child_ids: list[str],
                                caption: str) -> str:
    """
    Step 3: Create one carousel container referencing all image containers.
    Returns the carousel container ID.
    """
    data = _post(
        f"{ig_user_id}/media",
        {
            "media_type":   "CAROUSEL",
            "children":     ",".join(child_ids),
            "caption":      caption,
            "access_token": access_token,
        }
    )
    return data["id"]


def _publish_container(ig_user_id: str, access_token: str,
                       container_id: str) -> str:
    """
    Step 4: Publish the carousel container. Returns the live media ID.
    """
    data = _post(
        f"{ig_user_id}/media_publish",
        {
            "creation_id":  container_id,
            "access_token": access_token,
        }
    )
    return data["id"]


# ── Public API ────────────────────────────────────────────────────────────────

def post_carousel(
    slide_paths:  list[Path],
    carousel:     dict,
    channel_key:  str,
    notify:       callable = None,
) -> str:
    """
    Full pipeline: render PNGs → imgbb → Instagram → returns media ID.

    slide_paths:  ordered list of PNG files from renderer.render_carousel()
    carousel:     carousel dict with caption, hashtags fields
    channel_key:  key into CHANNELS config (e.g. 'productivity')
    notify:       optional async-safe callback for progress messages
                  signature: notify(text: str) — called with status updates
                  In production this sends a Telegram message.

    Returns Instagram media ID on success.
    Raises RuntimeError on any failure — caller handles cleanup.
    """
    channel_cfg  = CHANNELS.get(channel_key, {})
    ig_user_id   = channel_cfg.get("ig_user_id", "")
    access_token = channel_cfg.get("ig_access_token", "")

    if not ig_user_id or ig_user_id == "dummy":
        raise RuntimeError(
            f"No IG credentials for channel '{channel_key}'. "
            f"Set {channel_key.upper()}_IG_USER_ID in .env"
        )
    if not access_token or access_token == "dummy":
        raise RuntimeError(
            f"No IG access token for channel '{channel_key}'. "
            f"Set {channel_key.upper()}_IG_ACCESS_TOKEN in .env"
        )

    def _log(msg: str):
        print(f"  {msg}")
        if notify:
            notify(msg)

    # Build caption
    tags     = " ".join(
        h if h.startswith("#") else f"#{h}"
        for h in carousel.get("hashtags", [])
    )
    caption  = f"{carousel.get('caption', '')}\n\n{tags}".strip()

    # Step 1 — upload slides to imgbb
    _log(f"Uploading {len(slide_paths)} slides to imgbb...")
    image_urls = upload_slides(slide_paths)
    _log(f"✓ {len(image_urls)} slides uploaded")

    # Step 2 — create one image container per slide
    _log("Creating image containers...")
    child_ids = []
    for i, url in enumerate(image_urls, 1):
        cid = _create_image_container(ig_user_id, access_token, url)
        child_ids.append(cid)
        _log(f"  slide {i}/{len(image_urls)} container: {cid}")
        if i < len(image_urls):
            time.sleep(ITEM_DELAY)

    # Step 3 — create carousel container
    _log("Creating carousel container...")
    carousel_id = _create_carousel_container(
        ig_user_id, access_token, child_ids, caption
    )
    _log(f"✓ Carousel container: {carousel_id}")
    time.sleep(PUBLISH_WAIT)

    # Step 4 — publish
    _log("Publishing to Instagram...")
    media_id = _publish_container(ig_user_id, access_token, carousel_id)
    _log(f"✓ Posted! Media ID: {media_id}")

    return media_id


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from datetime import datetime
    from renderer import render_carousel, delete_carousel

    print("instagram.py — standalone test")
    print("=" * 40)

    # Check credentials for productivity channel
    channel_key = "productivity"
    cfg         = CHANNELS.get(channel_key, {})
    ig_user_id  = cfg.get("ig_user_id", "")
    ig_token    = cfg.get("ig_access_token", "")

    if not ig_user_id or ig_user_id == "dummy":
        print(f"\n✗ PROD_IG_USER_ID not set in .env")
        print("  → Follow the PREREQUISITES in this file to get your IG User ID")
        sys.exit(1)

    if not ig_token or ig_token == "dummy":
        print(f"\n✗ PROD_IG_ACCESS_TOKEN not set in .env")
        print("  → Follow the PREREQUISITES in this file to get a long-lived token")
        sys.exit(1)

    print(f"✓ IG User ID:    {ig_user_id}")
    print(f"✓ Access token:  ...{ig_token[-8:]}")

    # Render a minimal 3-slide test carousel
    print("\n[1] Rendering 3-slide test carousel...")
    sample = {
        "hook":            "This is a test post — please ignore.",
        "slides":          ["Test slide body text.", "Another test slide."],
        "cta":             "Test complete — will delete shortly.",
        "caption":         "Automated test post from Instagram Content Agent.",
        "hashtags":        ["test"],
        "virality_score":  1,
        "content_pillar":  "systems",
    }
    date_str = datetime.now().strftime("%Y-%m-%d")
    paths    = render_carousel(sample, date_str, 99)
    print(f"    ✓ {len(paths)} slides rendered")

    # Run the full pipeline
    print("\n[2] Running full post pipeline...")
    try:
        media_id = post_carousel(
            slide_paths = paths,
            carousel    = sample,
            channel_key = channel_key,
        )
        print(f"\n✓ SUCCESS — Media ID: {media_id}")
        print(f"  Check your Instagram account for the test post.")
        print(f"  You can delete it manually from the Instagram app.")
    except Exception as e:
        print(f"\n✗ FAILED: {e}")
        sys.exit(1)
    finally:
        # Always clean up local PNGs
        delete_carousel(date_str, 99)
        print(f"\n[3] Local PNGs cleaned up")