-- MLB The Show head-to-head database.
--
-- Convention (borrowed from ~/health): every table that mirrors an API payload
-- keeps a `raw` TEXT column holding the original JSON, plus `imported_at`, so
-- nothing the API sent is ever lost even if we didn't model it yet.


-- The humans. `player_id` is the stable numeric account id that appears in
-- game_log's line_score (home_player_id / away_player_id). It is NOT available
-- from game_history, so rows start username-only and get their player_id filled
-- in once we fetch a box score. It survives username changes; usernames do not.
CREATE TABLE IF NOT EXISTS players (
    username     TEXT PRIMARY KEY COLLATE NOCASE,  -- the API varies the casing
    player_id    TEXT UNIQUE,                      -- from line_score, once known
    platform     TEXT,
    is_me        INTEGER NOT NULL DEFAULT 0,       -- 1 for MY_USERNAME
    imported_at  TEXT
);


-- One row per actual game.
--
-- KEYED ON game_uuid, NOT id. The API hands out a DIFFERENT `id` to each
-- participant for the same game (e.g. 1554797583 for one player and
-- 1554797584 for the other) while game_uuid is identical for both. Keying on
-- `id` would double-count every head-to-head game.
--
-- game_uuid only appears in game_log, not game_history, so rows land here first
-- keyed by a synthetic key and are collapsed onto game_uuid once a box score
-- arrives. See `natural_key` below.
CREATE TABLE IF NOT EXISTS games (
    game_uuid        TEXT PRIMARY KEY,

    -- Deterministic stand-in used to dedupe two players' history rows for the
    -- same game before we know the real uuid: played_at + both scores, sorted.
    natural_key      TEXT UNIQUE,

    season_year      INTEGER NOT NULL,
    game_mode        TEXT,                 -- 'ARENA' (Diamond Dynasty) | 'EXHIBITION'
    -- Naive LOCAL time. The API's string is UTC (see identity.parse_date for
    -- how that was pinned down), so it is converted on the way in; storing it
    -- verbatim once filed 90 of 121 head-to-head games under the wrong day.
    played_at        TEXT,
    display_date     TEXT,                 -- the original API string, still UTC

    innings          INTEGER,              -- can exceed 9; see game_innings
    ruling           TEXT,                 -- undocumented; 0 = normal, others seen: 2, 6, 15

    home_username    TEXT COLLATE NOCASE,
    away_username    TEXT COLLATE NOCASE,
    home_player_id   TEXT,
    away_player_id   TEXT,
    home_squad       TEXT,                 -- DD squad name, or an MLB team in exhibition
    away_squad       TEXT,

    home_runs        INTEGER,
    away_runs        INTEGER,
    home_hits        INTEGER,
    away_hits        INTEGER,
    home_errors      INTEGER,
    away_errors      INTEGER,
    winner           TEXT,                 -- 'home' | 'away' | NULL if undecided

    display_pitcher_info TEXT,             -- "W: Jhoan Duran (1-1, 0.00), L: ..."

    is_vs_cpu        INTEGER NOT NULL DEFAULT 0,  -- real computer opponent
    is_h2h           INTEGER NOT NULL DEFAULT 0,  -- me vs FRIEND_USERNAME (opponents)
    -- Both of us were in the game but NOT against each other — i.e. co-op, on
    -- the same side. Detected by the game appearing in both accounts' history
    -- crawls. Not head-to-head, but still "a game we both played".
    is_coop          INTEGER NOT NULL DEFAULT 0,
    is_third_party   INTEGER NOT NULL DEFAULT 0,  -- neither slot was blanked
    has_box_score    INTEGER NOT NULL DEFAULT 0,

    raw              TEXT,
    imported_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_games_h2h  ON games(is_h2h, played_at);
CREATE INDEX IF NOT EXISTS idx_games_coop ON games(is_coop, played_at);
CREATE INDEX IF NOT EXISTS idx_games_date ON games(played_at);


-- Maps each participant's private `id` back to the shared game.
-- Needed because game_log.json requires the (id, username, platform) triple to
-- match — you cannot read a game using someone else's id.
CREATE TABLE IF NOT EXISTS game_source_ids (
    game_uuid    TEXT NOT NULL,
    natural_key  TEXT NOT NULL,
    username     TEXT NOT NULL COLLATE NOCASE,
    api_id       TEXT NOT NULL,
    imported_at  TEXT,
    PRIMARY KEY (natural_key, username)
);

