# Instagram Automation

Python automation project for generating carousel content, uploading slides, posting to Instagram, and logging lifecycle events to Google Sheets.

## Features
- Telegram + FastAPI webhook server scaffold
- Instagram carousel posting pipeline via Graph API
- Slide hosting via Cloudinary
- Google Sheets logging for generated/approved/rejected/posted status

## Project Structure
- `server.py`: FastAPI webhook server entry point
- `bot.py`: Telegram handlers registration stub
- `instagram.py`: Instagram posting pipeline
- `cloudinary_host.py`: Upload local slide images and return public URLs
- `sheets.py`: Google Sheets logging and status updates
- `renderer.py`: Carousel image rendering
- `config.py`: Centralized config + channel resolution from env
- `channels.json`: Channel definitions and env key mapping

## Requirements
- Python 3.10+ (3.11+ recommended)
- Telegram bot token
- Meta app + Instagram Graph API credentials
- cloudinary API key
- Google service account credentials and shared sheets

## Setup
1. Create and activate virtual environment:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. Install dependencies:
```powershell
pip install -r requirements.txt
```

3. Create `.env` in project root and fill required values:
- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_USER_ID`
- `WEBHOOK_SECRET_TOKEN`
- `WEBHOOK_URL`
- `GEMINI_API_KEY`
- `CLOUDINARY_API_KEY`
- `MAN_WOMAN_IG_USER_ID`
- `MAN_WOMAN_IG_ACCESS_TOKEN`
- `WEALTH_MINISTER_IG_USER_ID`
- `WEALTH_MINISTER_IG_ACCESS_TOKEN`
- `MAN_WOMAN_GOOGLE_SHEET_ID`
- `WEALTH_MINISTER_GOOGLE_SHEET_ID`
- `SSL_CERT_PATH` and `SSL_KEY_PATH` (production)

4. Place Google credentials file in project root:
- `google_creds.json`

5. Share each Google Sheet with your service account email as Editor.

## Run
### Test Sheets integration
```powershell
python sheets.py
```

### Test Instagram posting flow
```powershell
python instagram.py
```

### Start webhook server
```powershell
python server.py
```

## Notes
- `LOCAL_DEV=true` in `.env` runs server without SSL for local ngrok testing.
- Keep `.env` and Google credential files private (already ignored by `.gitignore`).
