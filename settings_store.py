"""
Persistent, bot-configurable settings store.

These settings used to live in `.env`. They now live here instead, in a
small JSON file on disk, and are configured by the admin from *inside*
Telegram (see plugins/setup.py) the first time the bot starts and later
via /settings.

Keys stored here: mongo_uri, admins, log_channel, db_channel,
force_sub_channel, site_name, site_tagline, bot_name, creator_name, url,
stream_mode, link_expiry_days, max_concurrent_transmissions.
"""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

SETTINGS_PATH = os.environ.get("SETTINGS_PATH", "bot_settings.json").strip() or "bot_settings.json"

DEFAULTS = {
    "mongo_uri": "",
    "admins": [],
    "log_channel": 0,
    "db_channel": 0,
    "force_sub_channel": 0,
    "site_name": "StreamLink",
    "site_tagline": "Generate instant links & stream anything — right in your browser.",
    "bot_name": "File-to-Link Bot",
    "creator_name": "Saqueeb",
    "url": "",
    "stream_mode": True,
    "link_expiry_days": None,
    "max_concurrent_transmissions": 24,
    "setup_complete": False,
}

_lock = threading.Lock()
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    data = dict(DEFAULTS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
            if isinstance(on_disk, dict):
                data.update(on_disk)
        except Exception as e:
            logger.warning("Could not read %s (%s) — using defaults.", SETTINGS_PATH, e)
    _cache = data
    return _cache


def _flush():
    data = _load()
    with _lock:
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, SETTINGS_PATH)


def get(key: str, default=None):
    data = _load()
    return data.get(key, DEFAULTS.get(key, default))


def get_all() -> dict:
    return dict(_load())


def set(key: str, value):
    data = _load()
    data[key] = value
    _flush()


def set_many(values: dict):
    data = _load()
    data.update(values)
    _flush()


def is_setup_complete() -> bool:
    return bool(get("setup_complete", False)) and bool(get("admins"))