CREATE INDEX IF NOT EXISTS idx_source_ids_uuid ON game_source_ids(game_uuid);


-- Per-inning line score. CAPPED AT 9 BY THE API: a game with innings > 9 will
-- have runs that appear in games.home_runs/away_runs but in no row here.
-- Verified on an 11-inning game whose per-inning runs summed to 2 against a
-- true total of 3. Treat games.*_runs as authoritative; this table is for
-- drawing the line score only.
CREATE TABLE IF NOT EXISTS game_innings (
    game_uuid    TEXT NOT NULL,
    inning_no    INTEGER NOT NULL,
    home_runs    INTEGER,
    away_runs    INTEGER,
    PRIMARY KEY (game_uuid, inning_no)
);


-- One row per batter per game.
-- player_name is LAST NAME ONLY plus a position tag, e.g. "Clement, LF" — the
-- API exposes no player id here, so two different cards of the same real player
-- (and two players sharing a surname) are indistinguishable. Known limitation,
-- requested by the community and still not fixed as of MLB 26.
CREATE TABLE IF NOT EXISTS batting_lines (
    game_uuid    TEXT NOT NULL,
    side         TEXT NOT NULL,            -- 'home' | 'away'
    username     TEXT COLLATE NOCASE,      -- denormalized owner, for fast leaderboards
    slot         INTEGER NOT NULL,         -- order within the box score, for uniqueness
    player_name  TEXT,                     -- "Clement" (surname, split off the position)
    pos          TEXT,                     -- "LF"
    ab INTEGER, r INTEGER, h INTEGER, rbi INTEGER, bb INTEGER, so INTEGER,
    doubles INTEGER, triples INTEGER, hr INTEGER,
    sh INTEGER, sf INTEGER, gidp INTEGER, e INTEGER, hbp INTEGER,
    sb INTEGER, cs INTEGER,
    raw          TEXT,
    imported_at  TEXT,
    PRIMARY KEY (game_uuid, side, slot)
);

CREATE INDEX IF NOT EXISTS idx_batting_owner ON batting_lines(username, player_name);


-- One row per pitcher per game.
-- `outs` is the important column: the API reports innings pitched in baseball
-- notation where .1 = one out and .2 = two outs, so summing ip as a float gives
-- wrong ERA and K/9. outs is the integer truth; ip_text keeps the original.
CREATE TABLE IF NOT EXISTS pitching_lines (
    game_uuid    TEXT NOT NULL,
    side         TEXT NOT NULL,
    username     TEXT COLLATE NOCASE,
    slot         INTEGER NOT NULL,
    player_name  TEXT,
    ip_text      TEXT,
    outs         INTEGER,
    r INTEGER, h INTEGER, er INTEGER, bb INTEGER, so INTEGER,
    win INTEGER, loss INTEGER, save INTEGER, hold INTEGER, wp INTEGER,
    raw          TEXT,
    imported_at  TEXT,
    PRIMARY KEY (game_uuid, side, slot)
);

CREATE INDEX IF NOT EXISTS idx_pitching_owner ON pitching_lines(username, player_name);


-- The narrative play-by-play, stored verbatim. It is marked-up prose
-- (^n^ = newline, ^c51^ = inning header, ^c46^ = critical play, ...) with no
-- structured events. Kept whole so it can be parsed later without re-crawling.
CREATE TABLE IF NOT EXISTS game_log_text (
    game_uuid    TEXT PRIMARY KEY,
    text         TEXT,
    imported_at  TEXT
);


-- Events pulled out of the play-by-play prose (see playbyplay.py). The API has
-- no pitch-level endpoint; this is the only place pitch type, location and
-- swing timing exist. Rebuilt from game_log_text, so re-parsing never re-crawls.
--
-- Both usernames are stored because a strikeout has two owners: the batter who
-- was beaten and the pitcher who did it. "How he gets you out" needs the pair.
CREATE TABLE IF NOT EXISTS pa_events (
    game_uuid         TEXT NOT NULL,
    idx               INTEGER NOT NULL,   -- order within the game
    inning            INTEGER,
    squad             TEXT,
    batting_username  TEXT COLLATE NOCASE,
    pitching_username TEXT COLLATE NOCASE,
    batter            TEXT,
    kind              TEXT,               -- 'strikeout' | 'home_run'
    pitch_type        TEXT,               -- strikeouts only
    location          TEXT,               -- strikeouts only
    timing            TEXT,               -- chasing | late | early | looking | swinging
    distance          INTEGER,            -- home runs only, feet
    direction         TEXT,               -- home runs only
    -- Home runs only, counted from the "<Runner> scores." sentences the log
    -- prints behind the homer. 4 is a grand slam; the log never uses the phrase.
    rbi               INTEGER,
    critical          INTEGER NOT NULL DEFAULT 0,
    scored            INTEGER NOT NULL DEFAULT 0,
    go_ahead          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_uuid, idx)
);

