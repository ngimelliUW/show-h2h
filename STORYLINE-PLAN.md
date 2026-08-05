# Storyline / news-desk feature — plan

Generate a beat-writer's coverage of the LinguiniEater vs TallThibaut48 rivalry:
game recaps, roster-debut stories, streak and slump watches. Runs entirely on
Nic's Mac as part of the existing nightly job. No API key, no per-token cost.

Status: **planned, not built.** Numbers below measured against `data/seed.db`
on 2026-08-05 (126 H2H games).

---

## 1. Where the AI runs

Claude Code headless, already installed:

    /Users/Nic/.local/bin/claude   # v2.1.222

    claude -p "<fact block>" --append-system-prompt "<beat-writer rules>"

This bills against the existing Claude subscription, not the API — no token
budget, no key management, no `.env` secret. It is the whole reason this
design works the way it does.

**launchd gotcha:** `com.show-h2h.nightly-refresh.plist` runs with a minimal
PATH. `claude` will not be on it. Call the absolute path, and treat a missing
binary as a soft failure — the refresh must still commit `seed.db` if story
generation dies. Same tolerant-step pattern `ingest refresh` already uses.

**Local gotcha (hit 4+ times in this project):** the `snip` PreToolUse hook
truncates piped/redirected shell output. Do not build the fact block with
`sqlite3 ... > facts.txt` or read the model's output through a pipe in a way
that a hook can see. Build the prompt string inside Python, pass it via
`subprocess.run([...], input=..., capture_output=True)`, and write results with
`Path.write_text`.

---

## 2. The core idea: facts from SQL, voice from the model

The failure mode for this feature is slop. The fix is not better prompting —
it is never letting the model source a fact.

The hand-written Peanut Johnson recap worked because it had *"the bid ended on
the first pitch of the eighth,"* a game score of 73, a 98 mph perfect-perfect,
and the Mamie Johnson footnote. Hand a model a raw box score and say "write a
recap" and it produces mush. Hand it

    NOTABLE (rank 1 of 126): Johnson, 7.0ip, 1h, 0k — most innings with 0 K
    NOTABLE: 12 innings (3rd-longest of 126)
    NOTABLE: Harper 2 HR, both go-ahead, 10th and 12th

and it can only rearrange true things into prose. It also means a recap can
never invent a stat, which is the non-negotiable requirement — data accuracy is
the point of this whole project.

Corollary: **every notable names its subject.** No "a big home run" — always
"Harper, 405 feet to right." This matches the existing rule for feats on the
site.

---

## 3. What's already detectable

### 3a. Game notables — 88% coverage today

A first-pass scorer over existing tables flagged **111 of 126 H2H games (88%)**
with at least one notable; 41 games had three or more.

| type | games | source |
|---|---|---|
| scorched (110+ mph) | 74 | `contact_events` |
| one-run game | 44 | `v_h2h_games` |
| shutout | 43 | `v_h2h_games` |
| 12+ K | 23 | `pitching_lines` |
| multi-HR game | 15 | `batting_lines` |
| 1-hit gem (5+ ip) | 15 | `pitching_lines` |
| late go-ahead HR (8th+) | 14 | `pa_events` |
| extra innings (11+) | 7 | `v_h2h_games` |
| moonshot (450+ ft) | 7 | `pa_events` |
| 4+ hit game | 5 | `batting_lines` |
| blowout (8+ runs) | 5 | `v_h2h_games` |

Structured coverage is complete — `batting_lines`, `pitching_lines`,
`half_innings`, `pa_events`, `game_log_text`, `game_meta` all cover 126/126.
Only `contact_events` has a gap (111/126), so exit-velo notables must degrade
gracefully rather than assume presence.

**Rarity rank is what makes it readable.** A notable needs to know whether it is
the best ever, top-5, or merely good — that is the difference between "Johnson
threw seven no-hit innings" and "Johnson threw the only seven-inning no-hit
start in the 126 games these two have played." Each notable carries a
`rank_alltime` and `n_games` computed in SQL.

### 3b. Roster debuts — works, with one hard limit

**There is no card identifier anywhere in the data.** Both candidate fields are
per-game roster slots, not stable IDs:

- `batting_lines.raw.p_inx` — 75 of 165 (owner, surname) pairs span multiple
  values; slot 531 alone covers Abrams, Adell, Anderson, Bellinger, Brito,
  Conforto, Crow-Armstrong, Delgado…
- `pitching_lines.raw.p_idx` — same story. 22 of 26 (owner, p_idx) pairs map to
  multiple names; slot 527 covers 12 different LinguiniEater pitchers.

(An earlier note in this project claimed `p_idx` was a stable card index. It is
not. It appeared to disambiguate the two Johnsons only because they belonged to
different accounts, which the username already told us.)

So identity is **(owner, surname)** and nothing more. That means:

