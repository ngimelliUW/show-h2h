# show-h2h

Head-to-head stats for MLB The Show 26, because the game doesn't keep them.

Crawls the public Show API into a local SQLite database and serves a localhost
dashboard: the rivalry record, batting and pitching leaderboards, and records
like biggest blowout and longest win streak. The dashboard reads only from the
database — pull fresh data explicitly when you want it.

Currently tracking **LinguiniEater vs TallThibaut48** (PSN), 114 head-to-head
games since 2026-04-15.

## Setup

```bash
cp .env.example .env      # then edit the two usernames + platform
uv sync
uv run python -m show_h2h.ingest init-db
uv run python -m show_h2h.ingest history      # ~20 pages, both accounts
uv run python -m show_h2h.ingest box-scores   # ~119 games, ~1 minute
```

## Use

```bash
uv run streamlit run app/dashboard.py         # the dashboard
uv run python analysis/rivalry_report.py      # same thing as terminal text
uv run python -m show_h2h.ingest refresh      # pull new games after a session
uv run python -m show_h2h.ingest status       # what's in the database
uv run python -m show_h2h.ingest parse-logs   # re-parse play-by-play (no network)
```

`refresh` is the one to run regularly — it stops crawling as soon as it hits
games it already has, then fetches box scores for anything new.

Both the dashboard and the shared page have a **Viewing as** switch, so either
player sees the record, results and run differential from their own side.

## Hosting

Live at <https://ttvlinguinimlbtheshowstats.streamlit.app> — Streamlit Community
Cloud, deployed from this repo with `app/dashboard.py` as the entry point and
free to run.

`data/seed.db` is committed so the app has data on a cold start, and
the **Pull new games** button crawls the Show API for anything played since.
That crawl is incremental — it stops as soon as it reaches a game already
stored, so it usually costs a couple of requests.

Streamlit Cloud's disk is ephemeral: games pulled with the button survive while
the app is warm but are lost when it restarts, falling back to the committed
seed. To make new games permanent:

```bash
uv run python -m show_h2h.ingest refresh
uv run python -m show_h2h.ingest snapshot   # checkpoints WAL, writes data/seed.db
git commit -am "refresh data" && git push
```

### Nightly refresh

`scripts/nightly-refresh.sh` pulls new games at **02:00**, verifies them, and
commits `data/seed.db` — which is what makes new games permanent, since the app's
own button writes to Streamlit Cloud's ephemeral disk and is lost on restart.

Scheduled by `~/Library/LaunchAgents/com.show-h2h.nightly-refresh.plist`. The
machine is on `America/Chicago` and launchd honours local time through daylight
saving, so it stays 2am Central without the twice-a-year drift a UTC cron would
have. If the Mac is asleep at 2am, launchd runs the job on the next wake.

```bash
launchctl print gui/$(id -u)/com.show-h2h.nightly-refresh   # is it loaded?
launchctl kickstart -k gui/$(id -u)/com.show-h2h.nightly-refresh  # run it now
tail -f ~/Library/Logs/show-h2h/refresh.log
launchctl bootout gui/$(id -u)/com.show-h2h.nightly-refresh  # remove it
```

**It can't run in GitHub Actions.** The Show API returns **403 to GitHub's
runners** — verified with four different User-Agents including a real browser
one, so it's the datacenter IP range, not the client. A workflow was written and
deleted; don't rewrite it. Any host that isn't a residential connection will
likely hit the same wall.

It publishes only if the data actually changed, and only if every check passes:

1. abort if `data/seed.db` already has uncommitted changes
2. `ingest refresh` + `parse-logs`
3. compare row counts — no change means no commit, since a SQLite file's bytes
   differ on every checkpoint even when no row does
4. `_verify.py` and `_flip.py` must pass
5. `ingest snapshot`, which **refuses to publish a database with fewer rows** than
   the one it's replacing, so a half-failed crawl can't delete history
6. `_smoke.py`, then commit and push

Rehearse the whole thing against a throwaway copy with
`uv run python analysis/_nightly.py` — it drives the real commands and asserts
each failure mode, including that verification *fails* on a damaged database.

**The app never writes to the committed database.** `data/seed.db` is a
published snapshot written by `ingest snapshot`; the CLI's working database
(`data/show.db`) is gitignored. On boot the app copies the seed to a temp path
and works there, re-seeding whenever the seed is newer. This matters: the app writes on every boot (schema migrations)
and Streamlit Cloud redeploys by pulling, and a pull will not overwrite a
locally-modified file. Writing in place pinned the deploy to whatever database
existed the first time the app ever ran — new code, stale tables, new pages
silently empty.

Two controls in the scoreboard drive the whole page:

