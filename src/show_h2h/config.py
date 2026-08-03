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

# Both accounts we crawl. Order matters only for logging.
USERNAMES = [MY_USERNAME, FRIEND_USERNAME]
