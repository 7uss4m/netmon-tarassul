import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from calendar import monthrange
import math

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
        cur = conn.execute("PRAGMA table_info(fetches)")
        cols = {row[1] for row in cur.fetchall()}
        if "is_midnight" not in cols:
            conn.execute("ALTER TABLE fetches ADD COLUMN is_midnight INTEGER NOT NULL DEFAULT 0")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS baseline_fetches (
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
    is_midnight: bool = False,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO fetches (
                fetched_at, product_id, product_name, month_accu_volume_kb,
                max_service_usage_mb, usage_percent, exceed_day, month_begin, month_end, raw_json, is_midnight
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                1 if is_midnight else 0,
            ),
        )
        return cur.lastrowid


def insert_baseline_fetch(
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
            """INSERT INTO baseline_fetches (
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


def get_latest_baseline_fetch():
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM baseline_fetches ORDER BY fetched_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_history_for_month(month_begin: str) -> list:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM fetches WHERE month_begin = ? ORDER BY fetched_at ASC",
            (month_begin,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_history_for_month_baseline(month_begin: str) -> list:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM baseline_fetches WHERE month_begin = ? ORDER BY fetched_at ASC",
            (month_begin,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_all_fetches(limit: int = 500, offset: int = 0) -> list:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM fetches WHERE is_midnight = 0 ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]


def notification_already_sent(month_begin: str, threshold: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT 1 FROM notifications WHERE month_begin = ? AND threshold = ?",
            (month_begin, threshold),
        )
        return cur.fetchone() is not None


def record_notification_sent(month_begin: str, threshold: int, sent_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO notifications (month_begin, threshold, sent_at) VALUES (?, ?, ?)",
            (month_begin, threshold, sent_at),
        )


def get_daily_usage(limit_days: int = 31) -> list:
    with get_conn() as conn:
        cur = conn.execute(
            """
            WITH baseline AS (
                SELECT product_id, date(fetched_at) AS d, month_accu_volume_kb AS vol
                FROM baseline_fetches
                WHERE fetched_at >= date('now', ?)
            ),
            latest_per_day AS (
                SELECT product_id, date(fetched_at) AS d, product_name, month_accu_volume_kb AS vol
                FROM fetches f1
                WHERE fetched_at >= date('now', ?)
                  AND fetched_at = (
                      SELECT max(fetched_at) FROM fetches f2
                      WHERE f2.product_id = f1.product_id AND date(f2.fetched_at) = date(f1.fetched_at)
                  )
            )
            SELECT l.d AS fetch_date, l.product_id, l.product_name,
                   (l.vol - b.vol) AS daily_usage_kb
            FROM latest_per_day l
            JOIN baseline b ON l.product_id = b.product_id AND l.d = b.d
            WHERE l.vol >= b.vol
            ORDER BY l.d DESC, l.product_id
            LIMIT 200
            """,
            (f"-{limit_days} days", f"-{limit_days} days"),
        )
        rows = cur.fetchall()
    out = []
    for row in rows:
        r = dict(row)
        kb = r.get("daily_usage_kb") or 0
        r["daily_usage_gb"] = round(kb / (1024 * 1024), 2)
        out.append(r)
    return out


def get_daily_usage_for_product_month(product_id: str, month_begin: str, lookback_days: int = 60) -> list:
    rows = get_daily_usage(limit_days=lookback_days)
    month_prefix = (month_begin or "")[:7]
    return [
        r for r in rows
        if r.get("product_id") == product_id and (r.get("fetch_date") or "").startswith(month_prefix)
    ]


def predict_exceed_day_from_daily_usage(
    product_id: str,
    month_begin: str,
    current_usage_gb: float,
    limit_gb: float,
) -> int | None:
    if not month_begin or current_usage_gb >= limit_gb:
        return None
    history = get_daily_usage_for_product_month(product_id, month_begin)
    if not history:
        return None
    avg_daily = sum(r.get("daily_usage_gb") or 0 for r in history) / len(history)
    if avg_daily <= 0:
        return None
    remaining_gb = max(0.0, limit_gb - current_usage_gb)
    days_needed = math.ceil(remaining_gb / avg_daily)
    try:
        start = date.fromisoformat(month_begin)
    except ValueError:
        return None
    year, month = start.year, start.month
    days_in_month = monthrange(year, month)[1]
    today = date.today()
    if today < start:
        today = start
    end = date(year, month, days_in_month)
    exceed_date = today + timedelta(days=days_needed)
    if exceed_date > end:
        exceed_date = end
    return exceed_date.day


init_db()
