#!/usr/bin/env python3
"""
verify_web.py — self-contained smoke test for the File-to-Link web layer.

Proves every web fix/upgrade works WITHOUT needing Telegram, MongoDB, or any
network. It stubs the `info` and `utils` modules and a fake DB, spins up the
real aiohttp app in-process, and asserts the behavior of every route.

Usage:
    pip install aiohttp jinja2
    python verify_web.py

Exit code 0 = all checks passed, 1 = a check failed.
"""
import asyncio
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))


def _install_stubs():
    """Stub the heavy app deps so web/app.py imports cleanly offline."""
    info = types.ModuleType("info")
    info.DB_CHANNEL = -100
    info.WEB_SERVER_BIND_ADDRESS = "0.0.0.0"
    info.WEB_SERVER_PORT = 8080
    info.SITE_NAME = "StreamLink"
    info.SITE_TAGLINE = "Generate instant links & stream anything."
    info.CREATOR_NAME = "Saqueeb"
    sys.modules["info"] = info

    utils = types.ModuleType("utils")

    def humanbytes(n):
        n = float(n)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"

    utils.humanbytes = humanbytes
    sys.modules["utils"] = utils


def _load_app_module():
    import importlib.util
    sys.path.insert(0, os.path.join(HERE, "web"))
    spec = importlib.util.spec_from_file_location(
        "webapp", os.path.join(HERE, "web", "app.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeDB:
    async def get_file(self, uid):
        if uid == "missing":
            return None
        return {
            "msg_id": 5,
            "file_size": 1234567,
            "file_name": "Demo Movie [HD].mkv",
            "mime_type": "video/x-matroska",
            "type": "video",
            "saved_at": "2026-06-01T00:00:00",
        }

    async def get_batch(self, bid):
        return {"status": "done", "files": ["f1", "f2"]}

    async def increment_stat(self, key):
        pass

    async def increment_file_stat(self, file_id, key, amount=1):
        pass


PASSED = 0
FAILED = 0


def check(label, cond):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  \u2705 {label}")
    else:
        FAILED += 1
        print(f"  \u274c {label}")


async def run():
    _install_stubs()
    webapp = _load_app_module()

    from aiohttp.test_utils import TestClient, TestServer

    app = webapp.create_app(client=object(), db=FakeDB(), base_url="https://example.test")
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        print("\nRoutes & security headers:")
        for path, expect in [
            ("/", 200), ("/file/abc", 200), ("/batch/B1", 200),
            ("/info/abc", 200), ("/robots.txt", 200), ("/sitemap.xml", 200),
            ("/static/theme.css", 200), ("/static/theme.js", 200),
            ("/static/favicon.svg", 200), ("/file/missing", 404),
        ]:
            r = await client.get(path)
            check(f"GET {path} -> {r.status} (want {expect})", r.status == expect)

        print("\nKey fixes:")
        r = await client.get("/info/abc")
        body = await r.text()
        check("/info/abc returns 200 JSON (was 500)",
              r.status == 200 and r.headers.get("Content-Type", "").startswith("application/json"))

        r = await client.get("/")
        check("Security headers present (CSP + X-Frame-Options)",
              "Content-Security-Policy" in r.headers and r.headers.get("X-Frame-Options") == "DENY")

        r = await client.head("/download/abc")
        check("HEAD /download -> 200 with Accept-Ranges",
              r.status == 200 and r.headers.get("Accept-Ranges") == "bytes")
        check("Streaming response NOT mutated with CSP (raw bytes safe)",
              "Content-Security-Policy" not in r.headers)

        print("\nRate limiter (/info, 120/min):")
        statuses = []
        for _ in range(130):
            rr = await client.get("/info/abc")
            statuses.append(rr.status)
        check("Returns 429 after the limit", 429 in statuses)
        check("Allows up to ~120 before limiting", statuses.count(200) >= 100)
    finally:
        await client.close()

    print(f"\n{'='*48}\n  PASSED: {PASSED}   FAILED: {FAILED}\n{'='*48}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run()))
    except ModuleNotFoundError as e:
        print(f"Missing dependency: {e}. Run: pip install aiohttp jinja2")
        sys.exit(2)
