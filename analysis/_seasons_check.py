"""Season derivation against synthetic games, plus invariants on the real ones.

The league opens with nothing played, so almost every state the season engine
can reach — a closed season, a World Series, a dead heat, a broken rotation rule
— is unreachable from the real database for weeks. Waiting for the games to
arrive before testing the code that reads them is how the populated page ships
having only ever been seen empty.

So this builds games. Each scenario is a scripted list of results fed through
the real schema and the real derive(), which is the only way to know the
advantage ladder, the World Series hand-off and the rotation audit work before
they matter.

  uv run python analysis/_seasons_check.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from show_h2h import config, db, seasons  # noqa: E402

ME, THEM = config.MY_USERNAME, config.FRIEND_USERNAME
ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


def build(results: list, starters: list | None = None) -> dict:
    """Derive a league from a list of results.

    `results` is one entry per game: "W" (I win), "L" (they win), "T" (tie) or
    "N" (no contest). `starters` is an optional parallel list of
    (my starter, their starter) so the rotation rule can be exercised.

    A tie is a regulation game the scores agree on; a no contest is one called
    before five innings. Both are produced the way the real ingester would, so
    v_game_status classifies them on its own rules rather than being told.
    """
    scratch = Path(tempfile.mkdtemp(prefix="show-h2h-seasons-")) / "test.db"
    original = config.DB_PATH
    config.DB_PATH, config.DATA_DIR = scratch, scratch.parent
    try:
        conn = db.connect()
        db.init_db(conn)
        for i, res in enumerate(results):
            mine, theirs = (5, 2) if res == "W" else (2, 5) if res == "L" else (3, 3)
            conn.execute(
                """INSERT INTO games (game_uuid, natural_key, season_year, game_mode,
                       played_at, display_date, innings, ruling,
                       home_username, away_username, home_runs, away_runs,
                       winner, is_h2h, has_box_score, imported_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,?)""",
                (f"uuid-{i:04}", f"key-{i:04}", 26, "ARENA",
                 f"2026-09-{1 + i // 20:02}T{10 + i % 20:02}:00:00", "",
                 3 if res == "N" else 9,          # under five innings = no contest
                 "0" if res in ("W", "L") else "6",   # non-zero ruling = called early
                 ME, THEM, mine, theirs,
                 "home" if res == "W" else "away" if res == "L" else None,
                 db.now_iso()))
            if starters and i < len(starters):
                for user, name in zip((ME, THEM), starters[i]):
                    conn.execute(
                        """INSERT INTO pitching_lines (game_uuid, side, username, slot,
                               player_name, ip_text, outs, r, h, er, bb, so,
                               win, loss, save, hold, wp, imported_at)
                           VALUES (?,?,?,0,?, '6.0',18,2,5,2,1,6, 0,0,0,0,0, ?)""",
                        (f"uuid-{i:04}", "home" if user == ME else "away", user,
                         name, db.now_iso()))
        conn.commit()
        conn.close()
        return seasons.derive()
    finally:
        config.DB_PATH, config.DATA_DIR = original, original.parent


LEAGUE_START = config.LEAGUE_START
config.LEAGUE_START = "2026-09-01"   # all synthetic games fall after this

try:
    # ---------------------------------------------------------------- empty
    state = build([])
    check("empty league reports pregame", state["pregame"])
    check("empty league still describes series 1",
          state["current"]["no"] == 1 and state["current"]["season"] == 1)
    check("empty league has no titles", state["titles"] == {ME: 0, THEM: 0})
    check("empty league's first series is not the postseason",
          not state["current"]["postseason"])

    # ------------------------------------------------------- one live series
    state = build(["W", "W"])
    check("a live series is not complete", not state["current"]["complete"])
    check("a live series counts wins", state["current"]["wins"] == {ME: 2, THEM: 0},
          str(state["current"]["wins"]))
    check("a live series is best-of-five", state["current"]["max_games"] == 5)

    # --------------------------------------------------- ties and no contests
    state = build(["W", "T", "N", "W", "W"])
    check("a tie and a no contest advance no counter",
          state["series"][0]["wins"] == {ME: 3, THEM: 0}, str(state["series"][0]["wins"]))
    check("but they still belong to the series",
          len(state["series"][0]["games"]) == 5,
          f"{len(state['series'][0]['games'])} games for 3 decisive")

    # ------------------------------------------------------- series boundary
    state = build(["W", "W", "W", "W"])
    check("a series closes at exactly three wins",
          state["series"][0]["complete"] and len(state["series"][0]["games"]) == 3)
    check("the fourth game opens the next series",
          len(state["series"]) == 2 and len(state["series"][1]["games"]) == 1)
    check("no series exceeds its maximum",
          all(sum(g["decisive"] for g in s["games"]) <= s["max_games"]
              for s in state["series"]))

    # ----------------------------------------------- a full 8-0 regular season
    sweep = ["W"] * 24                      # 8 series, swept 3-0 each
    state = build(sweep)
    check("eight sweeps close the regular season", len(state["seasons"]) == 1,
          f"{len(state['seasons'])} season(s)")
    check("an 8-0 season is recorded", state["seasons"][0]["series"] == {ME: 8, THEM: 0},
          str(state["seasons"][0]["series"]))
    check("an 8-0 season earns the whole ladder",
          set(state["seasons"][0]["advantage"][ME]) == {"home", "repeat", "ban", "spot"},
          str(state["seasons"][0]["advantage"]))
    check("the next series is automatically the World Series",
          state["current"]["postseason"] and state["current"]["max_games"] == 7)
    check("no title is awarded before the World Series is played",
          state["titles"] == {ME: 0, THEM: 0})

    # ---------------------------------------------------------- a 6-2 season
    six_two = []
    for s in range(8):
        six_two += ["L"] * 3 if s < 2 else ["W"] * 3
    state = build(six_two)
    check("a 6-2 season is recorded", state["seasons"][0]["series"] == {ME: 6, THEM: 2},
          str(state["seasons"][0]["series"]))
    check("6-2 earns home field and one repeat",
          set(state["seasons"][0]["advantage"][ME]) == {"home", "repeat"},
          str(state["seasons"][0]["advantage"]))

    # ------------------------------------------------------- a 4-4 dead heat
    tied = []
    for s in range(8):
        tied += ["W"] * 3 if s % 2 == 0 else ["L"] * 3
    state = build(tied)
    check("a 4-4 season has no winner", state["seasons"][0]["winner"] is None,
          str(state["seasons"][0]["series"]))
    check("a 4-4 season earns no advantage", state["seasons"][0]["advantage"] == {},
          str(state["seasons"][0]["advantage"]))

    # --------------------------------------------- World Series and the title
    state = build(sweep + ["W"] * 4)
    check("the World Series needs four wins",
          state["series"][-1]["complete"] and state["series"][-1]["postseason"])
    check("winning it awards a championship", state["titles"] == {ME: 1, THEM: 0},
          str(state["titles"]))
    check("the season closes with a champion",
          state["seasons"][0]["complete"] and state["seasons"][0]["champion"] == ME)
    check("the next game starts season 2", state["current"]["season"] == 2
          and state["current"]["no"] == 1 and not state["current"]["postseason"])

    # ------------------------------------------------------- rotation rule
    # Three games, and I start the same arm twice.
    state = build(["W", "W", "W"],
                  [("Ace", "Greene"), ("Ace", "Verlander"), ("Burke", "Sasaki")])
    check("repeating a starter in a regular-season series is a violation",
          [v["owner"] for v in state["series"][0]["violations"]] == [ME],
          str(state["series"][0]["violations"]))
    check("the violation names the repeated arm",
          state["series"][0]["violations"][0]["repeated"] == ["Ace"])
    check("a clean rotation is not flagged",
          not any(v["owner"] == THEM for v in state["series"][0]["violations"]))
    check("starters are listed for both sides",
          state["series"][0]["starters"][THEM] == ["Greene", "Verlander", "Sasaki"],
          str(state["series"][0]["starters"][THEM]))

    # A repeat in the World Series is LEGAL for the side holding the 6-2 tier.
    ws = ["W"] * 4
    rot = [("A", "x"), ("B", "y"), ("C", "z"), ("A", "w")]   # I repeat "A"
    state = build(six_two + ws, [(f"r{i}", f"s{i}") for i in range(24)] + rot)
    final = state["series"][-1]
    check("the World Series carries the earned advantage",
          "repeat" in final["advantage"].get(ME, ()), str(final["advantage"]))
    check("a repeat allowed by the 6-2 advantage is NOT a violation",
          not any(v["owner"] == ME for v in final["violations"]),
          str(final["violations"]))

    # ...but the side that did NOT earn it is still bound by the rule.
    rot_them = [("A", "x"), ("B", "y"), ("C", "z"), ("D", "x")]  # they repeat "x"
    state = build(six_two + ws, [(f"r{i}", f"s{i}") for i in range(24)] + rot_them)
    check("the side without the advantage is still bound",
          [v["owner"] for v in state["series"][-1]["violations"]] == [THEM],
          str(state["series"][-1]["violations"]))

    # A second repeat exceeds the one-repeat allowance.
    rot_two = [("A", "x"), ("A", "y"), ("B", "z"), ("B", "w")]
    state = build(six_two + ws, [(f"r{i}", f"s{i}") for i in range(24)] + rot_two)
    check("a second repeat exceeds the allowance",
          any(v["owner"] == ME for v in state["series"][-1]["violations"]),
          str(state["series"][-1]["violations"]))

    # ---------------------------------------------- missing box scores
    state = build(["W", "W", "W"], [("Ace", "Greene")])   # only game 1 has lines
    check("games without a box score are reported, not assumed clean",
          state["series"][0]["starters_unknown"] == 2,
          f"{state['series'][0]['starters_unknown']} unknown")
finally:
    config.LEAGUE_START = LEAGUE_START

# ------------------------------------------------------- invariants, real data
state = seasons.derive()
for s in state["series"]:
    decisive = sum(g["decisive"] for g in s["games"])
    if s["complete"]:
        check(f"real series {s['season']}.{s['no']} winner has exactly the target",
              s["wins"][s["winner"]] == s["target"])
    check(f"real series {s['season']}.{s['no']} within its maximum",
          decisive <= s["max_games"])
seen = [g["uuid"] for s in state["series"] for g in s["games"]]
check("every game after the league opened belongs to exactly one series",
      len(seen) == len(set(seen)) == state["games_counted"],
      f"{len(seen)} placed, {state['games_counted']} eligible")
for s in state["seasons"]:
    check(f"real season {s['no']} holds exactly {config.SEASON_LENGTH} series",
          sum(s["series"].values()) == config.SEASON_LENGTH)

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
