"""Head-to-head dashboard. Run with:  uv run streamlit run app/dashboard.py

Deliberately thin. The entire UI — scoreboard, tabs, sortable leaderboards, the
you-are switch — is hand-written HTML/CSS/JS in app/report_template.html, and
this file just renders it against the current database and embeds it.

Why not build it out of Streamlit widgets: the design is a full-bleed scoreboard
over dense box-score tables, and Streamlit's DOM can't be pushed there without a
pile of fragile CSS overrides. An earlier attempt did exactly that and drifted
into a different-looking product. One page, one design.

Streamlit's remaining job is hosting and the one thing the embedded page can't
do for itself: reach out to the Show API for new games.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# Streamlit Community Cloud installs requirements.txt but not this project, so
# make the src/ layout importable without an editable install. Harmless locally.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Streamlit re-executes this script on every interaction but keeps imported
# modules in sys.modules, so after a redeploy the process can hold the previous
# release's Python while serving the new report template — which is read from
# disk every render. That skew shipped twice: a page whose markup expected data
# the stale builder did not produce, needing a manual reboot to clear.
# Dropping the package before importing costs a few milliseconds and makes a
# deploy self-healing.
for _name in [m for m in list(sys.modules) if m == "show_h2h" or m.startswith("show_h2h.")]:
    del sys.modules[_name]

from show_h2h import config, db, report  # noqa: E402

st.set_page_config(page_title="The Rivalry — MLB The Show 26", page_icon="⚾",
                   layout="wide", initial_sidebar_state="collapsed")

SEED = Path(__file__).resolve().parents[1] / "data" / "seed.db"


def use_writable_copy() -> None:
    """Run against a copy of the database outside the repo.

    The app writes to the database — schema migrations on boot, and the refresh
    button. Streamlit Cloud redeploys by pulling, and a pull will not clobber a
    locally-modified file, so writing to the committed copy pinned the deploy to
    whatever database existed the first time the app ran: new code reading old
    tables, with the new pages silently empty.

    The runtime directory is named after a fingerprint of the seed, so a new
    seed always lands somewhere new. Comparing timestamps instead looked
    equivalent and was not — the app rewrites its copy on every boot, so which
    file is "newer" depends on deploy ordering, and a stale copy kept winning.
    """
    fingerprint = "empty"
    if SEED.exists():
        stat = SEED.stat()
        fingerprint = hashlib.sha256(
            f"{stat.st_size}-{int(stat.st_mtime)}".encode()).hexdigest()[:16]

    runtime = Path(tempfile.gettempdir()) / "show-h2h" / fingerprint / "show.db"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    if SEED.exists() and not runtime.exists():
        shutil.copy2(SEED, runtime)
    config.DB_PATH = runtime
    config.DATA_DIR = runtime.parent


use_writable_copy()
db.init_db()

# Strip Streamlit's chrome so the embedded page is the whole app: no toolbar
# over the dark band, no padding insetting a design that runs edge to edge.
# The owner still gets "Manage app" and everything on share.streamlit.io.
st.markdown("""
<style>
  [data-testid="stHeader"], [data-testid="stSidebar"] { display: none !important; }
  .block-container {
    padding: 0 !important; max-width: 100% !important;
  }
  [data-testid="stMainBlockContainer"] { padding: 0 !important; }
  /* The report renders in an iframe, which needs an explicit height. Fill the
     viewport and let the page scroll inside it, minus the refresh bar. */
  iframe[title="st.iframe"] { height: calc(100vh - 52px) !important; width: 100% !important; }
  /* Refresh bar: a slim footer, styled to read as part of the page. */
  .st-key-refresh [data-testid="stButton"] button {
    width: 100%; border-radius: 0; border: 0;
    border-top: 1px solid rgba(255,255,255,.12);
    background: #0C1522; color: #8496AC;
    font-size: 13px; min-height: 44px;
  }
  .st-key-refresh [data-testid="stButton"] button:hover { color: #E9EEF5; background: #16223A; }
  .st-key-refresh { position: fixed; bottom: 0; left: 0; right: 0; z-index: 50; }
</style>
""", unsafe_allow_html=True)

components.html(report.render(), height=1400, scrolling=True)

with st.container(key="refresh"):
    if st.button("↻  Check the Show API for new games", width="stretch"):
        from show_h2h.importers import game_history, game_log

        with st.spinner("Looking for games played since the last pull…"):
            try:
                game_history.run_import(incremental=True)
                res = game_log.run_import(scope="both-played")
                st.toast(f"Up to date — {res['imported']} new box score(s).")
            except Exception as e:
                st.toast(f"Couldn't reach the API: {e}", icon="⚠️")
        st.rerun()
