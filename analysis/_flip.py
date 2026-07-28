"""Check the perspective switch is a true mirror, not just non-crashing.

Run:  uv run python analysis/_flip.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from streamlit.testing.v1 import AppTest  # noqa: E402

from show_h2h import config  # noqa: E402


def scoreboard_html(viewer: str) -> str:
    at = AppTest.from_file("app/dashboard.py", default_timeout=180)
    at.session_state["viewer"] = viewer
    at.session_state["page"] = "Rivalry"
    at.run()
    if at.exception:
        raise SystemExit(f"app raised for {viewer}: {at.exception[0].message}")
    # The record lives in injected HTML rather than st.metric, and the strip is
    # a separate block so the "you are" toggle can sit beside it — so join every
    # markdown block and parse the lot.
    return "\n".join(str(m.value) for m in at.markdown)


def parse(html: str) -> dict:
    wins = re.findall(r'class="sb-wins[^"]*">(\d+)<', html)
    strip = dict(re.findall(
        r'class="sb-k">([^<]+)</span><span class="sb-v">([^<]+)<', html))
    return {"wins": int(wins[0]), "losses": int(wins[1]), **strip}


a = parse(scoreboard_html(config.MY_USERNAME))
b = parse(scoreboard_html(config.FRIEND_USERNAME))
print(f"{config.MY_USERNAME:15s} {a['wins']}–{a['losses']}  run diff {a['Run diff']}  "
      f"streak {a['Streak']}")
print(f"{config.FRIEND_USERNAME:15s} {b['wins']}–{b['losses']}  run diff {b['Run diff']}  "
      f"streak {b['Streak']}")

checks = {
    "record is mirrored": (a["wins"], a["losses"]) == (b["losses"], b["wins"]),
    "run diff is negated": int(a["Run diff"]) == -int(b["Run diff"]),
    "runs are swapped": a["Runs"] == "–".join(reversed(b["Runs"].split("–"))),
    "games identical": a["Games"] == b["Games"],
    "streak flips W/L": a["Streak"][-1] != b["Streak"][-1],
}
print()
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}  {name}")
raise SystemExit(0 if all(checks.values()) else 1)
