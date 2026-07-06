"""
First-run setup wizard + /settings — configures the bot from inside Telegram
instead of `.env`.

Covers: DB_CHANNEL, LOG_CHANNEL, FORCE_SUB_CHANNEL, MONGO_URI, URL (web
portal address — enabling it also turns the web server on), SITE_NAME,
SITE_TAGLINE, BOT_NAME, CREATOR_NAME, MAX_CONCURRENT_TRANSMISSIONS,
STREAM_MODE, LINK_EXPIRY_DAYS, ADMINS.

Flow:
  • The very first person to message the bot (when no admin is configured
    yet) is auto-promoted to admin and walked through a one-time setup
    wizard (see plugins/start.py, which calls maybe_claim_owner()).
  • Any admin can re-run the wizard with /setup, or tweak a single value
    any time with /settings.
  • Settings that are baked into the process at startup (MONGO_URI,
    MAX_CONCURRENT_TRANSMISSIONS) apply on the next restart, which the bot
    triggers automatically after saving.
"""

import logging
import re
from urllib.parse import urlparse

from pyrogram import Client, filters, StopPropagation
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import info
import owner_claim
import settings_store
from utils import is_admin, restart_bot

logger = logging.getLogger(__name__)

# user_id -> {"steps": [...], "index": int, "values": {...}, "single": bool}
_WIZARD_STATE: dict[int, dict] = {}

# user_ids currently mid-way through proving they know the current
# rotating 6-digit claim code, i.e. they've been asked for it but
# haven't answered correctly yet.
_CLAIM_PENDING: set[int] = set()


def _parse_channel_id(message: Message):
    """Accept a forwarded channel post (auto-fills the ID) or a typed ID."""
    if message.forward_from_chat and message.forward_from_chat.id:
        return message.forward_from_chat.id
    text = (message.text or "").strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return None


def _parse_bool(message: Message):
    text = (message.text or "").strip().lower()
    if text in ("yes", "true", "on", "1", "enable", "enabled"):
        return True
    if text in ("no", "false", "off", "0", "disable", "disabled"):
        return False
    return None


def _parse_int_or_none(message: Message):
    text = (message.text or "").strip().lower()
    if text in ("skip", "none", "never", "", "0"):
        return None
    if text.isdigit() and int(text) > 0:
        return int(text)
    return "invalid"


def _parse_int(message: Message):
    text = (message.text or "").strip()
    if text.isdigit() and int(text) > 0:
        return int(text)
    return None


def _parse_text(message: Message):
    text = (message.text or "").strip()
    return text or None


_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.-]+(:\d+)?$")


def _parse_url(message: Message):
    """Accepts a full URL, or a bare domain (auto-prepends https://)."""
    text = (message.text or "").strip()
    if not text:
        return None
    if any(ch.isspace() for ch in text):
        return "invalid"
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        return "invalid"
    if not parsed.netloc or not _HOSTNAME_RE.match(parsed.netloc):
        return "invalid"
    return text.rstrip("/")


