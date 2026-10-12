"""The regular-season dossier every awards voter reads.

    uv run python awards/dossier.py 1      # writes awards/season-1/dossier.{md,json}

Regular season only: real ballots are due before the postseason, so the World
Series is left out. See awards/README.md for the whole process.
"""
import re, sqlite3, json, collections, sys
from pathlib import Path
from show_h2h import seasons, config

SEASON = int(sys.argv[1])
OUT = str(Path(__file__).resolve().parent / f"season-{SEASON}") + "/"
Path(OUT).mkdir(parents=True, exist_ok=True)
ME, TH = config.MY_USERNAME, config.FRIEND_USERNAME
TEAM = {}
st = seasons.derive()
S1 = [s for s in st["series"] if s["season"] == SEASON and not s["postseason"]]
reg = [g["uuid"] for s in S1 for g in s["games"]]
c = sqlite3.connect(config.DB_PATH); c.row_factory = sqlite3.Row
ph = ",".join("?" * len(reg))
L = []; P = L.append

for r in c.execute(f"select squad, batting_username u, count(*) n from half_innings where game_uuid in ({ph}) group by 1,2", reg):
    TEAM[r["u"]] = r["squad"]
tag = lambda u: f"{TEAM.get(u, '?')} ({u})"

def rate3(x): return "—" if x is None else f"{x:.3f}".replace("0.", ".", 1) if x < 1 else f"{x:.3f}"
def div(a, b): return a / b if b else None
def table(rows, cols):
    P("| " + " | ".join(cols) + " |"); P("|" + "---|" * len(cols))
    for r in rows: P("| " + " | ".join(str(r.get(k, "")) for k in cols) + " |")
    P("")

# ---------------- league / teams
P(f"# Season {SEASON} regular season — awards dossier\n")
P(f"League: two clubs, **{tag(ME)}** and **{tag(TH)}**. Regular season = 8 best-of-five series, "
  f"{len(reg)} games, {S1[0]['games'][0]['at'][:10]} to {S1[-1]['ended'][:10]}. "
  "Everything below is regular season ONLY — the World Series that followed is excluded, as ballots are due before the postseason.\n")
P("Players are video-game cards (MLB The Show 26 Diamond Dynasty), identified by surname. The same surname can appear on both clubs — they are different cards; always name the club.\n")
P("## Series results\n")
table([{"series": s["no"], "winner": tag(s["winner"]), "games": f"{s['wins'][ME]}-{s['wins'][TH]} ({TEAM[ME]}-{TEAM[TH]})",
        "hosted by": TEAM[s["host"]], "ended": s["ended"][:10]} for s in S1], ["series", "winner", "games", "hosted by", "ended"])

games = [dict(r) for r in c.execute(f"""select g.*, s.status from games g join v_game_status s using(game_uuid)
                                         where game_uuid in ({ph}) order by played_at""", reg)]
team = {u: collections.Counter() for u in (ME, TH)}
for g in games:
    for u in (ME, TH):
        home = g["home_username"] == u
        rs, ra = (g["home_runs"], g["away_runs"]) if home else (g["away_runs"], g["home_runs"])
        t = team[u]; t["g"] += 1; t["rs"] += rs; t["ra"] += ra
        if g["status"] == "final":
            w = (g["winner"] == "home") == home
            t["w" if w else "l"] += 1
            if abs(rs - ra) == 1: t["one_w" if w else "one_l"] += 1
            if g["innings"] > 9: t["xi_w" if w else "xi_l"] += 1
            t["home_w" if (home and w) else "home_l" if home else "road_w" if w else "road_l"] += 1
        else: t["nodecision"] += 1
P("## Club records (regular season)\n")
table([{"club": tag(u), "W-L": f"{t['w']}-{t['l']}", "series": sum(1 for s in S1 if s["winner"] == u),
        "RS": t["rs"], "RA": t["ra"], "run diff": t["rs"] - t["ra"],
        "1-run games": f"{t['one_w']}-{t['one_l']}", "extras": f"{t['xi_w']}-{t['xi_l']}",
        "home": f"{t['home_w']}-{t['home_l']}", "road": f"{t['road_w']}-{t['road_l']}",
        "ties/no contest": t["nodecision"]} for u, t in team.items()],
      ["club", "W-L", "series", "RS", "RA", "run diff", "1-run games", "extras", "home", "road", "ties/no contest"])

