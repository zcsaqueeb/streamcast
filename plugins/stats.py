"""
Extra stats/ping commands available to all users.
"""

import time
import sys

from pyrogram import Client, filters
from pyrogram.types import Message


@Client.on_message(filters.command("ping") & filters.private)
async def ping_command(client: Client, message: Message):
    start = time.monotonic()
    msg = await message.reply("🏓 Pong!")
    elapsed = (time.monotonic() - start) * 1000
    await msg.edit(f"🏓 **Pong!**\n⚡ `{elapsed:.2f} ms`")


@Client.on_message(filters.command("id") & filters.private)
async def id_command(client: Client, message: Message):
    """Return the user's Telegram ID (and target user if replying)."""
    lines = [f"🆔 **Your ID:** `{message.from_user.id}`"]
    if message.reply_to_message and message.reply_to_message.from_user:
        ru = message.reply_to_message.from_user
        lines.append(f"👤 **Target ID:** `{ru.id}` ({ru.first_name})")
    if message.reply_to_message and message.reply_to_message.forward_from:
        fu = message.reply_to_message.forward_from
        lines.append(f"🔁 **Forwarded-from ID:** `{fu.id}` ({fu.first_name})")
    await message.reply("\n".join(lines))