STEPS = [
    {
        "key": "db_channel",
        "label": "📥 DB Channel",
        "required": True,
        "parser": _parse_channel_id,
        "prompt": (
            "**Step: DB Channel**\n\n"
            "This is where all uploaded files are stored. Add this bot as "
            "**admin** in a private channel, then either:\n"
            "▸ forward any message from that channel here, or\n"
            "▸ type its ID (e.g. `-1001234567890`)"
        ),
        "invalid": "That doesn't look like a channel. Forward a message from it, or send its numeric ID.",
    },
    {
        "key": "log_channel",
        "label": "📝 Log Channel",
        "required": False,
        "parser": _parse_channel_id,
        "prompt": (
            "**Step: Log Channel** _(optional)_\n\n"
            "Bot startup notices & broadcasts get logged here. Forward a "
            "message from the channel, type its ID, or tap Skip."
        ),
        "invalid": "That doesn't look like a channel. Forward a message from it, type its numeric ID, or tap Skip.",
    },
    {
        "key": "force_sub_channel",
        "label": "🔒 Force-Sub Channel",
        "required": False,
        "parser": _parse_channel_id,
        "prompt": (
            "**Step: Force-Subscribe Channel** _(optional)_\n\n"
            "Users must join this channel before using the bot. Forward a "
            "message from it, type its ID, or tap Skip to disable."
        ),
        "invalid": "That doesn't look like a channel. Forward a message from it, type its numeric ID, or tap Skip.",
    },
    {
        "key": "mongo_uri",
        "label": "🗄️ MongoDB URI",
        "required": False,
        "parser": _parse_text,
        "prompt": (
            "**Step: MongoDB URI** _(optional but recommended)_\n\n"
            "Paste your MongoDB connection string, e.g.\n"
            "`mongodb+srv://user:password@cluster.mongodb.net/?appName=App`\n\n"
            "Without it the bot uses a local on-disk store. Tap Skip to use that instead."
        ),
        "invalid": None,
    },
    {
        "key": "url",
        "label": "🌐 Website URL",
        "required": False,
        "parser": _parse_url,
        "prompt": (
            "**Step: Website URL** _(optional)_\n\n"
            "The public address of this bot's deployment (e.g. your Railway/"
            "Render/VPS domain) — `https://your-app.up.railway.app`. Setting "
            "this turns on the web portal and adds download/stream/web-page "
            "links to every file. Tap Skip to leave the web portal off."
        ),
        "invalid": "That doesn't look like a valid URL — send something like `https://your-app.up.railway.app`, or tap Skip.",
    },
    {
        "key": "site_name",
        "label": "📛 Site Name",
        "required": False,
        "parser": _parse_text,
        "prompt": "**Step: Website Name** _(optional)_\n\nShown across the web pages. Tap Skip to keep `StreamLink`.",
        "invalid": None,
    },
    {
        "key": "site_tagline",
        "label": "🏷️ Site Tagline",
        "required": False,
        "parser": _parse_text,
        "prompt": "**Step: Website Tagline** _(optional)_\n\nTap Skip to keep the default tagline.",
        "invalid": None,
    },
    {
        "key": "bot_name",
        "label": "🤖 Bot Name",
        "required": False,
        "parser": _parse_text,
        "prompt": (
            "**Step: Bot Name** _(optional)_\n\n"
            "Shown across the bot's own messages (welcome, help, stats). "
            "Tap Skip to keep `File-to-Link Bot`."
        ),
        "invalid": None,
    },
    {
        "key": "creator_name",
        "label": "👤 Creator Name",
        "required": False,
        "parser": _parse_text,
        "prompt": "**Step: Creator Name** _(optional)_\n\nShown on the About screen. Tap Skip to keep the default.",
        "invalid": None,
    },
    {
        "key": "max_concurrent_transmissions",
        "label": "⚡ Parallel Transfers",
        "required": False,
        "parser": _parse_int,
        "prompt": (
            "**Step: Parallel Transfers** _(optional)_\n\n"
            "How many downloads/streams may run at the same time. Send a "
            "number (e.g. `24`) or tap Skip to keep `24`."
        ),
        "invalid": "Send a positive whole number, or tap Skip.",
    },
    {
        "key": "stream_mode",
        "label": "▶️ Stream Mode",
        "required": False,
        "parser": _parse_bool,
        "prompt": "**Step: Stream Mode** _(optional)_\n\nEnable in-browser streaming links? Send `yes`/`no` or tap Skip to keep `yes`.",
        "invalid": "Send `yes` or `no`, or tap Skip.",
    },
    {
        "key": "link_expiry_days",
        "label": "⏳ Link Expiry",
        "required": False,
        "parser": _parse_int_or_none,
        "prompt": (
            "**Step: Link Expiry (days)** _(optional)_\n\n"
            "Send a number of days after which links expire, or tap Skip "
            "for permanent links."
        ),
        "invalid": "Send a positive whole number of days, or tap Skip.",
    },
]

