import asyncio
import logging
import threading
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
import database as db

logger = logging.getLogger(__name__)

_bot_app: Application | None = None
_bot_thread: threading.Thread | None = None


async def _send_message(token: str, chat_ids: str, text: str):
    """Send a message via Telegram bot to all comma-separated chat IDs."""
    if not token or not chat_ids:
        logger.warning("Telegram not configured — skipping message")
        return
    bot = Bot(token=token)
    for cid in chat_ids.split(","):
        cid = cid.strip()
        if not cid:
            continue
        try:
            await bot.send_message(chat_id=cid, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send Telegram message to {cid}: {e}")


async def send_alert(text: str):
    """Send an alert using settings from the database."""
    muted = await db.get_setting("notifications_muted", "false")
    if muted == "true":
        logger.info("Notifications muted — skipping alert")
        return

    token = await db.get_setting("telegram_bot_token")
    chat_id = await db.get_setting("telegram_chat_id")

    if not token:
        from config import TELEGRAM_BOT_TOKEN
        token = TELEGRAM_BOT_TOKEN
    if not chat_id:
        from config import TELEGRAM_CHAT_ID
        chat_id = TELEGRAM_CHAT_ID

    await _send_message(token, chat_id, text)


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("notifications_muted", "true")
    await update.message.reply_text("🔇 Notifications muted. Use /unmute to re-enable.")


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("notifications_muted", "false")
    await update.message.reply_text("🔔 Notifications unmuted.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs = await db.get_all_tracking_pairs()
    muted = await db.get_setting("notifications_muted", "false")

    lines = [f"<b>EMA Tracker Status</b>"]
    lines.append(f"Notifications: {'🔇 Muted' if muted == 'true' else '🔔 Active'}\n")

    if not pairs:
        lines.append("No tracking pairs configured.")
    else:
        for p in pairs:
            status = "✅ Active" if p["is_active"] else "⏸️ Paused"
            trend = p["current_trend"] or "Unknown"
            lines.append(f"• <b>{p['symbol']}</b> ({p['timeframe']}) — {trend} [{status}]")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def _run_bot_loop(token: str):
    """Run the Telegram bot in a separate thread with its own event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _start():
        global _bot_app
        app = Application.builder().token(token).build()
        app.add_handler(CommandHandler("mute", cmd_mute))
        app.add_handler(CommandHandler("unmute", cmd_unmute))
        app.add_handler(CommandHandler("status", cmd_status))
        _bot_app = app
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

    loop.run_until_complete(_start())


async def start_bot():
    """Start the Telegram bot in a background thread."""
    global _bot_thread

    token = await db.get_setting("telegram_bot_token")
    if not token:
        from config import TELEGRAM_BOT_TOKEN
        token = TELEGRAM_BOT_TOKEN

    if not token:
        logger.warning("No Telegram bot token configured — bot not started")
        return

    _bot_thread = threading.Thread(target=_run_bot_loop, args=(token,), daemon=True)
    _bot_thread.start()
    logger.info("Telegram bot started in background thread")


async def stop_bot():
    """Signal the bot to stop."""
    global _bot_app
    if _bot_app:
        logger.info("Stopping Telegram bot...")
        try:
            await _bot_app.updater.stop()
            await _bot_app.stop()
            await _bot_app.shutdown()
        except Exception as e:
            logger.error(f"Error stopping Telegram bot: {e}")
        _bot_app = None
