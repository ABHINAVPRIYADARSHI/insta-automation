"""
config.py
=========
Single source of truth for all configuration.
Every other module imports from here - no module reads .env or channels.json directly.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# SSL
SSL_CERT_PATH = os.getenv("SSL_CERT_PATH")
SSL_KEY_PATH = os.getenv("SSL_KEY_PATH")

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Cloudinary (recommended media host for Instagram Graph API compatibility)
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()
CLOUDINARY_FOLDER = os.getenv("CLOUDINARY_FOLDER", "instagram_agent").strip()


# Channels
def load_channels() -> dict:
    """
    Load channels.json and resolve each channel's secrets from env vars.
    Returns a dict of channel_key -> resolved config.

    Example resolved config for 'man_woman':
    {
        "name": "man_woman",
        "emoji": "<emoji>",
        "default_niche": "...",
        "default_tone": "...",
        "ig_user_id": "123456789",
        "ig_access_token": "EAAxxxx...",
        "google_sheet_id": "1BxiMVs0XRA..."
    }
    """
    raw_path = BASE_DIR / "channels.json"
    with open(raw_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    resolved = {}
    for key, cfg in raw.items():
        resolved[key] = {
            "name": cfg["name"],
            "emoji": cfg["emoji"],
            "default_niche": cfg["default_niche"],
            "default_tone": cfg["default_tone"],
            "ig_user_id": os.getenv(cfg["ig_user_id_env"], ""),
            "ig_access_token": os.getenv(cfg["ig_access_token_env"], ""),
            "google_sheet_id": os.getenv(cfg["google_sheet_id_env"], ""),
        }
    return resolved


CHANNELS = load_channels()

# Content options
# 10 niches per channel key from channels.json.
CHANNEL_NICHES = {
    # Channel key: "finance" -> channel name: "the_wealth_minister"
    "finance": [
        # "Daily systems & routines",
        # "Deep work & focus",
        # "Money habits & financial discipline",
        # "Mental models & decision making",
        # "Building income as a solo operator",
        # "High performance morning routines",
        # "Notion & productivity systems",
        # "Mindset & self discipline",
        # "Wealth building for beginners",
        # "Content creation & personal brand",
        "The 5 AM Lie (What Rich People Actually Do)- Debunking morning routine myths, real billionaire habits, contrarian truth",
        "Why Saving Money Keeps You Poor- Inflation reality, asset accumulation vs. hoarding cash, velocity of money",
        "The $10K/Month Solo Business Blueprint- Specific income goal, one-person leverage, skill stacking monetization",
        "Money Mistakes Keeping You Broke at 30- Age-specific urgency, lifestyle inflation traps, compound interest lost",
        "How to Think Like a Millionaire (Mental Models)- Inversion thinking, second-order effects, opportunity cost framework",
        "The First $100K is Hell (Then It's Easy)- Charlie Munger quote angle, exponential growth psychology, breakthrough threshold",
        "Passive Income Myths That Waste Your Time- Debunking gurus, real asset classes, effort vs. return analysis",
        "Why You'll Never Get Rich Working 9-5- Time-for-money ceiling, ownership vs. employment, leverage necessity",
        "The Discipline Paradox (Less Effort, More Results)- Systems over willpower, environment design, atomic habits for wealth",
        "3 Books That Made Me $500K- Specific ROI claim, knowledge application, tangible transformation story",
    ],
    # Channel key: "man_woman" -> channel name: "man_woman"
    "man_woman": [
        "Why She Loses Interest After You Open Up - Vulnerability paradox, emotional timing, the confession trap",
        "The 3 Texts That Make Them Obsess - Specific psychology, scarcity in messaging, dopamine loops",
        "What Silence Does to Their Brain - No contact psychology, the void you leave, anxious attachment triggers",
        "Signs They're Testing You (And How to Pass) - Shit tests, loyalty checks, power plays decoded",
        "Why Good Guys Finish Last (Science) - Niceness vs. kindness, predictability kills desire, edge theory",
        "The First 7 Seconds: Make or Break - Instant attraction, presence hacks, primal assessment",
        "Dark Psychology: The Push-Pull Method - Hot-cold dynamics, intermittent reinforcement, addiction mechanics",
        "Why They Want What They Can't Have - Forbidden fruit effect, chase reversal, scarcity mindset",
        "Body Language That Screams Confidence - Power poses, space dominance, non-verbal seduction (specific examples)",
        "The Biggest Turn-Off (You're Doing It) - Over-availability, neediness signals, desperation markers",
    ],
}

# Shared across channels.
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

def get_niches_for_channel(channel_key: str) -> list[str]:
    """Return channel-specific niches. Raise on unknown channel key."""
    if channel_key not in CHANNEL_NICHES:
        known = ", ".join(CHANNEL_NICHES.keys())
        raise KeyError(
            f"Unknown channel key '{channel_key}' for niches. Known keys: {known}"
        )
    return CHANNEL_NICHES[channel_key]


# Paths
FONTS_DIR = BASE_DIR / "fonts"
FONT_PATH = FONTS_DIR / "Poppins-Bold.ttf"
OUTPUT_DIR = BASE_DIR / "outputs"


# Validate on import
def validate() -> list[str]:
    """
    Returns a list of missing/empty required config values.
    Call this at startup to catch misconfiguration early.
    """
    required = {
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "ALLOWED_USER_ID": ALLOWED_USER_ID,
        "WEBHOOK_SECRET_TOKEN": WEBHOOK_SECRET_TOKEN,
        "WEBHOOK_URL": WEBHOOK_URL,
        "GEMINI_API_KEY": GEMINI_API_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    return missing


if __name__ == "__main__":
    # Quick sanity check
    missing = validate()
    if missing:
        print(f"Missing config: {', '.join(missing)}")
    else:
        print("All required config present")

    print(f"\nChannels loaded: {list(CHANNELS.keys())}")
    for key, cfg in CHANNELS.items():
        ig_ok = "ok" if cfg["ig_access_token"] not in ("", "dummy") else "dummy"
        sheet_ok = "ok" if cfg["google_sheet_id"] else "missing"
        print(f"  {cfg['emoji']} {cfg['name']}: IG={ig_ok}  Sheet={sheet_ok}")

    print("\nNiches by channel:")
    for key, niches in CHANNEL_NICHES.items():
        print(f"  {key}: {len(niches)}")
    print(f"Tones: {len(TONES)}")
    print(f"Font exists: {FONT_PATH.exists()}")
