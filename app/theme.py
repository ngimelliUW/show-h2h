"""Scoreboard identity for the dashboard: CSS + the header block.

The look is a night-game scoreboard — a dark panel carrying the series score in
condensed uppercase and monospace numerals, over quiet paper-white box scores.
Everything below the panel stays deliberately plain so the header is the only
loud thing on the page.

Kept separate from dashboard.py so the markup and the app logic don't tangle.
"""
from __future__ import annotations

import html

# Colours match .streamlit/config.toml. Player colours are keyed on the fixed
# usernames elsewhere, never on "me"/"them", so they can't swap when the viewer
# switches seats.
HOME_BLUE = "#1B6CA8"
AWAY_RED = "#C8102E"
AMBER = "#E9A825"

CSS = """
<style>
  :root {
    --sb-ground: #0C1522;
    --sb-ground-2: #16223A;
    --sb-amber: #E9A825;
    --sb-on: #E9EEF5;
    --sb-on-muted: #8496AC;
    --sb-display: "Haettenschweiler", "Arial Narrow Bold", "Arial Narrow",
                  "Helvetica Neue", Helvetica, Arial, sans-serif;
    --sb-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
               "Liberation Mono", monospace;
  }

  /* Reclaim most of the very generous default top padding — costly on a phone —
     but keep enough to clear Streamlit's fixed header, or the first widget
     renders underneath the Deploy toolbar and looks like it's missing. */
  .block-container { padding-top: 3.25rem !important; padding-bottom: 3rem !important; }

  h1, h2, h3 {
    font-family: var(--sb-display);
    text-transform: uppercase;
    letter-spacing: .06em;
    text-wrap: balance;
  }
  h2 { font-size: 1.35rem !important; }
  h3 { font-size: 1.1rem !important; }

  /* Numbers read as scoreboard digits wherever they line up in columns. */
  [data-testid="stMetricValue"] {
    font-family: var(--sb-mono);
    font-variant-numeric: tabular-nums;
  }
  [data-testid="stDataFrame"] { font-variant-numeric: tabular-nums; }

  /* ---------- the scoreboard panel ---------- */
  .sb {
    background: var(--sb-ground);
    background-image: radial-gradient(ellipse at 50% -40%, var(--sb-ground-2), var(--sb-ground) 62%);
    color: var(--sb-on);
    border-bottom: 3px solid var(--sb-amber);
    border-radius: 8px;
    padding: 18px 20px 14px;
    margin-bottom: 14px;
  }
  .sb-eyebrow {
    font-family: var(--sb-display); text-transform: uppercase; letter-spacing: .18em;
    font-size: 11px; color: var(--sb-on-muted); margin-bottom: 12px;
  }
  .sb-row {
    display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 14px;
    grid-template-areas: "home score away";
  }
  .sb-team { display: flex; flex-direction: column; gap: 3px; min-width: 0; grid-area: home; }
  .sb-team.right { align-items: flex-end; text-align: right; grid-area: away; }
  .sb-score { grid-area: score; }
  .sb-name {
    font-family: var(--sb-display); text-transform: uppercase; letter-spacing: .03em;
    font-size: clamp(13px, 3.6vw, 30px); font-weight: 700; line-height: 1.05;
    /* Never hyphenate a gamertag mid-word — "LINGUINIEATE / R" reads as a bug. */
    overflow-wrap: normal; word-break: keep-all; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; max-width: 100%;
  }
  .sb-tag {
    font-family: var(--sb-mono); font-size: 10px; letter-spacing: .08em;
    text-transform: uppercase; color: var(--sb-on-muted);
  }
  .sb-swatch { width: 24px; height: 4px; border-radius: 2px; }
  .sb-score { display: flex; align-items: center; gap: clamp(8px, 2.5vw, 16px); }
  .sb-wins {
    font-family: var(--sb-mono); font-variant-numeric: tabular-nums;
    font-size: clamp(30px, 10vw, 62px); font-weight: 700; line-height: 1; letter-spacing: -.02em;
  }
  .sb-wins.lead { color: var(--sb-amber); }
  .sb-dash { font-family: var(--sb-display); font-size: 13px; color: var(--sb-on-muted); }
  .sb-verdict {
    font-family: var(--sb-display); text-transform: uppercase; letter-spacing: .05em;
    font-size: clamp(12px, 3vw, 17px); text-align: center; margin-top: 10px;
  }
  .sb-strip {
    display: flex; flex-wrap: wrap; gap: 10px 20px;
    border-top: 1px solid rgba(255,255,255,.1); margin-top: 12px; padding-top: 11px;
  }
  .sb-k {
    font-family: var(--sb-display); text-transform: uppercase; letter-spacing: .12em;
    font-size: 9px; color: var(--sb-on-muted); display: block;
  }
  .sb-v {
    font-family: var(--sb-mono); font-variant-numeric: tabular-nums;
    font-size: 15px; font-weight: 600;
  }

  /* ---------- phones ---------- */
  @media (max-width: 640px) {
    .block-container { padding-left: .75rem !important; padding-right: .75rem !important; }
    .sb { padding: 14px 14px 12px; border-radius: 6px; }
    /* Three columns can't hold two gamertags and a score on a 390px screen, so
       the score moves onto its own row and the names sit under it — the layout
       an actual scoreboard uses. */
    .sb-row {
      grid-template-columns: 1fr 1fr;
      grid-template-areas: "score score" "home away";
      gap: 4px 10px; justify-items: stretch;
    }
    .sb-score { justify-content: center; margin-bottom: 2px; }
    .sb-strip { gap: 8px 14px; }
    .sb-v { font-size: 13px; }
    h2 { font-size: 1.15rem !important; }
    /* Dense stat tables are unreadable at default size on a phone; they scroll
       horizontally either way, so shrinking gets more columns in per swipe. */
    [data-testid="stDataFrame"] { font-size: 11.5px; }
    /* Segmented controls render as stButtonGroup. Let the nav scroll sideways
       rather than wrapping into a tall stack that pushes content off-screen. */
    [data-testid="stButtonGroup"] { overflow-x: auto; scrollbar-width: none; }
    [data-testid="stButtonGroup"]::-webkit-scrollbar { display: none; }
    [data-testid="stButtonGroup"] > div { flex-wrap: nowrap !important; }
    /* Tap targets: Apple's guidance is ~44px; Streamlit's default is tighter. */
    [data-testid="stButtonGroup"] button { min-height: 42px; }
    [data-testid="stButton"] button { min-height: 44px; }
  }
</style>
"""


