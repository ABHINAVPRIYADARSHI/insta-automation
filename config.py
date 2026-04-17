"""
config.py
=========
Single source of truth for all configuration.
Every other module imports from here — no module reads .env or channels.json directly.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID      = int(os.getenv("ALLOWED_USER_ID", "0"))
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN")
WEBHOOK_URL          = os.getenv("WEBHOOK_URL")

# ── SSL ───────────────────────────────────────────────────────────────────────
SSL_CERT_PATH = os.getenv("SSL_CERT_PATH")
SSL_KEY_PATH  = os.getenv("SSL_KEY_PATH")

# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Optional legacy image-host key (no longer required by default flow)
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")

# Cloudinary (recommended media host for Instagram Graph API compatibility)
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY    = os.getenv("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()
CLOUDINARY_FOLDER     = os.getenv("CLOUDINARY_FOLDER", "instagram_agent").strip()

# ── Channels ──────────────────────────────────────────────────────────────────
def load_channels() -> dict:
    """
    Load channels.json and resolve each channel's secrets from env vars.
    Returns a dict of channel_key → resolved config.

    Example resolved config for 'productivity':
    {
        "name": "Productivity",
        "emoji": "📱",
        "default_niche": "Daily systems & routines",
        "default_tone": "Punchy & direct",
        "ig_user_id": "123456789",
        "ig_access_token": "EAAxxxx...",
        "google_sheet_id": "1BxiMVs0XRA..."
    }
    """
    raw_path = BASE_DIR / "channels.json"
    with open(raw_path, "r") as f:
        raw = json.load(f)

    resolved = {}
    for key, cfg in raw.items():
        resolved[key] = {
            "name":             cfg["name"],
            "emoji":            cfg["emoji"],
            "default_niche":    cfg["default_niche"],
            "default_tone":     cfg["default_tone"],
            "ig_user_id":       os.getenv(cfg["ig_user_id_env"], ""),
            "ig_access_token":  os.getenv(cfg["ig_access_token_env"], ""),
            "google_sheet_id":  os.getenv(cfg["google_sheet_id_env"], ""),
        }
    return resolved

CHANNELS = load_channels()

# ── Content options ───────────────────────────────────────────────────────────
NICHES = [
    "Daily systems & routines",
    "Deep work & focus",
    "Money habits & financial discipline",
    "Mental models & decision making",
    "Building income as a solo operator",
    "High performance morning routines",
    "Notion & productivity systems",
    "Mindset & self discipline",
    "Wealth building for beginners",
    "Content creation & personal brand",
]

TONES = [
    "Punchy & direct",
    "Calm & insightful",
    "Provocative & contrarian",
    "Educational & structured",
    "Motivational & energising",
    "Stoic & philosophical",
    "Data driven & analytical",
    "Conversational & relatable",
    "Bold & unapologetic",
    "Minimalist & precise",
]

# ── Paths ─────────────────────────────────────────────────────────────────────
FONTS_DIR  = BASE_DIR / "fonts"
FONT_PATH  = FONTS_DIR / "Poppins-Bold.ttf"
OUTPUT_DIR = BASE_DIR / "outputs"

# ── Validate on import ────────────────────────────────────────────────────────
def validate() -> list[str]:
    """
    Returns a list of missing/empty required config values.
    Call this at startup to catch misconfiguration early.
    """
    required = {
        "TELEGRAM_BOT_TOKEN":   TELEGRAM_BOT_TOKEN,
        "ALLOWED_USER_ID":      ALLOWED_USER_ID,
        "WEBHOOK_SECRET_TOKEN": WEBHOOK_SECRET_TOKEN,
        "WEBHOOK_URL":          WEBHOOK_URL,
        "GEMINI_API_KEY":       GEMINI_API_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    return missing


if __name__ == "__main__":
    # Quick sanity check
    missing = validate()
    if missing:
        print(f"⚠ Missing config: {', '.join(missing)}")
    else:
        print("✓ All required config present")

    print(f"\nChannels loaded: {list(CHANNELS.keys())}")
    for key, cfg in CHANNELS.items():
        ig_ok    = "✓" if cfg["ig_access_token"] not in ("", "dummy") else "✗ dummy"
        sheet_ok = "✓" if cfg["google_sheet_id"] else "✗ missing"
        print(f"  {cfg['emoji']} {cfg['name']}: IG={ig_ok}  Sheet={sheet_ok}")

    print(f"\nNiches: {len(NICHES)}")
    print(f"Tones:  {len(TONES)}")
    print(f"Font exists: {FONT_PATH.exists()}")