- **You are** switches whose side every number is written from.
- **Window** is a slider limiting every stat — record, leaderboards, pitch grid,
  contact quality — to any number of recent games, with one-tap presets because
  dragging to an exact 10 on a 111-wide track is fiddly on a phone. Playing-time
  qualifiers scale with it, or a 50-AB minimum over ten games would qualify
  nobody and every leaderboard would come up empty.

The window is why the page carries per-game rows rather than totals: the browser
re-aggregates on every change. Those rows are column-encoded (names once,
repeated strings as dictionary indexes), which is 173 KB instead of 618 KB.

Nothing here is secret: the Show API needs no key, and `.env` holds only the two
usernames and the platform (all of which have defaults in `config.py`, so the
hosted app runs without it).

There was briefly a second, static copy served from GitHub Pages. It's gone —
two front-ends meant two designs to keep in sync, and they immediately drifted.

## Checks

```bash
uv run python analysis/_verify.py   # stat math + ingest correctness, 21 assertions
uv run python analysis/_smoke.py    # every page renders, from both perspectives
uv run python analysis/_flip.py     # the perspective switch is a true mirror

# end-to-end, needs a running app; playwright is pulled in per-run
uv run streamlit run app/dashboard.py --server.port 8502 --server.headless true &
uv run --with playwright python analysis/_browser.py
```

`_browser.py` asserts against the report's **iframe**, not the page.
`page.on("pageerror")` does not surface exceptions thrown in a child frame, so a
naive check reports "no errors" while the page is visibly broken — that is
exactly how a crash in `renderFeats` once shipped.

`_verify.py` asserts against figures measured directly from the API before the
pipeline existed, so it catches a regression in ingestion, not just a crash.

## Data sources

| Endpoint | Status | Notes |
|---|---|---|
| `game_history.json` | ✅ | Paginated list of games, 25/page. No auth. |
| `game_log.json` | ✅ | Full box score + play-by-play for one game. |
| `player_search.json` | 🔜 | Lifetime/season profile stats, not yet used. |

No API key, token or login is required — these endpoints are public given a
username, and Show profiles cannot be made private.

## Things the API does that will confuse you

Everything here was verified against live responses, not the docs.

- **`game.json` does not exist.** The box-score endpoint is `game_log.json`.
  Requesting `game.json` returns a 22 KB HTML 404 page with **HTTP 200**.
- **Game IDs are per-participant.** The same game is `1554797583` in one
  player's history and `1554797584` in the other's. Only `game_uuid` (which
  appears in `game_log`, never in `game_history`) identifies a game globally.
  Dedupe on that or you'll double-count every game.
- **The API blanks out whoever is asking.** Your own name comes back as the
  literal string `"CPU"` in `game_history` and as `""` in `game_log`. A real
  game against the computer is identified by the *squad* field
  (`home_full_name`/`away_full_name`) reading `"CPU"`, not the name field.
- **`mode=all` excludes Exhibition games.** `all` and `arena` return identical
  sets; `exhibition` is disjoint. Both are crawled and merged.
- **`platform` is ignored by `game_history` but enforced by `game_log`**, which
  rejects any (id, username, platform) triple that doesn't match.
- **Usernames carry badge suffixes** (`"LinguiniEater ^b53^"`) in history but
  not in box scores, and the API's casing differs from what you'd type. All
  comparisons are normalized.
- **The line score is capped at 9 innings and loses extra-inning runs.** An
  11-inning game here has per-inning runs summing to 2 against a real total of
  3. Game totals are correct; only the inning-by-inning breakdown is lossy.
- **Batters are surname-only** (`"Clement, LF"`) with no player id, and long
  surnames are truncated (`"Misiorowsk..."`). Two cards of the same player
  merge; two players sharing a surname are indistinguishable. Both players
  routinely field a card with the same surname, so anything keyed on the name
  alone (a chart axis, a group-by) has to carry the owner too.
- **Pitcher names carry the decision** — `W`, `L`, `S`, `H` and `BS` are appended
  to the name (`"Kluber (W)"`). All five must be stripped, or one pitcher splits
  into several leaderboard rows with partial stats.
- **`ruling` is undocumented and non-zero means the game ended early.** Two games
  here have a tied score with a winner awarded — one of them 0–0. They count in
  the record because the game awarded them, but they aren't shutouts.
- **Innings pitched use baseball notation** — `8.1` means 8⅓, not 8.1. Summing
  it as a float gives wrong ERA. The `outs` column is the integer truth.
- **Paging past `total_pages` re-serves the last page** rather than returning
  empty, so "loop until empty" never terminates.
- **History is per-edition.** `mlb26` cannot see MLB 25 games. Set
  `SEASON_YEAR=25` and re-run to backfill an older season alongside.
- No documented rate limits and no rate-limit headers, but SDS does throttle.
  Requests are spaced by `REQUEST_DELAY` (default 0.35s).
