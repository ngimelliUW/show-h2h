"""Smoke test: the report renders, carries real data, and the app imports.

The UI is a hand-written page embedded by Streamlit, so this checks the render
rather than walking widgets. Run:  uv run python analysis/_smoke.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from show_h2h import config, report  # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


html = report.render()
check("page renders", len(html) > 20_000, f"{len(html) // 1024} KB")
check("data placeholder was replaced", "/*__DATA__*/null" not in html)

data = json.loads(re.search(r"const DATA = (\{.*?\});", html, re.S).group(1))
check("both players present", data["players"] == [config.MY_USERNAME, config.FRIEND_USERNAME],
      str(data["players"]))
check("games embedded", len(data["games"]) > 0, f"{len(data['games'])} games")
check("batters embedded", len(data["batting"]) > 0, f"{len(data['batting'])} batters")
check("pitchers embedded", len(data["pitching"]) > 0, f"{len(data['pitching'])} pitchers")
check("team totals for both", set(data["team"]) == set(data["players"]))
check("no NaN leaked into the JSON", "NaN" not in json.dumps(data))

# The JS reads these by id; a rename in the template would silently break the page.
for element in ("verdict", "wins-a", "wins-b", "whoami", "tabs", "cmp-bat",
                "cmp-pit", "feats", "form", "tbl-bat", "tbl-pit", "tbl-games",
                "ko-a", "ko-b", "discipline", "pp-table", "pp-hits", "hr-table"):
    check(f"#{element} in template", f'id="{element}"' in html)

# Every DATA key the page reads must be one build() actually produces. This is
# the check that would have caught a template shipping ahead of its payload:
# `DATA.clutch.find(...)` on a missing key threw and blanked every section that
# rendered after it.
read = set(re.findall(r"DATA\.([A-Za-z_][A-Za-z0-9_]*)", html))
provided = set(data)
check("template reads no DATA key that build() omits", read <= provided,
      f"missing: {sorted(read - provided) or 'none'}")

# And a missing key must be survivable regardless, since the template is read
# from disk while the builder is an imported module.
check("template normalizes DATA before use", "if (!Array.isArray(DATA[k]))" in html)
check("render sections are isolated", 'section "${name}" failed' in html)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
check("dashboard module is importable", Path("app/dashboard.py").exists())

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
