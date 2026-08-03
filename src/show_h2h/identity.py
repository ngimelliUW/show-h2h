"""Working out who actually played in a game.

This is the fiddly part of the whole project, because the API deliberately
hides the identity of whoever is asking:

  * In game_history, YOUR OWN name comes back as the literal string "CPU".
  * In game_log's line_score, the same slot is an empty string instead.
  * A genuine game against the computer ALSO says "CPU" — but there it's the
    *squad* name (home_full_name / away_full_name) that reads "CPU".

So the squad field, not the name field, is what distinguishes "me" from "the
computer". Get this backwards and every offline game counts as a head-to-head.

Names also arrive with a platform-badge suffix ("LinguiniEater ^b53^") in
game_history but not in game_log, and the API's casing differs from what a
human types, so every comparison is normalized first.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from show_h2h import config

_BADGE = re.compile(r"\s*\^b\d+\^\s*$")

# Marks the requesting user's own slot: "CPU" in game_history, "" in game_log.
_SELF_MARKERS = {"cpu", ""}


def clean_name(name: str | None) -> str:
    """Strip the ^bNN^ platform badge and surrounding whitespace."""
    return _BADGE.sub("", name or "").strip()


def same_user(a: str | None, b: str | None) -> bool:
    return clean_name(a).lower() == clean_name(b).lower() and clean_name(a) != ""


def parse_date(display_date: str | None) -> str | None:
    """'08/03/2026 04:55:27' -> '2026-08-02T23:55:27', i.e. UTC -> local.

    **The API reports UTC.** This is undocumented, and it was wrong here for
    months: the string was stored as-is, so 90 of 121 head-to-head games were
    shown on the wrong day and the late ones looked like 4am starts.

    How it was settled, since guessing at a timezone is how it broke the first
    time. Read as local, 84% of these games fall between 2am and 6am. Read as
    UTC and converted, 87% fall between 8pm and 1am — which is when they were
    actually played. Nic independently dated two games to "last night"; both are
    stored just after 04:00 and land at 11:06 PM and 11:55 PM local under the UTC
    reading, and at 4am under the naive one.

    Returns naive local time, matching the format the rest of the schema and the
    report already assume. The original string is kept in games.display_date, so
    this is always re-derivable. One wrinkle worth knowing: on the hour that DST
    repeats each November, two games an hour apart can sort as equal.
    """
    if not display_date:
        return None
    try:
        naive = datetime.strptime(display_date.strip(), "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None
    return (naive.replace(tzinfo=timezone.utc)
                 .astimezone(config.LOCAL_TZ)
                 .replace(tzinfo=None)
                 .isoformat())


def natural_key(entry: dict) -> str:
    """A stable id for a game before we know its game_uuid.

    game_uuid only appears in game_log, but we need to dedupe the two players'
    game_history rows for the same game long before we fetch box scores — and
    their `id` fields differ. Timestamp plus both scores is enough: the same two
    people cannot start two games in the same second.
    """
    return "|".join([
        (entry.get("display_date") or "").strip(),
        str(entry.get("home_runs")), str(entry.get("away_runs")),
        str(entry.get("home_hits")), str(entry.get("away_hits")),
        (entry.get("home_full_name") or ""), (entry.get("away_full_name") or ""),
    ])


def resolve(entry: dict, queried_username: str) -> dict:
    """Work out who was home, who was away, and what kind of game this was.

    `entry` is a game_history item or a game_log line_score — both carry the
    same home_name/away_name/home_full_name/away_full_name shape.

    Returns home_username / away_username (with the queried user's blanked slot
    filled back in), plus is_vs_cpu / is_third_party flags.
    """
    home_name, away_name = clean_name(entry.get("home_name")), clean_name(entry.get("away_name"))
    home_squad, away_squad = (entry.get("home_full_name") or ""), (entry.get("away_full_name") or "")

    # A real computer opponent is identified by its SQUAD being "CPU".
    is_vs_cpu = home_squad.strip().upper() == "CPU" or away_squad.strip().upper() == "CPU"

    home_is_self = home_name.lower() in _SELF_MARKERS
    away_is_self = away_name.lower() in _SELF_MARKERS

    is_third_party = False
    if home_is_self and not away_is_self:
        home_username, away_username = queried_username, away_name
    elif away_is_self and not home_is_self:
        home_username, away_username = home_name, queried_username
    elif home_is_self and away_is_self:
        # Both slots blank: an offline game where the queried user played both
        # sides, or vs CPU. Attribute home to them and let is_vs_cpu carry it.
        home_username, away_username = queried_username, away_name or "CPU"
    else:
        # Neither slot was blanked — the queried user was not one of the two
        # named players. Seen on co-op records that leak into a partner's
        # history. Keep the row but never count it as head-to-head.
        home_username, away_username = home_name, away_name
        is_third_party = True

    return {
        "home_username": home_username,
        "away_username": away_username,
        "home_squad": home_squad,
        "away_squad": away_squad,
        "is_vs_cpu": int(is_vs_cpu),
        "is_third_party": int(is_third_party),
    }


def is_head_to_head(resolved: dict) -> bool:
    """True iff this is me against the configured rival.

    Note the API exposes no field distinguishing an invited "Play vs Friend"
    game from a random matchmake, so this is purely opponent identity.
    """
    if resolved["is_vs_cpu"] or resolved["is_third_party"]:
        return False
    names = {resolved["home_username"].lower(), resolved["away_username"].lower()}
    return {config.MY_USERNAME.lower(), config.FRIEND_USERNAME.lower()} <= names


def outs_from_ip(ip_text: str | None) -> int:
    """'8.1' -> 25 outs.

    Innings pitched use baseball notation: the decimal is a count of outs
    (.1 = one out, .2 = two outs), NOT a fraction. Summing ip as a float gives
    wrong ERA and K/9, which is why we store outs instead.
    """
    if not ip_text:
        return 0
    try:
        whole, _, frac = str(ip_text).strip().partition(".")
        outs = int(whole or 0) * 3
        if frac:
            partial = int(frac[0])
            if partial in (1, 2):
                outs += partial
        return outs
    except (ValueError, TypeError):
        return 0