CREATE INDEX IF NOT EXISTS idx_pa_kind ON pa_events(kind, batting_username);


-- "Perfect Contact Hits (Perfect-Perfect)" from the log's trailer: the only
-- exit-velocity data the API exposes, and only for perfectly-struck balls —
-- never a full batted-ball set.
CREATE TABLE IF NOT EXISTS contact_events (
    game_uuid   TEXT NOT NULL,
    idx         INTEGER NOT NULL,
    batter      TEXT,
    username    TEXT COLLATE NOCASE,      -- resolved via that game's box score
    exit_velo   INTEGER,                  -- mph
    outcome     TEXT,                     -- the log's own wording
    result      TEXT,                     -- home run | triple | double | single | out
    PRIMARY KEY (game_uuid, idx)
);


-- One row per half-inning, from the totals line the log prints after each.
-- The only place pitch counts exist, which is what makes an immaculate inning
-- (three strikeouts on exactly nine pitches) detectable at all.
CREATE TABLE IF NOT EXISTS half_innings (
    game_uuid        TEXT NOT NULL,
    idx              INTEGER NOT NULL,   -- order within the game
    inning           INTEGER,
    squad            TEXT,
    batting_username TEXT COLLATE NOCASE,
    pitching_username TEXT COLLATE NOCASE,
    runs INTEGER, hits INTEGER, walks INTEGER, errors INTEGER,
    pitches INTEGER, lob INTEGER, strikeouts INTEGER,
    -- Turned by the fielding side, so they belong to pitching_username. The box
    -- score has no double-play column at all; these come from the play's tag.
    double_plays INTEGER NOT NULL DEFAULT 0,
    triple_plays INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_uuid, idx)
);


-- Per-game context from the trailer. Difficulty is here because the games were
-- not all played on the same one.
CREATE TABLE IF NOT EXISTS game_meta (
    game_uuid           TEXT PRIMARY KEY,
    hitting_difficulty  TEXT,
    pitching_difficulty TEXT,
    stadium             TEXT,
    weather             TEXT
);


CREATE TABLE IF NOT EXISTS import_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT,
    range_start  TEXT,
    range_end    TEXT,
    rows         INTEGER,
    ran_at       TEXT
);


-- --------------------------------------------------------------------------
-- Views. All dashboard statistics live here rather than in Python, so a
-- different front-end later is a rendering change, not a data-layer change.
-- --------------------------------------------------------------------------

-- Whether a game counts, and for what.
--
-- The Show awards a decision on every game that ends early, and a disconnect
-- looks exactly like a finished game apart from `ruling`. All six here went to
-- the home player — including a 0-0, a 1-1, and one where the home side was
-- losing 2-4. Taking those at face value inflates the record with games nobody
-- won on the field.
--
-- Rather than invent a rule, this is baseball's own. A game is *regulation*
-- once five innings are complete; called before that it is a "no game" and
-- counts for nothing. A regulation game called with the score tied is a tie:
-- the statistics stand, but no one is credited with a win or a loss. A
-- regulation game called with someone ahead is simply a win, the way a
-- rain-shortened game is.
--
-- Simplification worth knowing: the real rule makes a game regulation after
-- 4½ innings if the home side leads, since it does not bat in the bottom half.
-- `games.innings` counts whole innings, so that half-inning case would need
-- `half_innings`. No game in this data sits on that boundary.
DROP VIEW IF EXISTS v_game_status;
CREATE VIEW v_game_status AS
SELECT
    game_uuid,
    status,
    status = 'final'                                AS counts_record,
    status <> 'no_contest'                          AS counts_stats
