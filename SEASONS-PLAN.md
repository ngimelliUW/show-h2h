# Seasons, series, and the World Series — plan

A competitive structure layered on top of the LinguiniEater vs TallThibaut48
rivalry, since MLB The Show 26 has no concept of one. Games roll up into
series, series into seasons, seasons into a World Series with earned advantages.

Companion to `STORYLINE-PLAN.md` — the news desk is what makes this *feel* like
something, and this is what gives the news desk something to build toward.

Status: **designed, not built.** All numbers measured against `data/seed.db`
on 2026-08-05 (126 H2H games).

---

## 1. The unit chain

```
game  →  best-of-5 series  →  8-series season  →  best-of-7 World Series
 ~1 day        ~2 days              ~3-4 weeks           ~1 week
```

Measured, not estimated: 126 games produce **32 complete best-of-5 series**
(~3.9 games each), and 8-series seasons ran 21–30 days each.

## 2. Series

Best-of-five, first to 3 wins.

**Ties and no contests do not count.** A tied game or a disconnect-shortened no
contest is replayed and does not advance either side's series count. This falls
straight out of the existing `v_game_status` rules, so the series layer inherits
the disconnect policy already agreed on rather than inventing a second one.

**Series are derived, never entered by hand.** Walk `v_h2h_games` in
`played_at` order, count decided games, cut when either side reaches 3. That is
deterministic, requires zero bookkeeping during play, and applies retroactively
to all 126 games already in the database.

## 3. Season

**Eight series.** Standing is **series won, not games won** — deliberately
unlike MLB. Winning a series 3–0 and 3–2 are worth exactly the same, so running
up the score in a decided series earns nothing.

Honest note on what this does: series **amplify** the favourite's edge rather
than damping it. Over the existing history, Nic is .688 in games but **.812 in
series (26–6)**. A best-of-5 gives the better player more chances to assert.
The reason to use series anyway is not parity — it is that a series is a
discrete, winnable trophy that resolves every couple of days, so the underdog
banks real wins instead of watching a single lifetime counter.

## 3b. Home dates

**Hosting alternates every series**, so an eight-series season splits 4–4 and
neither player goes a whole season without last at-bat. A series is played at
one house from start to finish, and `FIRST_HOST` names who takes the first
series of a season — defaulting to TallThibaut48, since he has never hosted.

This is the rule with the most ground to make up. **All 126 games played before
the league opened were hosted by LinguiniEater**, so his opponent has never once
had last at-bat. With 44 of those games decided by a single run, that is not a
cosmetic imbalance.

The postseason is the exception: home field there is *won*, not scheduled, so
the World Series is played wherever the advantage ladder puts it. A season that
finishes level earns nobody home field and designates no host.

Audited from `games.home_username` against the series' scheduled host.

## 4. The advantage ladder

The prize scales with the **margin**, not the win. A binary reward would make
every series dead once someone clinches; a ladder keeps the last series of a
lopsided season worth playing for both sides — one is chasing a tier, the other
is avoiding one.

| season | World Series advantage |
|---|---|
| 8–0 | home field + repeat a starter + one card ban + series opens 1–0 |
| 7–1 | home field + repeat a starter + one card ban |
| 6–2 | home field + **may start one pitcher twice in the series** |
| 5–3 | home field for all seven games |
| 4–4 | nothing — straight best-of-7 |

**Why home field is the right base prize:** it is a completely unused dimension
in this rivalry, so it costs nothing to introduce and neither player has ever
experienced the downside.

- Nic has been the home team in **all 126 games**. TallThibaut48 has never had
  last at-bat. (Verified real, not an ingestion artifact — the API reports the
  queried user as away in 151 other games, so the field does vary.)
- All 126 games have been played at **American Family Field**. One park, every
  time.

Given 44 of 126 games were decided by one run, last at-bat is not a token prize.

**Park choice is not part of the ladder at all.** An earlier draft made it a
tier of its own, on the logic that an unused dimension is a free prize. But
unused is not the same as valuable: with every game ever played at American
Family Field there is no evidence a different park is worth anything, and a
prize neither player would bother spending is not a prize. A later draft kept it
as flavour attached to home field, which was no better — it still put a
meaningless choice in front of the reader. It is dropped entirely.

**The 6–2 tier spends the scarcest resource in the design instead.** With the
rotation rule in force a best-of-7 demands seven different starters, which
neither player has ever managed — Nic has 10 distinct starters in his entire
history and used 4 across his last 30 games. Being allowed a single repeat is an
ace on short rest in Game 7: large, thematic, and auditable from
`pitching_lines` like every other rule.

The **card ban** is the biggest swing and the most likely to breed resentment —
first thing to cut if it sours. It is also by far the best material the news
desk will ever get.

## 5. Postseason

**Straight to a best-of-seven World Series. No preliminary rounds.**

With two players there is nobody to eliminate, so bracket rounds would be pure
theater — a "Division Series" that both players are guaranteed to reach and that
eliminates one of two teams is just a shorter World Series with a worse name.

