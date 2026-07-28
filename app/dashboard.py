"""Head-to-head dashboard. Run with:  uv run streamlit run app/dashboard.py

Reads only from the local database — never hits the API. Refresh data with:
  uv run python -m show_h2h.ingest refresh
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# Streamlit Community Cloud installs requirements.txt but not this project, so
# make the src/ layout importable without an editable install. Harmless locally.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import theme  # noqa: E402
from show_h2h import config, db  # noqa: E402

st.set_page_config(page_title="Show H2H", page_icon="⚾", layout="wide",
                   initial_sidebar_state="collapsed")
db.init_db()
st.markdown(theme.CSS, unsafe_allow_html=True)

# Whose side the page is written from. The views are all built from
# MY_USERNAME's perspective, so picking the other player flips the games frame
# (see flip_perspective) rather than rebuilding the SQL.
#
# This lives in the main body, not the sidebar: Streamlit collapses the sidebar
# behind a hamburger on phones, and "which of us am I" is the first thing either
# player needs to set.
# The widget itself is rendered later, inside the scoreboard band — but its
# value is needed up here to build the board. Streamlit puts a keyed widget's
# value in session_state before the script reruns, so reading it first and
# rendering it further down is safe.
VIEWER = st.session_state.get("viewer") or config.MY_USERNAME
ME = VIEWER
THEM = config.FRIEND_USERNAME if VIEWER == config.MY_USERNAME else config.MY_USERNAME
FLIPPED = VIEWER != config.MY_USERNAME


def flip_perspective(df):
    """Rewrite a v_h2h_games frame to read from the other player's side."""
    if not FLIPPED or df.empty:
        return df
    out = df.copy()
    swaps = [("my_runs", "their_runs"), ("my_hits", "their_hits"),
             ("my_squad", "their_squad")]
    for a, b in swaps:
        if a in out.columns and b in out.columns:
            out[a], out[b] = out[b].copy(), out[a].copy()
    if "result" in out.columns:
        out["result"] = out["result"].map({"W": "L", "L": "W"})
    if "my_side" in out.columns:
        out["my_side"] = out["my_side"].map({"home": "away", "away": "home"})
    return out

# One colour per player, used everywhere. Without an explicit map plotly assigns
# colours by order of first appearance, so the two of you would swap colours
# whenever the sort changed — same page, different sort, swapped identity.
# Keyed on the FIXED usernames, never on ME/THEM: those follow the "Viewing as"
# choice, so keying on them would swap the colours when you switch seats.
# These two are colourblind-safe and readable on both light and dark themes.
PLAYER_COLORS = {config.MY_USERNAME: "#0072B2", config.FRIEND_USERNAME: "#D55E00"}
PLAYER_ORDER = {"username": [config.MY_USERNAME, config.FRIEND_USERNAME]}
GRIDLINE = "#888888"  # mid-grey: visible on either theme (plotly shapes aren't themed)

# The play-by-play is prose with in-band markup: ^n^ is a newline, ^e^ ends the
# stadium name, and ^cNN^ tags highlight things (46 = critical play, 48 = run
# scored, 51 = inning header, ...). Strip the tags, keep the prose.
_MARKUP = re.compile(r"\^(?:c\d+|b\d+|e)\^")


def clean_play_by_play(text: str) -> str:
    return _MARKUP.sub("", (text or "").replace("^n^", "\n")).strip()


def pretty_date(display_date: str) -> str:
    """'07/28/2026 04:02:21' -> 'Jul 28, 2026'. Nobody needs the seconds."""
    try:
        return pd.to_datetime(display_date, format="%m/%d/%Y %H:%M:%S").strftime("%b %-d, %Y")
    except (ValueError, TypeError):
        return str(display_date or "")


def rate(v) -> str:
    """0.295 -> '.295'. Baseball drops the leading zero on AVG/OBP/SLG/OPS.

    Kept as fixed-width text so column-header sorting still orders correctly:
    '.' sorts below every digit, so '.295' < '1.028' exactly as the numbers do.
    (ERA and WHIP keep their leading zero — that IS their convention — so they
    stay numeric, where '10.99' vs '2.70' would sort wrong as text.)
    """
    if pd.isna(v):
        return ""
    s = f"{float(v):.3f}"
    return s[1:] if s.startswith("0.") else s


RATE_COLS = ("avg", "obp", "slg", "ops", "iso", "babip", "sb_pct")


@st.cache_data(ttl=60)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return db.query(sql, params)