# pre-league context for the managers
pre = c.execute("""select sum(result='W') w, sum(result='L') l from v_h2h_games where played_at < ?""", (config.LEAGUE_START,)).fetchone()
P(f"Context for Manager of the Year: before the league opened, {TEAM[ME]} ({ME}) led the all-time rivalry {pre['w']}-{pre['l']} "
  f"({pre['w']/(pre['w']+pre['l']):.3f}). Each club's 'manager' is its human player: {ME} manages {TEAM[ME]}, {TH} manages {TEAM[TH]}. "
  "Series 1 of the season was won by the underdog. Rotation rule in force all season: a pitcher may start only once per series.\n")

# ---------------- batting
def norm(n): return re.sub(r"^[a-z0-9]-", "", n or "")   # "a-Walker" is Walker pinch-hitting
bat = collections.defaultdict(collections.Counter); posg = collections.defaultdict(collections.Counter)
for r in c.execute(f"select * from batting_lines where game_uuid in ({ph})", reg):
    k = (r["username"], norm(r["player_name"])); b = bat[k]
    for f in ("ab","r","h","rbi","bb","so","doubles","triples","hr","sh","sf","gidp","e","hbp","sb","cs"): b[f] += r[f] or 0
    b["g"] += 1
    pos = (r["pos"] or "").split("-")[-1]
    if pos and pos not in ("PH", "PR"): posg[k][pos] += 1
extra = collections.defaultdict(collections.Counter)
for r in c.execute(f"select batting_username u, batter, kind, go_ahead, rbi, distance from pa_events where game_uuid in ({ph})", reg):
    e = extra[(r["u"], r["batter"])]
    if r["kind"] == "home_run": e["ga_hr"] += r["go_ahead"] or 0; e["maxhr"] = max(e["maxhr"], r["distance"] or 0)
for r in c.execute(f"select username u, batter, exit_velo, result from contact_events where game_uuid in ({ph})", reg):
    e = extra[(r["u"], r["batter"])]; e["pp"] += 1; e["pp_out"] += r["result"] == "out"

first_seen = {}
for r in c.execute("select b.username, b.player_name, min(g.played_at) d from batting_lines b join games g using(game_uuid) where g.is_h2h=1 group by 1,2"):
    k = (r["username"], norm(r["player_name"])); first_seen[k] = min(first_seen.get(k, "9"), r["d"])
first_seen_p = {(r["username"], r["player_name"]): r["d"] for r in c.execute(
    "select b.username, b.player_name, min(g.played_at) d from pitching_lines b join games g using(game_uuid) where g.is_h2h=1 group by 1,2")}

def batrow(k, b):
    pa = b["ab"] + b["bb"] + b["hbp"] + b["sf"] + b["sh"]
    tb = b["h"] + b["doubles"] + 2 * b["triples"] + 3 * b["hr"]
    obp = div(b["h"] + b["bb"] + b["hbp"], b["ab"] + b["bb"] + b["hbp"] + b["sf"]); slg = div(tb, b["ab"])
    e = extra[k]
    return {"player": k[1], "club": TEAM[k[0]], "pos (games)": ", ".join(f"{p} {n}" for p, n in posg[k].most_common()),
            "G": b["g"], "PA": pa, "AB": b["ab"], "R": b["r"], "H": b["h"], "2B": b["doubles"], "3B": b["triples"], "HR": b["hr"],
            "RBI": b["rbi"], "BB": b["bb"], "SO": b["so"], "SB": b["sb"], "CS": b["cs"], "GIDP": b["gidp"],
            "AVG": rate3(div(b["h"], b["ab"])), "OBP": rate3(obp), "SLG": rate3(slg),
            "OPS": rate3((obp or 0) + (slg or 0)) if b["ab"] else "—", "TB": tb,
            "go-ahead HR": e["ga_hr"], "perfect-contact balls": e["pp"], "rookie": "ROOKIE" if first_seen[k] >= config.LEAGUE_START else "",
            "_pa": pa, "_ops": (obp or 0) + (slg or 0), "_k": k}
