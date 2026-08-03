"""SQLite connection + helpers. Canonical store in WAL mode."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

from show_h2h import config


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


# Columns added after the first version shipped. CREATE TABLE IF NOT EXISTS
# won't add them to an existing database, and re-crawling box scores just to
# gain a column would be silly, so add them in place.
_MIGRATIONS = {
    "games": [("is_coop", "INTEGER NOT NULL DEFAULT 0")],
    # Re-parsing fills these in; it reads stored text, so it costs no network.
    "pa_events": [("rbi", "INTEGER")],
    "half_innings": [("double_plays", "INTEGER NOT NULL DEFAULT 0"),
                     ("triple_plays", "INTEGER NOT NULL DEFAULT 0")],
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table doesn't exist yet; the schema script will create it
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _retime(conn: sqlite3.Connection) -> int:
    """Re-derive games.played_at from the original API string.

    The API reports UTC and it used to be stored verbatim, as if it were local
    time — so most games were filed under the wrong day and evening sessions
    looked like 4am ones. display_date still holds the untouched original, so
    every row can simply be recomputed.

    Idempotent by construction: it writes only where the stored value differs
    from what the parser now produces, so it is free to run on every boot and
    fixes a database in place without a version stamp to keep in sync.
    """
    from show_h2h import identity

    rows = conn.execute(
        "SELECT game_uuid, display_date, played_at FROM games").fetchall()
    stale = [(want, r["game_uuid"]) for r in rows
             if (want := identity.parse_date(r["display_date"]))
             and want != r["played_at"]]
    if stale:
        conn.executemany("UPDATE games SET played_at = ? WHERE game_uuid = ?", stale)
    return len(stale)


def init_db(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or connect()
    try:
        _migrate(conn)
        conn.executescript(config.SCHEMA_PATH.read_text())
        seed_players(conn)
        _retime(conn)
        conn.commit()
    finally:
        if own:
            conn.close()


def seed_players(conn: sqlite3.Connection) -> None:
    """Make sure both accounts exist, so views that join on is_me work."""
    for username in config.USERNAMES:
        conn.execute(
            "INSERT INTO players (username, platform, is_me, imported_at) VALUES (?,?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET platform=excluded.platform, is_me=excluded.is_me",
            (username, config.PLATFORM,
             1 if username.lower() == config.MY_USERNAME.lower() else 0, now_iso()),
        )


def log_import(conn: sqlite3.Connection, source: str, start, end, rows: int) -> None:
    conn.execute(
        "INSERT INTO import_log (source, range_start, range_end, rows, ran_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (source, str(start) if start else None, str(end) if end else None, rows, now_iso()),
    )
    conn.commit()


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a read query and return a DataFrame. Convenience for analysis."""
    conn = connect()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
