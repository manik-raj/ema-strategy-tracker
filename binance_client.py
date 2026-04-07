from binance.client import Client
from config import BINANCE_INTERVAL_MAP

# Lazy-initialized client — avoids ping() call at import time
_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client("", "", {"timeout": 20})
    return _client


def get_klines(symbol: str, timeframe: str, limit: int = 50):
    """Fetch kline/candlestick data from Binance.
    Returns (closes, last_close_time) where closes is a list of floats
    and last_close_time is the close timestamp (ms) of the last completed candle.
    """
    client = _get_client()
    interval = BINANCE_INTERVAL_MAP.get(timeframe, timeframe)
    # limit+1 because the last candle may be incomplete (still open)
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit + 1)
    # Each kline: [open_time, open, high, low, close, volume, close_time, ...]
    # Exclude the last candle if it's still open (close_time in future)
    import time
    now_ms = int(time.time() * 1000)
    completed = [k for k in klines if k[6] <= now_ms]
    closes = [float(k[4]) for k in completed]
    last_close_time = completed[-1][6] if completed else 0
    return closes, last_close_time


def get_current_price(symbol: str) -> float:
    """Get the current ticker price for a symbol."""
    client = _get_client()
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])


def get_spot_symbols() -> list[str]:
    """Fetch all USDT spot trading pairs from Binance."""
    client = _get_client()
    info = client.get_exchange_info()
    symbols = []
    for s in info["symbols"]:
        if (
            s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
            and s["isSpotTradingAllowed"]
        ):
            symbols.append(s["symbol"])
    symbols.sort()
    return symbols
