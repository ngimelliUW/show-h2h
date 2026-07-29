"""CLI: python -m show_h2h.ingest <command> [options]

Examples:
  uv run python -m show_h2h.ingest init-db
  uv run python -m show_h2h.ingest history            # full backfill, both accounts
  uv run python -m show_h2h.ingest box-scores         # box scores for H2H games
  uv run python -m show_h2h.ingest box-scores --all   # ...for every game, not just H2H
  uv run python -m show_h2h.ingest refresh            # incremental: new games only
  uv run python -m show_h2h.ingest status             # what's in the database
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3

from show_h2h import config, db


# Tables whose row counts should never fall between snapshots.
TRACKED_TABLES = ("games", "game_source_ids", "batting_lines", "pitching_lines",
                  "game_innings", "game_log_text", "pa_events", "contact_events",
                  "half_innings")


def _table_counts(path) -> dict[str, int]:
    """Row counts per table, for the never-shrink guard in `snapshot`."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        out = {}
        for table in TRACKED_TABLES:
            try:
                out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                out[table] = 0
        return out
    finally:
        conn.close()


def _status() -> None:
    rows = db.query("""
        SELECT
          (SELECT COUNT(*) FROM games)                        AS games,
          (SELECT COUNT(*) FROM games WHERE is_h2h = 1)       AS h2h,
          (SELECT COUNT(*) FROM games WHERE is_coop = 1)      AS coop,
          (SELECT COUNT(*) FROM games WHERE is_vs_cpu = 1)    AS vs_cpu,
          (SELECT COUNT(*) FROM games WHERE has_box_score = 1) AS box_scores,
          (SELECT COUNT(*) FROM batting_lines)                AS batting_lines,
          (SELECT COUNT(*) FROM pitching_lines)               AS pitching_lines
    """).iloc[0]
    print(f"  games          {rows['games']}")
    print(f"  head-to-head   {rows['h2h']}")
    print(f"  co-op together {rows['coop']}")
    print(f"  vs CPU         {rows['vs_cpu']}")
    print(f"  box scores     {rows['box_scores']}")
    print(f"  batting lines  {rows['batting_lines']}")
    print(f"  pitching lines {rows['pitching_lines']}")

    rec = db.query("SELECT * FROM v_h2h_record")
    if not rec.empty and rec.iloc[0]["games"]:
        r = rec.iloc[0]
        print(f"\n  {config.MY_USERNAME} vs {config.FRIEND_USERNAME}: "
              f"{int(r['wins'])}-{int(r['losses'])} ({r['win_pct']}), "
              f"runs {int(r['runs_for'])}-{int(r['runs_against'])}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="show_h2h.ingest")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create the database schema.")

    h = sub.add_parser("history", help="Crawl game history for both accounts.")
    h.add_argument("--incremental", action="store_true",
                   help="Stop once a page contains only games we already have.")

    b = sub.add_parser("box-scores", help="Fetch full box scores.")
    b.add_argument("--scope", choices=("both-played", "h2h", "all"), default="both-played",
                   help="both-played (default): every game we were both in, as opponents or "
                        "teammates. h2h: rivalry games only. all: every game either of us "
                        "played (several hundred more requests).")
    b.add_argument("--limit", type=int, help="Cap how many to fetch this run.")

    sub.add_parser("parse-logs", help="Re-parse stored play-by-play into events (no network).")
    sn = sub.add_parser("snapshot", help="Write data/seed.db — the copy the hosted app ships with.")
    sn.add_argument("--force", action="store_true",
                    help="Publish even if the new database has fewer rows than the current seed.")
    sub.add_parser("refresh", help="Incremental history + any missing H2H box scores.")
    sub.add_parser("status", help="Show what's in the database.")
    sub.add_parser("counts", help="Row counts as JSON — used to detect whether a refresh changed anything.")

    args = ap.parse_args(argv)

    db.init_db()

    if args.command == "init-db":
        print(f"Initialized schema at {db.config.DB_PATH}")
        return 0

    if args.command == "history":
        from show_h2h.importers import game_history

        print(f"Crawling game history from {config.BASE_URL} ...")
        counts = game_history.run_import(incremental=args.incremental)
        for user, n in counts.items():
            print(f"  {user}: {n} games")
        _status()
        return 0

    if args.command == "box-scores":
        from show_h2h.importers import game_log

        print(f"Fetching box scores (scope: {args.scope}) ...")
        res = game_log.run_import(scope=args.scope, limit=args.limit)
        print(f"  imported {res['imported']}, failed {res['failed']}, pending {res['pending']}")
        return 0 if res["failed"] == 0 else 1

    if args.command == "snapshot":
        # The working database is written constantly and lives in WAL mode, so
        # copying the file alone can miss recent writes. Checkpoint first, then
        # publish to a path nothing ever writes to — a file the hosted container
        # has modified will not accept a git pull, which is how the deploy ended
        # up pinned to a months-old database.
        conn = db.connect()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        finally:
            conn.close()

        seed = config.DATA_DIR / "seed.db"
        counts = _table_counts(config.DB_PATH)
        # This runs unattended every night. A crawl that half-failed would
        # otherwise publish a database with games missing, and the loss would be
        # committed over the good copy. Rows should only ever grow.
        if seed.exists() and not args.force:
            published = _table_counts(seed)
            shrunk = {t: (published[t], counts[t]) for t in published
                      if counts.get(t, 0) < published[t]}
            if shrunk:
                print("Refusing to publish — the new database has FEWER rows:")
                for table, (was, now) in shrunk.items():
                    print(f"  {table}: {was} -> {now}")
                print("Re-run the ingest, or pass --force if this is intentional.")
                return 1

        shutil.copy2(config.DB_PATH, seed)
        print(f"Wrote {seed} ({seed.stat().st_size / 1024 / 1024:.1f} MB) — "
              + ", ".join(f"{n} {t}" for t, n in sorted(counts.items()) if n))
        return 0

    if args.command == "parse-logs":
        from show_h2h.importers import play_by_play

        print("Parsing stored play-by-play ...")
        res = play_by_play.run_import()
        print(f"  {res['games']} games -> {res['events']} events, "
              f"{res['contacts']} perfect-contact balls")
        return 0

    if args.command == "refresh":
        from show_h2h.importers import game_history, game_log, play_by_play

        print("Refreshing ...")
        ok = True
        try:
            counts = game_history.run_import(incremental=True)
            print(f"  history: {sum(counts.values())} games seen "
                  f"({', '.join(f'{u} {n}' for u, n in counts.items())})")
        except Exception as e:  # keep going so one bad step doesn't block the other
            ok = False
            print(f"  history: FAILED — {e}")
        try:
            res = game_log.run_import(scope="both-played")
            print(f"  box scores: {res['imported']} new, {res['failed']} failed")
        except Exception as e:
            ok = False
            print(f"  box scores: FAILED — {e}")
        try:
            res = play_by_play.run_import()
            print(f"  play-by-play: {res['events']} events from {res['games']} games")
        except Exception as e:
            ok = False
            print(f"  play-by-play: FAILED — {e}")
        _status()
        return 0 if ok else 1

    if args.command == "counts":
        # A SQLite file's bytes change on every checkpoint even when no row did,
        # so the nightly job compares these instead of diffing the binary. That
        # keeps it from committing an identical database every night.
        print(json.dumps(_table_counts(config.DB_PATH), sort_keys=True))
        return 0

    if args.command == "status":
        _status()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