def empty_state(msg: str, cmd: str) -> None:
    st.info(f"{msg}\n\nRun: `{cmd}`")


# Display names + number formats for every column that reaches a table.
# Values are (header, format); format None means text/leave alone.
COLUMNS = {
    "rank": ("#", "%d"),
    "username": ("Owner", None),
    "player_name": ("Player", None),
    "games": ("G", "%d"),
    # batting
    "ab": ("AB", "%d"), "pa": ("PA", "%d"), "h": ("H", "%d"), "runs": ("R", "%d"),
    "rbi": ("RBI", "%d"), "hr": ("HR", "%d"), "doubles": ("2B", "%d"),
    "triples": ("3B", "%d"), "bb": ("BB", "%d"), "so": ("SO", "%d"),
    "sb": ("SB", "%d"), "cs": ("CS", "%d"), "hbp": ("HBP", "%d"),
    "avg": ("AVG", None), "obp": ("OBP", None), "slg": ("SLG", None),
    "ops": ("OPS", None), "iso": ("ISO", None), "babip": ("BABIP", None),
    "sb_pct": ("SB%", None),
    "k_pct": ("K%", "%.1f"), "bb_pct": ("BB%", "%.1f"),
    # pitching
    "innings": ("IP", "%.1f"), "era": ("ERA", "%.2f"), "ra9": ("RA/9", "%.2f"),
    "whip": ("WHIP", "%.3f"), "k_per_9": ("K/9", "%.2f"), "bb_per_9": ("BB/9", "%.2f"),
    "k_bb": ("K/BB", "%.2f"), "er": ("ER", "%d"), "wins": ("W", "%d"),
    "losses": ("L", "%d"), "saves": ("SV", "%d"), "holds": ("HLD", "%d"),
    "wp": ("WP", "%d"), "starts": ("GS", "%d"), "r": ("R", "%d"),
    "ip": ("IP", None),
    # games
    "display_date": ("Date", None), "played_at": ("Date", None),
    "my_runs": (ME, "%d"), "their_runs": (THEM, "%d"),
    "my_squad": ("Your squad", None), "their_squad": ("Their squad", None),
    "my_side": ("Side", None), "result": ("W/L", None), "score": ("Score", None),
    "home_username": ("Home", None), "away_username": ("Away", None),
    "home_squad": ("Home squad", None), "away_squad": ("Away squad", None),
    "home_runs": ("Home R", "%d"), "away_runs": ("Away R", "%d"),
    "winner": ("Winner", None), "kind": ("Type", None), "note": ("Note", None),
    "opponent": ("Opponent", None), "our_score": ("Score", None),
    "our_side": ("Our side", None),
    "pos": ("Pos", None), "side": ("Side", None), "inn": ("Inn", "%d"),
}

# Never show these to a player — internal keys and helper columns.
HIDDEN = {"game_uuid", "natural_key", "has_box_score", "extra_innings", "me",
          "outs", "slot", "ruling", "ended_early", "label", "margin", "total_runs",
          "win", "is_h2h", "is_coop", "is_vs_cpu"}


def col_config(df) -> dict:
    cfg = {}
    for c in df.columns:
        if c in HIDDEN:
            continue
        label, fmt = COLUMNS.get(c, (c.replace("_", " ").title(), None))
        cfg[c] = (st.column_config.NumberColumn(label, format=fmt) if fmt
                  else st.column_config.Column(label))
    return cfg


def show_table(df, *, height=None, column_order=None, **kwargs):
    """st.dataframe with baseball headers, aligned decimals, no internal columns.

    Height is sized to content unless capped, so a short table (the 8 co-op
    games) doesn't pad out with blank rows that read as a render failure.
    """
    visible = [c for c in df.columns if c not in HIDDEN]
    out = df[visible].copy()
    # A column that's all-numeric-but-one-None arrives as object dtype and then
    # renders the word "None" (e.g. K/BB for a pitcher who has never walked
    # anyone). Coerce so it renders as an empty cell instead.
    for c in visible:
        if COLUMNS.get(c, (None, None))[1]:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    if height:  # cap tall tables, but never pad a short one with blank rows
        kwargs["height"] = min(height, 36 * len(out) + 40)
    st.dataframe(out, column_config=col_config(out), hide_index=True,
                 width="stretch", column_order=column_order, **kwargs)


def as_display(df):
    """Copy with rate stats rendered in baseball notation."""
    out = df.copy()
    for c in RATE_COLS:
        if c in out.columns:
            out[c] = out[c].map(rate)
    return out


