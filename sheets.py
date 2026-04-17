"""
sheets.py
=========
Logs every carousel lifecycle event to a Google Sheet.
One row per carousel per day. Status updated in place as lifecycle progresses.

Lifecycle:  generated → approved / rejected → posted

SHEET COLUMNS
─────────────
A  Date
B  Carousel #
C  Channel
D  Content pillar
E  Niche
F  Tone
G  Virality score
H  Hook
I  Slides              (pipe-separated)
J  CTA
K  Caption
L  Hashtags
M  Status              generated | approved | rejected | posted
N  Instagram ID        filled after posting
O  Follower count      fill manually once a week
P  Notes               optional free text

PREREQUISITES
─────────────
1. Google Cloud project with Sheets API enabled
2. Service account JSON key saved as google_creds.json in project root
3. Each Google Sheet shared with the service account email as Editor
4. Sheet IDs set in .env as MAN_WOMAN_GOOGLE_SHEET_ID / WEALTH_MINISTER_GOOGLE_SHEET_ID

Imported by bot.py. Run as __main__ for standalone testing.
"""

from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import BASE_DIR, CHANNELS

# ── Constants ─────────────────────────────────────────────────────────────────

CREDS_FILE = BASE_DIR / "google_creds.json"
SCOPES     = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_TAB  = "Content Log"

HEADERS = [
    "Date", "Carousel #", "Channel", "Content pillar",
    "Niche", "Tone", "Virality score",
    "Hook", "Slides", "CTA", "Caption", "Hashtags",
    "Status", "Instagram ID", "Follower count", "Notes",
]

# Column indices (0-based) for targeted updates


# ── Client ────────────────────────────────────────────────────────────────────

def _service():
    creds = service_account.Credentials.from_service_account_file(
        str(CREDS_FILE), scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _sheet_range(a1_range: str) -> str:
    """Return a safe A1 range with sheet tab quoted for names with spaces."""
    escaped_tab = SHEET_TAB.replace("'", "''")
    return f"'{escaped_tab}'!{a1_range}"


def _ensure_sheet_tab(svc, sheet_id: str) -> None:
    """Create SHEET_TAB if it does not already exist."""
    meta = svc.spreadsheets().get(
        spreadsheetId=sheet_id,
        fields="sheets(properties(title))",
    ).execute()
    titles = {
        s.get("properties", {}).get("title", "")
        for s in meta.get("sheets", [])
    }
    if SHEET_TAB in titles:
        return

    svc.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={
            "requests": [
                {"addSheet": {"properties": {"title": SHEET_TAB}}}
            ]
        },
    ).execute()


# ── Sheet setup ───────────────────────────────────────────────────────────────

def ensure_headers(sheet_id: str) -> None:
    """
    Write header row if sheet is empty or headers don't match.
    Safe to call on every startup.
    """
    svc    = _service()
    _ensure_sheet_tab(svc, sheet_id)
    result = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=_sheet_range("A1:P1")
    ).execute()
    existing = result.get("values", [[]])[0]
    if existing != HEADERS:
        svc.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=_sheet_range("A1"),
            valueInputOption="RAW",
            body={"values": [HEADERS]}
        ).execute()


def ensure_all_headers() -> None:
    """Call ensure_headers for every configured channel on startup."""
    for key, cfg in CHANNELS.items():
        sheet_id = cfg.get("google_sheet_id", "")
        if sheet_id and sheet_id not in ("dummy", ""):
            try:
                ensure_headers(sheet_id)
                print(f"  ✓ Sheet headers OK: {cfg['name']}")
            except Exception as e:
                print(f"  ✗ Sheet error ({cfg['name']}): {e}")


# ── Row finder ────────────────────────────────────────────────────────────────

