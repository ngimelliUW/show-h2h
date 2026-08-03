"""Check the you-are switch is a true mirror.

The switch itself is JavaScript in the page (fromView / record), so this
verifies the same invariant against the data those functions consume: reading
every game from either side must produce mirrored records, and the two views
must agree about which games happened.

Run:  uv run python analysis/_flip.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from show_h2h import report  # noqa: E402


def from_view(game: dict, who: str) -> dict:
    """Python mirror of the page's fromView()."""
    mine = game["home"].lower() == who.lower()
    return {
        "my": game["hr"] if mine else game["ar"],
        "their": game["ar"] if mine else game["hr"],
        "st": game["st"],
        "res": None if game["win"] is None
        else ("W" if (game["win"] == "home") == mine else "L"),
    }


def record(games: list[dict], who: str) -> dict:
    """Mirrors the page's record(), including which games it leaves out.

    A game that never reached regulation counts for nothing — the page drops it
    from the tallies but still lists it, so the mirror has to make the same
    distinction or this check would pass while the page disagreed with itself.
    """
    seen = [from_view(g, who) for g in games]
    counted = [g for g in seen if g["st"] != "no_contest"]
    return {
        "w": sum(g["res"] == "W" for g in counted),
        "l": sum(g["res"] == "L" for g in counted),
        "t": sum(g["st"] == "tie" for g in counted),
        "rf": sum(g["my"] for g in counted),
        "ra": sum(g["their"] for g in counted),
        "n": len(counted),
    }


data = report.build()
p1, p2 = data["players"]
a, b = record(data["games"], p1), record(data["games"], p2)
voided = sum(g["st"] == "no_contest" for g in data["games"])

print(f"{p1:15s} {a['w']}–{a['l']}  runs {a['rf']}–{a['ra']}")
print(f"{p2:15s} {b['w']}–{b['l']}  runs {b['rf']}–{b['ra']}")
print(f"{'':15s} {a['t']} tie(s), {voided} no contest(s)\n")

checks = {
    "record is mirrored": (a["w"], a["l"]) == (b["l"], b["w"]),
    "runs are swapped": (a["rf"], a["ra"]) == (b["ra"], b["rf"]),
    "both sides agree on which games count": a["n"] == b["n"] == len(data["games"]) - voided,
    "both sides agree on the ties": a["t"] == b["t"],
    # A tie is neither side's win, so the two win counts plus the ties account
    # for every game that counts — and for no more than that.
    "every counting game is a win, a loss or a tie": a["w"] + a["l"] + a["t"] == a["n"],
    "no game counts as a win for both": a["w"] + b["w"] + a["t"] == a["n"],
}
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}  {name}")
raise SystemExit(0 if all(checks.values()) else 1)