def leader_chart(top, value_col, label):
    """Bar chart of the top N.

    Players are keyed by SURNAME ONLY, so both owners routinely field a card
    with the same name (two Messicks, two Fingers, two Durans). Plotting on the
    bare name makes plotly stack them into a single bar belonging to neither
    player, so the axis uses an owner-disambiguated label and bars are grouped.
    """
    top = top.copy()
    top["label"] = top["player_name"] + "  (" + top["username"].str.slice(0, 4) + ")"
    fig = px.bar(top, x="label", y=value_col, color="username", barmode="group",
                 color_discrete_map=PLAYER_COLORS, category_orders=PLAYER_ORDER,
                 labels={"label": "", value_col: label, "username": ""})
    fig.update_xaxes(categoryorder="array", categoryarray=top["label"].tolist())
    fig.update_layout(height=320, margin=dict(t=10, b=0), legend_title_text="")
    return fig


def streaks(results: list[str]) -> tuple[int, str, int, int]:
    """(current streak, its W/L, longest win streak, longest loss streak).
    `results` must be oldest-first."""
    cur = best_w = best_l = 0
    cur_kind = ""
    for r in results:
        cur = cur + 1 if r == cur_kind else 1
        cur_kind = r
        if cur_kind == "W":
            best_w = max(best_w, cur)
        elif cur_kind == "L":
            best_l = max(best_l, cur)
    return cur, cur_kind, best_w, best_l


# (label, lower_is_better, needs_playing_time_minimum)
# A minimum matters for rate stats, and equally for "fewest X" counting stats —
# without one, "fewest earned runs" is topped by whoever threw a single inning.
BATTING_SORTS = {
    "hr": ("Home runs", False, False),
    "rbi": ("RBI", False, False),
    "h": ("Hits", False, False),
    "runs": ("Runs scored", False, False),
    "sb": ("Stolen bases", False, False),
    "doubles": ("Doubles", False, False),
    "triples": ("Triples", False, False),
    "bb": ("Walks drawn", False, False),
    "so": ("Strikeouts (most K'd)", False, False),
    "ab": ("At-bats", False, False),
    "games": ("Games played", False, False),
    "avg": ("Batting average", False, True),
    "obp": ("On-base % (OBP)", False, True),
    "slg": ("Slugging % (SLG)", False, True),
    "ops": ("OPS", False, True),
    "iso": ("Isolated power (ISO)", False, True),
    "babip": ("BABIP", False, True),
    "sb_pct": ("Stolen-base %", False, True),
    "k_pct": ("Strikeout rate (worst)", False, True),
    "bb_pct": ("Walk rate (best)", False, True),
}

PITCHING_SORTS = {
    "so": ("Strikeouts", False, False),
    "wins": ("Wins", False, False),
    "saves": ("Saves", False, False),
    "starts": ("Games started", False, False),
    "innings": ("Innings pitched", False, False),
    "games": ("Appearances", False, False),
    "losses": ("Losses (most)", False, False),
    "era": ("ERA (lowest)", True, True),
    "ra9": ("Runs allowed / 9", True, True),
    "whip": ("WHIP (lowest)", True, True),
    "k_per_9": ("K / 9", False, True),
    "bb_per_9": ("BB / 9 (lowest)", True, True),
    "k_bb": ("K / BB", False, True),
    "er": ("Earned runs (fewest)", True, True),
    "h": ("Hits allowed (fewest)", True, True),
    "bb": ("Walks allowed (fewest)", True, True),
}


def leaderboard_controls(df, sorts: dict, default: str, *, qual_col: str, qual_noun: str,
                         default_min: int):
    """Owner filter + sort + playing-time minimum, applied to the WHOLE table.

    The sort runs across every qualifying player before anything is rendered, so
    the top row really is the leader in that stat. (Sorting a pre-truncated
    top-20 would just reorder those twenty, which is not a leaderboard.)
    """
    c1, c2, c3 = st.columns([3, 2, 2])
    sort_by = c1.selectbox("Sort by", list(sorts), index=list(sorts).index(default),
                           format_func=lambda k: sorts[k][0])
    who = c2.radio("Card owner", ["Both", ME, THEM], horizontal=True,
                   help="Whose roster the card belongs to — not who they played against.")
    label, lower_is_better, needs_min = sorts[sort_by]

    ceiling = int(max(df[qual_col].max(), 2))
    floor = min(default_min, ceiling) if needs_min else 0
    min_qual = c3.number_input(f"Min {qual_noun}", 0, ceiling, floor,
                               help="Rate stats and 'fewest' leaderboards need a playing-time "
                                    "floor to be meaningful; counting stats don't, so this "
                                    "drops to 0 when you sort by one.")

    view = df[df[qual_col] >= min_qual]
    if who != "Both":
        view = view[view["username"].str.lower() == who.lower()]

    search = st.text_input("Find a player", placeholder="surname…",
                           key=f"search_{qual_col}")
    if search:
        view = view[view["player_name"].str.contains(search, case=False, na=False)]

    view = view.sort_values(sort_by, ascending=lower_is_better,
                            na_position="last").reset_index(drop=True)
    view.insert(0, "rank", range(1, len(view) + 1))
    return view, sort_by, label


