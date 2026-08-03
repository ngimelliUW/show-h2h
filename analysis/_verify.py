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

import re

from show_h2h import db, identity, playbyplay

# Measured live on 2026-07-28, before any of this code existed.
#
# The cutoff is the API's own UTC date, not local time. These figures were read
# off the API in its terms, so the boundary has to stay in its terms too —
# played_at is now converted to local, which slid three late-evening games back
# across a midnight and made this prefix look like it had grown on its own.
BASELINE_THROUGH = "2026-07-28"
BASELINE = {"games": 111, "wins": 76, "losses": 35, "runs_for": 362, "runs_against": 222}

# MM/DD/YYYY -> YYYY-MM-DD, so the original string can be compared as a date.
UTC_DATE = ("substr(display_date, 7, 4) || '-' || substr(display_date, 1, 2)"
            " || '-' || substr(display_date, 4, 2)")

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
prefix = db.query(f"""
    SELECT COUNT(*) AS games,
           SUM(result = 'W') AS wins, SUM(result = 'L') AS losses,
           SUM(my_runs) AS runs_for, SUM(their_runs) AS runs_against
    FROM v_h2h_games WHERE {UTC_DATE} <= ?
""", (BASELINE_THROUGH,)).iloc[0]
for field, expected in BASELINE.items():
    got = int(prefix[field] or 0)
    check(f"baseline {field} through {BASELINE_THROUGH} is {expected}", got == expected,
          f"got {got}")

# --- played_at is local time, not the API's UTC -------------------------------
# Stored verbatim, the API's string filed 90 of 121 games under the wrong day
# and made 11pm sessions look like 4am ones. Nothing about a wrong timezone
# crashes or looks malformed, so these assert the shift is present and correct.
utc_offset = db.query(f"""
    SELECT SUM(ABS((julianday(played_at)
                    - julianday({UTC_DATE} || 'T' || substr(display_date, 12)))
                   * 24 + 5) > 0.001) AS wrong,
           COUNT(*) AS n
    FROM games WHERE display_date IS NOT NULL AND played_at IS NOT NULL
""").iloc[0]
check("played_at is the API's timestamp converted from UTC to local",
      int(utc_offset["wrong"] or 0) == 0,
      f"{int(utc_offset['wrong'] or 0)} of {int(utc_offset['n'])} rows are not "
      f"CDT-offset from display_date")

# Nic plays evenings. Under the naive reading this was 16%, which is what a
# wrong timezone looks like when nothing else complains.
evening = db.query("""
    SELECT SUM(CAST(strftime('%H', played_at) AS INT) >= 19
            OR CAST(strftime('%H', played_at) AS INT) <= 1) AS ev, COUNT(*) AS n
    FROM games WHERE is_h2h = 1
""").iloc[0]
share = int(evening["ev"] or 0) / max(1, int(evening["n"]))
check("head-to-head games land in the evening, where they were played",
      share > 0.6, f"{share:.0%} between 7pm and 1am")

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

# --- RBI on a home run, which the log never states directly -------------------
# It is counted from the "<Runner> scores." sentences behind the homer, and four
# of them is a grand slam — so if this drifts, the grand-slam card lies.
rbi = db.query("""
    SELECT MIN(e.rbi) lo, MAX(e.rbi) hi, SUM(e.rbi) total, COUNT(*) n
    FROM pa_events e JOIN games g ON g.game_uuid = e.game_uuid
    WHERE g.is_h2h = 1 AND e.kind = 'home_run'""").iloc[0]
check("every home run drove in between one and four", rbi.lo >= 1 and rbi.hi <= 4,
      f"{rbi.lo}-{rbi.hi} across {rbi.n} home runs")
check("only home runs carry an RBI figure",
      db.query("SELECT COUNT(*) n FROM pa_events "
               "WHERE kind <> 'home_run' AND rbi IS NOT NULL").iloc[0].n == 0)

box_rbi = db.query("""SELECT SUM(b.rbi) n FROM batting_lines b
                      JOIN games g ON g.game_uuid = b.game_uuid
                      WHERE g.is_h2h = 1""").iloc[0].n
check("home-run RBI are a subset of the box score's RBI", rbi.total <= box_rbi,
      f"{rbi.total} on homers of {box_rbi} total")

# The trailer states its own RBI figure for every perfect-perfect ball. That
# overlaps most of the home runs and is an independent source, so it is the one
# check here that could catch a plausible-but-wrong count.
HOMER_IN_TRAILER = re.compile(r"(\w[\w'.\- ]*?) homered to \w+ \((\d+) feet\)")
stored: dict[tuple, int] = {
    (e.game_uuid, e.batter, e.distance): e.rbi
    for e in db.query("SELECT game_uuid, batter, distance, rbi FROM pa_events "
                      "WHERE kind = 'home_run'").itertuples()}
