"""Import game_history.json for every configured account.

Both accounts are crawled because each one's history is the only place its own
`id` for a shared game appears, and game_log needs that id paired with that
username. Rows from the two crawls are collapsed onto one game via natural_key.
"""
from __future__ import annotations

import json

from show_h2h import client, config, db, identity


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _upsert_game(conn, entry: dict, queried_username: str) -> None:
    resolved = identity.resolve(entry, queried_username)
    nkey = identity.natural_key(entry)
    is_h2h = int(identity.is_head_to_head(resolved))

    home_runs, away_runs = _to_int(entry.get("home_runs")), _to_int(entry.get("away_runs"))
    winner = None
    if entry.get("home_display_result") == "W":
        winner = "home"
    elif entry.get("away_display_result") == "W":
        winner = "away"
    elif home_runs is not None and away_runs is not None and home_runs != away_runs:
        winner = "home" if home_runs > away_runs else "away"

    # game_uuid isn't available from this endpoint; use the natural key as a
    # placeholder primary key until a box score supplies the real uuid.
    conn.execute(
        """
        INSERT INTO games (
            game_uuid, natural_key, season_year, game_mode, played_at, display_date,
            innings, home_username, away_username, home_squad, away_squad,
            home_runs, away_runs, home_hits, away_hits, home_errors, away_errors,
            winner, display_pitcher_info, is_vs_cpu, is_h2h, is_third_party, raw, imported_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(natural_key) DO UPDATE SET
            game_mode=excluded.game_mode,
            played_at=excluded.played_at,
            innings=COALESCE(games.innings, excluded.innings),
            -- Only overwrite identity when the new row actually knows more:
            -- each crawl blanks its own user, so the two passes complete each
            -- other rather than clobbering.
            home_username=CASE WHEN excluded.home_username != '' AND excluded.home_username IS NOT NULL
                               THEN excluded.home_username ELSE games.home_username END,
            away_username=CASE WHEN excluded.away_username != '' AND excluded.away_username IS NOT NULL
                               THEN excluded.away_username ELSE games.away_username END,
            is_h2h=MAX(games.is_h2h, excluded.is_h2h),
            is_vs_cpu=excluded.is_vs_cpu,
            is_third_party=MIN(games.is_third_party, excluded.is_third_party),
            winner=excluded.winner,
            raw=excluded.raw,
            imported_at=excluded.imported_at
        """,
        (
            nkey, nkey, config.SEASON_YEAR, entry.get("game_mode"),
            identity.parse_date(entry.get("display_date")), entry.get("display_date"),
            None,
            resolved["home_username"], resolved["away_username"],
            resolved["home_squad"], resolved["away_squad"],
            home_runs, away_runs,
            _to_int(entry.get("home_hits")), _to_int(entry.get("away_hits")),
            _to_int(entry.get("home_errors")), _to_int(entry.get("away_errors")),
            winner, entry.get("display_pitcher_info"),
            resolved["is_vs_cpu"], is_h2h, resolved["is_third_party"],
            json.dumps(entry), db.now_iso(),
        ),
    )

    conn.execute(
        "INSERT INTO game_source_ids (game_uuid, natural_key, username, api_id, imported_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(natural_key, username) DO UPDATE SET api_id=excluded.api_id",
        (nkey, nkey, queried_username, entry.get("id"), db.now_iso()),
    )


def _flag_coop(conn) -> None:
    """Mark games both accounts were in but which aren't head-to-head.

    If a game shows up in both crawls yet the two of us weren't opponents, we
    were on the same side — a co-op game against someone else. (The API gives
    no co-op field; this is inferred purely from the game appearing in both
    histories, which is also how those records leak in at all.)
    """
    conn.execute("UPDATE games SET is_coop = 0")
    conn.execute(
        """
        UPDATE games SET is_coop = 1
        WHERE is_h2h = 0
          AND natural_key IN (
              SELECT natural_key FROM game_source_ids
              GROUP BY natural_key
              HAVING COUNT(DISTINCT LOWER(username)) > 1
          )
        """)


def run_import(conn=None, *, modes=("all", "exhibition"), incremental: bool = False) -> dict:
    """Crawl both accounts. Returns counts per username.

    mode='all' is a misnomer in this API — it excludes Exhibition games
    entirely, and the two result sets are disjoint. So both are crawled and
    merged. (Neither of our accounts has ever played an Exhibition game, but
    the crawl is one cheap request when empty.)
    """
    own = conn is None
    conn = conn or db.connect()
    counts: dict[str, int] = {}
    try:
        db.seed_players(conn)
        for username in config.USERNAMES:
            stop_at = None
            if incremental:
                stop_at = {r["api_id"] for r in conn.execute(
                    "SELECT api_id FROM game_source_ids WHERE username = ?", (username,))}
            total = 0
            for mode in modes:
                entries = client.game_history(username, mode=mode, stop_at_ids=stop_at)
                for entry in entries:
                    _upsert_game(conn, entry, username)
                total += len(entries)
            counts[username] = total
            conn.commit()
        _flag_coop(conn)
        conn.commit()
        db.log_import(conn, "game_history", None, None, sum(counts.values()))
    finally:
        if own:
            conn.close()
    return counts