# ---- the scoreboard, on every page ----
_all = flip_perspective(q("SELECT * FROM v_h2h_games ORDER BY played_at"))
if _all.empty:
    st.title("⚾ The Rivalry")
    empty_state("No head-to-head games yet.", "uv run python -m show_h2h.ingest history")
    st.stop()

_played = _all.dropna(subset=["result"])
_res = _played["result"].tolist()
_w = int((_played["result"] == "W").sum())
_l = int((_played["result"] == "L").sum())
_cur, _kind, _bw, _bl = streaks(_res)
_last10 = _res[-10:]
_rf, _ra = int(_all["my_runs"].sum()), int(_all["their_runs"].sum())

with st.container(key="scoreboard"):
    st.markdown(theme.scoreboard_top(ME, THEM, _w, _l,
                                     PLAYER_COLORS[ME], PLAYER_COLORS[THEM]),
                unsafe_allow_html=True)
    _strip_col, _who_col = st.columns([3, 1], vertical_alignment="bottom")
    _strip_col.markdown(
        theme.strip_only(
            [("Games", len(_all)),
             ("Run diff", f"{_rf - _ra:+d}"),
             ("Runs", f"{_rf}–{_ra}"),
             ("Streak", f"{_cur}{_kind}"),
             ("Longest", f"{_bw}W · {_bl}L"),
             ("Last 10", f"{_last10.count('W')}–{_last10.count('L')}")]),
        unsafe_allow_html=True)
    with _who_col:
        st.segmented_control(
            "You are", [config.MY_USERNAME, config.FRIEND_USERNAME],
            default=config.MY_USERNAME, key="viewer",
            help="Switches whose side every number on the page is written from.")

PAGES = ["Rivalry", "Feats", "Hitters", "Pitchers", "Games"]
with st.container(key="nav"):
    page = st.segmented_control("Page", PAGES, default="Rivalry", key="page",
                                label_visibility="collapsed") or "Rivalry"

# Pulling straight from the API keeps the hosted copy genuinely live rather than
# a snapshot — the crawl is incremental, so it stops as soon as it reaches games
# already stored and normally costs a couple of requests.
_bar1, _bar2 = st.columns([1, 3])
if _bar1.button("↻ Pull new games", width="stretch"):
    from show_h2h.importers import game_history, game_log

    with st.spinner("Checking the Show API for new games…"):
        try:
            game_history.run_import(incremental=True)
            res = game_log.run_import(scope="both-played")
            q.clear()
            st.toast(f"Up to date — {res['imported']} new box score(s).")
        except Exception as e:
            st.error(f"Couldn't reach the API: {e}")
    st.rerun()

_latest = q("SELECT MAX(played_at) d FROM games WHERE is_h2h = 1")
if not _latest.empty and _latest.iloc[0]["d"]:
    _bar2.caption(f"Data through {str(_latest.iloc[0]['d'])[:10]} · "
                  f"{len(_all)} head-to-head games")


