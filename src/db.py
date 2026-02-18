"""
SQLite database for Syrian Telecom Self Portal.
Schema: settings (key/value), fetches (per-fetch rows), notifications (sent alerts).
"""
import os
import sqlite3
import bcrypt
from contextlib import contextmanager

DB_PATH = os.environ.get("PORTAL_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))

DEFAULT_SETTINGS = {
    "telecom_base_url": "http://syriantelecom.com.sy/Sync/selfPortal.php",
    "telecom_fid": "3",
    "telecom_username": "",
    "telecom_password": "",
    "telecom_lang": "1",
    "fetch_hour_1": "8",
    "fetch_hour_2": "20",
    "ntfy_url": "",
}


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fetches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at TEXT NOT NULL,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                month_accu_volume_kb INTEGER NOT NULL,
                max_service_usage_mb INTEGER NOT NULL,
                usage_percent REAL NOT NULL,
                exceed_day INTEGER,
                month_begin TEXT NOT NULL,
                month_end TEXT NOT NULL,
                raw_json TEXT
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month TEXT NOT NULL,
                threshold INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE(month, threshold)
            );
        """)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        cur = conn.execute("SELECT 1 FROM settings WHERE key = 'dashboard_password_hash'")
        if cur.fetchone() is None:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('dashboard_password_hash', ?)",
                (bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode(),),
            )


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        cur = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )


def get_all_settings() -> dict:
    with get_conn() as conn:
        cur = conn.execute("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in cur.fetchall()}


def set_settings(updates: dict) -> None:
    with get_conn() as conn:
        for key, value in updates.items():
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value)),
            )


def insert_fetch(
    fetched_at: str,
    product_id: str,
    product_name: str,
    month_accu_volume_kb: int,
    max_service_usage_mb: int,
    usage_percent: float,
    exceed_day: int | None,
    month_begin: str,
    month_end: str,
    raw_json: str | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO fetches (
                fetched_at, product_id, product_name, month_accu_volume_kb,
                max_service_usage_mb, usage_percent, exceed_day, month_begin, month_end, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fetched_at,
                product_id,
                product_name,
                month_accu_volume_kb,
                max_service_usage_mb,
                usage_percent,
                exceed_day,
                month_begin,
                month_end,
                raw_json,
            ),
        )
        return cur.lastrowid


def get_latest_fetch():
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM fetches ORDER BY fetched_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_history_for_month(month_begin: str) -> list:
    """month_begin: YYYY-MM-DD (start of billing month)."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM fetches WHERE month_begin = ? ORDER BY fetched_at ASC",
            (month_begin,),
        )
        return [dict(row) for row in cur.fetchall()]


def notification_sent(month: str, threshold: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT 1 FROM notifications WHERE month = ? AND threshold = ?",
            (month, threshold),
        )
        return cur.fetchone() is not None


def record_notification(month: str, threshold: int, sent_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO notifications (month, threshold, sent_at) VALUES (?, ?, ?)",
            (month, threshold, sent_at),
        )


def verify_password(password: str) -> bool:
    stored = get_setting("dashboard_password_hash", "")
    if not stored:
        return False
    return bcrypt.checkpw(password.encode(), stored.encode())


def set_dashboard_password(password: str) -> None:
    set_setting("dashboard_password_hash", bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode())


# Ensure schema exists as soon as db is imported (before scheduler or routes run)
init_db()