FROM (
    SELECT
        g.game_uuid,
        CASE
            -- ruling is NULL for history-only rows (no box score fetched) and
            -- '0' for a normal finish. Neither is in question.
            WHEN g.ruling IS NULL OR g.ruling = '0'            THEN 'final'
            WHEN g.innings >= 5 AND g.home_runs <> g.away_runs THEN 'final'
            WHEN g.innings >= 5                                THEN 'tie'
            ELSE 'no_contest'
        END AS status
    FROM games g
);


-- Head-to-head games flattened to "me" vs "them" regardless of home/away.
DROP VIEW IF EXISTS v_h2h_games;
CREATE VIEW v_h2h_games AS
SELECT
    g.game_uuid,
    g.played_at,
    g.display_date,
    g.innings,
    g.innings > 9                                    AS extra_innings,
    me.username                                      AS me,
    CASE WHEN g.home_username = me.username THEN 'home'        ELSE 'away'        END AS my_side,
    CASE WHEN g.home_username = me.username THEN g.home_runs   ELSE g.away_runs   END AS my_runs,
    CASE WHEN g.home_username = me.username THEN g.away_runs   ELSE g.home_runs   END AS their_runs,
    CASE WHEN g.home_username = me.username THEN g.home_hits   ELSE g.away_hits   END AS my_hits,
    CASE WHEN g.home_username = me.username THEN g.away_hits   ELSE g.home_hits   END AS their_hits,
    CASE WHEN g.home_username = me.username THEN g.home_squad  ELSE g.away_squad  END AS my_squad,
    CASE WHEN g.home_username = me.username THEN g.away_squad  ELSE g.home_squad  END AS their_squad,
    -- Only a game that counts for the record carries a decision. A tie and a
    -- no contest both come back NULL, so anything summing W/L ignores them
    -- without having to know this rule exists.
    CASE
        WHEN s.status <> 'final' THEN NULL
        WHEN g.winner IS NULL THEN NULL
        WHEN g.winner = CASE WHEN g.home_username = me.username THEN 'home' ELSE 'away' END THEN 'W'
        ELSE 'L'
    END                                              AS result,
    -- The decision exactly as the API reported it, before any policy is applied.
    -- Kept so a check on *ingestion* can measure what the API actually said —
    -- otherwise changing the policy makes a fixed historical measurement look
    -- like the crawl started losing games.
    CASE
        WHEN g.winner IS NULL THEN NULL
        WHEN g.winner = CASE WHEN g.home_username = me.username THEN 'home' ELSE 'away' END THEN 'W'
        ELSE 'L'
    END                                              AS api_result,
    g.has_box_score,
    g.ruling,
    -- ruling is undocumented; 0 is a normal finish. Non-zero shows up on games
    -- that ended early. See v_game_status for what is done with them.
    g.ruling <> '0'                                  AS ended_early,
    s.status,
    s.counts_record,
    s.counts_stats
FROM games g
JOIN players me ON me.is_me = 1
JOIN v_game_status s ON s.game_uuid = g.game_uuid
WHERE g.is_h2h = 1;


-- The headline record.
--
-- `games` counts what the record is built from — games that reached regulation,
-- ties included. No contests are reported separately rather than folded in or
-- silently dropped, so every game ever played is still accounted for:
-- games + no_contests = every head-to-head game.
--
-- Runs come only from games that count, for the same reason the at-bats do.
DROP VIEW IF EXISTS v_h2h_record;
CREATE VIEW v_h2h_record AS
SELECT
    SUM(counts_stats)                               AS games,
    SUM(result = 'W')                               AS wins,
    SUM(result = 'L')                               AS losses,
    SUM(status = 'tie')                             AS ties,
    SUM(status = 'no_contest')                      AS no_contests,
    COUNT(*)                                        AS games_played,
    ROUND(CAST(SUM(result = 'W') AS REAL) / NULLIF(SUM(result IN ('W','L')), 0), 3) AS win_pct,
    SUM(CASE WHEN counts_stats THEN my_runs    ELSE 0 END) AS runs_for,
    SUM(CASE WHEN counts_stats THEN their_runs ELSE 0 END) AS runs_against,
    ROUND(AVG(CASE WHEN counts_stats THEN my_runs    END), 2) AS avg_runs_for,
    ROUND(AVG(CASE WHEN counts_stats THEN their_runs END), 2) AS avg_runs_against
FROM v_h2h_games;