The postseason earns its weight through **constraint and ceremony**, not extra
rounds: the advantage ladder applies, the rotation rule tightens (below), and
the champion takes a permanent pennant in the site's trophy case.

Deliberately **no mechanical carry-over for the defending champion.** Advantages
are re-earned every season. A champion who also starts the next World Series
ahead compounds into a runaway.

## 6. The rotation rule

**No starting pitcher may start twice in the same series.** Best-of-5 requires
up to 5 different starters; the best-of-7 World Series requires up to 7. It
applies to regular-season series and the postseason alike — the point is that
your *rotation* has to be good, not one pitcher.

The single exception is the 6–2 advantage above, which buys the season winner
exactly one repeat in that World Series. The audit must therefore be
**advantage-aware**: the violation threshold is a function of the earned tier,
not a constant, or the site accuses the season winner of cheating for spending
the prize he won.

This is the single highest-impact rule in the design, because the two rosters
are built completely differently:

| | distinct starters (126g) | top-5 share | last 30 games |
|---|---|---|---|
| LinguiniEater | **10** | 90% | **4 starters** — 17 of 30 Misiorowski |
| TallThibaut48 | **23** | 60% | 9 starters |

- Nic has started 5 different pitchers in 5 straight games **0 times out of 122
  opportunities**.
- TallThibaut48 has done it 7 times.
- Neither has ever done 7 straight.

Three reasons to adopt it:

1. **It rewards roster construction, not a spot.** Rotation depth winning in
   October is a real baseball value. It currently favours TallThibaut48, but only
   because he built deeper — if Nic responds by building depth, the edge
   neutralises. It is self-correcting rather than a permanent handicap, which
   matters given the expectation that the skill gap closes.
2. **It is preventative maintenance on a problem already in the data.** Card
   performance decays with appearance count — Misiorowski's collapse showed a
   cliff between appearances 40 and 50, and he sits at 50 starts. Capping any
   one arm to a single start per series slows how fast a card burns through its
   useful life.
3. **It makes Games 6 and 7 feel like real Games 6 and 7** — thin arms, bullpen
   games, improvisation.

Fallback if requiring 7 distinct starters proves miserable: **no starter more
than twice per series.** Still forces depth, far more forgiving.

## 7. Everything is auditable

No honour system. Every rule leaves a trace in data already collected:

| rule | verified by |
|---|---|
| home field | `games.home_username` |
| card ban | absence of the surname in `batting_lines` / `pitching_lines` |
| rotation rule | starter per game = `pitching_lines` min `slot` |
| series/season boundaries | derived from `v_h2h_games` order |

So the site can flag a violated rule, and the news desk can write about it.

## 8. Retroactive validation

Applying the whole structure to the existing 126 games:

| season | span | days | G | series | winner | advantage earned |
|---|---|---|---|---|---|---|
| S1 | 04-16 → 05-17 | 30 | 32 | 8–0 | Nic | everything |
| S2 | 05-18 → 06-08 | 21 | 28 | **4–4** | **tied** | none |
| S3 | 06-10 → 07-10 | 29 | 30 | 8–0 | Nic | everything |
| S4 | 07-12 → 08-03 | 22 | 33 | 6–2 | Nic | home + one repeat |
| S5 | 08-03 → live | — | 3 | in progress | — | — |

Across the 32 series: 14 sweeps, only 5 went the distance, median length 2 days.

The important result is **S2 finished 4–4**. Even at a .688 clip, this format
produced one genuinely tied season out of four — where month-as-season produced
five Nic titles out of five with no month ever close. The structure ships with
four seasons of history and a real tied one already in the books.

## 9. Schema sketch

Everything derives from existing tables. No manual entry anywhere.

```sql
CREATE VIEW v_series AS ...    -- series_no, season_no, game_uuid, seq,
                               -- wins_me, wins_them, winner, is_clincher
CREATE VIEW v_season_standings AS ...  -- season_no, series_w, series_l,
                                       -- advantage_tier, clinched_at
CREATE VIEW v_rule_audit AS ...        -- game_uuid, rule, expected, actual, ok
```

Postseason designation needs no storage either: once `SEASON_LENGTH` series have
closed, the next series simply *is* the World Series. Nothing to declare.

## 10. Settled since drafting

- **The rotation rule applies in the regular season too**, not only the
  postseason. Your rotation has to be good, not one pitcher.
- **Nothing is backfilled.** Season 1 opens with the first game after
  `LEAGUE_START`; both players start at zero championships. The 126 existing
  games stay visible in the stat tabs but belong to no season. The four
  retroactive seasons below are kept only as evidence the format works.
- **The World Series derives automatically** from series count — no command, no
  manual flag.

## 11. Open questions

- Season length: 8 series (~3-4 weeks, ~10 titles/year) vs 12 series (~6 weeks,
  fewer and weightier). 8 matches the natural rhythm already in the data, and is
  a config knob rather than a hard-coded constant.
- Does a 4–4 season deserve a tiebreaker series, or is "no advantage" enough?
- What happens to a series interrupted by a long gap — does a 10-day break
  between games 2 and 3 still count as one series? (Longest observed series
  span: 6 days.)