- ✅ *"Baldwin's first game with the Worms"* — reliable. First appearance of a
  surname on an owner's roster is unambiguous.
- ✅ Debut stat line, and a follow-up once N games accumulate.
- ❌ Swapping an 85-overall Harper for a 99-overall Harper is **invisible**.
  Same surname, reads as the same player.
- ⚠️ A card *leaving* can only be inferred from absence over N games. That is a
  heuristic, not a fact — phrase it as "hasn't appeared since," never "was cut."

Churn is real and asymmetric, which is itself a storyline:

| | distinct names | Apr | May | Jun | Jul | Aug |
|---|---|---|---|---|---|---|
| LinguiniEater | 80 | 38 | 21 | 12 | 9 | 0 |
| TallThibaut48 | 85 | 25 | 13 | 20 | 24 | 3 |

One manager's roster has settled; the other never stops tinkering.

### 3c. Squad eras — free narrative structure

| owner | squad | games | record | span |
|---|---|---|---|---|
| Nic | SWEs | 58 | 38–19 | 2026-04-16 → 06-05 |
| Nic | Gooners | 4 | 3–1 | 2026-06-08 → 06-11 |
| Nic | Birds | 64 | 43–18 | 2026-06-15 → 08-05 |
| TallThibaut48 | Worms | 126 | — | 2026-04-16 → 08-05 |

Nic has rebranded twice; TallThibaut48 has been the Worms since day one.

---

## 4. Schema additions

```sql
-- One row per notable thing that happened, one game.
CREATE VIEW v_game_notables AS ...   -- game_uuid, kind, subject, owner,
                                     -- detail, rank_alltime, n_games, weight

-- First appearance of a surname on an owner's roster.
CREATE VIEW v_roster_debuts AS ...   -- game_uuid, owner, squad, player_name,
                                     -- debut_line, is_pitcher

-- Standing narratives for days with no game.
CREATE VIEW v_storylines AS ...      -- streaks, slumps, milestone watch

-- Generated prose. The only table the model writes to.
CREATE TABLE stories (
  story_id    INTEGER PRIMARY KEY,
  game_uuid   TEXT,          -- NULL for an off-day / standing story
  kind        TEXT NOT NULL, -- 'recap' | 'debut' | 'watch'
  headline    TEXT NOT NULL,
  body        TEXT NOT NULL,
  facts       TEXT NOT NULL, -- the exact fact block fed to the model
  model       TEXT,
  generated_at TEXT NOT NULL
);
```

Storing `facts` alongside `body` is deliberate: it makes a bad story
diagnosable (was the fact wrong, or the writing?) and makes regeneration
reproducible.

---

## 5. Guardrails

1. **Fact-only.** System prompt forbids any number or claim not in the block.
2. **Boring games get boring coverage.** If total notable weight is under a
   threshold, write two sentences, not a drama. A 3–1 game where nothing
   happened should read like a wire brief. Forcing narrative onto every game is
   what makes generated content feel fake.
3. **Named subjects always.**
4. **Idempotent.** Only generate where no `stories` row exists for that
   `(game_uuid, kind)`. Re-running the nightly job costs nothing.
5. **Soft-fail.** Story generation never blocks the `seed.db` commit.
6. **Human-checkable.** `analysis/_verify.py` gains a check that every number
   appearing in a story body also appears in its `facts` block.

---

## 6. Delivery

Banner above the tabs in the existing hand-written report UI. Reads from
`stories` like any other stat — the SQL-view architecture is unchanged, and the
report stays a thin renderer.

Push notifications (WhatsApp/Discord) are **out of scope for now** per Nic.
Note for later: WhatsApp outbound outside a 24h window needs Meta Business
verification and an approved template capped near 1,024 characters — the Peanut
recap was 1,845 — so that channel would carry a headline plus a link, not the
story. Discord webhooks have neither limit.

---

## 7. Build order

1. `v_game_notables` + rarity ranks. Verify against known games by hand.
2. Fact-block builder (`src/show_h2h/story.py`), printable standalone so the
   input can be eyeballed before any model is involved.
3. `claude -p` runner + `stories` table. Generate the last 10 games, read them,
   tune the system prompt.
4. Wire into `nightly-refresh.sh` after `ingest snapshot`, before `git add`.
5. Banner in `report_template.html`.
6. `v_roster_debuts` and debut stories.
7. `v_storylines` for off-days.

Steps 1–3 are the risky ones and produce readable output before anything is
wired up or committed. Stop after 3 and evaluate.

---

## 8. Open questions

- Voice: neutral wire-service (as drafted for the Peanut game) or a
  personality-driven beat writer with opinions about the rivalry?
- Should stories be regenerated when a season ends and context changes, or
  frozen at write time? (Leaning frozen — a recap that rewrites itself is
  unsettling.)
- Do generated stories belong in git alongside `seed.db`? They are derived data,
  but they are also the only non-reproducible artifact in the pipeline.