_STEP_BY_KEY = {s["key"]: s for s in STEPS}

# ── Settings-only extras ──────────────────────────────────────────────────────
# Same shape as STEPS (so they reuse _send_step / the wizard machinery), but
# these are NEVER part of the first-run setup wizard — only reachable via
# /settings. Nothing here blocks or gets asked during initial setup; each one
# starts at a safe default until an admin explicitly opts in.
EXTRA_SETTINGS = [
    {
        "key": "show_uploader_info",
        "label": "👤 Show Uploader Info",
        "required": False,
        "parser": _parse_bool,
        "prompt": (
            "**Setting: Show Uploader Info** _(optional, off by default)_\n\n"
            "When ON, every file stored in the DB Channel gets a "
            "\"👤 Uploaded by\" block appended to its caption — the "
            "uploader's name, @username, numeric user ID, and the "
            "upload date/time.\n\n"
            "This is OFF by default: it exposes the uploader's Telegram "
            "identity inside the storage channel, which not every "
            "deployment wants shown automatically.\n\n"
            "Send `yes` to enable or `no` to disable, or tap Skip to leave "
            "it as-is."
        ),
        "invalid": "Send `yes` or `no`, or tap Skip.",
    },
]
_STEP_BY_KEY.update({s["key"]: s for s in EXTRA_SETTINGS})


def _skip_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip", callback_data="setupskip")]])


async def _send_step(client: Client, chat_id: int, state: dict):
    step = state["steps"][state["index"]]
    markup = None if step["required"] else _skip_markup()
    await client.send_message(chat_id, step["prompt"], reply_markup=markup)


async def _advance(client: Client, user_id: int, chat_id: int):
    state = _WIZARD_STATE[user_id]
    state["index"] += 1
    if state["index"] >= len(state["steps"]):
        await _finish(client, user_id, chat_id)
        return
    await _send_step(client, chat_id, state)


async def _finish(client: Client, user_id: int, chat_id: int):
    state = _WIZARD_STATE.pop(user_id, None)
    if not state:
        return
    values = state["values"]

    if not state.get("single"):
        admins = settings_store.get("admins", []) or []
        if user_id not in admins:
            admins.append(user_id)
        values["admins"] = admins
        values["setup_complete"] = True

    settings_store.set_many(values)

    lines = ["✅ **Settings saved!**\n"]
    for key, val in values.items():
        if key in ("admins", "setup_complete"):
            continue
        label = _STEP_BY_KEY.get(key, {}).get("label", key)
        shown = "— (disabled/default)" if val in (None, "", 0) else f"`{val}`"
        lines.append(f"▸ {label}: {shown}")
    lines.append("\n🔄 Restarting the bot now to apply these changes…")

    await client.send_message(chat_id, "\n".join(lines))
    restart_bot()


async def _handle_value(client: Client, message: Message, state: dict, value):
    step = state["steps"][state["index"]]
    if value == "invalid" or (value is None and step["required"]):
        err = step.get("invalid") or "That value doesn't look right — try again."
        await message.reply(err)
        return
    if value is not None:
        state["values"][step["key"]] = value
    await _advance(client, message.from_user.id, message.chat.id)


def start_wizard(user_id: int, chat_id: int, steps=None, single: bool = False):
    _WIZARD_STATE[user_id] = {
        "steps": steps or STEPS,
        "index": 0,
        "values": {},
        "single": single,
    }