def _find_row(svc, sheet_id: str, date_str: str, carousel_index: int) -> int | None:
    """
    Find the 1-based row number for a given date + carousel index.
    Returns None if not found.
    """
    result = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=_sheet_range("A:B")
    ).execute()
    rows = result.get("values", [])
    for i, row in enumerate(rows):
        if (len(row) >= 2
                and row[0] == date_str
                and row[1] == str(carousel_index)):
            return i + 1   # 1-based
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def log_carousel(
    carousel:       dict,
    carousel_index: int,
    channel_key:    str,
    niche:          str,
    tone:           str,
    status:         str,
    date_str:       str = None,
) -> None:
    """
    Append one row for a carousel. Call this when status = 'generated'.
    Subsequent status changes use update_status() instead.

    status: 'generated' | 'approved' | 'rejected' | 'posted'
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    channel_cfg = CHANNELS.get(channel_key, {})
    sheet_id    = channel_cfg.get("google_sheet_id", "")
    if not sheet_id or sheet_id == "dummy":
        print(f"  ⚠ Skipping sheet log — no sheet ID for channel '{channel_key}'")
        return

    slides_str   = " | ".join(carousel.get("slides", []))
    hashtags_str = " ".join(
        h if h.startswith("#") else f"#{h}"
        for h in carousel.get("hashtags", [])
    )

    row = [
        date_str,
        str(carousel_index),
        channel_cfg.get("name", channel_key),
        carousel.get("content_pillar", ""),
        niche,
        tone,
        str(carousel.get("virality_score", "")),
        carousel.get("hook", ""),
        slides_str,
        carousel.get("cta", ""),
        carousel.get("caption", ""),
        hashtags_str,
        status,
        "",   # Instagram ID — empty until posted
        "",   # Follower count — manual
        "",   # Notes — manual
    ]

    svc = _service()
    svc.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=_sheet_range("A:P"),
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()


def update_status(
    channel_key:     str,
    date_str:        str,
    carousel_index:  int,
    status:          str,
    instagram_id:    str = "",
) -> None:
    """
    Update the status (and optionally Instagram ID) of an existing row.
    Used for: generated → approved, generated → rejected, approved → posted.
    """
    channel_cfg = CHANNELS.get(channel_key, {})
    sheet_id    = channel_cfg.get("google_sheet_id", "")
    if not sheet_id or sheet_id == "dummy":
        return

    svc     = _service()
    row_num = _find_row(svc, sheet_id, date_str, carousel_index)
    if row_num is None:
        print(f"  ⚠ Row not found: {date_str} carousel {carousel_index}")
        return

    # Update columns M (status) and N (instagram_id) in one call
    svc.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=_sheet_range(f"M{row_num}:N{row_num}"),
        valueInputOption="RAW",
        body={"values": [[status, instagram_id]]}
    ).execute()


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("sheets.py — standalone test")
    print("=" * 40)

    # Check creds file exists
    if not CREDS_FILE.exists():
        print(f"\n✗ google_creds.json not found at {CREDS_FILE}")
        print("  → Download your service account JSON from Google Cloud Console")
        print("  → Rename it to google_creds.json and place it in the project root")
        sys.exit(1)

    print(f"✓ google_creds.json found")

    # Check at least one real sheet ID is configured
    real_channels = {
        k: v for k, v in CHANNELS.items()
        if v.get("google_sheet_id") not in ("", "dummy", None)
    }
    if not real_channels:
        print("\n✗ No real Google Sheet IDs configured in .env")
        print("  → Set MAN_WOMAN_GOOGLE_SHEET_ID and/or WEALTH_MINISTER_GOOGLE_SHEET_ID")
        sys.exit(1)

    # Test with first real channel
    test_channel_key = list(real_channels.keys())[0]
    test_channel     = real_channels[test_channel_key]
    sheet_id         = test_channel["google_sheet_id"]
    print(f"\nTesting with channel: {test_channel['name']} (sheet: {sheet_id[:20]}...)")

    # Step 1: ensure headers
    print("\n[1] Writing headers...")
    ensure_headers(sheet_id)
    print("    ✓ Headers OK")

    # Step 2: log a test carousel as 'generated'
    sample = {
        "hook":            "This is a test hook slide.",
        "slides":          ["Test slide 1", "Test slide 2", "Test slide 3"],
        "cta":             "Follow for more.",
        "caption":         "Test caption for smoke test.",
        "hashtags":        ["test", "productivity"],
        "virality_score":  7,
        "content_pillar":  "systems",
    }
    date_str = datetime.now().strftime("%Y-%m-%d")

    print("\n[2] Logging carousel as 'generated'...")
    log_carousel(
        carousel       = sample,
        carousel_index = 99,          # use 99 to avoid collision with real data
        channel_key    = test_channel_key,
        niche          = "Daily systems & routines",
        tone           = "Punchy & direct",
        status         = "generated",
        date_str       = date_str,
    )
    print("    ✓ Row appended")

    # Step 3: update to 'approved'
    print("\n[3] Updating status → 'approved'...")
    update_status(test_channel_key, date_str, 99, "approved")
    print("    ✓ Status updated")

    # Step 4: update to 'posted' with a fake IG ID
    print("\n[4] Updating status → 'posted' with fake Instagram ID...")
    update_status(test_channel_key, date_str, 99, "posted", "17841234567890123")
    print("    ✓ Status + Instagram ID updated")

    print(f"\n✓ All tests passed.")
    print(f"  Open your Google Sheet and verify row with Carousel # = 99")
    print(f"  Sheet: https://docs.google.com/spreadsheets/d/{sheet_id}")
