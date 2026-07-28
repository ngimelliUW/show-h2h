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

  /* The scoreboard runs edge to edge at the very top, so Streamlit's floating
     toolbar would sit on the dark band with dark text. Hide it — this is a
     viewer-facing app, and the owner still gets "Manage app" bottom-right and
     the full controls on share.streamlit.io. */
  [data-testid="stHeader"] { display: none !important; }

  /* Side padding is pinned so the full-bleed band can use the same value and
     line its contents up with everything below it. */
  .block-container {
    padding-top: 0 !important;
    padding-bottom: 3rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 100% !important;
  }

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

  /* ---------- the scoreboard band ----------
     Full-bleed: escape the centred container by pushing to 100vw and pulling
     back by half. Inner padding matches .block-container so the eyebrow lines
     up with the headings underneath. */
  .st-key-scoreboard {
    /* Full-bleed by cancelling the container's own side padding. Exact, unlike
       the 100vw trick, which overshoots by the scrollbar width. Streamlit pins
       the block to width:100%, so the width has to grow explicitly — negative
       margins alone just slide it left and leave a gap on the right. */
    width: calc(100% + 4rem) !important;
    max-width: none !important;
    flex: 0 0 auto !important;
    margin-left: -2rem;
    margin-right: -2rem;
    background: var(--sb-ground);
    background-image: radial-gradient(ellipse at 50% -40%, var(--sb-ground-2), var(--sb-ground) 62%);
    color: var(--sb-on);
    border-bottom: 3px solid var(--sb-amber);
    padding: 22px 2rem 14px;
    margin-bottom: 18px;
  }
  .st-key-scoreboard p,
  .st-key-scoreboard label,
  .st-key-scoreboard [data-testid="stWidgetLabel"] * { color: var(--sb-on-muted) !important; }

  /* The "you are" toggle sits inside the band, so it has to read on dark. */
  .st-key-scoreboard [data-testid="stButtonGroup"] button {
    background: transparent !important;
    color: var(--sb-on-muted) !important;
    border-color: rgba(255,255,255,.25) !important;
  }
  .st-key-scoreboard [data-testid="stButtonGroup"] button[aria-checked="true"],
  .st-key-scoreboard [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] {
    background: var(--sb-on) !important;
    color: var(--sb-ground) !important;
  }

  /* ---------- page nav: underlined text tabs, not boxed buttons ---------- */
  .st-key-nav [data-testid="stButtonGroup"] button {
    background: transparent !important;
    border: 0 !important;
    border-bottom: 3px solid transparent !important;
    border-radius: 0 !important;
    font-family: var(--sb-display);
    text-transform: uppercase;
    letter-spacing: .1em;
    font-size: 13px;
    color: #5E6C80 !important;
    padding: 10px 14px !important;
    /* Never ellipsise a tab name — "RIVA…" tells the reader nothing. Let the
       strip scroll sideways instead. */
    white-space: nowrap !important;
    flex: 0 0 auto !important;
    min-width: max-content !important;
  }
  .st-key-nav [data-testid="stButtonGroup"] button * {
    overflow: visible !important; text-overflow: clip !important;
    white-space: nowrap !important;
  }
  .st-key-nav [data-testid="stButtonGroup"] button[aria-checked="true"],
  .st-key-nav [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] {
    color: #0F1826 !important;
    border-bottom-color: var(--sb-amber) !important;
  }
  .st-key-nav { border-bottom: 1px solid #D6DDE6; margin-bottom: 10px; }

  /* ---------- comparison: value | label | value ---------- */
  .cmp-card {
    background: #fff; border: 1px solid #D6DDE6; border-radius: 6px; overflow: hidden;
  }
  .cmp-head {
    font-family: var(--sb-display); text-transform: uppercase; letter-spacing: .1em;
    font-size: 11px; color: #5E6C80; padding: 11px 12px; border-bottom: 1px solid #D6DDE6;
  }
  table.cmp { width: 100%; border-collapse: collapse; }
  table.cmp td { padding: 8px 12px; border-bottom: 1px solid #E8ECF2; }
  table.cmp td.k {
    font-family: system-ui, sans-serif; color: #5E6C80; font-size: 13px;
    text-align: center; width: 44%;
  }
  table.cmp td.v {
    font-family: var(--sb-mono); font-variant-numeric: tabular-nums;
    font-size: 15px; width: 28%; color: #0F1826;
  }
  table.cmp td.v.left { text-align: left; }
  table.cmp td.v.right { text-align: right; }
  /* Winner carries that player's colour, the same two used everywhere else. */
  table.cmp td.v.win { font-weight: 700; }
  table.cmp td.v.win.left { color: #1B6CA8; }
  table.cmp td.v.win.right { color: #C8102E; }
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
  /* When the strip shares a row with the toggle it owns the divider, and the
     toggle column needs to line its baseline up with the numbers. */
  .sb-strip-solo { margin-top: 0; }
  .st-key-scoreboard [data-testid="stHorizontalBlock"] { align-items: flex-end; }
  .st-key-scoreboard [data-testid="stVerticalBlock"] { gap: .35rem; }
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
    /* Keep the band flush with the screen edge at the narrower page padding. */
    .st-key-scoreboard {
      width: calc(100% + 1.5rem) !important;
      margin-left: -.75rem !important; margin-right: -.75rem !important;
      padding-left: .75rem !important; padding-right: .75rem !important;
    }
    .st-key-nav [data-testid="stButtonGroup"] { overflow-x: auto; }
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


def cmp_table(title: str, rows: list[tuple[str, str, str, bool, bool]]) -> str:
    """Comparison card: your value, the stat name, their value — winner bolded.

    rows are (left, label, right, left_wins, right_wins).
    """
    body = "".join(
        f'<tr><td class="v left{" win" if lw else ""}">{html.escape(left)}</td>'
        f'<td class="k">{html.escape(label)}</td>'
        f'<td class="v right{" win" if rw else ""}">{html.escape(right)}</td></tr>'
        for left, label, right, lw, rw in rows
    )
    return (f'<div class="cmp-card"><div class="cmp-head">{html.escape(title)}</div>'
            f'<table class="cmp"><tbody>{body}</tbody></table></div>')


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


def strip_only(strip: list[tuple[str, str]]) -> str:
    """The headline-numbers strip on its own, so the 'you are' toggle — a real
    Streamlit widget, which can't live inside injected HTML — can sit beside it
    in a column instead of stacking underneath."""
    cells = "".join(
        f'<div><span class="sb-k">{html.escape(k)}</span>'
        f'<span class="sb-v">{html.escape(str(v))}</span></div>'
        for k, v in strip
    )
    return f'<div class="sb-strip sb-strip-solo">{cells}</div>'


def scoreboard_top(me: str, them: str, wins: int, losses: int,
                   me_color: str, them_color: str) -> str:
    """Everything above the strip: eyebrow, the two names, the score, verdict."""
    full = scoreboard(me, them, wins, losses, [], me_color, them_color)
    return full.split('<div class="sb-strip">')[0] + "</div>"
