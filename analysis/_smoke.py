"""Headless smoke test: run every dashboard page, from both perspectives.

Not a real test suite — just enough to catch a page that blows up before you
open the browser. Run:  uv run python analysis/_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from streamlit.testing.v1 import AppTest  # noqa: E402

from show_h2h import config  # noqa: E402

PAGES = ["Rivalry", "Feats", "Hitters", "Pitchers", "Games"]
VIEWERS = [config.MY_USERNAME, config.FRIEND_USERNAME]

failures = 0
for viewer in VIEWERS:
    for page in PAGES:
        at = AppTest.from_file("app/dashboard.py", default_timeout=180)
        # Both nav controls are segmented_controls; driving them through
        # session_state is stabler than hunting for the widget in the tree.
        at.session_state["viewer"] = viewer
        at.session_state["page"] = page
        at.run()
        if at.exception:
            failures += 1
            print(f"FAIL [{viewer}] {page}: {at.exception[0].message}")
        else:
            print(f"ok   [{viewer}] {page}: {len(at.dataframe)} tables, "
                  f"{len(at.metric)} metrics, {len(at.error)} errors")

print(f"FAILURES: {failures}")
raise SystemExit(1 if failures else 0)