# --------------------------------------------------------------------------- #
# Rivalry
# --------------------------------------------------------------------------- #
if page == "Rivalry":
    # The scoreboard above already carries the headline numbers, so this page
    # goes straight to the comparison rather than restating the record.
    games = _all
    r = {"games": len(games), "wins": _w, "losses": _l,
         "runs_for": _rf, "runs_against": _ra,
         "avg_runs_for": round(games["my_runs"].mean(), 2),
         "avg_runs_against": round(games["their_runs"].mean(), 2)}

    early = int(games["ended_early"].sum()) if "ended_early" in games else 0
    if early:
        st.caption(f"⚑ {early} of these games ended early (the API flags them with a "
                   f"non-zero `ruling`, which is what a quit or disconnect looks like) — "
                   f"including one recorded as a **0–0 win**. They still count in the "
                   f"record above, because the game awarded them.")

    st.divider()

    # ---- direct comparison: the screenshot for the group chat ----
    st.subheader("Head to head, all 111 games")
    tb = q("SELECT * FROM v_team_batting").set_index("username")
    tp = q("SELECT * FROM v_team_pitching").set_index("username")

    def row(label, a, b, lower_better=False, fmt=str):
        """One comparison row as (yours, stat name, theirs, you won, they won)."""
        a_wins = (a < b) if lower_better else (a > b)
        b_wins = (b < a) if lower_better else (b > a)
        return (fmt(a), label, fmt(b), a_wins, b_wins)

    if ME in tb.index and THEM in tb.index:
        bat_rows = [
            row("Batting average", tb.loc[ME, "avg"], tb.loc[THEM, "avg"], fmt=rate),
            row("On-base %", tb.loc[ME, "obp"], tb.loc[THEM, "obp"], fmt=rate),
            row("Slugging %", tb.loc[ME, "slg"], tb.loc[THEM, "slg"], fmt=rate),
            row("OPS", tb.loc[ME, "ops"], tb.loc[THEM, "ops"], fmt=rate),
            row("Home runs", tb.loc[ME, "hr"], tb.loc[THEM, "hr"], fmt=lambda v: f"{int(v)}"),
            row("Runs", tb.loc[ME, "runs"], tb.loc[THEM, "runs"], fmt=lambda v: f"{int(v)}"),
            row("Stolen bases", tb.loc[ME, "sb"], tb.loc[THEM, "sb"], fmt=lambda v: f"{int(v)}"),
        ]
        pit_rows = [
            row("ERA", tp.loc[ME, "era"], tp.loc[THEM, "era"], True, lambda v: f"{v:.2f}"),
            row("WHIP", tp.loc[ME, "whip"], tp.loc[THEM, "whip"], True, lambda v: f"{v:.3f}"),
            row("K / 9", tp.loc[ME, "k_per_9"], tp.loc[THEM, "k_per_9"], fmt=lambda v: f"{v:.2f}"),
            row("BB / 9", tp.loc[ME, "bb_per_9"], tp.loc[THEM, "bb_per_9"], True,
                lambda v: f"{v:.2f}"),
            row("Strikeouts", tp.loc[ME, "so"], tp.loc[THEM, "so"], fmt=lambda v: f"{int(v)}"),
        ]
        st.caption(f"{ME} on the left, {THEM} on the right. Bold is the better mark. "
                   f"Totals are every card either of you played across all "
                   f"{len(games)} games.")
        bcol, pcol = st.columns(2)
        bcol.markdown(theme.cmp_table("Batting — both rosters", bat_rows),
                      unsafe_allow_html=True)
        pcol.markdown(theme.cmp_table("Pitching — both staffs", pit_rows),
                      unsafe_allow_html=True)

    st.divider()

    left, right = st.columns(2)
    with left:
        st.subheader("Recent form")
        g = games.dropna(subset=["result"]).copy()
        g["win"] = (g["result"] == "W").astype(int)
        g["game_no"] = range(1, len(g) + 1)
        g["rolling"] = g["win"].rolling(10, min_periods=3).mean()
        fig = px.line(g, x="game_no", y="rolling",
                      labels={"game_no": "Game number", "rolling": "Win % (last 10)"})
        fig.update_traces(line_color=PLAYER_COLORS[ME])
        fig.add_hline(y=0.5, line_dash="dot", line_color=GRIDLINE, opacity=0.7)
        fig.update_yaxes(range=[0, 1], tickformat=".0%")
        fig.update_layout(height=300, margin=dict(t=10, b=0))
        st.plotly_chart(fig, width="stretch")
        st.caption("Rolling 10-game win rate. A cumulative line flattens out and stops "
                   "saying anything after ~30 games; this shows who's better lately.")

    with right:
        st.subheader("Final margin")
        g["margin"] = g["my_runs"] - g["their_runs"]
        counts = g["margin"].value_counts().sort_index().reset_index()
        counts.columns = ["margin", "games"]
        counts["who"] = [ME if m > 0 else THEM for m in counts["margin"]]
        fig2 = px.bar(counts, x="margin", y="games", color="who",
                      color_discrete_map=PLAYER_COLORS, category_orders=PLAYER_ORDER,
                      labels={"margin": f"{ME} run margin", "games": "Games", "who": ""})
        fig2.add_vline(x=0, line_dash="dot", line_color=GRIDLINE, opacity=0.7)
        fig2.update_layout(height=300, margin=dict(t=10, b=0), legend_title_text="")
        st.plotly_chart(fig2, width="stretch")
        st.caption("One bar per run margin — how many games were blowouts vs nail-biters.")

    coop = q("SELECT COUNT(*) n FROM v_coop_games").iloc[0]["n"]
    if coop:
        st.caption(f"Plus {int(coop)} co-op games where you two were **teammates** — "
                   f"not part of the record. See the Games page.")


