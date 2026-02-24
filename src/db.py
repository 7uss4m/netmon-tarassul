"""
SQLite database for Netmon Tarassul.
Schema: fetches + notifications (ntfy sent per month/threshold). All settings and admin auth come from netmon.conf.
"""
import os
import sqlite3
from contextlib import contextmanager

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_project_root, "data", "data.db")


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


def _notifications_schema_ok(conn: sqlite3.Connection) -> bool:
    """True if notifications table has expected columns (month_begin, threshold, sent_at)."""
    cur = conn.execute("PRAGMA table_info(notifications)")
    names = {row[1] for row in cur.fetchall()}
    return "month_begin" in names and "threshold" in names and "sent_at" in names


def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with get_conn() as conn:
        conn.execute("""
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
            )
        """)
        # Recreate notifications if it exists with wrong schema (e.g. old deployment)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='notifications'"
        )
        if cur.fetchone():
            if not _notifications_schema_ok(conn):
                conn.execute("DROP TABLE notifications")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month_begin TEXT NOT NULL,
                threshold INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE(month_begin, threshold)
            )
        """)


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


def get_all_fetches(limit: int = 500, offset: int = 0) -> list:
    """All fetch records, newest first (paginated)."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM fetches ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]


def notification_already_sent(month_begin: str, threshold: int) -> bool:
    """True if we already sent ntfy for this month and threshold."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT 1 FROM notifications WHERE month_begin = ? AND threshold = ?",
            (month_begin, threshold),
        )
        return cur.fetchone() is not None


def record_notification_sent(month_begin: str, threshold: int, sent_at: str) -> None:
    """Record that ntfy was sent for this month/threshold (idempotent via UNIQUE)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO notifications (month_begin, threshold, sent_at) VALUES (?, ?, ?)",
            (month_begin, threshold, sent_at),
        )


# Ensure schema exists as soon as db is imported
init_db()
