# Regular-season awards

Once a regular season is complete, the league hands out the same awards real
baseball does, decided the same way: by secret ballot, using the real voting
bodies and the real point scales. The voters are AI agents, each given the same
stat sheet and a different voting philosophy.

The Season 1 awards presentation is a Claude artifact:
https://claude.ai/artifact/C7TF7WqqgmnS8mYQfskQ1h (private unless shared).

Everything a season produced is kept in `season-N/`. The site reads only
`season-N/awards.json`.

## Who votes on what

| Body | Size | Awards | Ballot |
|---|---|---|---|
| Baseball writers | 30 (two per city, 15 chapters) | MVP | top 10, 14-9-8-7-6-5-4-3-2-1 |
| | | Cy Young | top 5, 7-4-3-2-1 |
| | | Rookie of the Year | top 3, 5-3-1 |
| | | Manager of the Year | both managers, 5-3 |
| | | Comeback Player, Outstanding DH | one name |
| | 15 (one per chapter) | Relief Pitcher of the Year | top 3, 5-3-1 |
| Coaching staffs | 15 | Silver Slugger and Gold Glove per position, Platinum Glove | one name per position |
| Hall of Fame panel | 5 | Hank Aaron Award (best hitter), All-League teams | top 3, 5-3-1 |
| Retired relievers | 5 | Reliever of the Year | top 3, 5-3-1 |

Two chapters are the Birds and Worms beats; the other thirteen are neutral.
Stat titles (batting, ERA, home runs and so on) are not voted on.

## How this differs from the real thing

- **One league.** Real awards are split AL/NL; here there is one of each.
- **No fan vote.** The Hank Aaron Award, All-League teams and Platinum Glove are
  panel- and coach-only.
- **A staff may not vote for its own players**, as in real life. With thirteen
  neutral staffs that works; the Birds and Worms staffs can only pick the other
  club.
- **Rookie** means a card whose first appearance in the rivalry came after the
  league opened.
- **Gold Gloves** are 75% vote, 25% a fielding index, as in real life — but the
  game publishes no defensive numbers, so the index is rebuilt from the
  play-by-play (outs converted, less twice the errors). It says almost nothing
  about catchers.
- **Ballots are due before the postseason**, so the World Series is excluded.
- Not awarded: Roberto Clemente and Executive of the Year, which cannot be
  judged from game data.

## Running a season

```sh
uv run python awards/dossier.py N        # 1. the stat sheet every voter reads
#                                          2. run workflows/vote.js   -> season-N/ballots.json
#                                          3. write each ballot to season-N/cast/NN.json,
#                                             run workflows/notes.js  -> season-N/notes.json
uv run python awards/count.py N          # 4. count, and write awards.json for the site
uv run python -m show_h2h.report         # 5. rebuild the page
```

Steps 2 and 3 are Claude Code workflows (55 agents each). Before running them,
replace `season-N` in the two scripts with the real season. The vote must
finish before the notes: voters annotate the ballot they already cast, and no
pick changes afterwards.

`season-N/curated.json` is the only hand-written file: which card art to show
for each player, and the stat line and quote featured beside each major award.
Every quote in it must be verbatim from `notes.json`. The count does not depend
on it.

## Files in a season

| File | What it is |
|---|---|
| `dossier.md`, `dossier.json` | the stat sheet the voters read |
| `ballots.json` | all 55 ballots exactly as cast |
| `notes.json` | each voter's invented byline and their note on every vote |
| `curated.json` | card art and featured stats/quotes (hand-written) |
| `awards.json` | the counted result the site renders |
| `results.md` | the count, for reading |
| `ballot-book.md` | every ballot, signed and annotated |

Voter names and outlets are invented by the voters; a few collide, and the
count adds the chapter city to tell them apart.