# --------------------------------------------------------------------------- #
# Hitters
# --------------------------------------------------------------------------- #
elif page == "Hitters":
    st.title("⚾ Hitters")

    bat = q("SELECT * FROM v_batting_totals")
    if bat.empty:
        empty_state("No box scores yet.", "uv run python -m show_h2h.ingest box-scores")
        st.stop()

    st.caption("Career totals across head-to-head games.")
    view, sort_by, sort_label = leaderboard_controls(
        bat, BATTING_SORTS, "hr", qual_col="ab", qual_noun="AB", default_min=50)
    if view.empty:
        st.warning("Nobody clears that minimum. Lower it to see more players.")
        st.stop()

    cols = ["rank", "username", "player_name", "games", "pa", "ab", "h", "avg", "obp",
            "slg", "ops", "iso", "hr", "rbi", "runs", "doubles", "triples", "bb", "so",
            "k_pct", "bb_pct", "sb", "cs", "sb_pct", "babip"]
    lead = ["rank", "username", "player_name", "games", sort_by]
    order = lead + [c for c in cols if c not in lead]
    show_table(as_display(view[cols]), height=520, column_order=order)
    st.caption(f"{len(view)} players, ranked by {sort_label}. The column you sorted by "
               f"is moved next to the name. Clicking a header re-sorts the rows on "
               f"screen, but the **#** column always reflects the *Sort by* control.")

    st.plotly_chart(leader_chart(view.head(12), sort_by, sort_label),
                    width="stretch")

    with st.expander("About this data"):
        st.markdown(
            "- The API reports batters by **surname only** and truncates long names "
            "(`Misiorowsk...`), so two cards of the same player merge into one row and "
            "two players sharing a surname can't be told apart.\n"
            "- **OBP can sit below AVG** for a hitter with a sacrifice fly and no walks — "
            "a sac fly enlarges the OBP denominator without adding to the numerator. "
            "That's the rule, not a bug.\n"
            "- **OPS may differ from OBP + SLG by .001.** It's computed from full "
            "precision and rounded once, which is what Baseball-Reference does.\n"
            "- PA is reconstructed as AB + BB + HBP + SF + SH. Catcher's interference "
            "isn't reported by the API, so it's excluded (it's rare)."
        )


# --------------------------------------------------------------------------- #
# Pitchers
# --------------------------------------------------------------------------- #
elif page == "Pitchers":
    st.title("⚾ Pitchers")

    pit = q("SELECT * FROM v_pitching_totals")
    if pit.empty:
        empty_state("No box scores yet.", "uv run python -m show_h2h.ingest box-scores")
        st.stop()

    st.caption("Career totals across head-to-head games.")
    view, sort_by, sort_label = leaderboard_controls(
        pit, PITCHING_SORTS, "so", qual_col="innings", qual_noun="IP", default_min=15)
    if view.empty:
        st.warning("Nobody clears that minimum. Lower it to see more pitchers.")
        st.stop()

    cols = ["rank", "username", "player_name", "games", "starts", "innings", "so",
            "k_per_9", "bb_per_9", "k_bb", "era", "ra9", "whip", "h", "bb", "er",
            "wins", "losses", "saves", "holds", "wp"]
    lead = ["rank", "username", "player_name", "games", "innings", sort_by]
    order = lead + [c for c in cols if c not in lead]
    show_table(view[cols], height=520, column_order=order)
    st.caption(f"{len(view)} pitchers, ranked by {sort_label}. The column you sorted by "
               f"is moved next to the name. Clicking a header re-sorts the rows on "
               f"screen, but the **#** column always reflects the *Sort by* control.")

    st.plotly_chart(leader_chart(view.head(12), sort_by, sort_label),
                    width="stretch")

    with st.expander("About this data"):
        st.markdown(
            "- **IP is in real baseball notation** — `390.2` means 390 and two-thirds "
            "innings, not 390.7. ERA, K/9, BB/9 and WHIP are all computed from outs "
            "recorded, never from that string.\n"
            "- **RA/9** counts unearned runs, which ERA hides. Where it exceeds ERA, "
            "the defence gave runs away.\n"
            "- **K/BB is blank** for a pitcher who has never issued a walk — the ratio "
            "is undefined rather than infinite.\n"
            "- Long surnames arrive truncated (`Misiorowsk...`) and the API sends no "
            "first names. GS counts games where the pitcher was listed first."
        )


