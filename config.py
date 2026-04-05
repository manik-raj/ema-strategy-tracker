import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DB_PATH = os.path.join(os.path.dirname(__file__), "ema_tracker.db")

TIMEFRAMES = [
    ("1m", "1 Minute"),
    ("3m", "3 Minutes"),
    ("5m", "5 Minutes"),
    ("15m", "15 Minutes"),
    ("30m", "30 Minutes"),
    ("1h", "1 Hour"),
    ("2h", "2 Hours"),
    ("4h", "4 Hours"),
    ("6h", "6 Hours"),
    ("8h", "8 Hours"),
    ("12h", "12 Hours"),
    ("1d", "1 Day"),
    ("3d", "3 Days"),
    ("1w", "1 Week"),
    ("1M", "1 Month"),
]

# Binance kline interval mapping to python-binance constants
BINANCE_INTERVAL_MAP = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1d",
    "3d": "3d",
    "1w": "1w",
    "1M": "1M",
}
