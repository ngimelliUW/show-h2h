"""Thin client for the MLB The Show public API.

No auth of any kind is required — these endpoints are open given a username.
What they *do* have is a pile of failure modes that all look like success:

  * `/apis/game.json` (the endpoint you'd guess for a box score) does not exist
    and returns a 22 KB HTML 404 page with status 200. The real one is
    `game_log.json`.
  * Errors come back as HTTP 200 with an {"error": "..."} body.
  * Asking for a page beyond total_pages returns the LAST page again rather
    than an empty list, so "loop until empty" never terminates.
  * The server intermittently returns an empty history for users who do have
    games. total_pages == 0 means genuinely-unknown user; total_pages >= 1 with
    an empty list is a glitch worth retrying.

So every response goes through _check() before a caller ever sees it.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from show_h2h import config

USER_AGENT = "show-h2h/0.1 (personal head-to-head stats; local use)"


class ApiError(RuntimeError):
    pass


_last_request_at = 0.0


def _throttle() -> None:
    """Space requests out. The API documents no rate limit and returns no
    rate-limit headers, but SDS throttles clients that pull too fast."""
    global _last_request_at
    wait = config.REQUEST_DELAY - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def get_json(path: str, params: dict, *, retries: int = 4) -> dict:
    """GET <BASE_URL>/<path>.json?<params> and return parsed JSON."""
    url = f"{config.BASE_URL}/{path}.json?" + urllib.parse.urlencode(params)
    last_error: Exception | None = None

    for attempt in range(retries):
        _throttle()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                ctype = resp.headers.get("Content-Type", "")
                body = resp.read().decode("utf-8", errors="replace")
            if "application/json" not in ctype:
                # The HTML-404-with-status-200 case.
                raise ApiError(f"{path}: expected JSON, got {ctype!r} ({len(body)} bytes) — "
                               f"does this endpoint exist?")
            data = json.loads(body)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_error = e
            time.sleep(1.5 * (attempt + 1))
            continue

        if isinstance(data, dict) and data.get("error"):
            # Not retryable — it's a bad username/platform/id combination.
            raise ApiError(f"{path}: {data['error']}")
        return data

    raise ApiError(f"{path}: failed after {retries} attempts — {last_error}")


def game_history_page(username: str, page: int, mode: str = "all") -> dict:
    return get_json("game_history", {
        "page": page, "username": username,
        "platform": config.PLATFORM, "mode": mode,
    })


def game_history(username: str, mode: str = "all", *, max_pages: int | None = None,
                 stop_at_ids: set[str] | None = None) -> list[dict]:
    """Page through a user's history, newest first.

    Bounded by total_pages — never by an empty response, since page > total_pages
    silently re-serves the last page.

    stop_at_ids enables incremental refresh: stop as soon as a page is entirely
    made of games we already have.
    """
    games: list[dict] = []
    page, total_pages = 1, 1
    while page <= total_pages:
        data = game_history_page(username, page, mode)
        total_pages = int(data.get("total_pages") or 0)
        if total_pages == 0:
            break  # unknown username, or this user has no games in this mode

        batch = data.get("game_history") or []
        if not batch and page == 1:
            # Known glitch: empty list despite total_pages >= 1. Retry once.
            data = game_history_page(username, page, mode)
            batch = data.get("game_history") or []

        games.extend(batch)
        if stop_at_ids and batch and all(g["id"] in stop_at_ids for g in batch):
            break
        if max_pages and page >= max_pages:
            break
        page += 1
    return games


def game_log(api_id: str, username: str) -> dict:
    """Fetch one box score.

    Requires the (id, username, platform) triple to match the game record — the
    id must have come from *this* user's history. You cannot read a friend's
    game using your own username.

    Returns a dict keyed by section: 'line_score', 'game_log', 'box_score'.
    The API nests these as an array of [tag, payload] pairs, not an object.
    """
    data = get_json("game_log", {"id": api_id, "username": username,
                                 "platform": config.PLATFORM})
    sections = data.get("game") or []
    return {tag: payload for tag, payload in sections}
