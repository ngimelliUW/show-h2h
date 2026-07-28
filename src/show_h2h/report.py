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


def build() -> dict:
    me, them = config.MY_USERNAME, config.FRIEND_USERNAME

    games = _rows("""
        SELECT g.display_date AS d, g.played_at AS ts,
               g.home_username AS home, g.away_username AS away,
               g.home_runs AS hr, g.away_runs AS ar,
               g.home_hits AS hh, g.away_hits AS ah,
               g.home_squad AS hs, g.away_squad AS asq,
               g.innings AS inn, (g.ruling <> '0') AS early, g.winner AS win
        FROM games g WHERE g.is_h2h = 1 ORDER BY g.played_at
    """)

    batting = _rows("""
        SELECT username AS u, player_name AS p, games AS g, pa, ab, h, avg, obp, slg,
               ops, iso, hr, rbi, runs AS r, doubles AS d2, triples AS d3, bb, so,
               sb, cs, sb_pct AS sbp, babip, k_pct AS kp, bb_pct AS bbp
        FROM v_batting_totals ORDER BY hr DESC
    """)

    pitching = _rows("""
        SELECT username AS u, player_name AS p, games AS g, starts AS gs, innings AS ip,
               outs, so, k_per_9 AS k9, bb_per_9 AS bb9, k_bb AS kbb, era, ra9, whip,
               h, bb, er, wins AS w, losses AS l, saves AS sv, holds AS hld
        FROM v_pitching_totals ORDER BY so DESC
    """)

    team = {}
    for row in _rows("SELECT * FROM v_team_batting"):
        team.setdefault(row["username"], {})["bat"] = row
    for row in _rows("SELECT * FROM v_team_pitching"):
        team.setdefault(row["username"], {})["pit"] = row

    coop = _rows("""
        SELECT display_date AS d, home_username AS home, away_username AS away,
               home_runs AS hr, away_runs AS ar, home_squad AS hs, away_squad AS asq
        FROM v_coop_games ORDER BY played_at DESC
    """)

    latest = db.query("SELECT MAX(played_at) d FROM games WHERE is_h2h = 1").iloc[0]["d"]
    return {
        "players": [me, them],
        "generated": db.now_iso()[:10],
        "through": (str(latest) or "")[:10],
        "games": games,
        "batting": batting,
        "pitching": pitching,
        "team": team,
        "coop": coop,
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
    print(f"Wrote {OUT} ({size:.0f} KB) — {len(data['games'])} games, "
          f"{len(data['batting'])} batters, {len(data['pitching'])} pitchers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
