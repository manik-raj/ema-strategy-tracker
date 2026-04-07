import logging
import secrets
from contextlib import asynccontextmanager

import bcrypt
import uvicorn
from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
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


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.init_db()
    logger.info("Database initialized")

    # Create default admin account if none exists
    existing_user = await db.get_setting("auth_username")
    if not existing_user:
        await db.set_setting("auth_username", "admin")
        await db.set_setting("auth_password", hash_password("admin"))
        logger.info("Default admin account created (admin/admin)")

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
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["get_flashed_messages"] = get_flashed_messages

# Cache for spot symbols (loaded once, refreshed on request)
_symbols_cache: list[str] = []


# --- Auth dependency ---

async def require_login(request: Request):
    if not request.session.get("user"):
        raise _RedirectToLogin()


class _RedirectToLogin(Exception):
    pass


@app.exception_handler(_RedirectToLogin)
async def redirect_to_login(request: Request, exc: _RedirectToLogin):
    return RedirectResponse(url="/login", status_code=303)


# --- Auth routes (no login required) ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    stored_user = await db.get_setting("auth_username")
    stored_pass = await db.get_setting("auth_password")

    if stored_user and stored_pass and username == stored_user and verify_password(password, stored_pass):
        request.session["user"] = username
        flash(f"Welcome, {username}!")
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(request, "login.html", {
        "error": "Invalid username or password",
    })


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# --- Protected routes ---

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def dashboard(request: Request):
    pairs = await db.get_all_tracking_pairs()
    alerts = await db.get_recent_alerts(limit=20)
    return templates.TemplateResponse(request, "dashboard.html", {
        "pairs": pairs,
        "alerts": alerts,
    })


@app.get("/add", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def add_pair_form(request: Request):
    return templates.TemplateResponse(request, "add_pair.html", {
        "timeframes": config.TIMEFRAMES,
    })


@app.post("/add", dependencies=[Depends(require_login)])
async def add_pair(symbol: str = Form(...), timeframe: str = Form(...), retest_precision: float = Form(0.4)):
    retest_precision = max(0.01, min(10.0, retest_precision))
    success = await db.add_tracking_pair(symbol, timeframe, retest_precision)
    if success:
        flash(f"Added tracking pair: {symbol} ({timeframe})")
    else:
        flash(f"Tracking pair {symbol} ({timeframe}) already exists!")
    return RedirectResponse(url="/", status_code=303)


@app.post("/delete/{tp_id}", dependencies=[Depends(require_login)])
async def delete_pair(tp_id: int):
    await db.delete_tracking_pair(tp_id)
    flash("Tracking pair deleted.")
    return RedirectResponse(url="/", status_code=303)


@app.post("/toggle/{tp_id}", dependencies=[Depends(require_login)])
async def toggle_pair(tp_id: int):
    await db.toggle_tracking_pair(tp_id)
    flash("Tracking pair status updated.")
    return RedirectResponse(url="/", status_code=303)


@app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def settings_page(request: Request):
    token = await db.get_setting("telegram_bot_token")
    chat_id = await db.get_setting("telegram_chat_id")
    muted = await db.get_setting("notifications_muted", "false")
    return templates.TemplateResponse(request, "settings.html", {
        "telegram_bot_token": token,
        "telegram_chat_id": chat_id,
        "notifications_muted": muted,
    })


@app.post("/settings", dependencies=[Depends(require_login)])
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


@app.post("/change-password", dependencies=[Depends(require_login)])
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
):
    stored_pass = await db.get_setting("auth_password")
    if not verify_password(current_password, stored_pass):
        flash("Current password is incorrect.")
        return RedirectResponse(url="/settings", status_code=303)
    await db.set_setting("auth_password", hash_password(new_password))
    flash("Password changed successfully.")
    return RedirectResponse(url="/settings", status_code=303)


@app.get("/api/pairs", dependencies=[Depends(require_login)])
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