# --------------------------------------------------------------------------- #
# Feats  (named to avoid colliding with "Record", which means W–L)
# --------------------------------------------------------------------------- #
elif page == "Feats":
    st.title("🏆 Feats")

    g = flip_perspective(q("SELECT * FROM v_h2h_games ORDER BY played_at"))
    if g.empty:
        empty_state("No head-to-head games yet.",
                    "uv run python -m show_h2h.ingest history")
        st.stop()

    g["margin"] = g["my_runs"] - g["their_runs"]
    g["total_runs"] = g["my_runs"] + g["their_runs"]

    c1, c2, c3 = st.columns(3)
    biggest_win = g.loc[g["margin"].idxmax()]
    biggest_loss = g.loc[g["margin"].idxmin()]
    highest = g.loc[g["total_runs"].idxmax()]
    # Dates go in captions, not st.metric's delta slot — a green up-arrow next
    # to "Worst loss" reads as if losing badly were an improvement.
    c1.metric("Biggest win", f"{int(biggest_win['my_runs'])}–{int(biggest_win['their_runs'])}")
    c1.caption(pretty_date(biggest_win["display_date"]))
    c2.metric("Worst loss", f"{int(biggest_loss['my_runs'])}–{int(biggest_loss['their_runs'])}")
    c2.caption(pretty_date(biggest_loss["display_date"]))
    c3.metric("Highest scoring", f"{int(highest['my_runs'])}–{int(highest['their_runs'])}")
    c3.caption(pretty_date(highest["display_date"]))

    # A 0-0 game (awarded on a quit) is not a shutout for anybody, and counting
    # it would put the same game in both columns.
    real = g[g["total_runs"] > 0]
    c4, c5, c6 = st.columns(3)
    c4.metric("Opponent held scoreless", int((real["their_runs"] == 0).sum()))
    c5.metric("Held scoreless", int((real["my_runs"] == 0).sum()))
    c6.metric("Extra-inning games", int(g["extra_innings"].sum()))

    st.subheader("One-run games")
    close = g[g["margin"].abs() == 1]
    if close.empty:
        st.caption("None yet.")
    else:
        wins = int((close["result"] == "W").sum())
        st.caption(f"{len(close)} of them — {ME} is {wins}–{len(close) - wins} in nail-biters.")
        show_table(close[["display_date", "my_runs", "their_runs", "result"]], height=300)

    st.subheader("Single-game bests")
    bb = q("""
        SELECT b.username, b.player_name, b.hr, b.rbi, b.h, b.ab, g.display_date
        FROM batting_lines b JOIN games g ON g.game_uuid = b.game_uuid
        WHERE g.is_h2h = 1 ORDER BY b.hr DESC, b.rbi DESC, b.h DESC LIMIT 12
    """)
    pp = q("""
        SELECT p.username, p.player_name, p.so, p.ip_text AS ip, p.er, p.h, g.display_date
        FROM pitching_lines p JOIN games g ON g.game_uuid = p.game_uuid
        WHERE g.is_h2h = 1 ORDER BY p.so DESC, p.er ASC LIMIT 12
    """)
    left, right = st.columns(2)
    with left:
        st.markdown("**Most home runs in a game**")
        show_table(bb)
    with right:
        st.markdown("**Most strikeouts in a game**")
        show_table(pp)


