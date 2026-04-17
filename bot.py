"""
bot.py - Instagram Content Agent

Workflow:
1) Any message or /start -> choose mode (personal or random)
2) Personal mode -> choose channel
3) Choose channel-specific niche
4) Choose shared tone
5) Choose generate or restart
6) Generate runs full pipeline without further approval
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    ALLOWED_USER_ID,
    CHANNELS,
    GEMINI_API_KEY,
    TONES,
    get_niches_for_channel,
)
from instagram import post_carousel
from renderer import delete_paths, render_carousel

log = logging.getLogger(__name__)
_client = None
_types = None


CONTENT_PROMPT = """You are an expert Instagram content strategist.

Generate carousel concepts. Each must have:
- hook: under 10 words, scroll-stopping, slightly provocative or curiosity-driven
- slides: 4-6 body slides, max 15 words each, one punchy insight per slide
- cta: under 12 words, drives saves / shares / follows
- caption: 2-3 sentences, conversational, ends with a question
- hashtags: 8-10 tags, mix niche-specific and broad reach
- virality_score: 1-10
- content_pillar: systems | money | mindset | focus | income | relationships

Respond ONLY with a valid JSON array. No preamble, no markdown fences. Pure JSON.
"""


sessions: dict[int, dict] = {}


def is_allowed(uid: int) -> bool:
    return uid == ALLOWED_USER_ID


def _default_channel_key() -> str:
    return list(CHANNELS.keys())[0]


def get_session(uid: int) -> dict:
    if uid not in sessions:
        first_key = _default_channel_key()
        cfg = CHANNELS[first_key]
        sessions[uid] = {
            "mode": None,  # None | personal | random
            "step": "mode",
            "channel": first_key,
            "niche": cfg["default_niche"],
            "tone": cfg["default_tone"],
            "topic": "",
            "busy": False,
            "niche_key_to_full": {},
            "date_str": datetime.now().strftime("%Y-%m-%d"),
        }
    return sessions[uid]


def reset_session(s: dict) -> None:
    first_key = _default_channel_key()
    cfg = CHANNELS[first_key]
    s.update(
        {
            "mode": None,
            "step": "mode",
            "channel": first_key,
            "niche": cfg["default_niche"],
            "tone": cfg["default_tone"],
            "topic": "",
            "niche_key_to_full": {},
            "date_str": datetime.now().strftime("%Y-%m-%d"),
        }
    )


def mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("/personal mode", callback_data="mode:personal"),
                InlineKeyboardButton("/random mode", callback_data="mode:random"),
            ]
        ]
    )


def channel_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, cfg in CHANNELS.items():
        rows.append(
            [
                InlineKeyboardButton(
                    f"{cfg['emoji']} {cfg['name']}", callback_data=f"channel:{key}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("/restart", callback_data="action:restart")])
    return InlineKeyboardMarkup(rows)


def _niche_key(full_niche: str) -> str:
    return full_niche.split("-", 1)[0].strip()


def niche_keyboard(s: dict) -> InlineKeyboardMarkup:
    channel_key = s["channel"]
    niches = get_niches_for_channel(channel_key)
    key_to_full = {}
    rows = []
    for full in niches:
        key = _niche_key(full)
        key_to_full[key] = full
        rows.append([InlineKeyboardButton(key, callback_data=f"niche:{key}")])
    rows.append([InlineKeyboardButton("/restart", callback_data="action:restart")])
    s["niche_key_to_full"] = key_to_full
    return InlineKeyboardMarkup(rows)


def tone_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for tone in TONES:
        rows.append([InlineKeyboardButton(tone, callback_data=f"tone:{tone}")])
    rows.append([InlineKeyboardButton("/restart", callback_data="action:restart")])
    return InlineKeyboardMarkup(rows)


def action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("/generate", callback_data="action:generate"),
                InlineKeyboardButton("/restart", callback_data="action:restart"),
            ]
        ]
    )


def gemini_generate(niche: str, tone: str, topic: str, count: int) -> list[dict]:
    global _client, _types
    if _client is None or _types is None:
        try:
            from google import genai
            from google.genai import types as genai_types
        except Exception as e:
            raise RuntimeError(
                "Gemini client is unavailable. Install/verify google-genai dependency."
            ) from e
        _client = genai.Client(api_key=GEMINI_API_KEY)
        _types = genai_types

    prompt = f"Niche: {niche}\nTone: {tone}"
    if topic:
        prompt += f"\nAngle: {topic}"
    prompt += (
        f"\n\nGenerate {count} carousel(s). "
        f"Return JSON array with exactly {count} object(s)."
    )

    resp = _client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config=_types.GenerateContentConfig(system_instruction=CONTENT_PROMPT),
    )
    clean = resp.text.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(clean)
    return parsed if isinstance(parsed, list) else [parsed]


async def _run_single_carousel_pipeline(
    *,
    s: dict,
    channel_key: str,
    niche: str,
    tone: str,
    bot,
    chat_id: int,
    mode_label: str,
) -> None:
    """
    Full run: Gemini -> Sheet log -> render -> IG post -> Sheet update.
    Sends progress updates and failure stage to user.
    """
    s["date_str"] = datetime.now().strftime("%Y-%m-%d")
    date_str = s["date_str"]

    await bot.send_message(chat_id, f"Mode: {mode_label}")
    await bot.send_message(chat_id, f"Selected channel: {CHANNELS[channel_key]['name']}")
    await bot.send_message(chat_id, f"Selected niche: {niche}")
    await bot.send_message(chat_id, f"Selected tone: {tone}")

    carousel: dict | None = None
    paths: list[Path] = []
    stage = "initializing"

    try:
        stage = "Gemini"
        await bot.send_message(chat_id, "Stage: Gemini")
        carousel = gemini_generate(niche, tone, s.get("topic", ""), 1)[0]

        stage = "Logging generated content"
        await bot.send_message(chat_id, "Stage: Logging generated content")
        try:
            from sheets import log_carousel
            log_carousel(
                carousel=carousel,
                carousel_index=1,
                channel_key=channel_key,
                niche=niche,
                tone=tone,
                status="generated",
                date_str=date_str,
            )
        except Exception as e:
            log.warning("Sheet log failed on generated: %s", e)

        stage = "Rendering slides"
        await bot.send_message(chat_id, "Stage: Rendering slides")
        paths = render_carousel(carousel, date_str, 1)

        stage = "Posting to Instagram"
        await bot.send_message(chat_id, "Stage: Posting to Instagram")
        media_id = post_carousel(paths, carousel, channel_key)

        await bot.send_message(chat_id, f"Posted successfully. Media ID: `{media_id}`", parse_mode="Markdown")
        try:
            from sheets import update_status
            update_status(channel_key, date_str, 1, "posted", media_id)
        except Exception as e:
            log.warning("Sheet update failed after post: %s", e)

    except Exception as e:
        await bot.send_message(chat_id, f"Failed stage: {stage}\nReason: {e}")
        log.error("Pipeline failed: %s", e, exc_info=True)

    finally:
        if paths:
            delete_paths(paths)


async def _run_random_mode(s: dict, bot, chat_id: int) -> None:
    channel_key = random.choice(list(CHANNELS.keys()))
    niche = random.choice(get_niches_for_channel(channel_key))
    tone = random.choice(TONES)
    await _run_single_carousel_pipeline(
        s=s,
        channel_key=channel_key,
        niche=niche,
        tone=tone,
        bot=bot,
        chat_id=chat_id,
        mode_label="Random",
    )


async def _run_personal_mode(s: dict, bot, chat_id: int) -> None:
    await _run_single_carousel_pipeline(
        s=s,
        channel_key=s["channel"],
        niche=s["niche"],
        tone=s["tone"],
        bot=bot,
        chat_id=chat_id,
        mode_label="Personal",
    )


async def _show_mode_menu(message) -> None:
    await message.reply_text(
        "Choose mode:",
        reply_markup=mode_keyboard(),
    )


async def _handle_generate_action(s: dict, q) -> None:
    if s["busy"]:
        await q.message.reply_text("Already running. Please wait.")
        return

    s["busy"] = True
    try:
        if s["mode"] == "random":
            await _run_random_mode(s, q.message.get_bot(), q.message.chat_id)
        elif s["mode"] == "personal":
            await _run_personal_mode(s, q.message.get_bot(), q.message.chat_id)
        else:
            await q.message.reply_text("Select a mode first.")
    finally:
        s["busy"] = False


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("Unauthorised.")
        return
    s = get_session(uid)
    reset_session(s)
    await _show_mode_menu(update.message)


async def cmd_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    s = get_session(uid)
    if s["busy"]:
        await update.message.reply_text("Run in progress. Please wait.")
        return
    reset_session(s)
    await _show_mode_menu(update.message)


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    s = get_session(uid)
    if s["busy"]:
        await update.message.reply_text("Run in progress. Please wait.")
        return
    reset_session(s)
    await _show_mode_menu(update.message)


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if not is_allowed(uid):
        await q.answer("Unauthorised.")
        return
    await q.answer()

    s = get_session(uid)
    data = q.data

    if data == "mode:random":
        if s["busy"]:
            await q.message.reply_text("Already running. Please wait.")
            return
        s["mode"] = "random"
        s["step"] = "running"
        await q.message.reply_text("Random mode selected. Running full pipeline now...")
        await _handle_generate_action(s, q)
        reset_session(s)
        await q.message.reply_text("Run complete. Choose mode for next run:", reply_markup=mode_keyboard())
        return

    if data == "mode:personal":
        s["mode"] = "personal"
        s["step"] = "channel"
        await q.message.reply_text("Select a channel:", reply_markup=channel_keyboard())
        return

    if data.startswith("channel:"):
        key = data.split(":", 1)[1]
        if key not in CHANNELS:
            await q.message.reply_text("Unknown channel.")
            return
        s["channel"] = key
        s["step"] = "niche"
        await q.message.reply_text("Select a niche:", reply_markup=niche_keyboard(s))
        return

    if data.startswith("niche:"):
        niche_key = data.split(":", 1)[1]
        full = s.get("niche_key_to_full", {}).get(niche_key)
        if not full:
            await q.message.reply_text("Unknown niche. Please reselect channel.")
            s["step"] = "channel"
            await q.message.reply_text("Select a channel:", reply_markup=channel_keyboard())
            return
        s["niche"] = full
        s["step"] = "tone"
        await q.message.reply_text("Select a tone:", reply_markup=tone_keyboard())
        return

    if data.startswith("tone:"):
        tone = data.split(":", 1)[1]
        if tone not in TONES:
            await q.message.reply_text("Unknown tone.")
            return
        s["tone"] = tone
        s["step"] = "action"
        await q.message.reply_text(
            "Ready.\nChoose /generate to post now or /restart to start over.",
            reply_markup=action_keyboard(),
        )
        return

    if data == "action:generate":
        if s["mode"] != "personal":
            await q.message.reply_text("Generate is available after personal setup.")
            return
        if s["step"] not in ("action",):
            await q.message.reply_text("Complete channel, niche and tone selection first.")
            return
        await _handle_generate_action(s, q)
        reset_session(s)
        await q.message.reply_text("Run complete. Choose mode for next run:", reply_markup=mode_keyboard())
        return

    if data == "action:restart":
        if s["busy"]:
            await q.message.reply_text("Run in progress. Please wait.")
            return
        reset_session(s)
        await q.message.reply_text("Restarted. Choose mode:", reply_markup=mode_keyboard())
        return


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
