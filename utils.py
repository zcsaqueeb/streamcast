"""Utility helpers shared across plugins."""

import asyncio
import logging
import mimetypes
import os
import sys
from typing import Union

from pyrogram import Client
from pyrogram.types import Message
from pyrogram.enums import ChatMemberStatus

from info import FORCE_SUB_CHANNEL, ADMINS

# Membership states that count as "subscribed" for force-sub checks.
_SUBSCRIBED_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
}

logger = logging.getLogger(__name__)


# ── Streamable media detection (single source of truth) ─────────────────────
# Used by BOTH plugins/file_handler.py (the bot's Telegram reply — decides
# whether to show a Stream button/link) AND web/app.py (the web page —
# decides whether to show the in-browser player). Previously each module had
# its own separate, out-of-sync definition:
#
#   - file_handler.py only checked Telegram's own message type (video/audio/
#     voice/video_note/animation). A LOT of containers Telegram doesn't
#     recognize as playable video — .mkv, .avi, .wmv, .flv, .ts, and others —
#     get uploaded by Telegram clients as a plain "document" instead, so the
#     bot's own reply silently dropped the Stream button/link even though...
#   - web/app.py ALSO checked MIME type (resolved from the filename), so the
#     web page itself could serve these fine — just not the initial Telegram
#     message that pointed at it. That mismatch is exactly why .mkv (and
#     friends) "supported streaming" inconsistently.
#
# Centralizing both the MIME/extension tables and the streamable check here
# means both surfaces always agree, and broadening format coverage only has
# to happen in one place.

STREAMABLE_MSG_TYPES = {"video", "audio", "voice", "video_note", "animation"}

VIDEO_MIMES = {
    "video/mp4", "video/webm", "video/ogg", "video/mkv",
    "video/x-matroska", "video/avi", "video/quicktime",
    "video/x-msvideo", "video/3gpp", "video/3gpp2", "video/x-flv",
    "video/mp2t", "video/x-ms-wmv", "video/mpeg", "video/x-ms-asf",
    "video/divx", "video/x-ms-vob", "video/vnd.rn-realvideo",
    "application/vnd.rn-realmedia", "video/x-f4v",
    "video/x-dv", "video/x-nut", "video/x-yuv4mpeg", "video/x-ivf",
    "video/x-amv", "video/x-drc", "application/mxf", "video/mxf",
}
AUDIO_MIMES = {
    "audio/mpeg", "audio/ogg", "audio/wav", "audio/x-wav", "audio/flac",
    "audio/aac", "audio/mp4", "audio/x-m4a", "audio/opus",
    "audio/webm", "audio/amr", "audio/x-aiff", "audio/midi",
    "audio/x-ms-wma", "audio/3gpp",
    "audio/x-matroska", "audio/x-caf", "audio/x-pn-realaudio",
    "audio/x-ape", "audio/x-tta", "audio/x-wavpack",
    "audio/ac3", "audio/eac3", "audio/dts",
}

# Extensions mimetypes.guess_type() doesn't know, or gets wrong/generic.
EXTENSION_MIME_MAP = {
    # video containers
    ".mkv":  "video/x-matroska",
    ".ts":   "video/mp2t",
    ".m2ts": "video/mp2t",
    ".mts":  "video/mp2t",
    ".m4v":  "video/mp4",
    ".mov":  "video/quicktime",
    ".qt":   "video/quicktime",
    ".avi":  "video/x-msvideo",
    ".wmv":  "video/x-ms-wmv",
    ".asf":  "video/x-ms-asf",
    ".flv":  "video/x-flv",
    ".f4v":  "video/x-f4v",
    ".3gp":  "video/3gpp",
    ".3g2":  "video/3gpp2",
    ".mpg":  "video/mpeg",
    ".mpeg": "video/mpeg",
    ".mpe":  "video/mpeg",
    ".m1v":  "video/mpeg",
    ".m2v":  "video/mpeg",
    ".divx": "video/divx",
    ".vob":  "video/x-ms-vob",
    ".ogv":  "video/ogg",
    ".ogm":  "video/ogg",
    ".rm":   "video/vnd.rn-realvideo",
    ".rmvb": "application/vnd.rn-realmedia",
    ".webm": "video/webm",
    ".mxf":  "application/mxf",
    ".dv":   "video/x-dv",
    ".nut":  "video/x-nut",
    ".y4m":  "video/x-yuv4mpeg",
    ".ivf":  "video/x-ivf",
    ".amv":  "video/x-amv",
    ".drc":  "video/x-drc",
    # audio containers
    ".m4a":  "audio/mp4",
    ".m4b":  "audio/mp4",
    ".opus": "audio/opus",
    ".weba": "audio/webm",
    ".flac": "audio/flac",
    ".wma":  "audio/x-ms-wma",
    ".amr":  "audio/amr",
    ".aiff": "audio/x-aiff",
    ".aif":  "audio/x-aiff",
    ".mid":  "audio/midi",
    ".midi": "audio/midi",
    ".oga":  "audio/ogg",
    ".mka":  "audio/x-matroska",
    ".caf":  "audio/x-caf",
    ".ra":   "audio/x-pn-realaudio",
    ".ram":  "audio/x-pn-realaudio",
    ".ape":  "audio/x-ape",
    ".tta":  "audio/x-tta",
    ".wv":   "audio/x-wavpack",
    ".ac3":  "audio/ac3",
    ".eac3": "audio/eac3",
    ".dts":  "audio/dts",
    # subtitle sidecars (served as plain text/vtt for the player's <track>)
    ".srt":  "application/x-subrip",
    ".vtt":  "text/vtt",
    ".ass":  "text/x-ssa",
    ".ssa":  "text/x-ssa",
}


