@echo off
REM ── StreamCast one-click launcher (Windows) ──────────────────────────────
setlocal

cd /d "%~dp0"

if not exist env (
    echo Creating virtual environment...
    python -m venv env
)

call env\Scripts\activate.bat

echo Installing/checking dependencies...
pip install -r requirements.txt --quiet

if not exist .env (
    if exist .env.example (
        echo No .env found - copying .env.example to .env
        copy .env.example .env
        echo Please edit .env with your API_ID, API_HASH and BOT_TOKEN, then run this script again.
        pause
        exit /b 1
    ) else (
        echo No .env file found. Please create one with API_ID, API_HASH and BOT_TOKEN.
        pause
        exit /b 1
    )
)

echo Starting StreamCast...
python bot.py

pause
