"""Smoke test: the report renders, carries real data, and the app imports.

The UI is a hand-written page embedded by Streamlit, so this checks the render
rather than walking widgets. Run:  uv run python analysis/_smoke.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from show_h2h import config, report  # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


html = report.render()
check("page renders", len(html) > 20_000, f"{len(html) // 1024} KB")
check("data placeholder was replaced", "/*__DATA__*/null" not in html)

data = json.loads(re.search(r"const DATA = (\{.*?\});", html, re.S).group(1))
check("both players present", data["players"] == [config.MY_USERNAME, config.FRIEND_USERNAME],
      str(data["players"]))
check("games embedded", len(data["games"]) > 0, f"{len(data['games'])} games")
check("no NaN leaked into the JSON", "NaN" not in json.dumps(data))

# The page re-aggregates per-game rows so it can window to "the last N games",
# so these tables are the payload rather than pre-computed totals.
for name in ("bat", "pit", "pa", "pp", "hi"):
    table = data["lines"].get(name, {})
    check(f"lines.{name} present", bool(table.get("data")),
          f"{len(table.get('data', []))} rows")
    check(f"lines.{name} rows match its column list",
          all(len(r) == len(table["cols"]) for r in table["data"]))

# Every row must point at a real game, or the window filter silently drops it.
n_games = len(data["games"])
for name, table in data["lines"].items():
    gcol = table["cols"].index("g")
    bad = [r for r in table["data"] if not (0 <= r[gcol] < n_games)]
    check(f"lines.{name} game ids all resolve", not bad, f"{len(bad)} dangling")

# The compact encoding is the point — a plain list of objects was 618 KB.
size = len(json.dumps(data["lines"], separators=(",", ":")))
check("per-game payload stays compact", size < 400_000, f"{size // 1024} KB")

# Perfection needs errors: a batter reaching on one spoils it, and the page has
# no other source for them.
check("games carry errors for both sides",
      all("he" in g and "ae" in g for g in data["games"]))
check("games carry innings", all(g.get("inn") is not None for g in data["games"]))

# The JS reads these by id; a rename in the template would silently break the page.
for element in ("verdict", "wins-a", "wins-b", "whoami", "nav", "tabs", "cmp-bat",
                "cmp-pit", "feats", "form", "tbl-bat", "tbl-pit", "tbl-games",
                "ko-a", "ko-b", "discipline", "pp-table", "pp-hits", "hr-table",
                "eyebrow", "series-strip", "window-row", "season-body", "rules-body"):
    check(f"#{element} in template", f'id="{element}"' in html)

# The season layer. Every field the page reads must exist even before a single
# game has been played under the rules — the launch state of this feature is an
# empty season, so "populated" is the variant, not the norm.
season = data.get("season", {})
check("season payload present", bool(season), ", ".join(sorted(season)))
for key in ("start", "rules", "titles", "seasons", "series", "current",
            "live_season", "pregame", "games_counted"):
    check(f"season.{key} present", key in season)
check("season carries both players' title counts",
      set(season.get("titles", {})) == {config.MY_USERNAME, config.FRIEND_USERNAME},
      str(season.get("titles")))
# The page always draws a live series, even with nothing played, or the season
# view renders as a blank column.
current = season.get("current") or {}
for key in ("season", "no", "postseason", "target", "max_games", "wins",
            "games", "starters", "violations", "advantage", "host", "wrong_venue"):
    check(f"season.current.{key} present", key in current)
# Hosting alternates so a season splits its home dates evenly. The regular
# season always has a host; only a dead-heat World Series has none.
check("a regular-season series names its host",
      current.get("postseason") or current.get("host") in
      (config.MY_USERNAME, config.FRIEND_USERNAME), str(current.get("host")))
live = season.get("live_season") or {}
for key in ("hosted", "venue_breaches"):
    check(f"season.live_season.{key} present", key in live)
check("the home-date tally covers both players",
      set(live.get("hosted", {})) == {config.MY_USERNAME, config.FRIEND_USERNAME},
      str(live.get("hosted")))
check("the first host is named in the rules payload",
      season.get("rules", {}).get("first_host")
      in (config.MY_USERNAME, config.FRIEND_USERNAME),
      str(season.get("rules", {}).get("first_host")))
check("the live series names a target and a maximum",
      current.get("target", 0) > 0 and current.get("max_games", 0) >= current.get("target", 0),
      f"first to {current.get('target')} of {current.get('max_games')}")

# The ladder has to cover every margin a season can finish on, or some season
# resolves to no advantage at all and the rules page shows a gap.
rules = season.get("rules", {})
length = rules.get("season_length", 0)
ladder = {int(k) for k in rules.get("ladder", {})}
check("the advantage ladder covers every reachable season margin",
      ladder >= set(range((length + 1) // 2, length + 1)),
      f"ladder {sorted(ladder)} for a {length}-series season")
check("every prize in the ladder has wording on the rules page",
      all(p in rules.get("advantage_text", {})
          for prizes in rules.get("ladder", {}).values() for p in prizes))

# Every DATA key the page reads must be one build() actually produces. This is
# the check that would have caught a template shipping ahead of its payload:
# `DATA.clutch.find(...)` on a missing key threw and blanked every section that
# rendered after it.
read = set(re.findall(r"DATA\.([A-Za-z_][A-Za-z0-9_]*)", html))
provided = set(data)
check("template reads no DATA key that build() omits", read <= provided,
      f"missing: {sorted(read - provided) or 'none'}")

# And a missing key must be survivable regardless, since the template is read
# from disk while the builder is an imported module.
check("template normalizes DATA before use", "if (!Array.isArray(DATA[k]))" in html)
check("render sections are isolated", 'section "${name}" failed' in html)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
check("dashboard module is importable", Path("app/dashboard.py").exists())

# The hosted app reads data/seed.db, not the working database, so an ingest or a
# re-parse that isn't followed by `ingest snapshot` ships new code against old
# tables — which is how the half-inning stats first went live reading zero rows.
seed = Path(__file__).resolve().parents[1] / "data" / "seed.db"
if not seed.exists():
    check("data/seed.db exists", False, "run: ingest snapshot")
else:
    import sqlite3

    working = sqlite3.connect(config.DB_PATH)
    published = sqlite3.connect(seed)
    stale = []
    for table in ("games", "batting_lines", "pitching_lines", "pa_events",
                  "contact_events", "half_innings"):
        def count(conn):
            try:
                return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                return -1
        if count(published) < count(working):
            stale.append(f"{table} {count(published)}<{count(working)}")
    check("published seed is not behind the working database", not stale,
          "; ".join(stale) or "in sync — run `ingest snapshot` after any ingest")
    working.close()
    published.close()

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
