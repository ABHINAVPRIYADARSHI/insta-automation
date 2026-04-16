"""
bot.py — Instagram Content Agent
Complete implementation: Steps 8-12.

Step 8:  session, guard, channel selection, settings panel
Step 9:  Gemini intent parsing + generate flow
Step 10: carousel approval — ✅ ❌ 🔄 buttons
Step 11: manual post command — render → upload → post → log → delete
Step 12: auto-post mode — generate triggers full pipeline immediately
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters,
)

from config import ALLOWED_USER_ID, CHANNELS, NICHES, TONES, GEMINI_API_KEY
from renderer import render_carousel, delete_carousel
from instagram import post_carousel
from sheets import log_carousel, update_status

log = logging.getLogger(__name__)
_client = genai.Client(api_key=GEMINI_API_KEY)


# ── Prompts ───────────────────────────────────────────────────────────────────

CONTENT_PROMPT = """You are an expert Instagram content strategist for the niche "systems for ambitious people" — productivity, money habits, mental models, solo operator income.

Generate carousel concepts. Each must have:
- hook: under 10 words, scroll-stopping, slightly provocative or curiosity-driven
- slides: 4-6 body slides, max 15 words each, one punchy insight per slide
- cta: under 12 words, drives saves / shares / follows
- caption: 2-3 sentences, conversational, ends with a question
- hashtags: 8-10 tags, mix niche-specific and broad reach
- virality_score: 1-10
- content_pillar: systems | money | mindset | focus | income

Respond ONLY with a valid JSON array. No preamble, no markdown fences. Pure JSON."""

INTENT_PROMPT = """You are a concise assistant inside a Telegram bot that manages Instagram content.

Parse the user's message and return a JSON action object.

ACTIONS:
  generate   — generate carousels (optional: count, niche, tone, topic)
  set_niche  — set niche from the valid list
  set_tone   — set tone from the valid list
  set_topic  — set a custom angle string
  post       — post all approved carousels
  status     — show approval status
  help       — show help
  chat       — conversational reply, no action needed

VALID NICHES: Daily systems & routines, Deep work & focus, Money habits & financial discipline, Mental models & decision making, Building income as a solo operator, High performance morning routines, Notion & productivity systems, Mindset & self discipline, Wealth building for beginners, Content creation & personal brand

VALID TONES: Punchy & direct, Calm & insightful, Provocative & contrarian, Educational & structured, Motivational & energising, Stoic & philosophical, Data driven & analytical, Conversational & relatable, Bold & unapologetic, Minimalist & precise

Respond ONLY with JSON. Examples:
{"action":"generate","count":5,"reply":"Generating 5 carousels..."}
{"action":"generate","count":5,"niche":"Deep work & focus","reply":"Generating on deep work..."}
{"action":"set_niche","niche":"Deep work & focus","reply":"Niche set to Deep work & focus."}
{"action":"set_topic","topic":"morning routines that don't suck","reply":"Topic set."}
{"action":"post","reply":"Posting approved carousels..."}
{"action":"status","reply":""}
{"action":"chat","reply":"<your short friendly reply>"}

