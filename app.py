import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import database as db
from binance_client import get_spot_symbols
from tracker import run_tracker
from telegram_bot import start_bot, stop_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Flash message storage (in-memory, per-process)
_flash_messages: list[str] = []


def flash(msg: str):
    _flash_messages.append(msg)


def get_flashed_messages() -> list[str]:
    msgs = list(_flash_messages)
    _flash_messages.clear()
    return msgs


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.init_db()
    logger.info("Database initialized")

    # Sync .env values to DB as defaults (don't overwrite existing)
    if config.TELEGRAM_BOT_TOKEN:
        existing = await db.get_setting("telegram_bot_token")
        if not existing:
            await db.set_setting("telegram_bot_token", config.TELEGRAM_BOT_TOKEN)
    if config.TELEGRAM_CHAT_ID:
        existing = await db.get_setting("telegram_chat_id")
        if not existing:
            await db.set_setting("telegram_chat_id", config.TELEGRAM_CHAT_ID)

    await start_bot()

    scheduler.add_job(run_tracker, "interval", seconds=30, id="tracker_job")
    scheduler.start()
    logger.info("Tracker scheduler started (30s interval)")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    await stop_bot()
    logger.info("Application shut down")


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["get_flashed_messages"] = get_flashed_messages

# Cache for spot symbols (loaded once, refreshed on request)
_symbols_cache: list[str] = []


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    pairs = await db.get_all_tracking_pairs()
    alerts = await db.get_recent_alerts(limit=20)
    return templates.TemplateResponse(request, "dashboard.html", {
        "pairs": pairs,
        "alerts": alerts,
    })


@app.get("/add", response_class=HTMLResponse)
async def add_pair_form(request: Request):
    return templates.TemplateResponse(request, "add_pair.html", {
        "timeframes": config.TIMEFRAMES,
    })


@app.post("/add")
async def add_pair(symbol: str = Form(...), timeframe: str = Form(...)):
    success = await db.add_tracking_pair(symbol, timeframe)
    if success:
        flash(f"Added tracking pair: {symbol} ({timeframe})")
    else:
        flash(f"Tracking pair {symbol} ({timeframe}) already exists!")
    return RedirectResponse(url="/", status_code=303)


@app.post("/delete/{tp_id}")
async def delete_pair(tp_id: int):
    await db.delete_tracking_pair(tp_id)
    flash("Tracking pair deleted.")
    return RedirectResponse(url="/", status_code=303)


@app.post("/toggle/{tp_id}")
async def toggle_pair(tp_id: int):
    await db.toggle_tracking_pair(tp_id)
    flash("Tracking pair status updated.")
    return RedirectResponse(url="/", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    token = await db.get_setting("telegram_bot_token")
    chat_id = await db.get_setting("telegram_chat_id")
    muted = await db.get_setting("notifications_muted", "false")
    return templates.TemplateResponse(request, "settings.html", {
        "telegram_bot_token": token,
        "telegram_chat_id": chat_id,
        "notifications_muted": muted,
    })


@app.post("/settings")
async def save_settings(
    telegram_bot_token: str = Form(""),
    telegram_chat_id: str = Form(""),
    notifications_muted: str = Form(None),
):
    await db.set_setting("telegram_bot_token", telegram_bot_token)
    await db.set_setting("telegram_chat_id", telegram_chat_id)
    await db.set_setting("notifications_muted", "true" if notifications_muted else "false")
    flash("Settings saved successfully.")
    return RedirectResponse(url="/settings", status_code=303)


@app.get("/api/pairs")
async def api_pairs():
    global _symbols_cache
    if not _symbols_cache:
        try:
            _symbols_cache = get_spot_symbols()
        except Exception as e:
            logger.error(f"Failed to fetch Binance symbols: {e}")
            return []
    return _symbols_cache


if __name__ == "__main__":
    uvicorn.run("app:app", host=config.APP_HOST, port=config.APP_PORT, reload=False)