async def _grant_owner_and_start_wizard(client: Client, message: Message) -> bool:
    """Actually promote the user to admin and kick off the setup wizard."""
    user_id = message.from_user.id
    admins = settings_store.get("admins", []) or []
    if user_id not in admins:
        admins.append(user_id)
        settings_store.set("admins", admins)
    if user_id not in info.ADMINS:
        info.ADMINS.append(user_id)

    await message.reply(
        "Hey, welcome! 👋 Looks like setup hasn't been finished yet, so "
        "I've made you an admin.\n\nLet's get the essentials sorted — this "
        "replaces the old `.env` config, and it'll only take a minute."
    )
    start_wizard(user_id, message.chat.id)
    await _send_step(client, message.chat.id, _WIZARD_STATE[user_id])
    return True


async def maybe_claim_owner(client: Client, message: Message) -> bool:
    """
    Called from /start. If setup hasn't been completed yet, this asks the
    user for the current rotating 6-digit code shown in the bot's console
    output (see owner_claim.py). That code changes every 2 minutes and is
    never sent over Telegram, so a stranger who happens to message the bot
    before the real deployer can't win the race and claim admin for
    themselves — only someone actually watching the running process's
    terminal/logs can answer correctly.

    Returns True if it handled the message (i.e. /start shouldn't continue
    on to its normal behavior). Safe to call again if a previous setup run
    or claim attempt was interrupted (e.g. the process restarted).
    """
    if settings_store.is_setup_complete():
        return False

    user_id = message.from_user.id

    if user_id in _CLAIM_PENDING:
        # Already asked once — let owner_secret_input() judge their reply
        # instead of re-prompting here.
        return True

    _CLAIM_PENDING.add(user_id)
    await message.reply(
        "👋 Hey! This bot hasn't been set up yet.\n\n"
        "So a stranger can't grab admin just by messaging first, "
        "whoever deployed this bot needs to check the bot's **console "
        "output / logs** for the current **6-digit claim code** and "
        "send it here. It's a fresh code every 2 minutes, so if it's "
        "expired by the time you read this, just grab the latest one."
    )
    return True


@Client.on_message(filters.private, group=-3)
async def owner_secret_input(client: Client, message: Message):
    """
    Handles the reply to the owner-claim prompt above. Runs one group
    earlier than wizard_text_input (group=-2) so it always wins the race
    for a pending claimant's next message.
    """
    user_id = message.from_user.id
    if user_id not in _CLAIM_PENDING:
        return  # not mid-claim — let other handlers process this message

    submitted = (message.text or "").strip()

    # BUG FIX: this used to only exempt 5 named commands (/start, /help,
    # /about, /setup, /settings) via the handler's filter, so anything else
    # typed while a claim was pending — /ping, /id, /cancel, etc. — got
    # swallowed here and judged as a wrong claim code instead of reaching
    # its real handler. Any command should pass through untouched; only
    # plain text is a genuine claim-code attempt.
    if submitted.startswith("/"):
        return

    correct = owner_claim.check(submitted)

    if not correct:
        await message.reply(
            "❌ That's not the current code (or it already rotated). "
            "Check the bot's console output for the latest 6-digit "
            "code and send that."
        )
        raise StopPropagation

    _CLAIM_PENDING.discard(user_id)
    await _grant_owner_and_start_wizard(client, message)
    raise StopPropagation


# ── /setup — re-run the full wizard ────────────────────────────────────────

@Client.on_message(filters.command("setup") & filters.private)
async def setup_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not settings_store.is_setup_complete():
        await maybe_claim_owner(client, message)
        return
    if not is_admin(user_id):
        await message.reply("⛔ Admins only.")
        return
    start_wizard(user_id, message.chat.id)
    await message.reply("🔧 Re-running full setup…")
    await _send_step(client, message.chat.id, _WIZARD_STATE[user_id])


# ── /settings — menu to edit one value at a time ───────────────────────────