brows = sorted((batrow(k, b) for k, b in bat.items()), key=lambda r: -r["_pa"])
qual_pa = round(3.1 * len(reg))
lg = collections.Counter()
for b in bat.values(): lg.update(b)
lg_obp = div(lg["h"] + lg["bb"] + lg["hbp"], lg["ab"] + lg["bb"] + lg["hbp"] + lg["sf"])
lg_slg = div(lg["h"] + lg["doubles"] + 2 * lg["triples"] + 3 * lg["hr"], lg["ab"])
P("## Hitters (every card with a plate appearance)\n")
P(f"League line: AVG {rate3(div(lg['h'], lg['ab']))} / OBP {rate3(lg_obp)} / SLG {rate3(lg_slg)}; "
  f"{lg['hr']} HR and {lg['r']} runs in {len(reg)} games. This is a very low-offense environment — judge hitters against the league line, not against real MLB. "
  f"Rate-title qualifier (MLB rule, 3.1 PA per club game): **{qual_pa} PA**.\n")
BC = ["player","club","pos (games)","G","PA","AB","R","H","2B","3B","HR","RBI","BB","SO","SB","CS","GIDP","AVG","OBP","SLG","OPS","TB","go-ahead HR","perfect-contact balls","rookie"]
table(brows, BC)

# ---------------- pitching
pit = collections.defaultdict(collections.Counter)
for r in c.execute(f"select * from pitching_lines where game_uuid in ({ph})", reg):
    k = (r["username"], r["player_name"]); p = pit[k]
    for f in ("outs","r","h","er","bb","so","win","loss","save","hold","wp"): p[f] += r[f] or 0
    p["g"] += 1; p["gs"] += r["slot"] == 0; p["gr"] += r["slot"] != 0
    raw = json.loads(r["raw"] or "{}"); p["bs"] += int(raw.get("b_save") or 0)
    if r["slot"] == 0:
        p["qs"] += (r["outs"] or 0) >= 18 and (r["er"] or 0) <= 3
        p["cg"] += 0
    else: p["rel_outs"] += r["outs"] or 0; p["rel_er"] += r["er"] or 0
def ip(o): return f"{o // 3}.{o % 3}"
def pitrow(k, p):
    return {"pitcher": k[1], "club": TEAM[k[0]], "G": p["g"], "GS": p["gs"], "relief G": p["gr"], "W": p["win"], "L": p["loss"],
            "SV": p["save"], "BS": p["bs"], "HLD": p["hold"], "IP": ip(p["outs"]), "H": p["h"], "R": p["r"], "ER": p["er"], "BB": p["bb"], "SO": p["so"],
            "ERA": f"{27 * p['er'] / p['outs']:.2f}" if p["outs"] else "—", "WHIP": f"{3 * (p['h'] + p['bb']) / p['outs']:.2f}" if p["outs"] else "—",
            "K/9": f"{27 * p['so'] / p['outs']:.1f}" if p["outs"] else "—", "K/BB": f"{p['so'] / p['bb']:.1f}" if p["bb"] else "∞",
            "quality starts": p["qs"], "rookie": "ROOKIE" if first_seen_p[k] >= config.LEAGUE_START else "", "_outs": p["outs"], "_k": k}
prow = sorted((pitrow(k, p) for k, p in pit.items()), key=lambda r: -r["_outs"])
lgp = collections.Counter()
for p in pit.values(): lgp.update(p)
P("## Pitchers (every card that threw a pitch)\n")
P(f"League ERA {27 * lgp['er'] / lgp['outs']:.2f}, WHIP {3 * (lgp['h'] + lgp['bb']) / lgp['outs']:.2f}, K/9 {27 * lgp['so'] / lgp['outs']:.1f}. "
  f"ERA-title qualifier (MLB rule, 1 IP per club game): **{len(reg)} IP**. Long surnames arrive truncated ('Misiorowsk...'). "
  "GS = started the game; 'relief G' = any other appearance. A card can do both.\n")
PC = ["pitcher","club","G","GS","relief G","W","L","SV","BS","HLD","IP","H","R","ER","BB","SO","ERA","WHIP","K/9","K/BB","quality starts","rookie"]
table(prow, PC)

# ---------------- fielding from the play-by-play
fld = collections.defaultdict(collections.Counter)
squad_user = {v: k for k, v in TEAM.items()}
for r in c.execute(f"select game_uuid, text from game_log_text where game_uuid in ({ph})", reg):
    txt = re.sub(r"\^c\d+\^|\^n\^", " ", r["text"])
    parts = re.split(r"(\w[\w ]*?) batting\. ", txt)
    for squad, body in zip(parts[1::2], parts[2::2]):
        bu = squad_user.get(squad.strip().split()[-1])
        if not bu: continue
        fu = TH if bu == ME else ME
        body = body.split("Perfect Contact Hits")[0]
        for m in re.finditer(r"(?:out|fly|sacrificed|double play|triple play)(?: into a double play)? to ([A-Z][\w.'\-]*(?: [A-Z][\w.'\-]*)*?)(?: on a deflected hit)? \(([A-Z]*)(\d)", body):
            f = fld[(fu, m.group(1))]; f["plays"] += 1
            f["air" if m.group(2) in ("F", "L", "P", "SF") else "ground"] += 1
        for m in re.finditer(r"(throwing|fielding) error by ([A-Z][\w.'\-]*(?: [A-Z][\w.'\-]*)*?)(?: on| \(|\.)", body):
            fld[(fu, m.group(2))][m.group(1) + "_err"] += 1
        for m in re.finditer(r"\((?:[A-Z]*)([\d\-U]+) DP\)", body): pass
