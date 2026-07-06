"""
Utility script — run standalone (not via bot.py).
Usage:  python Script.py
"""

import asyncio
import sys
import os

if sys.version_info >= (3, 10):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from dotenv import load_dotenv
load_dotenv()

from pyrogram import Client
from info import API_ID, API_HASH, BOT_TOKEN, DB_CHANNEL


async def main():
    print("Connecting to Telegram…")
    async with Client("script_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN) as app:
        me = await app.get_me()
        print(f"Logged in as @{me.username} (id={me.id})")

        # Example: send a test message to the log channel
        # await app.send_message(LOG_CHANNEL, "Script test message")

        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