def scoreboard(me: str, them: str, wins: int, losses: int, strip: list[tuple[str, str]],
               me_color: str, them_color: str) -> str:
    """The dark panel: who, the series score, and a strip of headline numbers."""
    pct = f"{wins / max(wins + losses, 1):.3f}".lstrip("0")
    if wins > losses:
        verdict = f"You lead {them} {wins}–{losses} ({pct})"
    elif wins < losses:
        verdict = f"You trail {them} {wins}–{losses} ({pct})"
    else:
        verdict = f"You are level with {them} at {wins}–{losses}"

    cells = "".join(
        f'<div><span class="sb-k">{html.escape(k)}</span>'
        f'<span class="sb-v">{html.escape(str(v))}</span></div>'
        for k, v in strip
    )
    return f"""
<div class="sb">
  <div class="sb-eyebrow">MLB The Show 26 · Diamond Dynasty · head to head</div>
  <div class="sb-row">
    <div class="sb-team">
      <span class="sb-swatch" style="background:{me_color}"></span>
      <span class="sb-name">{html.escape(me)}</span>
      <span class="sb-tag">you</span>
    </div>
    <div class="sb-score">
      <span class="sb-wins{' lead' if wins >= losses else ''}">{wins}</span>
      <span class="sb-dash">–</span>
      <span class="sb-wins{' lead' if losses > wins else ''}">{losses}</span>
    </div>
    <div class="sb-team right">
      <span class="sb-swatch" style="background:{them_color}"></span>
      <span class="sb-name">{html.escape(them)}</span>
      <span class="sb-tag">opponent</span>
    </div>
  </div>
  <div class="sb-verdict">{html.escape(verdict)}</div>
  <div class="sb-strip">{cells}</div>
</div>
"""