-- Games we were both in but on the same side, against someone else.
DROP VIEW IF EXISTS v_coop_games;
CREATE VIEW v_coop_games AS
SELECT
    g.game_uuid,
    g.played_at,
    g.display_date,
    g.home_username, g.away_username,
    g.home_squad, g.away_squad,
    g.home_runs, g.away_runs,
    g.winner,
    g.has_box_score
FROM games g
WHERE g.is_coop = 1;


-- Whole-roster totals per player, for a direct side-by-side comparison.
-- Same formulas as the per-card views, grouped only by owner.
DROP VIEW IF EXISTS v_team_batting;
CREATE VIEW v_team_batting AS
SELECT
    b.username,
    SUM(b.ab) AS ab, SUM(b.h) AS h, SUM(b.hr) AS hr, SUM(b.rbi) AS rbi,
    SUM(b.r) AS runs, SUM(b.bb) AS bb, SUM(b.so) AS so,
    SUM(b.sb) AS sb, SUM(b.cs) AS cs,
    SUM(b.doubles) AS doubles, SUM(b.triples) AS triples,
    ROUND(CAST(SUM(b.h) AS REAL) / NULLIF(SUM(b.ab), 0), 3) AS avg,
    ROUND(CAST(SUM(b.h) + SUM(b.bb) + SUM(b.hbp) AS REAL)
          / NULLIF(SUM(b.ab) + SUM(b.bb) + SUM(b.hbp) + SUM(b.sf), 0), 3) AS obp,
    ROUND(CAST(SUM(b.h) + SUM(b.doubles) + 2 * SUM(b.triples) + 3 * SUM(b.hr) AS REAL)
          / NULLIF(SUM(b.ab), 0), 3) AS slg,
    ROUND(CAST(SUM(b.h) + SUM(b.bb) + SUM(b.hbp) AS REAL)
          / NULLIF(SUM(b.ab) + SUM(b.bb) + SUM(b.hbp) + SUM(b.sf), 0)
        + CAST(SUM(b.h) + SUM(b.doubles) + 2 * SUM(b.triples) + 3 * SUM(b.hr) AS REAL)
          / NULLIF(SUM(b.ab), 0), 3) AS ops
FROM batting_lines b
JOIN games g ON g.game_uuid = b.game_uuid
JOIN v_game_status s ON s.game_uuid = g.game_uuid
WHERE g.is_h2h = 1 AND s.counts_stats = 1
GROUP BY b.username;


DROP VIEW IF EXISTS v_team_pitching;
CREATE VIEW v_team_pitching AS
SELECT
    p.username,
    SUM(p.outs) AS outs,
    CAST(SUM(p.outs) / 3 AS INTEGER) + (SUM(p.outs) % 3) / 10.0 AS innings,
    SUM(p.so) AS so, SUM(p.bb) AS bb, SUM(p.h) AS h, SUM(p.er) AS er, SUM(p.r) AS r,
    ROUND(27.0 * SUM(p.er) / NULLIF(SUM(p.outs), 0), 2) AS era,
    ROUND(27.0 * SUM(p.so) / NULLIF(SUM(p.outs), 0), 2) AS k_per_9,
    ROUND(27.0 * SUM(p.bb) / NULLIF(SUM(p.outs), 0), 2) AS bb_per_9,
    ROUND(3.0 * (SUM(p.h) + SUM(p.bb)) / NULLIF(SUM(p.outs), 0), 3) AS whip
FROM pitching_lines p
JOIN games g ON g.game_uuid = p.game_uuid
JOIN v_game_status s ON s.game_uuid = g.game_uuid
WHERE g.is_h2h = 1 AND s.counts_stats = 1
GROUP BY p.username;


-- How each pitcher puts each batter away: type, spot, and how the hitter was
-- beaten. Grouped by the pair, because "what he strikes me out with" and "what
-- I strike him out with" are different questions.
DROP VIEW IF EXISTS v_strikeouts;
CREATE VIEW v_strikeouts AS
SELECT
    e.batting_username, e.pitching_username,
    e.pitch_type, e.location, e.timing, e.batter,
    COUNT(*) AS n
FROM pa_events e
JOIN games g ON g.game_uuid = e.game_uuid
JOIN v_game_status s ON s.game_uuid = g.game_uuid
WHERE g.is_h2h = 1 AND s.counts_stats = 1 AND e.kind = 'strikeout'
GROUP BY e.batting_username, e.pitching_username, e.pitch_type, e.location,
         e.timing, e.batter;