- **The play-by-play has a trailer that restates plays.** After the innings comes
  a legend, a perfect-contact list and the stadium/umpire block, and the plays it
  mentions appear in the narrative too. Parse the whole blob and home runs come
  out 57% high. `playbyplay.split_sections()` separates them.

## Chasing history

The Overview tab tracks what nobody has managed yet, each with the nearest miss,
because a bare zero says nothing about whether a feat is imminent or absurd.
Still outstanding: perfect game, no-hitter, the cycle (nobody has more than 3 of
the 4 hits — triples are the bottleneck, 20 in 2,011 batting lines), a 3-homer
game (best is 2), and a 20-strikeout game (best is 18). Anything achieved drops
off the list automatically.

Alongside it, the rarest things that *have* happened: 3 immaculate innings
(three strikeouts on exactly nine pitches — only detectable because the log
prints a pitch count per half-inning), 102 strike-out-the-sides, 15 walk-offs.

A
complete game means one pitcher recorded every out his side made in a game that
went the full nine — the five- and six-inning games in this record ended early,
and a no-hitter in a shortened game isn't one, which is why the count is 48 and
not 58.

Baserunners allowed is hits + walks + hit batsmen + the pitching side's errors.
That last term is a stand-in: the box score reports how many errors a side made,
not whether a batter reached on one, so a harmless fielding error would still
spoil a "perfect" here. It only ever costs a candidate, and every near-miss so
far has been error-free, so it has never mattered.

## What's only in the play-by-play

There's no pitch-level endpoint, but the prose in `game_log` carries a lot the
box score doesn't. Parsed into `pa_events` / `contact_events`:

- **Pitch type and location on strikeouts** — 1,700-odd of them name both, so
  you can see exactly where each hitter gets beaten. Only on strikeouts, so it's
  not a full pitch mix.
- **Swing timing** — chased, late, early, or caught looking.
- **Home-run distance and direction**, in feet.
- **Perfect-perfect contact with exit velocity** — the only batted-ball speed the
  API exposes, and only for perfectly-struck balls. Includes what happened, so
  you can count the ones that got caught anyway.
- **Go-ahead and critical plays**, from colour codes in the markup.
- Difficulty, weather and stadium per game, in `game_meta`.

Totals are asserted against the box score in `_verify.py` — if the parse drifts,
the strikeout and home-run counts stop matching.

## Layout

```
src/show_h2h/
  config.py       paths + .env
  db.py           SQLite (WAL) connect/init/migrate/query
  client.py       API client: throttling, retries, error-shaped-as-200 guards
  identity.py     who played whom — the CPU-masking and name-normalizing rules
  ingest.py       CLI
  playbyplay.py   parses the play-by-play prose into structured events
  report.py       builds the page: queries the views, embeds the data as JSON
  importers/
    game_history.py   the game list, both accounts
    game_log.py       box scores; promotes natural_key -> real game_uuid
    play_by_play.py   prose -> pa_events / contact_events (local, no network)
  schema.sql      tables + all the stat views
app/
  report_template.html   THE UI — hand-written HTML/CSS/JS
  dashboard.py           thin Streamlit shell: embeds the page, refresh button
analysis/         rivalry_report.py (text summary), _verify.py (checks)
data/show.db      working database (gitignored)
data/seed.db      published snapshot the hosted app ships with
```

**The UI is `app/report_template.html`, not Streamlit widgets.** The design is a
full-bleed scoreboard over dense box-score tables, which Streamlit's DOM can't
be styled into without a pile of brittle overrides — an earlier version tried
and drifted into a visibly different product. Streamlit's job is hosting, and
reaching the API for new games; the page does everything else, including the
you-are switch, the tabs and the sortable leaderboards.

Statistics live in SQL views (`v_h2h_record`, `v_batting_totals`,
`v_pitching_totals`, `v_team_batting`, ...), so the page is a renderer and the
numbers have exactly one definition.

Statistics live in SQL views (`v_h2h_record`, `v_batting_totals`,
`v_pitching_totals`, ...) rather than in dashboard code, so swapping Streamlit
for a hosted front-end later doesn't touch the data layer.

## Game classification

Each game is flagged as one of:

- `is_h2h` — the two of us as opponents. **This is what the record counts.**
- `is_coop` — both of us in the game but on the same side, against someone
  else. Inferred from the game appearing in both accounts' histories.
- `is_vs_cpu` — a real computer opponent.
- `is_third_party` — a record that leaked into a history without either of us
  being one of the two named players.

All games either account has played are stored (354 of them), not just the
rivalry ones — the history crawl is cheap and having the rest gives a baseline
to compare rivalry performance against. Box scores, which cost one request
each, are fetched only for games you were both in (`--scope all` widens this).

One thing the API cannot tell you: whether a game was an invited "Play vs
Friend" match or a random matchmake. There is no such field. Head-to-head is
determined purely by opponent identity.
