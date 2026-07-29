"""Render the whole report as one self-contained HTML page.

The page (app/report_template.html) is hand-written HTML, CSS and JS — the
scoreboard, the tabs, the sortable leaderboards and the you-are switch all live
there. Everything it needs is embedded as JSON at render time, so it needs no
server, no database and no network once rendered.

The Streamlit app embeds the result rather than rebuilding the UI out of
widgets: Streamlit's own DOM can't be styled into this layout, and maintaining
two versions of the design is what made them drift apart the first time.

  uv run python -m show_h2h.report   # writes a copy to dist/index.html
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from show_h2h import config, db

TEMPLATE = Path(__file__).resolve().parents[2] / "app" / "report_template.html"
OUT = Path(__file__).resolve().parents[2] / "dist" / "index.html"


def _clean(v):
    """JSON can't hold NaN/Infinity; emit null instead."""
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 4)
    return v


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    df = db.query(sql, params)
    return [{k: _clean(v) for k, v in rec.items()} for rec in df.to_dict("records")]


def _table(sql: str, game_index: dict[str, int], params: tuple = ()) -> dict:
    """Encode a per-game result set compactly for the browser.

    Every stat on the page can be filtered to "the last N games", which means
    the browser needs the per-game rows rather than the totals — 2,000 batting
    lines and 2,000 events. As a plain list of objects that's 618 KB, because
    every key and every repeated string is spelled out on every row.

    So: column names once, string columns replaced by an index into a small
    dictionary, and game_uuid replaced by its position. Same data, about a fifth
    the size, and the browser rebuilds objects in one pass.

    The first column must be the game uuid.
    """
    df = db.query(sql, params)
    cols = list(df.columns)
    dicts: dict[str, list] = {}
    data = []
    for rec in df.to_dict("records"):
        row = []
        for col in cols:
            value = _clean(rec[col])
            if col == "g":
                value = game_index.get(value, -1)
            elif isinstance(value, str):
                bucket = dicts.setdefault(col, [])
                if value not in bucket:
                    bucket.append(value)
                value = bucket.index(value)
            row.append(value)
        data.append(row)
    return {"cols": cols, "dicts": dicts, "data": data}


def build() -> dict:
    me, them = config.MY_USERNAME, config.FRIEND_USERNAME

    games = _rows("""
        SELECT g.game_uuid AS uuid, g.display_date AS d, g.played_at AS ts,
               g.home_username AS home, g.away_username AS away,
               g.home_runs AS hr, g.away_runs AS ar,
               g.home_hits AS hh, g.away_hits AS ah,
               g.home_errors AS he, g.away_errors AS ae,
               g.home_squad AS hs, g.away_squad AS asq,
               g.innings AS inn, (g.ruling <> '0') AS early, g.winner AS win
        FROM games g WHERE g.is_h2h = 1 ORDER BY g.played_at
    """)

    coop = _rows("""
        SELECT display_date AS d, home_username AS home, away_username AS away,
               home_runs AS hr, away_runs AS ar, home_squad AS hs, away_squad AS asq
        FROM v_coop_games ORDER BY played_at DESC
    """)

    # Per-game rows, so the page can re-aggregate for any "last N games" window.
    # Order matches `games` above, which is what the index refers to.
    index = {g["uuid"]: i for i, g in enumerate(games)}
    lines = {
        "bat": _table("""
            SELECT b.game_uuid AS g, b.username AS u, b.player_name AS p,
                   b.ab, b.h, b.hr, b.rbi, b.r, b.bb, b.so, b.sb, b.cs,
                   b.doubles AS d2, b.triples AS d3, b.hbp, b.sf, b.sh
            FROM batting_lines b JOIN games x ON x.game_uuid = b.game_uuid
            WHERE x.is_h2h = 1
        """, index),
        "pit": _table("""
            SELECT p.game_uuid AS g, p.username AS u, p.player_name AS p2,
                   p.outs AS o, p.so, p.bb, p.h, p.er, p.r,
                   p.win AS w, p.loss AS l, p.save AS sv, p.hold AS hld, p.slot AS s
            FROM pitching_lines p JOIN games x ON x.game_uuid = p.game_uuid
            WHERE x.is_h2h = 1
        """, index),
        "pa": _table("""
            SELECT e.game_uuid AS g, e.batting_username AS b, e.pitching_username AS t,
                   e.batter AS p, e.kind AS k, e.pitch_type AS pt, e.location AS lo,
                   e.timing AS ti, e.distance AS d, e.direction AS dir, e.go_ahead AS ga,
                   e.inning AS inn
            FROM pa_events e JOIN games x ON x.game_uuid = e.game_uuid
            WHERE x.is_h2h = 1
        """, index),
        # Half-innings carry the only pitch counts the API exposes, which is what
        # makes an immaculate inning detectable.
        "hi": _table('''
            SELECT h.game_uuid AS g, h.batting_username AS b, h.inning AS inn,
                   h.pitches AS pit, h.strikeouts AS k, h.runs AS r, h.idx
            FROM half_innings h JOIN games x ON x.game_uuid = h.game_uuid
            WHERE x.is_h2h = 1 ORDER BY h.game_uuid, h.idx
        ''', index),
        "pp": _table("""
            SELECT c.game_uuid AS g, c.username AS u, c.batter AS p,
                   c.exit_velo AS v, c.result AS res, c.outcome AS what
            FROM contact_events c JOIN games x ON x.game_uuid = c.game_uuid
            WHERE x.is_h2h = 1 AND c.username IS NOT NULL
        """, index),
    }

    latest = db.query("SELECT MAX(played_at) d FROM games WHERE is_h2h = 1").iloc[0]["d"]
    # When the pipeline last ran, which is the only signal that separates "you
    # haven't played in a week" from "the refresh has been broken for a week" —
    # the newest game's date can't tell those apart.
    checked = db.query("SELECT MAX(ran_at) t FROM import_log").iloc[0]["t"]
    return {
        "players": [me, them],
        "generated": db.now_iso()[:10],
        "through": (str(latest) or "")[:10],
        "checked": (str(checked) or "")[:10],
        "games": games,
        "coop": coop,
        "lines": lines,
    }


def render() -> str:
    """The full page, data baked in. This is what the Streamlit app embeds."""
    data = build()
    return TEMPLATE.read_text().replace(
        "/*__DATA__*/null", json.dumps(data, separators=(",", ":"), allow_nan=False))


def main() -> int:
    data = build()
    html = render()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    size = OUT.stat().st_size / 1024
    rows = sum(len(t["data"]) for t in data["lines"].values())
    print(f"Wrote {OUT} ({size:.0f} KB) — {len(data['games'])} games, {rows} per-game rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
