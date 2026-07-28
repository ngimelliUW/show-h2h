"""Headless smoke test: run every dashboard page, from both perspectives.

Not a real test suite — just enough to catch a page that blows up before you
open the browser. Run:  uv run python analysis/_smoke.py
"""
from __future__ import annotations

from streamlit.testing.v1 import AppTest

from show_h2h import config

PAGES = ["Rivalry", "Feats", "Hitters", "Pitchers", "Games"]
VIEWERS = [config.MY_USERNAME, config.FRIEND_USERNAME]

failures = 0
for viewer in VIEWERS:
    for page in PAGES:
        at = AppTest.from_file("app/dashboard.py", default_timeout=180)
        at.run()
        at.radio[0].set_value(viewer).run()   # "Viewing as"
        at.radio[1].set_value(page).run()     # "Page"
        if at.exception:
            failures += 1
            print(f"FAIL [{viewer}] {page}: {at.exception[0].message}")
        else:
            print(f"ok   [{viewer}] {page}: {len(at.dataframe)} tables, "
                  f"{len(at.metric)} metrics, {len(at.error)} errors")

print(f"FAILURES: {failures}")
raise SystemExit(1 if failures else 0)
