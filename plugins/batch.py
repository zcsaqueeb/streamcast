"""
/batch — Collect multiple files and generate a single shareable batch link.

Usage:
  /batch     → start collecting files
  send files → each gets saved and added to the batch
  /done      → finalize and receive a single batch link
  /cancel    → cancel current batch
"""

import logging
import uuid
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from info import DB_CHANNEL, URL
from utils import check_force_sub, humanbytes, build_uploader_caption
import batch_state

logger = logging.getLogger(__name__)

FILE_TYPES = (
    "document", "video", "audio", "photo",
    "voice", "video_note", "animation", "sticker"
)
STREAMABLE_TYPES = {"video", "audio", "voice", "video_note", "animation"}


def _get_file_info(message: Message) -> dict | None:
    for ftype in FILE_TYPES:
        obj = getattr(message, ftype, None)
        if not obj:
            continue
        return {
            "type": ftype,
            "file_id": getattr(obj, "file_id", None),
            # BUG FIX #1 — never use None/empty string as filename; fall back
            # to a clean type label so the name is never duplicated or blank.
            "file_name": (getattr(obj, "file_name", None) or "").strip() or ftype.replace("_", " ").title(),
            "file_size": getattr(obj, "file_size", 0) or 0,
            "mime_type": getattr(obj, "mime_type", "application/octet-stream") or "application/octet-stream",
        }
    return None


@Client.on_message(filters.command("batch") & filters.private)
async def batch_start(client: Client, message: Message):
    db = client.db  # type: ignore[attr-defined]
    user_id = message.from_user.id

    if not await check_force_sub(client, message):
        return

    existing = batch_state.get_batch_id(user_id) or await db.get_user_active_batch(user_id)
    if existing:
        await message.reply(
            "⚠️ **You already have an active batch!**\n\n"
            "▸ Keep sending files to add them\n"
            "▸ /done — finalize and get the batch link\n"
            "▸ /cancel — cancel and discard"
        )
        return

    batch_id = uuid.uuid4().hex[:10]
    await db.create_batch(batch_id, user_id)
    batch_state.set_batch(user_id, batch_id)

    await message.reply(
        "📦 **Batch Mode Started!**\n\n"
        f"▸ Batch ID: `{batch_id}`\n\n"
        "Now send your files one by one.\n"
        "When done, type /done to generate your batch link.\n"
        "To cancel, type /cancel.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Done", callback_data=f"batch_done_{batch_id}"),
             InlineKeyboardButton("❌ Cancel", callback_data=f"batch_cancel_{batch_id}")]
        ])
    )


@Client.on_message(filters.command("done") & filters.private)
async def batch_done_cmd(client: Client, message: Message):
    await _finalize_batch(client, message, message.from_user.id)


@Client.on_message(filters.command("cancel") & filters.private)
async def batch_cancel_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    db = client.db  # type: ignore[attr-defined]
    batch_id = batch_state.get_batch_id(user_id) or await db.get_user_active_batch(user_id)
    if not batch_id:
        await message.reply("ℹ️ No active batch to cancel.")
        return
    batch_state.clear_batch(user_id)
    await db.close_batch(batch_id)
    await message.reply("❌ **Batch cancelled.**")


@Client.on_message(filters.command("mybatch") & filters.private)
async def mybatch_cmd(client: Client, message: Message):
    """Show the current in-progress batch: how many files so far, with quick
    /done and /cancel actions — referenced from /help but never implemented
    until now."""
    user_id = message.from_user.id
    db = client.db  # type: ignore[attr-defined]
    batch_id = batch_state.get_batch_id(user_id) or await db.get_user_active_batch(user_id)

    if not batch_id:
        await message.reply(
            "ℹ️ **No active batch.**\n\nStart one with /batch, then send files one by one."
        )
        return

    batch = await db.get_batch(batch_id)
    files = (batch or {}).get("files", [])

    await message.reply(
        f"📦 **Active Batch**\n\n"
        f"▸ Batch ID: `{batch_id}`\n"
        f"▸ Files so far: **{len(files)}**\n\n"
        "Keep sending files to add more.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Done", callback_data=f"batch_done_{batch_id}"),
             InlineKeyboardButton("❌ Cancel", callback_data=f"batch_cancel_{batch_id}")]
        ])
    )


@Client.on_callback_query(filters.regex(r"^batch_done_(.+)$"))
async def batch_done_cb(client, cq):
    batch_id = cq.data.split("_", 2)[2]
    await cq.answer()
    await _finalize_batch(client, cq.message, cq.from_user.id, batch_id=batch_id)


