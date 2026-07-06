# 🎬 StreamCast

**StreamCast** turns any file sent to your Telegram bot into an instant, shareable web link — with seek-anywhere streaming, fast parallel downloads, batch link bundles, and a full admin suite. No self-hosted file storage to manage: Telegram is the storage layer, StreamCast is the link + streaming layer on top.

> It's a link-generation + streaming platform, not a file-storage service.
> The website is fully white-labelable — your own name, tagline, and branding.

---

## ✨ Features

| | |
|---|---|
| ⚡ **Instant Link Generation** | Send a file → get a clean `/file`, `/stream` and `/download` link in seconds |
| ▶️ **Seek-Anywhere Streaming** | YouTube-like player with HTTP Range support — jump anywhere without downloading the whole file |
| 🔀 **Parallel Downloads** | Multiple downloads/streams run at once, with resume support — no more "stuck loading" |
| 📊 **Per-file Counters** | Every file page shows views · streams · downloads |
| 📦 **Batch Links** | Bundle many files behind a single shareable page |
| 👤 **Optional Uploader Info** | Toggle an "Uploaded by" block (name, username, ID, timestamp) on stored files — off by default |
| 🎨 **White-label Branding** | Set your own `SITE_NAME` and `SITE_TAGLINE` |
| 💾 **Survives Restarts** | MongoDB, or a disk-persisted in-memory fallback if you don't have one |
| 🛡️ **Admin Suite** | Stats, bans, broadcasts, recent files, live server status |
| 🔐 **Secure First-run Claim** | Rotating console code (or fixed passphrase) so a stranger can't grab admin before you do |

---

## 🌐 Web Pages

| URL | Description |
|---|---|
| `/` | Landing page (your brand) |
| `/file/<id>` | File page — thumbnail, stream player, download button, live counters |
| `/batch/<id>` | Grid of all files in a batch |
| `/stream/<id>` | Direct stream with Range support (video seeking works) |
| `/download/<id>` | Force download (attachment) |
| `/thumbnail/<id>` | Thumbnail image for video/photo |
| `/info/<id>` | File metadata as JSON |
| `/health` | Health check endpoint |
| `/robots.txt` | Robots.txt file |
| `/sitemap.xml` | Sitemap.xml file |

---

## 🖱️ One-Click Start

After filling in your `.env` (see below), you can launch StreamCast without typing any commands:

- **Windows** — double-click `start.bat`
- **Linux / Mac** — double-click `start.sh`, or run `./start.sh` in a terminal

Both scripts create the virtual environment, install dependencies, and start the bot automatically. If no `.env` exists yet, they'll copy `.env.example` to `.env` and pause so you can fill it in first.

## 🚀 Quick Start (Manual)

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/streamcast.git
cd streamcast

# 2. Create and activate a virtual environment
python -m venv env
source env/bin/activate        # Windows: env\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env           # then fill in the required values below

# 5. Run it
python bot.py
```

Then message your bot on Telegram and follow the first-run claim + setup wizard — see below.

---

## 📊 Environment Variables

Only a handful of things need to live in `.env`. Everything else — channels, admins, branding, the web URL, database, uploader-info toggle, and more — is configured from inside Telegram (see [Configuring everything else](#-configuring-everything-else--from-inside-telegram)).

```makefile
# ── Required ──────────────────────────────────────────────────────────
API_ID=your_api_id                 # number from https://my.telegram.org/apps
API_HASH=your_api_hash             # string from the same page
BOT_TOKEN=your_bot_token           # from @BotFather

# ── Optional ────────────────────────────────────────────────────────────
BOT_USERNAME=your_bot_username     # cosmetic only; the real one is fetched live
PORT=8080                          # usually set for you by your host (e.g. Railway)
# WEB_SERVER_BIND_ADDRESS=0.0.0.0  # only needed for non-default binding
# LOCAL_DB_PATH=local_db.json      # only used when no MongoDB URI is configured
# OWNER_SECRET=some-long-random-string   # optional fixed passphrase; see below (default is a rotating console code, no setup needed)
```

---

## 🔐 Claiming Ownership on First Run

To stop a stranger from messaging the bot first and becoming admin by accident, claiming ownership is protected automatically — no configuration needed:

- On startup, the bot prints a **rotating 6-digit code** to its console every 2 minutes (never written to a file, never sent over Telegram by the bot itself).
- Whoever messages the bot first is asked for that code. Only someone watching the live console/logs at that moment can answer correctly.
- Codes expire automatically — the previous code is still accepted for one extra rotation as a grace window, then it's gone for good.

Prefer a fixed passphrase instead of a rotating code? Set `OWNER_SECRET` to a long random string in your hosting environment before deploying — the first message will be asked for that exact value instead, and console code printing is skipped entirely.

---

## 🔧 Configuring Everything Else — From Inside Telegram

Once ownership is claimed, that admin is walked through a one-time setup wizard covering:

- **DB_CHANNEL** — where uploaded files are stored (bot must be admin there)
- **LOG_CHANNEL** / **FORCE_SUB_CHANNEL** — optional
- **MONGO_URI** — optional; falls back to a local on-disk store
- **URL** — your public web address; setting this turns the web portal on automatically
- **SITE_NAME** / **SITE_TAGLINE** — branding shown on the website
- **BOT_NAME** / **CREATOR_NAME** — branding shown inside Telegram
- **MAX_CONCURRENT_TRANSMISSIONS**, **STREAM_MODE**, **LINK_EXPIRY_DAYS**

Re-run the full wizard any time with `/setup`, or change a single value with `/settings`. Everything is stored in `bot_settings.json` (or MongoDB, if configured), not `.env`.

### 👤 Uploader Info Toggle

By default, stored-file captions only show the filename. Admins who want to see *who* uploaded a file can turn on an extra block showing name, `@username`, numeric user ID, and upload timestamp:

- Open `/settings` → **"👤 Show Uploader Info"** → reply `yes` (or `no` to turn it back off)
- Off by default, and deliberately kept out of the required first-run wizard — it's opt-in, whenever an admin wants it, not something the bot decides for you
- Takes effect immediately, no restart required

---

## 👤 Creator

Created by **Saqueeb**.

## 👥 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/new-feature`
3. Commit your changes: `git commit -m "Add new feature"`
4. Push and open a pull request: `git push origin feature/new-feature`

---

## 📜 License

Licensed under the [MIT License](https://opensource.org/licenses/MIT).
