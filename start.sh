#!/usr/bin/env bash
# ── StreamCast one-click launcher (Linux/Mac) ─────────────────────────────
set -e

cd "$(dirname "$0")"

if [ ! -d "env" ]; then
    echo "Creating virtual environment..."
    python3 -m venv env
fi

source env/bin/activate

echo "Installing/checking dependencies..."
pip install -r requirements.txt --quiet

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "No .env found - copying .env.example to .env"
        cp .env.example .env
        echo "Please edit .env with your API_ID, API_HASH and BOT_TOKEN, then run this script again."
        exit 1
    else
        echo "No .env file found. Please create one with API_ID, API_HASH and BOT_TOKEN."
        exit 1
    fi
fi

echo "Starting StreamCast..."
python3 bot.py