@Client.on_message(filters.command("settings") & filters.private)
async def settings_menu_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Admins only.")
        return

    rows = []
    for step in STEPS + EXTRA_SETTINGS:
        rows.append([InlineKeyboardButton(step["label"], callback_data=f"editsetting:{step['key']}")])
    rows.append([InlineKeyboardButton("🔧 Run Full Setup Again", callback_data="editsetting:__all__")])

    current = settings_store.get_all()
    lines = ["⚙️ **Bot Settings**\n", "Tap a setting to change it:\n"]
    for step in STEPS + EXTRA_SETTINGS:
        val = current.get(step["key"])
        shown = "— (disabled/default)" if val in (None, "", 0, False) else f"`{val}`"
        lines.append(f"▸ {step['label']}: {shown}")

    await message.reply("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows))


@Client.on_callback_query(filters.regex(r"^editsetting:"))
async def edit_setting_cb(client: Client, cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        await cq.answer("⛔ Admins only.", show_alert=True)
        return
    key = cq.data.split(":", 1)[1]
    await cq.answer()
    if key == "__all__":
        start_wizard(cq.from_user.id, cq.message.chat.id)
        await _send_step(client, cq.message.chat.id, _WIZARD_STATE[cq.from_user.id])
        return
    step = _STEP_BY_KEY[key]
    start_wizard(cq.from_user.id, cq.message.chat.id, steps=[step], single=True)
    await _send_step(client, cq.message.chat.id, _WIZARD_STATE[cq.from_user.id])


@Client.on_callback_query(filters.regex("^setupskip$"))
async def setup_skip_cb(client: Client, cq: CallbackQuery):
    user_id = cq.from_user.id
    state = _WIZARD_STATE.get(user_id)
    if not state:
        await cq.answer()
        return
    await cq.answer("Skipped")
    await _advance(client, user_id, cq.message.chat.id)


# ── Text input while a wizard is active ────────────────────────────────────

# BUG FIX (DB Channel step / any wizard step not responding):
# This handler MUST win the race against every other group=-1 handler
# (antispam_guard in plugins/antispam.py loads first alphabetically and
# matches ALL private messages first). Pyrogram only runs the FIRST
# matching handler within a group, then moves to the next group — so
# antispam_guard was silently swallowing forwarded messages / typed
# channel IDs meant for the wizard, which then fell through to
# auto_help.py's "I work with files, not text" fallback in group=5.
# Running one group earlier (-2) guarantees wizard input always wins.
# BUG FIX (DB Channel step / any wizard step not responding):
# This handler MUST win the race against every other group=-1 handler
# (antispam_guard in plugins/antispam.py loads first alphabetically and
# matches ALL private messages first). Pyrogram only runs the FIRST
# matching handler within a group, then moves to the next group — so
# antispam_guard was silently swallowing forwarded messages / typed
# channel IDs meant for the wizard, which then fell through to
# auto_help.py's "I work with files, not text" fallback in group=5.
# Running one group earlier (-2) guarantees wizard input always wins.
@Client.on_message(filters.private, group=-2)
async def wizard_text_input(client: Client, message: Message):
    state = _WIZARD_STATE.get(message.from_user.id)
    if not state:
        return  # not in a wizard — let other handlers process this message

    # BUG FIX: this used to only exempt 5 named commands (/start, /help,
    # /about, /setup, /settings) via the handler's filter. Every OTHER
    # command — /ping, /cancel, /id, /batch, /ban, etc. — fell through to
    # here and got treated as a literal answer to whatever wizard step was
    # active. For a free-text step (site name, bot name, tagline, Mongo
    # URI…) that meant the command's own text got silently SAVED as the
    # setting's value; for a validated step it just produced a confusing
    # "that doesn't look right" reply. Any typed command should reach its
    # own handler untouched; only plain text (or a forwarded channel post,
    # even one whose original text happened to start with "/") is a
    # genuine wizard answer.
    text = (message.text or "").strip()
    if text.startswith("/") and not message.forward_from_chat:
        return

    step = state["steps"][state["index"]]
    value = step["parser"](message)
    await _handle_value(client, message, state, value)
    raise StopPropagation