frows = []
for k, f in fld.items():
    b = bat.get(k)
    pos = ", ".join(f"{p} {n}" for p, n in posg[k].most_common() if p != "DH") if k in posg else "P"
    err = f["throwing_err"] + f["fielding_err"]
    frows.append({"fielder": k[1], "club": TEAM[k[0]], "pos (games)": pos or "DH only", "outs recorded on balls hit to him": f["plays"],
                  "of which in the air": f["air"], "on the ground": f["ground"], "errors": err,
                  "throwing/fielding": f"{f['throwing_err']}/{f['fielding_err']}",
                  "clean rate": f"{f['plays'] / (f['plays'] + err):.3f}" if f["plays"] + err else "—", "_p": f["plays"]})
frows.sort(key=lambda r: -r["_p"])
P("## Fielding (reconstructed from the play-by-play)\n")
P("The game exposes no defensive metrics. 'Outs recorded' counts every out the log credits to the fielder who took the ball "
  "(e.g. 'flied out to McGee (F8)', 'grounded out to Keith (4-3)'). It is a range-and-opportunity proxy, not a full chance count: "
  "assists by the relay man and first basemen's putouts on throws are not credited. Errors are as the log reports them. Catchers' work is almost invisible here.\n")
table(frows, ["fielder","club","pos (games)","outs recorded on balls hit to him","of which in the air","on the ground","errors","throwing/fielding","clean rate"])

# ---------------- comeback candidates: before the league vs Season 1
P("## Before the league opened vs Season 1 (for Comeback Player)\n")
P("Cards that played both before the league opened (pre-season exhibition era, same rivalry) and in Season 1. Minimum 40 PA before and 25 PA in Season 1 for hitters; 10 IP both for pitchers.\n")
prebat = collections.defaultdict(collections.Counter)
for r in c.execute("""select b.* from batting_lines b join games g using(game_uuid) join v_game_status s using(game_uuid)
                      where g.is_h2h=1 and s.counts_stats=1 and g.played_at < ?""", (config.LEAGUE_START,)):
    b = prebat[(r["username"], norm(r["player_name"]))]
    for f in ("ab","h","bb","hbp","sf","sh","doubles","triples","hr","so"): b[f] += r[f] or 0
def ops(b):
    o = div(b["h"] + b["bb"] + b["hbp"], b["ab"] + b["bb"] + b["hbp"] + b["sf"]) or 0
    s = div(b["h"] + b["doubles"] + 2 * b["triples"] + 3 * b["hr"], b["ab"]) or 0
    return o + s
rows = []
for k, b in bat.items():
    p = prebat.get(k)
    if not p: continue
    ppa = p["ab"] + p["bb"] + p["hbp"] + p["sf"] + p["sh"]; pa = b["ab"] + b["bb"] + b["hbp"] + b["sf"] + b["sh"]
    if ppa >= 40 and pa >= 25:
        rows.append({"player": k[1], "club": TEAM[k[0]], "PA before": ppa, "AVG before": rate3(div(p["h"], p["ab"])), "OPS before": rate3(ops(p)),
                     "K% before": f"{100 * p['so'] / ppa:.0f}%", "PA S1": pa, "AVG S1": rate3(div(b["h"], b["ab"])), "OPS S1": rate3(ops(b)),
                     "K% S1": f"{100 * b['so'] / pa:.0f}%", "OPS change": f"{ops(b) - ops(p):+.3f}", "_d": ops(b) - ops(p)})