Keep 'reply' to 1-2 sentences. Never use markdown in reply."""


# ── Session ───────────────────────────────────────────────────────────────────

sessions: dict[int, dict] = {}

def get_session(uid: int) -> dict:
    if uid not in sessions:
        first_key = list(CHANNELS.keys())[0]
        cfg       = CHANNELS[first_key]
        sessions[uid] = {
            "channel":   first_key,
            "niche":     cfg["default_niche"],
            "tone":      cfg["default_tone"],
            "topic":     "",
            "carousels": [],
            "approval":  {},
            "auto_post": True,
            "date_str":  datetime.now().strftime("%Y-%m-%d"),
        }
    return sessions[uid]


# ── Guard ─────────────────────────────────────────────────────────────────────

def is_allowed(uid: int) -> bool:
    return uid == ALLOWED_USER_ID


# ── Gemini calls ──────────────────────────────────────────────────────────────

def gemini_generate(niche: str, tone: str, topic: str, count: int) -> list[dict]:
    prompt = f"Niche: {niche}\nTone: {tone}"
    if topic:
        prompt += f"\nAngle: {topic}"
    prompt += f"\n\nGenerate {count} carousel(s). Return JSON array with exactly {count} object(s)."
    resp   = _client.models.generate_content(
        model    = "gemini-3-flash-preview",
        contents = prompt,
        config   = types.GenerateContentConfig(system_instruction=CONTENT_PROMPT),
    )
    clean  = resp.text.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(clean)
    return parsed if isinstance(parsed, list) else [parsed]


def gemini_intent(user_msg: str, session: dict) -> dict:
    state  = (
        f"channel={session['channel']} niche={session['niche']} "
        f"tone={session['tone']} topic={session['topic'] or 'none'} "
        f"carousels={len(session['carousels'])} "
        f"approved={sum(1 for v in session['approval'].values() if v == 'approve')}"
    )
    resp   = _client.models.generate_content(
        model    = "gemini-3-flash-preview",
        contents = f"STATE: {state}\nUSER: {user_msg}",
        config   = types.GenerateContentConfig(system_instruction=INTENT_PROMPT),
    )
    clean  = resp.text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


# ── Keyboards ─────────────────────────────────────────────────────────────────

def channel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{cfg['emoji']} {cfg['name']}",
                              callback_data=f"channel:{key}")]
        for key, cfg in CHANNELS.items()
    ])

def niche_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(NICHES), 2):
        row = [InlineKeyboardButton(NICHES[i], callback_data=f"niche:{i}")]
        if i + 1 < len(NICHES):
            row.append(InlineKeyboardButton(NICHES[i+1], callback_data=f"niche:{i+1}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def tone_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(TONES), 2):
        row = [InlineKeyboardButton(TONES[i], callback_data=f"tone:{i}")]
        if i + 1 < len(TONES):
            row.append(InlineKeyboardButton(TONES[i+1], callback_data=f"tone:{i+1}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def settings_keyboard(s: dict) -> InlineKeyboardMarkup:
    cfg        = CHANNELS[s["channel"]]
    auto_label = "🟢 Auto-post ON" if s["auto_post"] else "🔴 Auto-post OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📱 Channel: {cfg['emoji']} {cfg['name']}", callback_data="open:channel")],
        [InlineKeyboardButton(f"🎯 Niche: {s['niche']}",                   callback_data="open:niche")],
        [InlineKeyboardButton(f"🎨 Tone: {s['tone']}",                     callback_data="open:tone")],
        [InlineKeyboardButton(auto_label,                                   callback_data="toggle:autopost")],
    ])

def carousel_keyboard(idx: int, total: int) -> InlineKeyboardMarkup:
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("← Prev", callback_data=f"nav:{idx-1}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton("Next →", callback_data=f"nav:{idx+1}"))
    rows = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{idx}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject:{idx}"),
        InlineKeyboardButton("🔄 Regen",   callback_data=f"regen:{idx}"),
    ]]
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)


# ── Formatters ────────────────────────────────────────────────────────────────

def session_header(s: dict) -> str:
    cfg = CHANNELS[s["channel"]]
    return (
        f"{cfg['emoji']} *{cfg['name']}*  |  "
        f"{s['niche']}  |  "
        f"{'🟢 Auto' if s['auto_post'] else '🔴 Manual'}"
    )

def fmt_carousel(idx: int, c: dict, approval: dict) -> str:
    icon = {"approve": "✅", "reject": "❌"}.get(approval.get(idx), "⬜")
    return (
        f"{icon} *{idx+1}. [{c['content_pillar'].upper()} · {c['virality_score']}/10]*\n"
        f"_{c['hook']}_\n"
        f"CTA: {c['cta']}"
    )

def fmt_slides(c: dict) -> str:
    lines = (
        [f"🖤 *HOOK:* {c['hook']}"]
        + [f"Slide {i+2}: {sl}" for i, sl in enumerate(c["slides"])]
        + [f"📣 *CTA:* {c['cta']}"]
    )
    return (
        "\n\n".join(lines)
        + f"\n\n📝 {c['caption']}\n\n{' '.join(c['hashtags'])}"
    )


# ── Core: generate + post pipelines ──────────────────────────────────────────

async def run_generate(s: dict, count: int, bot, chat_id: int) -> None:
    """
    Generate `count` carousels, log to Sheets, show first one.
    If auto_post is ON, immediately run run_post after generation.
    """
    s["approval"]  = {}
    s["carousels"] = []
    s["date_str"]  = datetime.now().strftime("%Y-%m-%d")

    await bot.send_message(chat_id,
        f"{session_header(s)}\n\nGenerating {count} carousels...",
        parse_mode="Markdown")

    try:
        carousels = gemini_generate(
            s["niche"], s["tone"], s["topic"], count
        )
    except Exception as e:
        await bot.send_message(chat_id, f"✗ Gemini error: {e}")
        return

    s["carousels"] = carousels

    # log all as generated
    for i, c in enumerate(carousels):
        try:
            log_carousel(c, i+1, s["channel"], s["niche"], s["tone"],
                         "generated", s["date_str"])
        except Exception as e:
            log.warning(f"Sheet log failed for carousel {i+1}: {e}")

    if s["auto_post"]:
        # mark all approved automatically
        for i in range(len(carousels)):
            s["approval"][i] = "approve"
        await bot.send_message(chat_id,
            f"✓ {len(carousels)} carousels generated. Auto-posting all...")
        await run_post(s, bot, chat_id)
    else:
        await bot.send_message(chat_id,
            f"✓ {len(carousels)} carousels ready. Showing first:",
            parse_mode="Markdown")
        await bot.send_message(
            chat_id,
            f"{session_header(s)}\n\n{fmt_carousel(0, carousels[0], s['approval'])}",
            parse_mode   = "Markdown",
            reply_markup = carousel_keyboard(0, len(carousels)),
        )


async def run_post(s: dict, bot, chat_id: int) -> None:
    """
    For every approved carousel: render → upload → post → log → delete.
    Reports success or failure per carousel.
    """
    approved = [(i, s["carousels"][i])
                for i, v in s["approval"].items() if v == "approve"]

    if not approved:
        await bot.send_message(chat_id,
            "No approved carousels. Approve some first.")
        return

    await bot.send_message(chat_id,
        f"Posting {len(approved)} approved carousel(s)...")

    for i, c in approved:
        paths: list[Path] = []
        try:
            await bot.send_message(chat_id, f"  [{i+1}] Rendering slides...")
            paths    = render_carousel(c, s["date_str"], i+1)

            await bot.send_message(chat_id, f"  [{i+1}] Uploading & posting...")
            media_id = post_carousel(paths, c, s["channel"])

            try:
                update_status(s["channel"], s["date_str"], i+1,
                              "posted", media_id)
            except Exception as e:
                log.warning(f"Sheet update failed after posting: {e}")

            await bot.send_message(chat_id,
                f"  ✓ Carousel {i+1} posted — ID: `{media_id}`",
                parse_mode="Markdown")

        except Exception as e:
            await bot.send_message(chat_id,
                f"  ✗ Carousel {i+1} failed: {e}")
            log.error(f"Post failed for carousel {i+1}: {e}")

        finally:
            # always delete local PNGs — success or failure
            if paths:
                delete_carousel(s["date_str"], i+1)

    await bot.send_message(chat_id, "Done.")


# ── Action executor ───────────────────────────────────────────────────────────

async def execute(action: dict, s: dict, update: Update) -> None:
    msg     = update.message
    bot     = msg.get_bot()
    chat_id = msg.chat_id
    reply   = action.get("reply", "")
    name    = action.get("action", "chat")

    if name == "generate":
        if action.get("niche") in NICHES:
            s["niche"] = action["niche"]
        if action.get("tone") in TONES:
            s["tone"] = action["tone"]
        if action.get("topic"):
            s["topic"] = action["topic"]
        count = int(action.get("count", 5))
        await run_generate(s, count, bot, chat_id)

    elif name == "set_niche":
        niche = action.get("niche", "")
        if niche in NICHES:
            s["niche"] = niche
            await msg.reply_text(reply or f"Niche set to: {niche}")
        else:
            await msg.reply_text("Unknown niche. Use /settings to pick.")

    elif name == "set_tone":
        tone = action.get("tone", "")
        if tone in TONES:
            s["tone"] = tone
            await msg.reply_text(reply or f"Tone set to: {tone}")
        else:
            await msg.reply_text("Unknown tone. Use /settings to pick.")

    elif name == "set_topic":
        s["topic"] = action.get("topic", "")
        await msg.reply_text(reply or f"Topic set: {s['topic']}")

    elif name == "post":
        if reply:
            await msg.reply_text(reply)
        await run_post(s, bot, chat_id)

    elif name == "status":
        if not s["carousels"]:
            await msg.reply_text("No carousels yet. Say 'generate' to start.")
            return
        lines = [fmt_carousel(i, c, s["approval"])
                 for i, c in enumerate(s["carousels"])]
        approved = sum(1 for v in s["approval"].values() if v == "approve")
        await msg.reply_text(
            "\n\n".join(lines) + f"\n\n*{approved}/{len(s['carousels'])} approved*",
            parse_mode="Markdown"
        )

    elif name in ("help", "chat"):
        await msg.reply_text(reply or _help_text())

    else:
        if reply:
            await msg.reply_text(reply)


def _help_text() -> str:
    return (
        "*Instagram Content Agent*\n\n"
        "Talk naturally or use commands:\n\n"
        "• _generate 5 carousels on deep work_\n"
        "• _approve 1 and 3_\n"
        "• _post the approved ones_\n"
        "• _show status_\n\n"
        "/settings — niche, tone, channel, auto-post\n"
        "/channel  — switch channel\n"
        "/generate — generate 5 carousels\n"
        "/post     — post approved carousels\n"
        "/status   — approval overview"
    )


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("Unauthorised.")
        return
    get_session(uid)
    await update.message.reply_text(
        "👋 *Instagram Content Agent*\n\nSelect a channel to work with:",
        parse_mode   = "Markdown",
        reply_markup = channel_keyboard(),
    )

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    s = get_session(uid)
    await update.message.reply_text(
        f"{session_header(s)}\n\n*Settings*",
        parse_mode   = "Markdown",
        reply_markup = settings_keyboard(s),
    )

async def cmd_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    await update.message.reply_text(
        "Select a channel:",
        reply_markup = channel_keyboard(),
    )

async def cmd_generate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    s   = get_session(uid)
    await run_generate(s, 5, update.message.get_bot(), update.message.chat_id)

async def cmd_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    s = get_session(uid)
    await run_post(s, update.message.get_bot(), update.message.chat_id)

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    s = get_session(uid)
    await execute({"action": "status"}, s, update)


# ── Natural language handler ──────────────────────────────────────────────────

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    s = get_session(uid)
    try:
        action = gemini_intent(update.message.text.strip(), s)
    except Exception as e:
        await update.message.reply_text(f"Could not parse that: {e}")
        return
    await execute(action, s, update)


# ── Callback handler ──────────────────────────────────────────────────────────

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id
    if not is_allowed(uid):
        await q.answer("Unauthorised.")
        return
    await q.answer()
    s    = get_session(uid)
    data = q.data

    # ── Settings callbacks ────────────────────────────────────────────────────
    if data.startswith("channel:"):
        key        = data.split(":", 1)[1]
        cfg        = CHANNELS[key]
        s["channel"]   = key
        s["niche"]     = cfg["default_niche"]
        s["tone"]      = cfg["default_tone"]
        s["carousels"] = []
        s["approval"]  = {}
        await q.edit_message_text(
            f"✓ Channel: {cfg['emoji']} *{cfg['name']}*\n\n"
            f"Niche: {s['niche']}\nTone: {s['tone']}\n\n"
            f"Say */generate* to start, or /settings to customise.",
            parse_mode="Markdown",
        )

    elif data == "open:channel":
        await q.edit_message_text("Select a channel:", reply_markup=channel_keyboard())

    elif data == "open:niche":
        await q.edit_message_text("Select a niche:", reply_markup=niche_keyboard())

    elif data == "open:tone":
        await q.edit_message_text("Select a tone:", reply_markup=tone_keyboard())

    elif data.startswith("niche:"):
        s["niche"] = NICHES[int(data.split(":", 1)[1])]
        await q.edit_message_text(f"✓ Niche: *{s['niche']}*", parse_mode="Markdown")

    elif data.startswith("tone:"):
        s["tone"] = TONES[int(data.split(":", 1)[1])]
        await q.edit_message_text(f"✓ Tone: *{s['tone']}*", parse_mode="Markdown")

    elif data == "toggle:autopost":
        s["auto_post"] = not s["auto_post"]
        status = "🟢 ON" if s["auto_post"] else "🔴 OFF"
        detail = (
            "Carousels will be posted immediately after generation."
            if s["auto_post"] else
            "You will review and approve each carousel before posting."
        )
        await q.edit_message_text(
            f"Auto-post: *{status}*\n\n{detail}",
            parse_mode   = "Markdown",
            reply_markup = settings_keyboard(s),
        )

    # ── Carousel review callbacks ─────────────────────────────────────────────
    elif data.startswith("approve:"):
        idx              = int(data.split(":", 1)[1])
        s["approval"][idx] = "approve"
        try:
            update_status(s["channel"], s["date_str"], idx+1, "approved")
        except Exception as e:
            log.warning(f"Sheet update failed: {e}")
        await q.edit_message_text(
            f"{session_header(s)}\n\n{fmt_carousel(idx, s['carousels'][idx], s['approval'])}",
            parse_mode   = "Markdown",
            reply_markup = carousel_keyboard(idx, len(s["carousels"])),
        )

    elif data.startswith("reject:"):
        idx              = int(data.split(":", 1)[1])
        s["approval"][idx] = "reject"
        try:
            update_status(s["channel"], s["date_str"], idx+1, "rejected")
        except Exception as e:
            log.warning(f"Sheet update failed: {e}")
        await q.edit_message_text(
            f"{session_header(s)}\n\n{fmt_carousel(idx, s['carousels'][idx], s['approval'])}",
            parse_mode   = "Markdown",
            reply_markup = carousel_keyboard(idx, len(s["carousels"])),
        )

    elif data.startswith("nav:"):
        idx = int(data.split(":", 1)[1])
        await q.edit_message_text(
            f"{session_header(s)}\n\n{fmt_carousel(idx, s['carousels'][idx], s['approval'])}",
            parse_mode   = "Markdown",
            reply_markup = carousel_keyboard(idx, len(s["carousels"])),
        )

    elif data.startswith("regen:"):
        idx = int(data.split(":", 1)[1])
        await q.edit_message_text(f"Regenerating carousel {idx+1}...")
        try:
            result              = gemini_generate(s["niche"], s["tone"], s["topic"], 1)
            s["carousels"][idx] = result[0]
            s["approval"].pop(idx, None)
            try:
                log_carousel(result[0], idx+1, s["channel"], s["niche"],
                             s["tone"], "generated", s["date_str"])
            except Exception as e:
                log.warning(f"Sheet log failed on regen: {e}")
            await q.edit_message_text(
                f"{session_header(s)}\n\n{fmt_carousel(idx, s['carousels'][idx], s['approval'])}",
                parse_mode   = "Markdown",
                reply_markup = carousel_keyboard(idx, len(s["carousels"])),
            )
        except Exception as e:
            await q.edit_message_text(f"✗ Regen failed: {e}")


# ── Handler registration ──────────────────────────────────────────────────────

def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("channel",  cmd_channel))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CommandHandler("post",     cmd_post))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))