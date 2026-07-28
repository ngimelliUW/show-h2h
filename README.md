# show-h2h

Head-to-head stats for MLB The Show 26, because the game doesn't keep them.

Crawls the public Show API into a local SQLite database and serves a localhost
dashboard: the rivalry record, batting and pitching leaderboards, and records
like biggest blowout and longest win streak. The dashboard reads only from the
database — pull fresh data explicitly when you want it.

Currently tracking **LinguiniEater vs TallThibaut48** (PSN), 111 head-to-head
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
```

`refresh` is the one to run regularly — it stops crawling as soon as it hits
games it already has, then fetches box scores for anything new.

Both the dashboard and the shared page have a **Viewing as** switch, so either
player sees the record, results and run differential from their own side.

## Hosting

Live at <https://ttvlinguinimlbtheshowstats.streamlit.app> — Streamlit Community
Cloud, deployed from this repo with `app/dashboard.py` as the entry point and
free to run.

`data/show.db` is committed as a seed so the app has data on a cold start, and
the **Pull new games** button crawls the Show API for anything played since.
That crawl is incremental — it stops as soon as it reaches a game already
stored, so it usually costs a couple of requests.

Streamlit Cloud's disk is ephemeral: games pulled with the button survive while
the app is warm but are lost when it restarts, falling back to the committed
seed. To make new games permanent, run `ingest refresh` locally and push the
database.

The **Which one are you?** control at the top switches whose side every number
is written from, so both players get their own view of the rivalry.

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
```

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

## Layout

```
src/show_h2h/
  config.py       paths + .env
  db.py           SQLite (WAL) connect/init/migrate/query
  client.py       API client: throttling, retries, error-shaped-as-200 guards
  identity.py     who played whom — the CPU-masking and name-normalizing rules
  ingest.py       CLI
  report.py       builds the page: queries the views, embeds the data as JSON
  importers/
    game_history.py   the game list, both accounts
    game_log.py       box scores; promotes natural_key -> real game_uuid
  schema.sql      tables + all the stat views
app/
  report_template.html   THE UI — hand-written HTML/CSS/JS
  dashboard.py           thin Streamlit shell: embeds the page, refresh button
analysis/         rivalry_report.py (text summary), _verify.py (checks)
data/show.db      the database (committed as a seed for the hosted app)
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
