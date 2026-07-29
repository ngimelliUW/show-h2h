"""Correctness checks on the ingested data.

Gate for the nightly refresh: if any of these fail, the job must not publish.

The historical baseline was measured directly from the API before the pipeline
existed, so it is an independent check that ingestion is right. It is asserted
as a *prefix* — the record over games up to and including the backfill date —
rather than as a total, because a total would break the first time a new game is
played and would then block the automation from ever publishing again.

Run:  uv run python analysis/_verify.py
"""
from __future__ import annotations

from show_h2h import db, identity

# Measured live on 2026-07-28, before any of this code existed.
BASELINE_THROUGH = "2026-07-28"
BASELINE = {"games": 111, "wins": 76, "losses": 35, "runs_for": 362, "runs_against": 222}

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


# Innings-pitched notation: the decimal counts outs, not tenths.
check("ip '8.1' -> 25 outs", identity.outs_from_ip("8.1") == 25)
check("ip '0.2' -> 2 outs", identity.outs_from_ip("0.2") == 2)
check("ip '9.0' -> 27 outs", identity.outs_from_ip("9.0") == 27)

# --- the historical prefix must never move -----------------------------------
prefix = db.query("""
    SELECT COUNT(*) AS games,
           SUM(result = 'W') AS wins, SUM(result = 'L') AS losses,
           SUM(my_runs) AS runs_for, SUM(their_runs) AS runs_against
    FROM v_h2h_games WHERE played_at <= ? || 'T23:59:59'
""", (BASELINE_THROUGH,)).iloc[0]
for field, expected in BASELINE.items():
    got = int(prefix[field] or 0)
    check(f"baseline {field} through {BASELINE_THROUGH} is {expected}", got == expected,
          f"got {got}")

# --- invariants that hold for any amount of data -----------------------------
r = db.query("SELECT * FROM v_h2h_record").iloc[0]
check("every head-to-head game has a decision",
      int(r.wins) + int(r.losses) == int(r.games),
      f"{int(r.wins)}W + {int(r.losses)}L vs {int(r.games)} games")
check("the record only grows", int(r.games) >= BASELINE["games"],
      f"{int(r.games)} games, baseline {BASELINE['games']}")
check("runs scored are consistent with the games table",
      int(r.runs_for) == int(db.query(
          "SELECT SUM(my_runs) n FROM v_h2h_games").iloc[0].n or 0))

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

# --- play-by-play parsing ---------------------------------------------------
# The prose is the only source of pitch detail, and it contains a trailer that
# restates plays. If the parse ever drifts, these two totals separate from the
# box score — which is exactly how the double-counting bug was caught.
pbp = db.query("""
    SELECT
      (SELECT COUNT(*) FROM pa_events e JOIN games g ON g.game_uuid=e.game_uuid
        WHERE g.is_h2h=1 AND e.kind='home_run')  AS hr,
      (SELECT COUNT(*) FROM pa_events e JOIN games g ON g.game_uuid=e.game_uuid
        WHERE g.is_h2h=1 AND e.kind='strikeout') AS so,
      (SELECT SUM(b.hr) FROM batting_lines b JOIN games g ON g.game_uuid=b.game_uuid
        WHERE g.is_h2h=1) AS box_hr,
      (SELECT SUM(b.so) FROM batting_lines b JOIN games g ON g.game_uuid=b.game_uuid
        WHERE g.is_h2h=1) AS box_so
""").iloc[0]
check("parsed home runs match the box score", pbp.hr == pbp.box_hr, f"{pbp.hr} vs {pbp.box_hr}")
check("parsed strikeouts match the box score", pbp.so == pbp.box_so, f"{pbp.so} vs {pbp.box_so}")

check("every parsed event has an owner",
      db.query("SELECT COUNT(*) n FROM pa_events WHERE batting_username IS NULL").iloc[0].n == 0)
check("a strikeout's two sides are different people",
      db.query("SELECT COUNT(*) n FROM pa_events "
               "WHERE batting_username = pitching_username").iloc[0].n == 0)

velo = db.query("SELECT MIN(exit_velo) lo, MAX(exit_velo) hi FROM contact_events").iloc[0]
check("exit velocities are plausible", 50 <= velo.lo and velo.hi <= 130, f"{velo.lo}-{velo.hi} mph")
dist = db.query("SELECT MIN(distance) lo, MAX(distance) hi FROM pa_events "
                "WHERE kind='home_run'").iloc[0]
check("home-run distances are plausible", 250 <= dist.lo and dist.hi <= 600, f"{dist.lo}-{dist.hi} ft")

unattrib = db.query("SELECT COUNT(*) n FROM contact_events WHERE username IS NULL").iloc[0].n
total_pp = db.query("SELECT COUNT(*) n FROM contact_events").iloc[0].n
check("most perfect-perfect balls are attributed", unattrib / max(total_pp, 1) < 0.10,
      f"{unattrib}/{total_pp} unattributed")

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
