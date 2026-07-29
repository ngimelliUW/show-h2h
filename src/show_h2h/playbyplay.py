"""Parse the play-by-play prose into structured events.

The API gives no pitch-level endpoint, but `game_log`'s narrative is far richer
than the box score: it names the pitch type and location on strikeouts, says
whether the batter chased, was late, or took it, gives home-run distance and
direction, and — in a trailer after the innings — lists every perfect-perfect
contact with its exit velocity, plus the difficulty the game was played on.

Two things make this trickier than it looks:

1. **The log has two sections.** After the innings comes a trailer ("Game Log
   Legend", perfect-contact list, stadium, umpires) that *restates* plays. Parse
   the whole thing naively and every listed hit is counted twice — home runs came
   out ~57% high before the split. Everything here parses the narrative and the
   trailer separately.
2. **Batter attribution is positional.** A half-inning opens with
   "Worms batting. Kluber pitching.", so the batting side is only knowable from
   the most recent header — the sentences themselves just say "Judge homered".

Nothing here re-crawls: it re-reads text already stored by the game_log import.
"""
from __future__ import annotations

import re

# Pitch names the game actually uses. Ordered longest-first so "knuckle curve"
# matches before "curve" and "two-seam fastball" before "fastball".
PITCH_TYPES = [
    "knuckle curve", "circle change", "four-seam fastball", "two-seam fastball",
    "knuckleball", "screwball", "forkball", "palmball", "splitter", "changeup",
    "curveball", "sweeper", "sinker", "slider", "cutter", "fastball", "curve",
]

# Location phrases, again longest-first: "low and away" must win over "low".
LOCATIONS = [
    "low and away", "low and in", "high and away", "high and in",
    "up and in", "up and away", "inside", "outside", "away", "low", "high",
]

_MARKUP = re.compile(r"\^c\d+\^")
_TRAILER = "Game Log Legend"

# The log colour-codes plays, and those codes are the only record of which ones
# mattered. Rather than discard them, swap each for a single sentinel character
# so it survives into the parse without disturbing the surrounding regexes.
# (Per the log's own legend: 46 critical play, 47 critical situation, 48 run
# scored, 49 simulated, 50 back-to-normal, 51 inning header. A literal "*" after
# a play means it put that team ahead.)
_SENTINELS = {
    "^c46^": "\x01",   # critical play
    "^c47^": "\x02",   # critical situation
    "^c48^": "\x03",   # run scored
    "^c49^": "\x05",   # simulated play
    "^c50^": "\x04",   # reset to normal
    "^c51^": "",       # inning header — the "Inning N:" text is enough
}
CRITICAL, SITUATION, RUN_SCORED = "\x01", "\x02", "\x03"


def _sentinelize(text: str) -> str:
    for marker, char in _SENTINELS.items():
        text = text.replace(marker, char)
    return _MARKUP.sub("", text)  # any code we didn't name


def split_sections(text: str, *, keep_markers: bool = False) -> tuple[str, str]:
    """(inning narrative, trailer). The trailer restates plays — never parse
    events out of it, or every hit is double-counted (home runs came out 57%
    high before this split existed)."""
    body = (text or "").replace("^n^", "\n").replace("^e^", " | ")
    body = _sentinelize(body) if keep_markers else _MARKUP.sub("", body)
    cut = body.find(_TRAILER)
    return (body[:cut], body[cut:]) if cut > 0 else (body, "")


def _find(haystack: str, needles: list[str]) -> str | None:
    low = haystack.lower()
    for n in needles:
        if n in low:
            return n
    return None


def _timing(sentence: str) -> str | None:
    """How the batter was beaten. 'chasing' is a swing out of the zone,
    'looking' is a called strike — the rest is timing on a swing."""
    low = sentence.lower()
    if "swinging early" in low:
        return "early"
    if "swinging late" in low:
        return "late"
    if "chasing" in low:
        return "chasing"
    if "looking" in low or "called out on strikes" in low:
        return "looking"
    if "swinging" in low:
        return "swinging"
    return None


# A batter's name as it appears mid-sentence, suffixes included. Splitting the
# line into sentences first looked tidier but silently dropped events: "Witt Jr.
# homered" splits at the "Jr." and orphans the verb, and a go-ahead play is
# prefixed with "*" so the name no longer starts the sentence. Matching the
# whole "<name> <verb>" pattern in place avoids both.
_NAME = r"[A-Z][\w'.\-]*(?:\s[A-Z][\w'.\-]*)*?"
_STRIKEOUT = re.compile(
    rf"({_NAME})\s+(?:struck out|was called out on strikes)([^.]*)")
