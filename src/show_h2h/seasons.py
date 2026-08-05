"""Seasons, series and the World Series, derived from the order games were played.

The Show keeps no season structure, so the site imposes one: games roll into
best-of-five series, series into fixed-length seasons, and each season ends in a
best-of-seven World Series whose terms are set by how the season was won. The
rules and the data behind them are in SEASONS-PLAN.md.

Nothing here is entered by hand. Walking the games in order is enough to know
which series is live, when a season ended and who won it, so there is no
bookkeeping to forget during a session and no state that can disagree with the
box scores. The World Series is simply whatever series follows the eighth one.

WHY THIS IS PYTHON AND NOT A VIEW
---------------------------------
Every other statistic in this project lives in a SQL view, deliberately, so the
dashboard stays a thin renderer. This one does not, because a series boundary is
not an aggregate: it is a sequential walk that carries state between rows and
resets on a condition. SQLite can express that only as a recursive CTE with the
series length, season length and World Series length spelled out as literals —
and those three are exactly the knobs the two players are most likely to
renegotiate. One function called by both the report and the checks keeps a
single implementation; a view templated from config would not.

    uv run python -m show_h2h.seasons     # print the current state
"""
from __future__ import annotations

from collections import Counter, defaultdict

from show_h2h import config, db


def _reachable(length: int) -> range:
    """Series counts the winning side of a season can finish on.

    Lowest is the dead heat, highest is the sweep. The ladder has to cover all
    of them or some season resolves to no tier at all.
    """
    return range((length + 1) // 2, length + 1)


_gap = sorted(n for n in _reachable(config.SEASON_LENGTH)
              if n not in config.ADVANTAGE_LADDER)
if _gap:
    raise ValueError(
        f"ADVANTAGE_LADDER covers {sorted(config.ADVANTAGE_LADDER)} but a "
        f"{config.SEASON_LENGTH}-series season can be won with {_gap}. "
        "Changing SEASON_LENGTH means restating the ladder in config.py — "
        "otherwise a season silently earns no advantage."
    )


def _games() -> list[dict]:
    """Head-to-head games since the league opened, oldest first.

    Ties and no contests come back too. They belong to the series they were
    played during — leaving them out would make a series look like it had fewer
    games than the two of them remember — but `decisive` is what advances it.
    """
    df = db.query(
        """
        SELECT v.game_uuid, v.played_at, v.my_runs, v.their_runs, v.status,
               v.result, v.counts_record
        FROM v_h2h_games v
        WHERE v.played_at >= ?
        ORDER BY v.played_at
        """,
        (config.LEAGUE_START,),
    )
    me, them = config.MY_USERNAME, config.FRIEND_USERNAME
    out = []
    for r in df.to_dict("records"):
        decisive = bool(r["counts_record"]) and r["result"] in ("W", "L")
        out.append({
            "uuid": r["game_uuid"],
            "at": str(r["played_at"]),
            "runs": {me: int(r["my_runs"]), them: int(r["their_runs"])},
            "status": r["status"],
            "decisive": decisive,
            "winner": (me if r["result"] == "W" else them) if decisive else None,
        })
    return out


def _starters() -> dict[str, dict[str, str]]:
    """{game_uuid: {username: starting pitcher}}.

    The starter is the pitching line with the lowest slot — slot 0 averages 20.8
    outs against 5.5 for slot 1, so the ordering is real rather than incidental.

    Long surnames arrive truncated ("Misiorowsk..."), which is fine here: the
    truncation is consistent, so two starts by the same card still compare
    equal. It would not be fine to join these to the play-by-play, which spells
    names out in full.
    """
    df = db.query("""
        SELECT p.game_uuid, p.username, p.player_name, p.slot
        FROM pitching_lines p
        ORDER BY p.game_uuid, p.username, p.slot
    """)
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for r in df.to_dict("records"):
        # First row wins: the query is ordered by slot, so that is the starter.
        out[r["game_uuid"]].setdefault(r["username"], r["player_name"])
    return out


def _audit(series: dict, starters: dict) -> None:
    """Fill in each side's starters, and any breach of the rotation rule.

    A pitcher may start once per series. The exception is the "repeat" advantage,
    which buys the season winner exactly one second start in that World Series —
    so the threshold depends on what was earned, not on a constant. Getting this
    wrong would have the site accusing a player of cheating for spending a prize
    he won on the field.

    A game whose box score has not been fetched yet contributes no starter. That
    is silence, not innocence, so it is reported rather than assumed clean.
    """
    used: dict[str, list[str]] = {u: [] for u in config.USERNAMES}
    unknown = 0
    for g in series["games"]:
        found = starters.get(g["uuid"], {})
        if not found:
            unknown += 1
        for user in config.USERNAMES:
            if found.get(user):
                used[user].append(found[user])

    series["starters"] = used
    series["starters_unknown"] = unknown
    series["violations"] = []
    for user, names in used.items():
        allowance = 1 if (series["postseason"]
                          and "repeat" in series["advantage"].get(user, ())) else 0
        counts = Counter(names)
        excess = sum(n - 1 for n in counts.values() if n > 1)
        if excess > allowance:
            series["violations"].append({
                "owner": user,
                "allowance": allowance,
                "repeated": sorted(p for p, n in counts.items() if n > 1),
            })


def _new_series(season_no: int, series_no: int, postseason: bool,
                advantage: dict[str, tuple]) -> dict:
    target = config.WORLD_SERIES_WINS if postseason else config.SERIES_WINS
    return {
        "season": season_no,
        "no": series_no,
        "postseason": postseason,
        "target": target,
        # A best-of-five is at most five decisive games; ties and no contests
        # are replayed and can push the actual game count past it.
        "max_games": target * 2 - 1,
        "wins": {u: 0 for u in config.USERNAMES},
        "winner": None,
        "complete": False,
        "advantage": advantage,
        "games": [],
    }


def derive() -> dict:
    """The whole league state: closed seasons, every series, and what is live."""
    games, starters = _games(), _starters()
    me, them = config.MY_USERNAME, config.FRIEND_USERNAME

    seasons: list[dict] = []
    series: list[dict] = []
    titles = {u: 0 for u in config.USERNAMES}

    season_no, closed, open_series = 1, 0, None
    # What the current season's World Series is worth. Empty until the regular
    # season closes; the postseason series is created holding whatever it won.
    advantage: dict[str, tuple] = {}
    season_start = None

    for g in games:
        if open_series is None:
            open_series = _new_series(season_no, closed + 1,
                                      closed >= config.SEASON_LENGTH, advantage)
            series.append(open_series)
            season_start = season_start or g["at"]

        open_series["games"].append(g)
        if g["decisive"]:
            open_series["wins"][g["winner"]] += 1

        leader = max(open_series["wins"], key=lambda u: open_series["wins"][u])
        if open_series["wins"][leader] < open_series["target"]:
            continue

        open_series["winner"] = leader
        open_series["complete"] = True
        open_series["ended"] = g["at"]

        if open_series["postseason"]:
            titles[leader] += 1
            seasons[-1].update(champion=leader, complete=True, ended=g["at"])
            season_no, closed, advantage, season_start = season_no + 1, 0, {}, None
        else:
            closed += 1
            if closed == config.SEASON_LENGTH:
                # Regular season over. Tally series and set the terms of the
                # World Series that starts with the very next game.
                won = Counter(s["winner"] for s in series
                              if s["season"] == season_no and not s["postseason"])
                top = max(config.USERNAMES, key=lambda u: won[u])
                low = them if top == me else me
                advantage = ({top: config.ADVANTAGE_LADDER[won[top]]}
                             if won[top] != won[low] else {})
                seasons.append({
                    "no": season_no,
                    "series": {u: won[u] for u in config.USERNAMES},
                    "winner": top if won[top] != won[low] else None,
                    "advantage": advantage,
                    "champion": None,
                    "complete": False,
                    "started": season_start,
                    "ended": None,
                })
        open_series = None

    for s in series:
        _audit(s, starters)

    # Always describe what comes next, even before a single pitch: the launch
    # state of this feature is an empty Season 1, and a page with nothing to
    # render is how an empty state ends up looking broken instead of new.
    current = open_series or _new_series(
        season_no, closed + 1, closed >= config.SEASON_LENGTH, advantage)
    if current is not open_series:
        _audit(current, starters)

    live_season = next((s for s in seasons if s["no"] == season_no), None)
    if live_season is None:
        won = Counter(s["winner"] for s in series
                      if s["season"] == season_no and not s["postseason"])
        live_season = {
            "no": season_no,
            "series": {u: won[u] for u in config.USERNAMES},
            "winner": None,
            "advantage": {},
            "champion": None,
            "complete": False,
            "started": season_start,
            "ended": None,
        }

    return {
        "start": config.LEAGUE_START,
        "rules": {
            "series_wins": config.SERIES_WINS,
            "season_length": config.SEASON_LENGTH,
            "world_series_wins": config.WORLD_SERIES_WINS,
            "ladder": {str(k): list(v) for k, v in config.ADVANTAGE_LADDER.items()},
            "advantage_text": dict(config.ADVANTAGE_TEXT),
        },
        "players": [me, them],
        "titles": titles,
        "seasons": seasons,
        "series": series,
        "current": current,
        "live_season": live_season,
        # True until the first game is played under the rules — the page uses
        # this to say "no games yet" rather than rendering a row of zeroes.
        "pregame": not games,
        "games_counted": len(games),
    }


def main() -> int:
    state = derive()
    cur, season = state["current"], state["live_season"]
    print(f"League opened {state['start']} — {state['games_counted']} game(s) since.")
    print(f"Titles: " + ", ".join(f"{u} {n}" for u, n in state["titles"].items()))
    print(f"\nSeason {season['no']}: "
          + " / ".join(f"{u} {n}" for u, n in season["series"].items())
          + f" ({config.SEASON_LENGTH} series)")
    label = "World Series" if cur["postseason"] else f"Series {cur['no']}"
    print(f"{label} (best of {cur['max_games']}): "
          + " / ".join(f"{u} {n}" for u, n in cur["wins"].items())
          + f" — {len(cur['games'])} game(s) played")
    for user, names in cur["starters"].items():
        print(f"    {user}: {', '.join(names) or 'no starters yet'}")
    for v in cur["violations"]:
        print(f"  !! rotation rule: {v['owner']} started {', '.join(v['repeated'])} twice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
