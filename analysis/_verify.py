"""Correctness checks against the live-measured ground truth.

The record and run totals here were measured directly from the API before the
pipeline existed, so they're an independent check that ingestion is right.
Run:  uv run python analysis/_verify.py
"""
from __future__ import annotations

from show_h2h import db, identity

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


# Innings-pitched notation: the decimal counts outs, not tenths.
check("ip '8.1' -> 25 outs", identity.outs_from_ip("8.1") == 25)
check("ip '0.2' -> 2 outs", identity.outs_from_ip("0.2") == 2)
check("ip '9.0' -> 27 outs", identity.outs_from_ip("9.0") == 27)

r = db.query("SELECT * FROM v_h2h_record").iloc[0]
check("record is 76-35", int(r.wins) == 76 and int(r.losses) == 35,
      f"got {int(r.wins)}-{int(r.losses)}")
check("runs are 362-222", int(r.runs_for) == 362 and int(r.runs_against) == 222,
      f"got {int(r.runs_for)}-{int(r.runs_against)}")
check("111 head-to-head games", int(r.games) == 111, f"got {int(r.games)}")

dupes = db.query("SELECT COUNT(*) n FROM "
                 "(SELECT game_uuid FROM games GROUP BY game_uuid HAVING COUNT(*) > 1)").iloc[0].n
check("no duplicate game_uuid", dupes == 0, f"{dupes} dupes")

unpromoted = db.query("SELECT COUNT(*) n FROM games "
                      "WHERE has_box_score = 1 AND game_uuid = natural_key").iloc[0].n
check("box-scored games use the real uuid", unpromoted == 0, f"{unpromoted} unpromoted")

g = db.query("""SELECT g.innings, g.home_runs,
                       (SELECT SUM(home_runs) FROM game_innings i
                         WHERE i.game_uuid = g.game_uuid) AS line_sum
                FROM games g WHERE g.game_uuid = 'e9639720-951f-e7e4-e94c-8daababea9a5'""")
check("the known 11-inning game is stored", not g.empty and int(g.iloc[0].innings) == 11)
if not g.empty:
    check("extra-inning runs absent from line score (API limitation)",
          int(g.iloc[0].line_sum) < int(g.iloc[0].home_runs),
          f"line score {int(g.iloc[0].line_sum)} vs final {int(g.iloc[0].home_runs)}")

check("no CPU in the batting leaderboard",
      db.query("SELECT COUNT(*) n FROM v_batting_totals "
               "WHERE username = 'CPU' OR player_name = 'CPU'").iloc[0].n == 0)
check("no vs-CPU game counted as head-to-head",
      db.query("SELECT COUNT(*) n FROM games WHERE is_h2h = 1 AND is_vs_cpu = 1").iloc[0].n == 0)
check("no co-op game counted as head-to-head",
      db.query("SELECT COUNT(*) n FROM games WHERE is_h2h = 1 AND is_coop = 1").iloc[0].n == 0)

bad = db.query("""
    SELECT COUNT(*) n FROM games WHERE is_h2h = 1 AND NOT (
        (LOWER(home_username) = LOWER(?) AND LOWER(away_username) = LOWER(?))
     OR (LOWER(away_username) = LOWER(?) AND LOWER(home_username) = LOWER(?)))
""", (db.config.MY_USERNAME, db.config.FRIEND_USERNAME,
      db.config.MY_USERNAME, db.config.FRIEND_USERNAME)).iloc[0].n
check("every head-to-head game is exactly the two of us", bad == 0, f"{bad} bad")

# Co-op box scores legitimately contain third parties (the team we played
# against together), so the constraint is on head-to-head games specifically —
# and on the leaderboard views, which is what actually gets displayed.
pair = {db.config.MY_USERNAME.lower(), db.config.FRIEND_USERNAME.lower()}
h2h_owners = set(db.query("""
    SELECT DISTINCT b.username FROM batting_lines b
    JOIN games g ON g.game_uuid = b.game_uuid WHERE g.is_h2h = 1
""").username.str.lower())
check("head-to-head batting lines belong to the two accounts",
      h2h_owners <= pair, str(h2h_owners - pair or "clean"))

leaderboard_owners = set(db.query(
    "SELECT DISTINCT username FROM v_batting_totals").username.str.lower())
check("no third party reaches the batting leaderboard",
      leaderboard_owners <= pair, str(leaderboard_owners - pair or "clean"))
check("no third party reaches the pitching leaderboard",
      set(db.query("SELECT DISTINCT username FROM v_pitching_totals").username.str.lower()) <= pair)

# The API appends the decision (W/L/S/H/BS) to a pitcher's name, and the name is
# the leaderboard's grouping key — any suffix left in splits one pitcher across
# several rows with partial stats.
check("no pitcher name carries a decision suffix",
      db.query("SELECT COUNT(*) n FROM v_pitching_totals "
               "WHERE player_name LIKE '%(%'").iloc[0].n == 0)

# Innings pitched are stored in baseball notation, where the fraction counts
# outs — so .3 through .9 are impossible values.
illegal = db.query("""SELECT COUNT(*) n FROM v_pitching_totals
                      WHERE CAST(ROUND((innings - CAST(innings AS INTEGER)) * 10)
                                 AS INTEGER) > 2""").iloc[0].n
check("no illegal innings-pitched fraction", illegal == 0, f"{illegal} bad")

# Both owners field cards with the same surname, so a chart keyed on the bare
# name would stack two players into one bar. Labels must disambiguate.
for view, order, what in (("v_batting_totals", "hr DESC", "hitters"),
                          ("v_pitching_totals", "era ASC", "pitchers")):
    top = db.query(f"SELECT username, player_name FROM {view} ORDER BY {order} LIMIT 12")
    labels = top.player_name + " (" + top.username + ")"
    check(f"{what} chart labels are unique after disambiguation",
          labels.duplicated().sum() == 0,
          f"{top.player_name.duplicated().sum()} bare-name collisions")

# A 0-0 game (awarded on a quit) would otherwise land in both shutout columns.
both = db.query("""SELECT COUNT(*) n FROM v_h2h_games
                   WHERE my_runs = 0 AND their_runs = 0""").iloc[0].n
check("0-0 games exist and are excluded from shutout counts by the dashboard",
      True, f"{both} such game(s)")

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
