"""Central config + paths. Loads .env from the project root."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "show.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

load_dotenv(PROJECT_ROOT / ".env")


def get(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


MY_USERNAME = get("MY_USERNAME", "LinguiniEater")
FRIEND_USERNAME = get("FRIEND_USERNAME", "TallThibaut48")
PLATFORM = get("PLATFORM", "psn")
SEASON_YEAR = int(get("SEASON_YEAR", "26"))
REQUEST_DELAY = float(get("REQUEST_DELAY", "0.35"))

# The API reports game times in UTC; games are stored and displayed in this
# zone. See identity.parse_date for how that was established.
LOCAL_TZ = ZoneInfo(get("LOCAL_TZ", "America/Chicago"))

# Each edition of the game is its own silo; mlb26 cannot see mlb25 games.
BASE_URL = f"https://mlb{SEASON_YEAR}.theshow.com/apis"

# ---------------------------------------------------------------- league rules
# The Show has no season structure, so we impose one: games roll into
# best-of-five series, series into seasons, and each season ends in a World
# Series whose terms are set by how the season was won. See SEASONS-PLAN.md.
#
# These are policy, not measurements — the length of a season is a thing the two
# players can renegotiate — so they live here rather than baked into SQL.
#
# Careful: SEASON_YEAR above is the *edition* of the game (26). Nothing here is
# named SEASON_* on purpose; the collision is easy to make and hard to see.

# Season 1 opens with the first game played on or after this moment. Everything
# before it belongs to no season and is deliberately not backfilled: the two of
# them start level at zero championships rather than inheriting a 26-6 series
# record accumulated under no rules at all.
#
# A bare date ("2026-08-06") or a full local timestamp both work — games are
# compared as ISO strings against games.played_at, which is naive local time, so
# a timestamp must carry no UTC offset or the comparison sorts on the suffix.
# This one is the moment the league was armed on 2026-08-05, chosen so the two
# games already played that afternoon stay out and the next one played is
# Season 1, Series 1, Game 1.
LEAGUE_START = get("LEAGUE_START", "2026-08-05T17:23:00")

SERIES_WINS = int(get("SERIES_WINS", "3"))              # best-of-five
SEASON_LENGTH = int(get("SEASON_LENGTH", "8"))          # series per season
WORLD_SERIES_WINS = int(get("WORLD_SERIES_WINS", "4"))  # best-of-seven

# What winning the season by each margin buys in the World Series. Keyed by the
# winner's series count, which is what the standings show — deriving it from the
# margin instead reads fine and silently maps 6-2 and 8-0 to the same tier.
ADVANTAGE_LADDER = {
    8: ("home", "repeat", "ban", "spot"),
    7: ("home", "repeat", "ban"),
    6: ("home", "repeat"),
    5: ("home",),
    4: (),
}

ADVANTAGE_TEXT = {
    "home": "Home field for all seven games",
    "repeat": "May start one pitcher twice in the series",
    "ban": "May ban one card from the opposing roster",
    "spot": "The series opens 1–0",
}

# Both accounts we crawl. Order matters only for logging.
USERNAMES = [MY_USERNAME, FRIEND_USERNAME]