# --------------------------------------------------------------------------- #
# Games
# --------------------------------------------------------------------------- #
elif page == "Games":
    st.title("⚾ Games")

    kind = st.radio("Show", ["Head-to-head", "Co-op together", "All games"],
                    horizontal=True)

    if kind == "Head-to-head":
        games = flip_perspective(q("SELECT * FROM v_h2h_games ORDER BY played_at DESC"))
        show = games.assign(
            note=["ended early" if e else "" for e in games["ended_early"]],
            inn=games["innings"],
        )[["display_date", "my_runs", "their_runs", "result", "inn",
           "my_squad", "their_squad", "note"]]
    elif kind == "Co-op together":
        games = q("SELECT * FROM v_coop_games ORDER BY played_at DESC")
        # The API names only one player per side, so a co-op game shows one of
        # you and the opposing player. Spell out that you were partners.
        ours, opp, score = [], [], []
        for _, gm in games.iterrows():
            home_is_ours = str(gm["home_username"]).lower() in (ME.lower(), THEM.lower())
            ours.append(f"{ME} + {THEM}")
            opp.append(gm["away_username"] if home_is_ours else gm["home_username"])
            us = gm["home_runs"] if home_is_ours else gm["away_runs"]
            them = gm["away_runs"] if home_is_ours else gm["home_runs"]
            score.append(f"{int(us)}–{int(them)}"
                         + ("  W" if us > them else "  L" if us < them else ""))
        show = games.assign(our_side=ours, opponent=opp, our_score=score)[
            ["display_date", "our_side", "our_score", "opponent"]]
    else:
        games = q("""SELECT display_date, home_username, home_squad, home_runs, away_runs,
                            away_squad, away_username, is_h2h, is_coop, is_vs_cpu, game_uuid
                     FROM games ORDER BY played_at DESC""")
        show = games.assign(kind=[
            "Head-to-head" if h else "Co-op" if c else "vs CPU" if v else "Other"
            for h, c, v in zip(games.is_h2h, games.is_coop, games.is_vs_cpu)
        ])[["display_date", "kind", "home_username", "home_squad", "home_runs",
            "away_runs", "away_squad", "away_username"]]

    if games.empty:
        empty_state("Nothing here yet.", "uv run python -m show_h2h.ingest history")
        st.stop()

    show_table(show, height=420)

    st.subheader("Game detail")
    labels = {}
    for _, gm in games.iterrows():
        date = pretty_date(gm["display_date"])
        if "my_runs" in games.columns:
            res = gm.get("result") or ""
            labels[gm["game_uuid"]] = (f"{date} · {int(gm['my_runs'])}–"
                                       f"{int(gm['their_runs'])} {res}")
        else:
            labels[gm["game_uuid"]] = (f"{date} · {gm['home_username']} "
                                       f"{int(gm['home_runs'])}–{int(gm['away_runs'])} "
                                       f"{gm['away_username']}")
    pick = st.selectbox("Pick a game", list(labels), format_func=lambda k: labels[k])

    innings = q("SELECT * FROM game_innings WHERE game_uuid = ? ORDER BY inning_no", (pick,))
    meta = q("SELECT * FROM games WHERE game_uuid = ?", (pick,))
    if not innings.empty and not meta.empty:
        m = meta.iloc[0]
        line = innings.set_index("inning_no")[["away_runs", "home_runs"]].T
        line.columns = [str(c) for c in line.columns]
        # R/H/E come from the game totals, which stay correct even when the
        # 9-column line score can't hold an extra-inning game.
        line["R"] = [m["away_runs"], m["home_runs"]]
        line["H"] = [m["away_hits"], m["home_hits"]]
        line["E"] = [m["away_errors"], m["home_errors"]]
        line.insert(0, "", [m["away_username"] or "away", m["home_username"] or "home"])
        st.dataframe(line, hide_index=True, width="stretch")
        if (m["innings"] or 0) > 9:
            st.info(f"This game went {int(m['innings'])} innings. The API only ever "
                    f"reports 9 columns, so runs scored in extras are missing from the "
                    f"grid — but the R/H/E totals on the right are correct.")
        if str(m["ruling"]) != "0":
            st.warning("This game ended early (non-zero `ruling`) — most likely a quit "
                       "or disconnect. A winner was still awarded.")

    for side in ("away", "home"):
        b = q("""SELECT player_name, pos, ab, r, h, rbi, bb, so, hr FROM batting_lines
                 WHERE game_uuid = ? AND side = ? ORDER BY slot""", (pick, side))
        p = q("""SELECT player_name, ip_text AS ip, h, r, er, bb, so FROM pitching_lines
                 WHERE game_uuid = ? AND side = ? ORDER BY slot""", (pick, side))
        if b.empty and p.empty:
            continue
        st.markdown(f"**{meta.iloc[0][f'{side}_username'] or side}** — "
                    f"{meta.iloc[0][f'{side}_squad']}")
        c1, c2 = st.columns([3, 2])
        with c1:
            show_table(b)
        with c2:
            show_table(p)

    text = q("SELECT text FROM game_log_text WHERE game_uuid = ?", (pick,))
    if not text.empty:
        with st.expander("Play-by-play"):
            st.text(clean_play_by_play(text.iloc[0]["text"]))
