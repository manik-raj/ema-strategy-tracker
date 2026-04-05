import logging
from datetime import datetime, timezone
from binance_client import get_klines
from telegram_bot import send_alert
import database as db

logger = logging.getLogger(__name__)


def calculate_ema(closes: list[float], period: int = 21) -> float:
    """Calculate EMA for the given closing prices."""
    if len(closes) < period:
        # Not enough data — use simple average
        return sum(closes) / len(closes) if closes else 0.0

    k = 2.0 / (period + 1)
    # Seed EMA with SMA of first `period` values
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


async def check_tracking_pair(tp: dict):
    """Check a single tracking pair for trend change and EMA retest."""
    symbol = tp["symbol"]
    timeframe = tp["timeframe"]
    tp_id = tp["id"]

    try:
        closes = get_klines(symbol, timeframe, limit=50)
    except Exception as e:
        logger.error(f"Failed to fetch klines for {symbol} ({timeframe}): {e}")
        return

    if len(closes) < 21:
        logger.warning(f"Not enough data for {symbol} ({timeframe}): {len(closes)} candles")
        return

    ema = calculate_ema(closes, period=21)
    last_close = closes[-1]

    # Determine current trend based on last completed candle close vs EMA
    new_trend = "UPTREND" if last_close > ema else "DOWNTREND"
    old_trend = tp["current_trend"]

    # Calculate distance from EMA
    ema_distance_pct = abs(last_close - ema) / ema * 100.0

    # Update EMA value and last close in DB
    update_fields = {"ema_value": round(ema, 6), "last_close": round(last_close, 6)}

    # Alert 1: Trend Change
    if old_trend is not None and new_trend != old_trend:
        direction = "above" if new_trend == "UPTREND" else "below"
        emoji = "🟢" if new_trend == "UPTREND" else "🔴"
        msg = (
            f"{emoji} <b>{symbol} ({timeframe})</b>: Trend changed to <b>{new_trend}</b>\n"
            f"Price closed {direction} 21 EMA\n"
            f"Close: <code>{last_close:.4f}</code> | EMA: <code>{ema:.4f}</code>"
        )
        await send_alert(msg)
        await db.add_alert_log(tp_id, "TREND_CHANGE", msg)
        logger.info(f"Trend change alert: {symbol} ({timeframe}) -> {new_trend}")

        update_fields["current_trend"] = new_trend
        update_fields["trend_changed_at"] = datetime.now(timezone.utc).isoformat()
        update_fields["retest_alert_sent"] = 0

    elif old_trend is None:
        # First run — set initial trend without alerting
        update_fields["current_trend"] = new_trend
        update_fields["trend_changed_at"] = datetime.now(timezone.utc).isoformat()
        update_fields["retest_alert_sent"] = 0

    else:
        # Same trend — check for EMA retest
        # Alert 2: EMA Retest (price within 0.4% of EMA, after a trend change, only once)
        if not tp["retest_alert_sent"] and ema_distance_pct <= 0.4:
            msg = (
                f"📍 <b>{symbol} ({timeframe})</b>: Price retesting 21 EMA\n"
                f"Trend: <b>{old_trend}</b>\n"
                f"Price: <code>{last_close:.4f}</code> | EMA: <code>{ema:.4f}</code> "
                f"({ema_distance_pct:.2f}% away)"
            )
            await send_alert(msg)
            await db.add_alert_log(tp_id, "EMA_RETEST", msg)
            logger.info(f"EMA retest alert: {symbol} ({timeframe}) — {ema_distance_pct:.2f}% from EMA")
            update_fields["retest_alert_sent"] = 1

    await db.update_tracking_pair(tp_id, **update_fields)


async def run_tracker():
    """Main tracker loop — called every 30 seconds by the scheduler."""
    pairs = await db.get_active_tracking_pairs()
    if not pairs:
        return

    for tp in pairs:
        try:
            await check_tracking_pair(tp)
        except Exception as e:
            logger.error(f"Error tracking {tp['symbol']} ({tp['timeframe']}): {e}")