_HOMER = re.compile(rf"({_NAME})\s+homered to (\w+) \((\d+) feet\)")

# How many runs a home run drove in is never stated. What the log does print,
# right after the homer, is one "<Runner> scores." sentence per runner who came
# home — so the RBI is one for the batter plus however many of those run on
# before the next play starts. The leading character class skips the sentence's
# own full stop, the colour sentinels, and the go-ahead "*".
#
# The trailer independently states an RBI figure for every perfect-perfect ball,
# which covers 132 of these home runs. All 132 agree with this count, which is
# what makes a four-RBI homer trustworthy as a grand slam.
_SCORED_RUNNER = re.compile(rf"^[.\s*\x01-\x05]*({_NAME})\s+scores\.")


def rbi_for_homer(text: str, end: int) -> int:
    """RBI on the home run whose sentence ends at `end` in `text`."""
    rest, rbi = text[end:], 1
    while True:
        m = _SCORED_RUNNER.match(rest)
        if not m:
            return rbi
        rbi += 1
        rest = rest[m.end():]


def parse_narrative(narrative: str) -> list[dict]:
    """One row per notable plate appearance, with the batting squad attached.

    Squad comes from the most recent "<squad> batting." header — the event
    sentences themselves never name the team.
    """
    events: list[dict] = []
    squad = None
    inning = 0
    for line in narrative.split("\n"):
        line = line.strip()
        if not line or line.startswith(("Runs:", "Game Log")):
            continue
        m = re.match(r"Inning (\d+):", line)
        if m:
            inning = int(m.group(1))
            continue
        head = re.match(r"(.+?) batting\.", line)
        if head:
            squad = head.group(1).strip()

        found = []
        for m in _STRIKEOUT.finditer(line):
            found.append((m, {
                "kind": "strikeout", "batter": m.group(1),
                "pitch_type": _find(m.group(2), PITCH_TYPES),
                "location": _find(m.group(2), LOCATIONS),
                "timing": _timing(m.group(0)),
                "distance": None, "direction": None, "rbi": None,
            }))
        for m in _HOMER.finditer(line):
            found.append((m, {
                "kind": "home_run", "batter": m.group(1),
                "pitch_type": None, "location": None, "timing": None,
                "direction": m.group(2), "distance": int(m.group(3)),
                "rbi": rbi_for_homer(line, m.end()),
            }))
        found.sort(key=lambda pair: pair[0].start())

        for idx, (m, event) in enumerate(found):
            # A play "owns" the text up to the next play on the line, which is
            # where its run-scoring clause and go-ahead "*" live.
            stop = found[idx + 1][0].start() if idx + 1 < len(found) else len(line)
            span = line[m.start():stop]
            before = line[max(0, m.start() - 2):m.start()]
            event.update({
                "inning": inning, "squad": squad,
                "critical": int(CRITICAL in before or SITUATION in before),
                "scored": int(RUN_SCORED in before or RUN_SCORED in span),
                "go_ahead": int("*" in span),
            })
            events.append(event)
    return events


# Each half-inning ends with its own line of totals. Splitting on it gives both
# the block of plays and the pitch count for those plays, which is the only
# place pitch counts appear at all.
_HALF_SUMMARY = re.compile(
    r"Runs: (\d+) Hits: (\d+) Walks: (\d+) Errors: (\d+) Pitches: (\d+)"
    r"(?: Runners Left On: (\d+))?")

# Turned double and triple plays, read off the scorer's tag in the play's
# parenthetical — "(4-6-3 DP)" — rather than the prose. The tag is the more
# complete signal: 14 of the 142 double plays in this record are
# strike-'em-out-throw-'em-out, written "(2-6 DP). <Runner> out." with the words
# "double play" appearing nowhere in the sentence.
#
# A triple play has never happened here, so its pattern is written from the
# double play's shape (the log uses standard scorer's abbreviations throughout —
# DP, FC, SH, WP) and widened with the prose form, so it is caught whichever way
# the game chooses to word it. analysis/_verify.py feeds it a synthetic one,
# because a detector for something that has never occurred is otherwise a
# detector nobody has ever seen fire.
_DOUBLE_PLAY = re.compile(r"\([^)]*\bDP\)")
_TRIPLE_PLAY = re.compile(r"\([^)]*\bTP\)|triple play", re.I)


