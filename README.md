# EMA Strategy Tracker

A FastAPI web app that tracks Binance trading pairs against the 21 EMA, detects trend changes and EMA retests, and sends Telegram alerts.

## Features

- **Dashboard** — View all tracking pairs with current trend, EMA value, last close price, and status
- **Add/Remove pairs** — Searchable dropdown of all Binance USDT spot pairs with timeframe selection (1m to 1M)
- **Pause/Resume** — Temporarily pause tracking for individual pairs
- **Trend Change Alerts** — Notifies when price closes above/below the 21 EMA, reversing the current trend
- **EMA Retest Alerts** — Notifies when price pulls back within 0.4% of the 21 EMA after a trend change
- **Multi-timeframe** — Track the same pair on multiple timeframes independently (e.g. BTCUSDT-1h and BTCUSDT-15m)
- **Telegram Bot** — `/mute`, `/unmute`, `/status` commands; supports multiple comma-separated chat IDs
- **Login** — Session-based authentication with bcrypt-hashed passwords (default: `admin`/`admin`)
- **Settings page** — Configure Telegram bot token, chat IDs, mute status, and change password from the UI

## Setup

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows Git Bash)
source venv/Scripts/activate

# Activate (Linux/macOS)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
```

Edit `.env` with your Telegram bot token and chat ID (optional — can also be configured from the Settings page):

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

## Running

```bash
python app.py
```

Open `http://localhost:8000` in your browser. Log in with the default credentials (`admin`/`admin`) and change the password from Settings.

## Architecture

Single Python web app — FastAPI backend serves Jinja2 templates (no separate frontend build).

| File | Purpose |
|------|---------|
| `app.py` | FastAPI routes, auth, lifespan (startup/shutdown), scheduler init |
| `tracker.py` | Core logic: fetches klines, calculates 21 EMA, detects trend changes and retests |
| `database.py` | SQLite via aiosqlite: CRUD for tracking_pairs, settings, alert_log |
| `binance_client.py` | Wrapper around python-binance (public API, no key needed) |
| `telegram_bot.py` | Telegram bot commands + alert sending to multiple chat IDs |
| `config.py` | Loads .env, defines timeframes and Binance interval mappings |
| `templates/` | Jinja2 HTML with Bootstrap 5 dark theme |
| `reference/` | Trading strategy documentation |

## How It Works

- A **Tracking Pair (TP)** is unique by `(symbol, timeframe)`, e.g. `BTCUSDT-1h`
- APScheduler polls Binance every **30 seconds** for all active tracking pairs
- **21 EMA** is calculated from the last 50 completed candles
- **Alert 1 — Trend Change**: fired when the last completed candle closes on the opposite side of the 21 EMA from the current trend
- **Alert 2 — EMA Retest**: fired once when price comes within 0.4% of the 21 EMA after a trend change
- Telegram config can come from the `.env` file or the dashboard Settings page (DB values take priority)
- SQLite database (`ema_tracker.db`) is auto-created on first run