rows.sort(key=lambda r: -r["_d"])
table(rows, ["player","club","PA before","AVG before","OPS before","K% before","PA S1","AVG S1","OPS S1","K% S1","OPS change"])
prepit = collections.defaultdict(collections.Counter)
for r in c.execute("""select b.* from pitching_lines b join games g using(game_uuid) join v_game_status s using(game_uuid)
                      where g.is_h2h=1 and s.counts_stats=1 and g.played_at < ?""", (config.LEAGUE_START,)):
    p = prepit[(r["username"], r["player_name"])]
    for f in ("outs","er","h","bb","so"): p[f] += r[f] or 0
rows = []
for k, p in pit.items():
    q = prepit.get(k)
    if q and q["outs"] >= 30 and p["outs"] >= 30:
        rows.append({"pitcher": k[1], "club": TEAM[k[0]], "IP before": ip(q["outs"]), "ERA before": f"{27 * q['er'] / q['outs']:.2f}",
                     "WHIP before": f"{3 * (q['h'] + q['bb']) / q['outs']:.2f}", "IP S1": ip(p["outs"]), "ERA S1": f"{27 * p['er'] / p['outs']:.2f}",
                     "WHIP S1": f"{3 * (p['h'] + p['bb']) / p['outs']:.2f}", "ERA change": f"{27 * p['er'] / p['outs'] - 27 * q['er'] / q['outs']:+.2f}",
                     "_d": 27 * p['er'] / p['outs'] - 27 * q['er'] / q['outs']})
rows.sort(key=lambda r: r["_d"])
table(rows, ["pitcher","club","IP before","ERA before","WHIP before","IP S1","ERA S1","WHIP S1","ERA change"])

P("## Statistical leaders (no vote — these are simply awarded)\n")
qb = [r for r in brows if r["_pa"] >= qual_pa]
LEADERS = []
def lead(rows, key, label, rev=True, fmt=str):
    top = sorted(rows, key=lambda r: key(r), reverse=rev)[:3]
    best = key(top[0])
    LEADERS.append({"label": label, "value": fmt(best),
                    "who": [{"player": r.get("player") or r.get("pitcher"), "club": r["club"]} for r in top if key(r) == best]})
    P(f"- **{label}:** " + "; ".join(f"{r.get('player') or r.get('pitcher')} ({r['club']}) {fmt(key(r))}" for r in top))
lead(qb, lambda r: float("0" + r["AVG"]), "Batting title (qualified)", fmt=lambda v: f"{v:.3f}"[1:])
lead(qb, lambda r: r["_ops"], "OPS (qualified)", fmt=lambda v: f"{v:.3f}")
for key, label in (("HR", "Home runs"), ("RBI", "RBI"), ("R", "Runs"), ("H", "Hits"), ("SB", "Stolen bases"), ("TB", "Total bases")):
    lead(brows, lambda r, k=key: r[k], label)
qp = [r for r in prow if r["_outs"] >= 3 * len(reg)]
lead(qp, lambda r: float(r["ERA"]), "ERA title (qualified)", rev=False, fmt=lambda v: f"{v:.2f}")
lead(qp, lambda r: float(r["WHIP"]), "WHIP (qualified)", rev=False, fmt=lambda v: f"{v:.2f}")
for key, label in (("W", "Wins"), ("SO", "Strikeouts"), ("SV", "Saves"), ("HLD", "Holds")):
    lead(prow, lambda r, k=key: r[k], label)
lead(prow, lambda r: r["_outs"], "Innings", fmt=lambda o: f"{o // 3}.{o % 3}")
P("")
P("## Notes for voters\n")
P("- **Rookie** = a card whose first-ever appearance in this rivalry came after the league opened (marked ROOKIE in the tables).\n"
  f"- Only {len(reg)} games were played, so samples are small. Weigh volume as well as rate: a .900 OPS in 20 PA is not a season.\n"
  "- A card on the winning club is not automatically more valuable; a card on the losing club is not disqualified.\n")
open(OUT + "dossier.md", "w").write("\n".join(L))
json.dump({"season": SEASON, "games": len(reg), "span": [S1[0]["games"][0]["at"][:10], S1[-1]["ended"][:10]],
           "clubs": {TEAM[u]: u for u in (ME, TH)},
           "record": {TEAM[u]: f"{t['w']}-{t['l']}" for u, t in team.items()},
           "leaders": LEADERS,
           "hitters": [{k: v for k, v in r.items() if not k.startswith("_")} for r in brows],
           "pitchers": [{k: v for k, v in r.items() if not k.startswith("_")} for r in prow],
           "fielders": [{k: v for k, v in r.items() if not k.startswith("_")} for r in frows]}, open(OUT + "dossier.json", "w"))
