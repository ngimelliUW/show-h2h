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
        "res": None if game["win"] is None
        else ("W" if (game["win"] == "home") == mine else "L"),
    }


def record(games: list[dict], who: str) -> dict:
    seen = [from_view(g, who) for g in games]
    return {
        "w": sum(g["res"] == "W" for g in seen),
        "l": sum(g["res"] == "L" for g in seen),
        "rf": sum(g["my"] for g in seen),
        "ra": sum(g["their"] for g in seen),
    }


data = report.build()
p1, p2 = data["players"]
a, b = record(data["games"], p1), record(data["games"], p2)

print(f"{p1:15s} {a['w']}–{a['l']}  runs {a['rf']}–{a['ra']}")
print(f"{p2:15s} {b['w']}–{b['l']}  runs {b['rf']}–{b['ra']}\n")

checks = {
    "record is mirrored": (a["w"], a["l"]) == (b["l"], b["w"]),
    "runs are swapped": (a["rf"], a["ra"]) == (b["ra"], b["rf"]),
    "every game has a decision": a["w"] + a["l"] == len(data["games"]),
    "no game counts as a win for both": a["w"] + b["w"] == len(data["games"]),
}
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}  {name}")
raise SystemExit(0 if all(checks.values()) else 1)