-- Every home run with its distance, direction and whether it put you ahead.
DROP VIEW IF EXISTS v_home_runs;
CREATE VIEW v_home_runs AS
SELECT
    e.game_uuid, e.batting_username AS username, e.batter,
    e.distance, e.direction, e.inning, e.go_ahead, g.display_date
FROM pa_events e
JOIN games g ON g.game_uuid = e.game_uuid
JOIN v_game_status s ON s.game_uuid = g.game_uuid
WHERE g.is_h2h = 1 AND s.counts_stats = 1 AND e.kind = 'home_run' AND e.distance IS NOT NULL;


-- Perfect-perfect contact per card: how often, how hard, and what came of it.
-- The out column is the interesting one — squaring a ball up perfectly and
-- still making an out is the most quotable thing in this dataset.
DROP VIEW IF EXISTS v_perfect_contact;
CREATE VIEW v_perfect_contact AS
SELECT
    c.username, c.batter,
    COUNT(*)                                        AS n,
    MAX(c.exit_velo)                                AS max_velo,
    ROUND(AVG(c.exit_velo), 1)                      AS avg_velo,
    SUM(c.result = 'home run')                      AS hr,
    SUM(c.result IN ('single', 'double', 'triple')) AS hits,
    SUM(c.result = 'out')                           AS outs
FROM contact_events c
JOIN games g ON g.game_uuid = c.game_uuid
JOIN v_game_status s ON s.game_uuid = g.game_uuid
WHERE g.is_h2h = 1 AND s.counts_stats = 1 AND c.username IS NOT NULL
GROUP BY c.username, c.batter;


-- Batting leaderboard across head-to-head games, per owner.
DROP VIEW IF EXISTS v_batting_totals;
CREATE VIEW v_batting_totals AS
SELECT
    b.username,
    b.player_name,
    COUNT(DISTINCT b.game_uuid)                     AS games,
    SUM(b.ab)                                       AS ab,
    SUM(b.h)                                        AS h,
    SUM(b.hr)                                       AS hr,
    SUM(b.rbi)                                      AS rbi,
    SUM(b.r)                                        AS runs,
    SUM(b.bb)                                       AS bb,
    SUM(b.so)                                       AS so,
    SUM(b.sb)                                       AS sb,
    SUM(b.doubles)                                  AS doubles,
    SUM(b.triples)                                  AS triples,
    SUM(b.hbp)                                      AS hbp,
    SUM(b.cs)                                       AS cs,
    -- Steals without caught-stealings is a half-truth: the break-even success
    -- rate is around 70-75%, so the ratio is the actual stat.
    ROUND(CAST(SUM(b.sb) AS REAL)
          / NULLIF(SUM(b.sb) + SUM(b.cs), 0), 3)    AS sb_pct,
    -- Plate appearances. SH is part of PA but deliberately NOT part of the OBP
    -- denominator below — the rules exclude a sacrifice bunt from OBP because
    -- it's an ordered play, while a sac fly still counts against the hitter.
    SUM(b.ab) + SUM(b.bb) + SUM(b.hbp) + SUM(b.sf) + SUM(b.sh) AS pa,
    ROUND(CAST(SUM(b.h) AS REAL) / NULLIF(SUM(b.ab), 0), 3) AS avg,
    -- total bases: singles + 2*2B + 3*3B + 4*HR
    ROUND(
        CAST(SUM(b.h) + SUM(b.doubles) + 2 * SUM(b.triples) + 3 * SUM(b.hr) AS REAL)
        / NULLIF(SUM(b.ab), 0), 3)                  AS slg,
    -- OBP needs plate appearances, which the API doesn't give; AB+BB+HBP+SF is
    -- the standard reconstruction and is exact apart from catcher's interference.
    ROUND(
        CAST(SUM(b.h) + SUM(b.bb) + SUM(b.hbp) AS REAL)
        / NULLIF(SUM(b.ab) + SUM(b.bb) + SUM(b.hbp) + SUM(b.sf), 0), 3) AS obp,
    ROUND(
        CAST(SUM(b.h) + SUM(b.bb) + SUM(b.hbp) AS REAL)
        / NULLIF(SUM(b.ab) + SUM(b.bb) + SUM(b.hbp) + SUM(b.sf), 0)
      + CAST(SUM(b.h) + SUM(b.doubles) + 2 * SUM(b.triples) + 3 * SUM(b.hr) AS REAL)
        / NULLIF(SUM(b.ab), 0), 3)                  AS ops,
    -- Isolated power = SLG - AVG, i.e. extra bases per at-bat. Separates a
    -- low-average slugger from a singles hitter with the same AVG.
    ROUND(CAST(SUM(b.doubles) + 2 * SUM(b.triples) + 3 * SUM(b.hr) AS REAL)
          / NULLIF(SUM(b.ab), 0), 3)                AS iso,
    -- Batting average on balls in play — the standard read on whether an
    -- average is skill or luck.
    ROUND(CAST(SUM(b.h) - SUM(b.hr) AS REAL)
          / NULLIF(SUM(b.ab) - SUM(b.so) - SUM(b.hr) + SUM(b.sf), 0), 3) AS babip,
    ROUND(100.0 * SUM(b.so)
          / NULLIF(SUM(b.ab) + SUM(b.bb) + SUM(b.hbp) + SUM(b.sf) + SUM(b.sh), 0), 1) AS k_pct,
    ROUND(100.0 * SUM(b.bb)
          / NULLIF(SUM(b.ab) + SUM(b.bb) + SUM(b.hbp) + SUM(b.sf) + SUM(b.sh), 0), 1) AS bb_pct