@Client.on_callback_query(filters.regex(r"^batch_cancel_(.+)$"))
async def batch_cancel_cb(client, cq):
    batch_id = cq.data.split("_", 2)[2]
    db = client.db  # type: ignore[attr-defined]
    batch_state.clear_batch(cq.from_user.id)
    await db.close_batch(batch_id)
    await cq.answer("Batch cancelled.")
    await cq.message.edit_text("❌ **Batch cancelled.**")


async def _finalize_batch(client, message, user_id: int, batch_id: str = None):
    db = client.db  # type: ignore[attr-defined]
    bid = batch_id or batch_state.get_batch_id(user_id) or await db.get_user_active_batch(user_id)

    if not bid:
        await message.reply("ℹ️ No active batch found. Start one with /batch.")
        return

    batch = await db.get_batch(bid)
    if not batch or not batch.get("files"):
        await message.reply("⚠️ **Empty batch.** Send at least one file before finishing.")
        return

    files = batch["files"]
    await db.close_batch(bid)
    batch_state.clear_batch(user_id)

    batch_url = f"{URL}/batch/{bid}" if URL else None

    lines = [f"✅ **Batch Ready! ({len(files)} files)**\n"]
    if batch_url:
        lines.append(f"🔗 **Batch Link:** `{batch_url}`")

    lines.append("\n**Individual Links:**")
    for i, fuid in enumerate(files, 1):
        fm = await db.get_file(fuid)
        fname = fm.get("file_name", fuid) if fm else fuid
        if URL:
            lines.append(f"{i}. [{fname}]({URL}/file/{fuid})")
        else:
            lines.append(f"{i}. `{fuid}` — {fname}")

    buttons = []
    if batch_url:
        buttons.append([InlineKeyboardButton("📦 Open Batch Page", url=batch_url)])

    await message.reply(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
        disable_web_page_preview=True,
    )


@Client.on_message(
    filters.private & (
        filters.document | filters.video | filters.audio |
        filters.voice | filters.video_note | filters.animation |
        filters.sticker | filters.photo
    ),
    group=1
)
async def batch_file_interceptor(client: Client, message: Message):
    db = client.db  # type: ignore[attr-defined]
    user_id = message.from_user.id

    batch_id = batch_state.get_batch_id(user_id) or await db.get_user_active_batch(user_id)
    if not batch_id:
        return

    batch_state.set_batch(user_id, batch_id)

    info = _get_file_info(message)
    if not info or not DB_CHANNEL:
        return

    processing = await message.reply("⏳ Adding to batch…")

    try:
        try:
            fwd = await message.copy(DB_CHANNEL, caption=build_uploader_caption(message, info["file_name"]))
        except Exception:
            # BUG FIX: see plugins/file_handler.py — a real Telegram-side
            # caption rejection (e.g. for a sticker) comes back as an
            # RPCError subclass, not ValueError, so the narrower except
            # this used to have never actually caught it. Retry without a
            # caption for any failure here; if THIS also fails, re-raise
            # so the real problem gets reported below.
            fwd = await message.copy(DB_CHANNEL)
    except Exception as e:
        logger.error("Batch forward error: %s", e)
        await processing.edit("❌ Could not save file. Make sure bot is admin in DB channel.")
        return

    file_uid = uuid.uuid4().hex[:12]
    await db.save_file(file_uid, {
        "file_id":     info["file_id"],
        "file_name":   info["file_name"],
        "file_size":   info["file_size"],
        "mime_type":   info["mime_type"],
        "type":        info["type"],
        "msg_id":      fwd.id,
        "uploader_id": user_id,
        "batch_id":    batch_id,
        "saved_at":    __import__("datetime").datetime.utcnow().isoformat(),
    })
    await db.add_file_to_batch(batch_id, file_uid)
    await db.increment_stat("files_uploaded")
    await db.increment_stat("links_generated")

    batch_data = await db.get_batch(batch_id)
    count = len(batch_data.get("files", [])) if batch_data else "?"

    await processing.edit(
        f"✅ **Added to batch** ({count} files so far)\n"
        f"▸ `{info['file_name']}` · {humanbytes(info['file_size'])}\n\n"
        "Send more files or type /done to finish.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Done", callback_data=f"batch_done_{batch_id}"),
             InlineKeyboardButton("❌ Cancel", callback_data=f"batch_cancel_{batch_id}")]
        ])
    )
    message.stop_propagation()
