"""Plain-text rivalry summary for the terminal.

Run:  uv run python analysis/rivalry_report.py [min_ab]
"""
from __future__ import annotations

import sys

from show_h2h import config, db

MIN_AB = int(sys.argv[1]) if len(sys.argv) > 1 else 15
ME, THEM = config.MY_USERNAME, config.FRIEND_USERNAME


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def table(df, cols: dict[str, str]) -> None:
    """Print a DataFrame as an aligned table. cols maps column -> header."""
    if df.empty:
        print("  (nothing yet)")
        return
    widths = {c: max(len(h), *(len(str(v)) for v in df[c])) for c, h in cols.items()}
    print("  " + "  ".join(h.rjust(widths[c]) for c, h in cols.items()))
    for _, row in df.iterrows():
        print("  " + "  ".join(str(row[c]).rjust(widths[c]) for c in cols))


rec = db.query("SELECT * FROM v_h2h_record")
if rec.empty or not rec.iloc[0]["games"]:
    print("No head-to-head games yet. Run: uv run python -m show_h2h.ingest history")
    raise SystemExit(0)

r = rec.iloc[0]
rule(f"{ME}  vs  {THEM}")
print(f"  Record        {int(r.wins)}–{int(r.losses)}  ({r.win_pct:.3f})")
print(f"  Games         {int(r.games)}")
print(f"  Runs          {int(r.runs_for)}–{int(r.runs_against)} "
      f"({int(r.runs_for - r.runs_against):+d})")
print(f"  Per game      {r.avg_runs_for} scored, {r.avg_runs_against} allowed")

games = db.query("SELECT * FROM v_h2h_games ORDER BY played_at")
results = games["result"].dropna().tolist()
cur = kind = 0, ""
streak, best_w, best_l, run, prev = 0, 0, 0, 0, None
for res in results:
    run = run + 1 if res == prev else 1
    prev = res
    if res == "W":
        best_w = max(best_w, run)
    else:
        best_l = max(best_l, run)
print(f"  Streak        {run}{prev}  (longest {best_w}W / {best_l}L)")

rule("Home / away")
g = games.dropna(subset=["result"]).copy()
g["win"] = (g["result"] == "W").astype(int)
split = g.groupby("my_side").agg(games=("win", "size"), wins=("win", "sum")).reset_index()
split["losses"] = split["games"] - split["wins"]
split["pct"] = (split["wins"] / split["games"]).round(3)
table(split, {"my_side": "side", "games": "G", "wins": "W", "losses": "L", "pct": "PCT"})
if len(split) == 1:
    print(f"  ({ME} has been the {split.iloc[0]['my_side']} team in every game — "
          f"the sides have never swapped.)")

rule(f"Top hitters (min {MIN_AB} AB, head-to-head games only)")
bat = db.query("SELECT * FROM v_batting_totals WHERE ab >= ? ORDER BY avg DESC LIMIT 12", (MIN_AB,))
table(bat, {"username": "owner", "player_name": "player", "ab": "AB", "h": "H",
            "avg": "AVG", "hr": "HR", "rbi": "RBI"})

rule("Most home runs")
hr = db.query("SELECT * FROM v_batting_totals ORDER BY hr DESC, rbi DESC LIMIT 10")
table(hr, {"username": "owner", "player_name": "player", "hr": "HR", "rbi": "RBI", "ab": "AB"})

rule("Most strikeouts (pitching)")
k = db.query("SELECT * FROM v_pitching_totals ORDER BY so DESC LIMIT 10")
table(k, {"username": "owner", "player_name": "player", "innings": "IP", "so": "K",
          "k_per_9": "K/9", "era": "ERA", "whip": "WHIP"})

rule("Best ERA (min 6 IP)")
era = db.query("SELECT * FROM v_pitching_totals WHERE outs >= 18 ORDER BY era LIMIT 10")
table(era, {"username": "owner", "player_name": "player", "innings": "IP", "era": "ERA",
            "so": "K", "whip": "WHIP"})

rule("Notables")
g["margin"] = g["my_runs"] - g["their_runs"]
big = g.loc[g["margin"].idxmax()]
worst = g.loc[g["margin"].idxmin()]
print(f"  Biggest win        {int(big.my_runs)}–{int(big.their_runs)}   {big.display_date}")
print(f"  Worst loss         {int(worst.my_runs)}–{int(worst.their_runs)}   {worst.display_date}")
print(f"  Shutouts thrown    {int((g.their_runs == 0).sum())}")
print(f"  Shutouts suffered  {int((g.my_runs == 0).sum())}")
print(f"  One-run games      {int((g.margin.abs() == 1).sum())}  "
      f"({int(((g.margin.abs() == 1) & (g.result == 'W')).sum())} won)")
print(f"  Extra innings      {int(g.extra_innings.sum())}")

coop = db.query("SELECT COUNT(*) n FROM v_coop_games").iloc[0].n
if coop:
    print(f"  Co-op together     {int(coop)} games (not counted in the record)")
print()
