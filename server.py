"""
server.py
=========
FastAPI webhook server. Receives Telegram updates, validates them,
and passes them to bot logic.

Runs on port 8443 with SSL using your existing Certbot certificates.
Telegram only supports ports 443, 80, 88, 8443 for webhooks — we use 8443
since 443 is already occupied by your signalling server.

STARTUP SEQUENCE
────────────────
1. Config validated — missing keys reported and server exits cleanly
2. Google Sheet headers verified for all configured channels
3. Telegram application initialised
4. FastAPI app starts on port 8443 with SSL
5. Webhook registered with Telegram automatically on first health check
   (or run register_webhook.py separately — see Phase 4)

ENDPOINTS
─────────
POST /webhook   — receives Telegram updates (secret token validated)
GET  /health    — liveness check, returns config and channel status

LOCAL TESTING WITH NGROK
─────────────────────────
Since Telegram needs a public HTTPS URL, test locally using ngrok:

  1. Install ngrok: https://ngrok.com/download
  2. Run your server locally WITHOUT ssl (set LOCAL_DEV=true in .env):
       python server.py
  3. In another terminal:
       ngrok http 8443
  4. Copy the ngrok HTTPS URL (e.g. https://abc123.ngrok.io)
  5. Run register_webhook.py with that URL
  6. Talk to your bot — messages flow: Telegram → ngrok → your server → bot logic

Set LOCAL_DEV=false (or remove it) on Oracle Cloud — SSL kicks in automatically.
"""

import os
import sys
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from telegram import Update
from telegram.ext import Application

from config import (
    TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET_TOKEN, WEBHOOK_URL,
    SSL_CERT_PATH, SSL_KEY_PATH, ALLOWED_USER_ID, CHANNELS,
    validate,
)
from sheets import ensure_all_headers

logging.basicConfig(
    format  = "%(asctime)s %(levelname)s %(name)s — %(message)s",
    level   = logging.INFO,
)
log = logging.getLogger(__name__)

LOCAL_DEV = os.getenv("LOCAL_DEV", "false").lower() == "true"


# ── Telegram Application (initialised once at startup) ────────────────────────

# bot_app is the python-telegram-bot Application instance.
# bot.py registers all handlers onto this instance.
# server.py owns the lifecycle — starts and stops it with the FastAPI app.
bot_app: Application = None


# ── Lifespan (startup + shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup and shutdown.
    Startup:  validate config → ensure sheet headers → init bot
    Shutdown: gracefully stop bot
    """
    global bot_app

    log.info("=" * 50)
    log.info("Instagram Content Agent — starting up")
    log.info("=" * 50)

    # 1. Validate config
    missing = validate()
    if missing:
        log.error(f"Missing required config: {', '.join(missing)}")
        log.error("Fix your .env file and restart.")
        sys.exit(1)
    log.info("✓ Config validated")

    # 2. Ensure Google Sheet headers for all channels
    log.info("Checking Google Sheet headers...")
    try:
        ensure_all_headers()
    except Exception as e:
        log.warning(f"Sheet header check failed: {e} — continuing anyway")

    # 3. Build Telegram Application
    log.info("Initialising Telegram bot...")
    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register all bot handlers (imported here to avoid circular imports)
    from bot import register_handlers
    register_handlers(bot_app)
    log.info("✓ Bot handlers registered")

    # 4. Initialise and start the bot (no polling — webhook only)
    await bot_app.initialize()
    await bot_app.start()
    log.info("✓ Bot started")

    log.info(f"✓ Allowed user ID: {ALLOWED_USER_ID}")
    log.info(f"✓ Channels: {list(CHANNELS.keys())}")
    log.info(f"✓ Webhook URL: {WEBHOOK_URL}")
    log.info(f"✓ Local dev mode: {LOCAL_DEV}")
    log.info("Ready — waiting for Telegram updates")

    yield   # server is running

    # Shutdown
    log.info("Shutting down...")
    await bot_app.stop()
    await bot_app.shutdown()
    log.info("✓ Bot stopped cleanly")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title    = "Instagram Content Agent",
    version  = "1.0.0",
    docs_url = None,    # disable swagger UI in production
    lifespan = lifespan,
)


# ── Webhook endpoint ──────────────────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request) -> Response:
    """
    Receives all Telegram updates.

    Security:
    - Validates X-Telegram-Bot-Api-Secret-Token header on every request
    - Any request without the correct token gets 403 — Telegram never sees
      our bot logic, neither does any scanner probing the endpoint
    """
    # Validate secret token
    incoming_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if incoming_token != WEBHOOK_SECRET_TOKEN:
        log.warning(f"Rejected webhook request — bad secret token")
        raise HTTPException(status_code=403, detail="Forbidden")

    # Parse update
    try:
        body   = await request.json()
        update = Update.de_json(body, bot_app.bot)
    except Exception as e:
        log.error(f"Failed to parse Telegram update: {e}")
        return Response(status_code=200)   # always return 200 to Telegram

    # Process update asynchronously — don't block the webhook response
    asyncio.create_task(
        bot_app.process_update(update)
    )

    # Telegram requires a 200 response quickly — return immediately
    return Response(status_code=200)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> JSONResponse:
    """
    Liveness check. Returns config status and channel info.
    Useful for verifying deployment is alive on Oracle Cloud.
    """
    channel_status = {
        key: {
            "name":      cfg["name"],
            "ig_ready":  bool(cfg.get("ig_access_token"))
                         and cfg.get("ig_access_token") != "dummy",
            "sheet_ready": bool(cfg.get("google_sheet_id"))
                           and cfg.get("google_sheet_id") != "dummy",
        }
        for key, cfg in CHANNELS.items()
    }
    return JSONResponse({
        "status":       "ok",
        "webhook_url":  WEBHOOK_URL,
        "local_dev":    LOCAL_DEV,
        "channels":     channel_status,
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if LOCAL_DEV:
        # Local dev — no SSL, plain HTTP on 8443
        # Use with ngrok: ngrok http 8443
        log.info("Starting in LOCAL DEV mode (no SSL) on port 8443")
        uvicorn.run(
            "server:app",
            host    = "0.0.0.0",
            port    = 8443,
            reload  = False,
        )
    else:
        # Production — SSL on port 8443 using Certbot certs
        if not SSL_CERT_PATH or not SSL_KEY_PATH:
            log.error("SSL_CERT_PATH and SSL_KEY_PATH must be set in .env for production")
            sys.exit(1)
        log.info(f"Starting in PRODUCTION mode with SSL on port 8443")
        log.info(f"Cert: {SSL_CERT_PATH}")
        uvicorn.run(
            "server:app",
            host        = "0.0.0.0",
            port        = 8443,
            ssl_certfile = SSL_CERT_PATH,
            ssl_keyfile  = SSL_KEY_PATH,
            reload      = False,
        )