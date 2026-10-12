"""Count a season's ballots and write everything the site and the record need.

    uv run python awards/count.py 1

Reads   awards/season-N/{dossier,ballots,notes,curated}.json
Writes  awards/season-N/awards.json      what the site renders
        awards/season-N/results.md       the count, for reading
        awards/season-N/ballot-book.md   every ballot, signed and annotated

Nothing here decides an award. Voters did that; this applies the real point
scales to what they wrote down. `curated.json` is the only hand-written input:
the card art to show for each player, and the stat line and quote featured
beside each major award. It can be missing — the count does not depend on it.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

SEASON = int(sys.argv[1])
D = Path(__file__).resolve().parent / f"season-{SEASON}"
dos = json.loads((D / "dossier.json").read_text())
ballots = json.loads((D / "ballots.json").read_text())["ballots"]
notes_path, curated_path = D / "notes.json", D / "curated.json"
notes = ({n["index"]: n for n in json.loads(notes_path.read_text())["notes"]}
         if notes_path.exists() else {})
curated = json.loads(curated_path.read_text()) if curated_path.exists() else {}

H = {(r["player"], r["club"]): r for r in dos["hitters"]}
PT = {(r["pitcher"], r["club"]): r for r in dos["pitchers"]}
F = {(r["fielder"], r["club"]): r for r in dos["fielders"]}
KNOWN = set(H) | set(PT)
OWNER = dos["clubs"]                       # squad -> username
unreadable: list[str] = []


def key(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def canon(pick: dict, pool: set | None = None):
    """Match a name on a ballot to the dossier's spelling for that club.

    Voters copy names by hand, and long surnames arrive truncated in the data
    ("Misiorowsk..."), so "Misiorowski" and "Mize" for "C. Mize" have to land.
    """
    pool = pool or KNOWN
    name, club = pick["player"].strip(), pick["club"]
    if (name, club) in pool:
        return (name, club)
    k = key(name)
    close = [n for n in pool if n[1] == club and (
        key(n[0]) == k or key(n[0]).startswith(k) or k.startswith(key(n[0])) or k.endswith(key(n[0])))]
    if len(close) == 1:
        return close[0]
    anywhere = [n for n in pool if key(n[0]) == k]     # right name, wrong club
    if len(anywhere) == 1:
        return anywhere[0]
    unreadable.append(f"{name} ({club})")
    return None


def pretty(name: str) -> str:
    return curated.get("names", {}).get(name, name)


def person(k: tuple) -> dict:
    """A player as the site needs him: display name, the name the stat tables
    use (so a badge can find him), club, owner and card art."""
    return {"player": pretty(k[0]), "raw": k[0], "club": k[1], "owner": OWNER[k[1]],
            "card": curated.get("cards", {}).get(pretty(k[0]))}


def ranked(votes: list, scale: list, pool=None, eligible=None) -> dict:
    pts: collections.Counter = collections.Counter()
    place: dict = collections.defaultdict(collections.Counter)
    thrown = 0
    for ballot in votes:
        seen = set()
        for i, pick in enumerate(ballot[:len(scale)]):
            k = canon(pick, pool)
            if not k or k in seen or (eligible and not eligible(k)):
                thrown += 1
                continue
            seen.add(k)
            pts[k] += scale[i]
            place[k][i] += 1
    order = sorted(pts, key=lambda k: (-pts[k], -place[k][0], -place[k][1]))
    return {"ballots": len(votes), "max": scale[0] * len(votes), "scale": "-".join(map(str, scale)),
            "discarded": thrown,
            "votes": [dict(person(k), points=pts[k], firsts=place[k][0], seconds=place[k][1],
                           thirds=place[k][2]) for k in order]}


def plurality(picks: list, pool=None, eligible=None) -> dict:
    cnt: collections.Counter = collections.Counter()
    for pick in picks:
        k = canon(pick, pool)
        if k and (not eligible or eligible(k)):
            cnt[k] += 1
    return {"ballots": len(picks), "max": len(picks), "scale": "one vote each", "discarded": 0,
            "votes": [dict(person(k), points=v, firsts=v) for k, v in cnt.most_common()]}


W = [b for b in ballots if b["body"] == "writer"]
S = [b for b in ballots if b["body"] == "staff"]
HOF = [b for b in ballots if b["body"] == "hof"]
REL = [b for b in ballots if b["body"] == "relievers"]


def is_rookie(k):
    return "ROOKIE" in ((H.get(k) or {}).get("rookie"), (PT.get(k) or {}).get("rookie"))


def is_reliever(k):
    return k in PT and PT[k]["relief G"] > PT[k]["GS"]


def is_dh(k):
    return k in H and H[k]["pos (games)"].startswith("DH")


majors: list[dict] = []


def major(k, title, body, result):
    top = result["votes"][0]
    if result["scale"] == "one vote each":
        line = f"{top['points']} of {result['max']} votes"
    else:
        line = f"{top['points']} of {result['max']} points · {top['firsts']} of {result['ballots']} first-place votes"
    if top["firsts"] == result["ballots"]:
        line += " · unanimous"
    majors.append(dict(result, key=k, title=title, body=body, winner=top, line=line,
                       **curated.get("majors", {}).get(k, {})))


major("mvp", "Most Valuable Player", "30 writers",
      ranked([b["ballot"]["mvp"] for b in W], [14, 9, 8, 7, 6, 5, 4, 3, 2, 1]))
major("cy_young", "Cy Young Award", "30 writers",
      ranked([b["ballot"]["cy_young"] for b in W], [7, 4, 3, 2, 1], pool=set(PT)))
major("rookie", "Rookie of the Year", "30 writers",
      ranked([b["ballot"]["rookie"] for b in W], [5, 3, 1], eligible=is_rookie))

mp: collections.Counter = collections.Counter()
mf: collections.Counter = collections.Counter()
for b in W:
    m = b["ballot"]["manager"]
    mp[m[0]] += 5
    mf[m[0]] += 1
    if len(m) > 1 and m[1] != m[0]:
        mp[m[1]] += 3
club_of = {u: c for c, u in OWNER.items()}
major("manager", "Manager of the Year", "30 writers", {
    "ballots": len(W), "max": 5 * len(W), "scale": "5-3", "discarded": 0,
    "votes": [{"player": u, "raw": u, "club": club_of[u], "owner": u, "card": None, "manager": True,
               "points": v, "firsts": mf[u]} for u, v in mp.most_common()]})

major("relief_pitcher", "Relief Pitcher of the Year", "15 writers, one per chapter",
      ranked([b["ballot"]["relief_pitcher"] for b in W if "relief_pitcher" in b["ballot"]],
             [5, 3, 1], pool=set(PT), eligible=is_reliever))
major("reliever", "Reliever of the Year", "5 retired relievers",
      ranked([b["ballot"]["reliever"] for b in REL], [5, 3, 1], pool=set(PT), eligible=is_reliever))
major("comeback", "Comeback Player of the Year", "30 writers",
      plurality([b["ballot"]["comeback"] for b in W]))
major("hank_aaron", "Hank Aaron Award", "5 Hall of Famers · best hitter",
      ranked([b["ballot"]["hank_aaron"] for b in HOF], [5, 3, 1], pool=set(H)))
major("dh", "Outstanding Designated Hitter", "30 writers",
      plurality([b["ballot"]["dh"] for b in W], pool=set(H), eligible=is_dh))

# ---- coaches: one Silver Slugger and one Gold Glove per position
silver = []
for pos in ["C", "1B", "2B", "3B", "SS"]:
    r = plurality([b["ballot"]["silver_slugger"][pos] for b in S], pool=set(H))
    silver.append(dict(r["votes"][0], pos=pos, of=len(S)))
r = plurality([b["ballot"]["silver_slugger"][s] for b in S for s in ("OF1", "OF2", "OF3")], pool=set(H))
silver += [dict(v, pos="OF", of=len(S)) for v in r["votes"][:3]]
for pos in ["DH", "UTIL"]:
    r = plurality([b["ballot"]["silver_slugger"][pos] for b in S], pool=set(H))
    silver.append(dict(r["votes"][0], pos=pos, of=len(S)))


def index(k) -> int:
    """The stats quarter of a Gold Glove: outs converted, less twice the errors."""
    f = F.get(k) or next((v for kk, v in F.items()
                          if kk[1] == k[1] and key(kk[0]).startswith(key(k[0]))), None)
    return (f["outs recorded on balls hit to him"] - 2 * f["errors"]) if f else 0


gold = []
for pos in ["P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "UTIL"]:
    cnt: collections.Counter = collections.Counter()
    for b in S:
        k = canon(b["ballot"]["gold_glove"][pos])
        if k:
            cnt[k] += 1
    total = sum(cnt.values()) or 1
    best = max((index(k) for k in cnt), default=0) or 1
    score = {k: 0.75 * v / total + 0.25 * max(index(k), 0) / best for k, v in cnt.items()}
    order = sorted(score, key=lambda k: -score[k])
    gold.append(dict(person(order[0]), pos=pos, points=cnt[order[0]], of=len(S),
                     score=round(score[order[0]], 2),
                     next=[dict(person(k), points=cnt[k], score=round(score[k], 2)) for k in order[1:2]]))

winners = {(g["raw"], g["club"]) for g in gold}
pts: collections.Counter = collections.Counter()
firsts: collections.Counter = collections.Counter()
for b in S:
    for i, pick in enumerate(b["ballot"]["best_defenders"][:3]):
        k = canon(pick)
        if k in winners:
            pts[k] += [5, 3, 1][i]
            firsts[k] += i == 0
major("platinum", "Platinum Glove", "15 coaching staffs · best defender", {
    "ballots": len(S), "max": 5 * len(S), "scale": "5-3-1", "discarded": 0,
    "votes": [dict(person(k), points=v, firsts=firsts[k]) for k, v in pts.most_common()]})

# ---- the All-League teams: a first-team vote is two points, a second-team one
groups = {"C": ["C"], "1B": ["1B"], "2B": ["2B"], "3B": ["3B"], "SS": ["SS"],
          "OF": ["OF1", "OF2", "OF3"], "DH": ["DH"],
          "SP": ["SP1", "SP2", "SP3", "SP4", "SP5"], "RP": ["RP1", "RP2"]}
first, second, taken = [], [], set()
for pos, slots in groups.items():
    p2: collections.Counter = collections.Counter()
    for b in HOF:
        for team, w in (("all_mlb_first", 2), ("all_mlb_second", 1)):
            for s in slots:
                k = canon(b["ballot"][team][s])
                if k:
                    p2[k] += w
    order = [k for k, _ in p2.most_common() if k not in taken]
    for k in order[:len(slots)]:
        first.append(dict(person(k), pos=pos, points=p2[k]))
        taken.add(k)
    for k in order[len(slots):2 * len(slots)]:
        second.append(dict(person(k), pos=pos, points=p2[k]))
        taken.add(k)

# ---- stat titles, straight from the dossier
leaders = [{"label": x["label"].replace(" (qualified)", ""), "value": x["value"],
            "who": [dict(person((w["player"], w["club"]))) for w in x["who"]]}
           for x in dos["leaders"]
           if x["label"].split(" (")[0] in curated.get("leaders", [x["label"].split(" (")[0]])]

# ---- every honour a card holds this season, for the marks beside his name
honours: dict = collections.defaultdict(list)
for m in majors:
    if not m["winner"].get("manager"):
        honours[(m["winner"]["raw"], m["winner"]["owner"])].append(["major", m["title"]])
for s in silver:
    honours[(s["raw"], s["owner"])].append(["silver", f"Silver Slugger ({s['pos']})"])
for g in gold:
    honours[(g["raw"], g["owner"])].append(["gold", f"Gold Glove ({g['pos']})"])
for x in leaders:
    for w in x["who"]:
        honours[(w["raw"], w["owner"])].append(["title", f"{x['label']} leader"])
badges = [{"raw": k[0], "owner": k[1], "player": pretty(k[0]), "honours": v} for k, v in honours.items()]

# ---- the ballot book
TITLE = {"mvp": "MVP", "mvp_down_ballot": "Down the MVP ballot", "cy_young": "Cy Young",
         "rookie": "Rookie of the Year", "manager": "Manager of the Year", "comeback": "Comeback Player",
         "dh": "Outstanding DH", "relief_pitcher": "Relief Pitcher of the Year",
         "silver_slugger": "Silver Sluggers", "gold_glove": "Gold Gloves",
         "best_defenders": "Best defenders", "hardest_call": "Hardest call",
         "hank_aaron": "Hank Aaron Award", "all_league_teams": "All-League teams",
         "reliever": "Reliever of the Year"}


def pk(p):
    return f"{pretty(p['player'])} ({p['club']})"


def picks(b, k):
    v = b["ballot"]
    if k == "manager":
        return " over ".join(v["manager"])
    if k in ("comeback", "dh"):
        return pk(v[k])
    if k in ("silver_slugger", "gold_glove"):
        return "; ".join(f"{pos} {pk(p)}" for pos, p in v[k].items())
    if k == "all_league_teams":
        return ("First: " + "; ".join(f"{s} {pk(p)}" for s, p in v["all_mlb_first"].items())
                + ". Second: " + "; ".join(f"{s} {pk(p)}" for s, p in v["all_mlb_second"].items()))
    if k == "mvp_down_ballot" or k not in v:
        return ""
    return "; ".join(f"{i + 1}. {pk(p)}" for i, p in enumerate(v[k]))


book = []
seen_bylines: collections.Counter = collections.Counter()
for i, b in enumerate(ballots):
    n = notes.get(i)
    if not n:
        continue
    where = (f"{b['city']} chapter, seat {b['seat']}" if b["body"] == "writer"
             else f"{b['city']} coaching staff" if b["body"] == "staff"
             else f"Hall of Fame panel, seat {b['seat']}" if b["body"] == "hof"
             else f"Relievers' panel, seat {b['seat']}")
    # Voters invented their own names independently, and a few collided.
    seen_bylines[n["byline"]] += 1
    byline = n["byline"] + (f" ({b['city']})" if seen_bylines[n["byline"]] > 1 and b.get("city") else "")
    book.append({"body": b["body"], "byline": byline, "outlet": n["outlet"], "where": where,
                 "lens": b["lens"].split(":")[0],
                 "notes": [{"title": TITLE.get(k, k), "picks": picks(b, k), "text": t}
                           for k, t in n["notes"].items()]})

out = {
    "season": SEASON, "games": dos["games"], "span": dos["span"], "clubs": OWNER, "record": dos["record"],
    "electorate": {"writers": len(W), "staffs": len(S), "hof": len(HOF), "relievers": len(REL)},
    "majors": majors, "silver": silver, "gold": gold,
    "all_league": {"first": first, "second": second},
    "leaders": leaders, "badges": badges, "book": book,
}
(D / "awards.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))

# ---------------------------------------------------------------- results.md
L: list[str] = []
P = L.append


def table(rows, cols):
    P("| " + " | ".join(cols) + " |")
    P("|" + "---|" * len(cols))
    for r in rows:
        P("| " + " | ".join(str(x) for x in r) + " |")
    P("")


def who(v):
    return v["player"] if v.get("manager") else f"{v['player']} ({v['club']})"


P(f"# Season {SEASON} regular-season awards — the count\n")
P(f"Ballots: {len(W)} writers, {len(S)} coaching staffs, {len(HOF)} Hall of Fame panelists, "
  f"{len(REL)} retired relievers. Regular season only: {dos['games']} games, "
  f"{dos['span'][0]} to {dos['span'][1]}.\n")
for m in majors:
    P(f"## {m['title']}\n")
    P(f"**{who(m['winner'])}** — {m['line']}. Voted by {m['body']}; scale {m['scale']}.\n")
    table([[i + 1, who(v), v["points"], v.get("firsts", "")] for i, v in enumerate(m["votes"][:10])],
          ["", "", "points", "1st"])
    if m["discarded"]:
        P(f"{m['discarded']} ineligible or unreadable line(s) discarded.\n")
P("## Silver Sluggers\n")
table([[s["pos"], who(s), f"{s['points']} of {s['of']}"] for s in silver], ["pos", "winner", "votes"])
P("## Gold Gloves\n")
P("75% the coaches' vote, 25% a fielding index (outs converted less twice the errors, "
  "as a share of the position's best), rebuilt from the play-by-play.\n")
table([[g["pos"], who(g), f"{g['points']} of {g['of']}", g["score"],
        "; ".join(f"{who(n)} {n['points']}v/{n['score']}" for n in g["next"])] for g in gold],
      ["pos", "winner", "votes", "score", "runner-up"])
P("## All-League teams\n")
for name, team in (("First Team", first), ("Second Team", second)):
    P(f"**{name}**\n")
    table([[t["pos"], who(t), t["points"]] for t in team], ["pos", "player", "points"])
P("## Stat titles\n")
table([[x["label"], x["value"], ", ".join(who(w) for w in x["who"])] for x in leaders],
      ["title", "", "leader"])
if unreadable:
    P("## Unreadable names on ballots\n\n" + ", ".join(sorted(set(unreadable))) + "\n")
(D / "results.md").write_text("\n".join(L))

# ------------------------------------------------------------ ballot-book.md
L = [f"# Season {SEASON} awards — the ballot book\n",
     "Every ballot as it was cast, signed by its voter, with their own note on each vote. "
     "Voter names and outlets are invented.\n"]
for body, head in (("writer", "The writers"), ("staff", "The coaching staffs"),
                   ("hof", "The Hall of Fame panel"), ("relievers", "The retired relievers' panel")):
    L.append(f"## {head}\n")
    for v in book:
        if v["body"] != body:
            continue
        L.append(f"### {v['byline']} — {v['outlet']}\n")
        L.append(f"*{v['where']} · {v['lens']}*\n")
        for n in v["notes"]:
            L.append(f"**{n['title']}**" + (f" — {n['picks']}" if n["picks"] else "") + f"\n\n> {n['text']}\n")
(D / "ballot-book.md").write_text("\n".join(L))

print(f"Season {SEASON}: {len(ballots)} ballots, {len(book)} signed. "
      + "; ".join(f"{m['title']}: {who(m['winner'])}" for m in majors))
if unreadable:
    print("unreadable:", sorted(set(unreadable)))
