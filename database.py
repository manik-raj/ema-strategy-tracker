import aiosqlite
from config import DB_PATH

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tracking_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                current_trend TEXT,
                trend_changed_at TEXT,
                retest_alert_sent INTEGER NOT NULL DEFAULT 0,
                retest_precision REAL NOT NULL DEFAULT 0.4,
                ema_value REAL,
                last_close REAL,
                last_candle_time INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(symbol, timeframe)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alert_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tp_id INTEGER NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (tp_id) REFERENCES tracking_pairs(id)
            )
        """)
        await db.commit()


async def get_all_tracking_pairs():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tracking_pairs ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_active_tracking_pairs():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tracking_pairs WHERE is_active = 1")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def add_tracking_pair(symbol: str, timeframe: str, retest_precision: float = 0.4):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO tracking_pairs (symbol, timeframe, retest_precision) VALUES (?, ?, ?)",
                (symbol.upper(), timeframe, retest_precision),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def delete_tracking_pair(tp_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM alert_log WHERE tp_id = ?", (tp_id,))
        await db.execute("DELETE FROM tracking_pairs WHERE id = ?", (tp_id,))
        await db.commit()


async def toggle_tracking_pair(tp_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tracking_pairs SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?",
            (tp_id,),
        )
        await db.commit()


async def update_tracking_pair(tp_id: int, **kwargs):
    if not kwargs:
        return
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [tp_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE tracking_pairs SET {set_clause} WHERE id = ?",
            values,
        )
        await db.commit()


async def add_alert_log(tp_id: int, alert_type: str, message: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO alert_log (tp_id, alert_type, message) VALUES (?, ?, ?)",
            (tp_id, alert_type, message),
        )
        await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value),
        )
        await db.commit()


async def get_recent_alerts(limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT a.*, t.symbol, t.timeframe
               FROM alert_log a
               JOIN tracking_pairs t ON a.tp_id = t.id
               ORDER BY a.created_at DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