FROM batting_lines b
JOIN games g ON g.game_uuid = b.game_uuid
JOIN v_game_status s ON s.game_uuid = g.game_uuid
WHERE g.is_h2h = 1 AND s.counts_stats = 1
GROUP BY b.username, b.player_name;


-- Pitching leaderboard. ERA and K/9 derive from `outs`, never from ip as float.
DROP VIEW IF EXISTS v_pitching_totals;
CREATE VIEW v_pitching_totals AS
SELECT
    p.username,
    p.player_name,
    COUNT(DISTINCT p.game_uuid)                     AS games,
    SUM(p.outs)                                     AS outs,
    -- Innings pitched in true baseball notation: whole innings, then the
    -- leftover outs as tenths (.1 = one out, .2 = two). Conveniently this also
    -- sorts correctly as a float, since the fraction is always < 1 — so the
    -- column stays clickable-sortable without lying about the notation.
    CAST(SUM(p.outs) / 3 AS INTEGER) + (SUM(p.outs) % 3) / 10.0 AS innings,
    SUM(p.so)                                       AS so,
    SUM(p.bb)                                       AS bb,
    SUM(p.h)                                        AS h,
    SUM(p.er)                                       AS er,
    SUM(p.r)                                        AS r,
    SUM(p.win)                                      AS wins,
    SUM(p.loss)                                     AS losses,
    SUM(p.save)                                     AS saves,
    SUM(p.hold)                                     AS holds,
    SUM(p.wp)                                       AS wp,
    -- Slot 0 is the first pitcher listed, i.e. the starter.
    COUNT(DISTINCT CASE WHEN p.slot = 0 THEN p.game_uuid END) AS starts,
    -- 27 = 9 innings x 3 outs, so these are all per-9-innings rates.
    ROUND(27.0 * SUM(p.er) / NULLIF(SUM(p.outs), 0), 2) AS era,
    -- ERA hides what the defence gave away; RA/9 counts unearned runs too.
    ROUND(27.0 * SUM(p.r)  / NULLIF(SUM(p.outs), 0), 2) AS ra9,
    ROUND(27.0 * SUM(p.so) / NULLIF(SUM(p.outs), 0), 2) AS k_per_9,
    ROUND(27.0 * SUM(p.bb) / NULLIF(SUM(p.outs), 0), 2) AS bb_per_9,
    -- NULL (shown as blank) rather than divide-by-zero for a pitcher who has
    -- never walked anyone — an infinite K/BB is conventionally left undefined.
    ROUND(CAST(SUM(p.so) AS REAL) / NULLIF(SUM(p.bb), 0), 2) AS k_bb,
    ROUND(3.0 * (SUM(p.h) + SUM(p.bb)) / NULLIF(SUM(p.outs), 0), 3) AS whip
FROM pitching_lines p
JOIN games g ON g.game_uuid = p.game_uuid
JOIN v_game_status s ON s.game_uuid = g.game_uuid
WHERE g.is_h2h = 1 AND s.counts_stats = 1
GROUP BY p.username, p.player_name;