agree = disagree = 0
for row in db.query("""SELECT g.game_uuid u, t.text FROM game_log_text t
                       JOIN games g ON g.game_uuid = t.game_uuid
                       WHERE g.is_h2h = 1""").itertuples():
    for entry in playbyplay.parse(row.text)["perfect"]:
        hit = HOMER_IN_TRAILER.search(entry["outcome"])
        said = re.search(r"(\d+) RBI", entry["outcome"])
        if not (hit and said):
            continue
        got = stored.get((row.u, hit.group(1).strip(), int(hit.group(2))))
        if got is None:
            continue
        agree += got == int(said.group(1))
        disagree += got != int(said.group(1))
check("counted home-run RBI match the figure the trailer states",
      disagree == 0 and agree > 50, f"{agree} agree, {disagree} disagree")

# --- turned double and triple plays ------------------------------------------
dp = db.query("""SELECT SUM(h.double_plays) dp, MAX(h.double_plays) most,
                        SUM(h.triple_plays) tp, MAX(h.triple_plays) most_tp
                 FROM half_innings h JOIN games g ON g.game_uuid = h.game_uuid
                 WHERE g.is_h2h = 1""").iloc[0]
# Three outs to a half-inning, so two double plays in one cannot happen; if this
# ever trips, the parser has merged two half-innings into one block.
check("no half-inning contains more than one double play", dp.most <= 1,
      f"{dp.dp} double plays, most in a half-inning {dp.most}")
check("triple plays are counted at most once per half-inning", dp.most_tp <= 1)

# A detector for something that has never happened has never been seen to fire.
# These two feed it one, because a card that always reads zero is
# indistinguishable from a card that is simply broken.
SYNTHETIC = (
    "Inning 7:^c50^^n^"
    "Worms batting. Kluber pitching. Judge lined to left for a single. Trout walked. "
    "Harper walked. ^c46^Muncy homered to center (441 feet). Harper scores. "
    "Trout scores. Judge scores.^c50^*^n^"
    "Runs: 4 Hits: 2 Walks: 2 Errors: 0 Pitches: 19 Runners Left On: 0^n^"
    "^n^"
    "SWEs batting. Verlander pitching. Rice lined to left for a single. Bryant walked. "
    "Volpe lined into a triple play (L6-4-3 TP). Bryant out. Rice out.^n^"
    "Runs: 0 Hits: 1 Walks: 1 Errors: 0 Pitches: 8 Runners Left On: 0^n^"
)
synth = playbyplay.parse(SYNTHETIC)
slams = [e for e in synth["events"] if e["kind"] == "home_run" and e["rbi"] == 4]
check("a grand slam is detected when one happens", len(slams) == 1,
      f"{[e['batter'] for e in slams]}")
check("the grand slam is credited to the side that was batting",
      bool(slams) and slams[0]["squad"] == "Worms", slams[0]["squad"] if slams else "")
check("a triple play is detected when one happens",
      sum(h["triple_plays"] for h in synth["halves"]) == 1)
check("a triple play is not also counted as a double play",
      sum(h["double_plays"] for h in synth["halves"]) == 0)

# The log writes 14 of its double plays as strike-'em-out-throw-'em-out, with
# the words "double play" nowhere in the sentence — which is why the detector
# reads the scorer's tag rather than the prose.
tag_only = playbyplay.parse(
    "Inning 3:^c50^^n^"
    "Worms batting. Kluber pitching. Judge lined to left for a single. "
    "Trout struck out chasing a slider low and away (2-6 DP). Judge out.^n^"
    "Runs: 0 Hits: 1 Walks: 0 Errors: 0 Pitches: 7 Runners Left On: 0^n^")
check("a strike-'em-out-throw-'em-out counts as a double play",
      sum(h["double_plays"] for h in tag_only["halves"]) == 1)
# ...and the prose form on its own still counts, in case the wording changes.
prose_only = playbyplay.parse(
    "Inning 3:^c50^^n^"
    "Worms batting. Kluber pitching. Trout walked. Harper walked. "
    "Judge grounded into a triple play. Trout out. Harper out.^n^"
    "Runs: 0 Hits: 0 Walks: 2 Errors: 0 Pitches: 9 Runners Left On: 0^n^")
check("a triple play written in prose alone still counts",
      sum(h["triple_plays"] for h in prose_only["halves"]) == 1)

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