def detect_mime(file_name: str, fallback: str = "application/octet-stream") -> str:
    """
    Guess MIME type from filename, using an extended extension table for
    containers mimetypes.guess_type() doesn't know or gets wrong (.mkv,
    .ts, .avi, .wmv, .flv, and more — see EXTENSION_MIME_MAP). Falls back
    to `fallback` (typically Telegram's own reported mime_type) if nothing
    matches.
    """
    if not file_name:
        return fallback
    ext = os.path.splitext(file_name)[1].lower()
    if ext in EXTENSION_MIME_MAP:
        return EXTENSION_MIME_MAP[ext]
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or fallback


def is_streamable_media(ftype: str, mime_type: str = None, file_name: str = None) -> bool:
    """
    True if this file should get a Stream button/link and player, checking
    BOTH Telegram's own message type (video/audio/voice/video_note/
    animation) AND the MIME type resolved from the filename/extension.

    Checking only the message type (the old, pre-upgrade behavior) misses
    files Telegram itself classifies as a generic "document" — extremely
    common for containers like .mkv, .avi, .wmv, .flv, .ts, which many
    Telegram clients don't recognize as playable video and upload as a
    plain file instead, even though the file is perfectly streamable once
    it reaches our web player.
    """
    if ftype in STREAMABLE_MSG_TYPES:
        return True
    mime = mime_type or (detect_mime(file_name) if file_name else None)
    return bool(mime) and mime in (VIDEO_MIMES | AUDIO_MIMES)


def humanbytes(size: int) -> str:
    """Convert bytes to a human-readable string."""
    if not size:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def restart_bot():
    """
    Re-exec the current process so settings saved to settings_store.json
    (MONGO_URI, MAX_CONCURRENT_TRANSMISSIONS, channels, etc.) are picked up
    fresh by info.py on the next import. Some of these are baked into the
    Pyrogram Client / DB connection at startup, so a clean restart is the
    simplest way to apply them reliably.
    """
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def check_force_sub(client: Client, message: Message) -> bool:
    """
    Return True if the user is subscribed to FORCE_SUB_CHANNEL
    (or force-sub is disabled).  Sends a prompt and returns False if not.
    """
    if not FORCE_SUB_CHANNEL:
        return True

    user_id = message.from_user.id
    try:
        member = await client.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        # BUG FIX: in Pyrogram 2.x `member.status` is a ChatMemberStatus enum,
        # not a string — comparing it against ("member", "creator", ...) was
        # ALWAYS False, so every user (even subscribers) was blocked.
        if member.status in _SUBSCRIBED_STATUSES:
            return True
    except Exception:
        pass

    try:
        invite = await client.create_chat_invite_link(FORCE_SUB_CHANNEL)
        link = invite.invite_link
    except Exception:
        # BUG FIX: `lstrip('-100')` strips ANY leading '-', '1', '0' chars,
        # which mangles channel IDs (e.g. -1001234 -> "234"). Strip the exact
        # "-100" prefix once instead.
        link = f"https://t.me/c/{str(FORCE_SUB_CHANNEL).replace('-100', '', 1)}"

    await message.reply(
        "⚠️ **Join Required**\n\n"
        "You must join our channel to use this bot.\n\n"
        f"👉 [Join Channel]({link})\n\n"
        "After joining, send your command again.",
        disable_web_page_preview=True,
    )
    return False


def build_uploader_caption(message: Message, file_name: str) -> str:
    """
    Build the caption used when storing a file in DB_CHANNEL.

    BUG FIX #1 — the old version prepended message.caption (which the sender
    may have written, and which could include the filename) *and* also showed
    file_name on line 1. That caused the filename to appear twice when the
    stored message was later copied back to a user.

    Now: the storage caption contains only the file name, plus — if the
    admin has opted in via /settings (SHOW_UPLOADER_INFO, off by default) —
    a block identifying who uploaded it and when. We no longer re-inject
    message.caption into it.
    """
    from datetime import datetime
    import info as cfg

    lines = [f"📁 {file_name}"]

    if cfg.SHOW_UPLOADER_INFO:
        user = message.from_user
        uploader_name = (user.first_name or "Unknown") if user else "Unknown"
        if user and user.last_name:
            uploader_name += f" {user.last_name}"
        uploader_tag = f"@{user.username}" if (user and user.username) else "(no username)"
        user_id = user.id if user else 0

        uploaded_at = datetime.utcnow().strftime("%d %b %Y, %I:%M %p UTC")

        lines += [
            "",
            "👤 **Uploaded by:**",
            f"▸ Name: {uploader_name}",
            f"▸ Username: {uploader_tag}",
            f"▸ User ID: `{user_id}`",
            f"▸ Date & Time: {uploaded_at}",
        ]
        # Deliberately NOT including message.caption here — it often contains
        # the filename already, which caused the duplicate display bug.

    return "\n".join(lines)


async def broadcast_message(client: Client, message: Message) -> tuple[int, int, int]:
    """
    Broadcast a message to all users.
    Returns (success_count, failed_count, total).
    """
    db = client.db  # type: ignore[attr-defined]

    success = failed = 0
    async for user in db.get_all_users():
        uid = user["_id"]
        try:
            await message.copy(uid)
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # flood-control friendly

    return success, failed, success + failed