def parse_half_innings(narrative: str) -> list[dict]:
    """One row per half-inning: who batted, how many pitches, what happened.

    Pitch counts unlock immaculate innings (three strikeouts on exactly nine
    pitches) and pitch efficiency, neither of which the box score can express.
    """
    halves: list[dict] = []
    inning = 0
    squad = None
    last_end = 0
    for m in _HALF_SUMMARY.finditer(narrative):
        block = narrative[last_end:m.start()]
        last_end = m.end()
        for header in re.finditer(r"Inning (\d+):", block):
            inning = int(header.group(1))
        bat = re.findall(r"(\S[^.\n]*?) batting\.", block)
        if bat:
            squad = bat[-1].strip()
        halves.append({
            "inning": inning,
            "squad": squad,
            "runs": int(m.group(1)), "hits": int(m.group(2)),
            "walks": int(m.group(3)), "errors": int(m.group(4)),
            "pitches": int(m.group(5)),
            "lob": int(m.group(6)) if m.group(6) else 0,
            "strikeouts": len(re.findall(r"struck out|called out on strikes", block)),
            # Credited to whoever was in the field, which is the other side from
            # the one this row says was batting.
            "double_plays": len(_DOUBLE_PLAY.findall(block)),
            # A triple play records all three outs, so a half-inning can contain
            # at most one — which is what makes a boolean safe here. Counting
            # matches instead would double up whenever the log writes both the
            # prose and the tag, the way it does for double plays.
            "triple_plays": int(bool(_TRIPLE_PLAY.search(block))),
        })
    return halves


def parse_trailer(trailer: str) -> dict:
    """Perfect-perfect contact (with exit velocity), difficulty, game scores."""
    perfect = [
        {"batter": name.strip(), "exit_velo": int(mph), "outcome": outcome.strip()}
        for name, mph, outcome in re.findall(
            r"^(\S[^:\n]*?): (\d+) mph \((.*?)\)\s*$", trailer, re.M)
    ]
    hit_diff = re.search(r"Hitting Difficulty is ([\w\- ]+?)\.", trailer)
    pit_diff = re.search(r"Pitching Difficulty is ([\w\- ]+?)\.", trailer)
    scores_line = re.search(r"Game Scores: (.+)", trailer)
    game_scores = (re.findall(r"(-?\d+) \(([^)]+)\)", scores_line.group(1))
                   if scores_line else [])
    stadium = re.search(r"\n([A-Z][^|\n]*?) \|\s+\((\d+) ft elevation\)", trailer)
    weather = re.search(r"Weather: (.+)", trailer)
    return {
        "perfect": perfect,
        "hitting_difficulty": hit_diff.group(1) if hit_diff else None,
        "pitching_difficulty": pit_diff.group(1) if pit_diff else None,
        "game_scores": [(who.strip(), int(score)) for score, who in game_scores],
        "stadium": stadium.group(1).strip() if stadium else None,
        "weather": weather.group(1).strip() if weather else None,
    }


def _squad_spans(narrative: str) -> list[tuple[int, str]]:
    """(offset, squad) for every half-inning header, in order."""
    return [(m.start(), m.group(1).strip())
            for m in re.finditer(r"^(.+?) batting\.", narrative, re.M)]


def attribute_contact(narrative: str, perfect: list[dict]) -> None:
    """Tag each perfect-perfect ball with the squad that hit it, in place.

    The trailer lists these without a team, and looking the surname up in the
    box score is ambiguous whenever both players run a card with that name —
    which was 37% of them. The play itself appears verbatim in the narrative,
    though, so finding it there and taking the enclosing half-inning's batting
    team resolves it exactly.
    """
    spans = _squad_spans(narrative)
    if not spans:
        return
    for entry in perfect:
        # The trailer appends " 2 RBI" and similar to the sentence; match the
        # first sentence only.
        key = entry["outcome"].split(".")[0].strip()
        if not key:
            continue
        at = narrative.find(key)
        if at < 0:
            continue
        squad = None
        for offset, name in spans:
            if offset <= at:
                squad = name
            else:
                break
        entry["squad"] = squad


def parse(text: str) -> dict:
    narrative, trailer = split_sections(text, keep_markers=True)
    trailer_data = parse_trailer(trailer)
    attribute_contact(narrative, trailer_data["perfect"])
    return {
        "events": parse_narrative(narrative),
        "halves": parse_half_innings(narrative),
        **trailer_data,
    }
