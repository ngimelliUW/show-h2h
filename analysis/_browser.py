"""End-to-end browser check against a running app.

  uv run streamlit run app/dashboard.py --server.port 8502 --server.headless true &
  uv run --with playwright python analysis/_browser.py [url]

Playwright is deliberately not a project dependency — it's a 90 MB browser
download that the app itself never needs, so it's pulled in per-run with
`--with`.

**The report renders inside an iframe.** `page.on("pageerror")` does not surface
exceptions thrown in a child frame, so a run can report "no errors" while the
page is visibly broken — which is exactly how a crash in renderFeats reached
production. Everything here is asserted against the report's own frame, and
console errors are collected too.
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8502"
# Two levels. The stat tables are nested under STATS, so nothing in the second
# row exists in the DOM as a visible control until the first row selects it.
NAV = ["season", "rules", "stats"]
TABS = ["overview", "matchup", "hitters", "pitchers", "games"]

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


def go(frame, page, section: str, tab: str | None = None) -> None:
    """Select a primary section, and optionally a stat tab beneath it."""
    frame.click(f'#nav button[data-n="{section}"]')
    page.wait_for_timeout(400)
    if tab:
        frame.click(f'#tabs button[data-t="{tab}"]')
        page.wait_for_timeout(400)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for label, viewport, mobile in (("desktop", {"width": 1400, "height": 1000}, False),
                                    ("phone", {"width": 390, "height": 844}, True)):
        page = browser.new_page(viewport=viewport, is_mobile=mobile,
                                device_scale_factor=2 if mobile else 1)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"uncaught: {e}"))
        page.on("console",
                lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(9000 if URL.startswith("http://localhost") else 16000)

        frame = next((f for f in page.frames if f.query_selector("#verdict")), None)
        check(f"[{label}] report frame rendered", frame is not None)
        if not frame:
            page.close()
            continue

        # ---- primary navigation and the two new sections
        check(f"[{label}] primary nav present",
              [b.inner_text().lower() for b in frame.query_selector_all("#nav button")] == NAV)
        check(f"[{label}] season is the landing section",
              frame.evaluate("() => !document.getElementById('tab-season').hidden"))
        check(f"[{label}] stat tabs are hidden until STATS is chosen",
              frame.evaluate("() => document.getElementById('tabs').hidden"))

        check(f"[{label}] season view populated",
              frame.evaluate("() => document.getElementById('season-body').children.length") > 0)
        # The series is drawn as one pip per possible game. No pips means the
        # live series never rendered, which is exactly how the launch state
        # would look if it were broken rather than empty.
        check(f"[{label}] the series strip draws its pips",
              frame.evaluate("() => document.querySelectorAll('#series-strip .dot-pip').length")
              == 2 * frame.evaluate("() => SEASON.current.target"),
              f"first to {frame.evaluate('() => SEASON.current.target')}")
        season_text = frame.evaluate(
            "() => document.getElementById('season-body').innerText").lower()
        check(f"[{label}] the season view names the trophy case and the ladder",
              "trophy case" in season_text and "world series advantage" in season_text)
        check(f"[{label}] the ladder covers every reachable margin",
              frame.evaluate(
                  "() => document.querySelectorAll('#season-body table.ladder tbody tr').length")
              == frame.evaluate("() => Object.keys(SEASON.rules.ladder).length"))
        # No tier is earned until every series is played — at 3-0 with five to
        # go, every rung is still live. A highlighted row mid-season would be
        # claiming an advantage nobody holds yet.
        lit, decided = frame.evaluate("""() => {
            const s = SEASON.live_season || {series: {}};
            const played = Object.values(s.series || {}).reduce((a, b) => a + b, 0);
            return [document.querySelectorAll('#season-body table.ladder tr.live').length,
                    played === SEASON.rules.season_length];
        }""")
        check(f"[{label}] the ladder highlights a tier only once the season is settled",
              (lit > 0) == decided, f"{lit} row(s) lit, season settled={decided}")

        go(frame, page, "rules")
        rules_text = frame.evaluate(
            "() => document.getElementById('rules-body').innerText").lower()
        check(f"[{label}] rules page renders", len(rules_text) > 800, f"{len(rules_text)} chars")
        for phrase in ("series", "world series", "rotation", "home field"):
            check(f"[{label}] rules page covers {phrase}", phrase in rules_text)
        # Numbers on the rules page must come from the payload, not from prose
        # typed alongside it, or the page drifts from the engine it describes.
        length = frame.evaluate("() => SEASON.rules.season_length")
        check(f"[{label}] the rules page states the configured season length",
              f"{length}-series season" in rules_text or f"{length} series" in rules_text,
              f"season_length={length}")

        # ---- everything below is the stat layer, one level down
        go(frame, page, "stats", "overview")
        check(f"[{label}] all stat tabs present",
              [b.inner_text().lower() for b in frame.query_selector_all("#tabs button")]
              == [t.upper().lower() for t in TABS])
        check(f"[{label}] feats populated",
              frame.evaluate("() => document.getElementById('feats').children.length") > 0)
        check(f"[{label}] form populated",
              frame.evaluate("() => document.getElementById('form').children.length") > 0)

        # The head-to-head tables drop any row whose stat is undefined, which is
        # silent: four rows referenced field names the totals object never had
        # and simply never appeared. Compare rendered rows against the
        # definitions rather than trusting the table to complain.
        for tbl, defs in (("cmp-bat", "CMP_BAT"), ("cmp-pit", "CMP_PIT")):
            got, want = frame.evaluate(
                f"() => [document.getElementById('{tbl}').children.length, {defs}.length]")
            missing = frame.evaluate(f"""() => {{
                const t = VIEW.team[viewer]?.{'bat' if tbl == 'cmp-bat' else 'pit'} || {{}};
                return {defs}.filter(([, f]) => t[f] === undefined).map(([l]) => l);
            }}""")
            check(f"[{label}] {tbl} renders every row it defines", got == want,
                  f"{got}/{want}" + (f", missing: {missing}" if missing else ""))
        check(f"[{label}] RBI is in the batting comparison",
              "Runs batted in" in frame.evaluate(
                  "() => document.getElementById('cmp-bat').innerText"))
        # The card labels are upper-cased in CSS, so compare case-insensitively.
        never_text = frame.evaluate(
            "() => document.getElementById('never').innerText").lower()
        check(f"[{label}] the never-done list names grand slams and triple plays",
              all(t in never_text for t in ("grand slam", "triple play")), never_text[:40])
        check(f"[{label}] double plays are in the rarest list",
              "double plays turned" in frame.evaluate(
                  "() => document.getElementById('rarest').innerText").lower())

        for tab in TABS:
            btn = frame.query_selector(f'#tabs button[data-t="{tab}"]')
            if not btn:
                check(f"[{label}] tab {tab} exists", False)
                continue
            btn.click()
            page.wait_for_timeout(600)
            visible = frame.evaluate(
                f"() => !document.getElementById('tab-{tab}').hidden")
            check(f"[{label}] tab {tab} shows", visible)

        # Leaving STATS must put the stat tables away. They used to be shown by
        # tab alone, so a section change left the previous panel on screen under
        # the new heading.
        go(frame, page, "season")
        check(f"[{label}] leaving stats hides every stat panel",
              frame.evaluate("() => TABS.every(([id]) => "
                             "document.getElementById('tab-' + id).hidden)"))
        check(f"[{label}] the window slider is hidden outside stats",
              frame.evaluate("() => document.getElementById('window-row').hidden"))
        go(frame, page, "stats", "overview")
        check(f"[{label}] the window slider returns with stats",
              frame.evaluate("() => !document.getElementById('window-row').hidden"))

        # the you-are switch must mirror the record
        before = frame.query_selector("#verdict").inner_text()
        other = frame.evaluate("() => DATA.players[1]")
        frame.query_selector(f'#whoami button[data-p="{other}"]').click()
        page.wait_for_timeout(600)
        after = frame.query_selector("#verdict").inner_text()
        check(f"[{label}] you-are switch flips the verdict", before != after,
              f"{before!r} -> {after!r}")

        # the window slider must re-derive the record, not just relabel itself
        wide = frame.query_selector("#verdict").inner_text()
        frame.evaluate("""() => { const s = document.getElementById('window-range');
            s.value = 10; s.dispatchEvent(new Event('input', {bubbles: true})); }""")
        page.wait_for_timeout(900)
        narrow = frame.query_selector("#verdict").inner_text()
        check(f"[{label}] window slider changes the record", wide != narrow,
              f"{wide!r} -> {narrow!r}")
        check(f"[{label}] leaderboards survive a narrow window",
              frame.evaluate("() => document.querySelectorAll('#tbl-bat tbody tr').length") > 0,
              "qualifiers must scale with the window")

        # Games that don't count must still be listed and labelled. Silently
        # dropping them would leave the games table shorter than the number of
        # games played, with nothing on the page to explain the difference.
        # Freshness must not depend on the hour it is read at. The original
        # differenced Date.parse("YYYY-MM-DD"), which is UTC midnight, against
        # Date.now() — correct all afternoon and off by one from 7pm Central,
        # once UTC crossed midnight. A single check at whatever time the suite
        # happens to run would have missed it, so this sweeps the clock.
        sweep = frame.evaluate("""() => {
            const at = (d, h) => new Date(2026, 7, d, h, 30);   // August 2026, local
            const hours = [0, 1, 6, 12, 17, 19, 21, 23];
            return {
                sameDay:  hours.map(h => daysAgo('2026-08-03', at(3, h))),
                dayBefore: hours.map(h => daysAgo('2026-08-02', at(3, h))),
                twoBefore: hours.map(h => daysAgo('2026-08-01', at(3, h))),
                acrossDst: daysAgo('2026-11-01', new Date(2026, 10, 2, 23, 30)),
                bad: daysAgo('not-a-date'),
            };
        }""")
        check(f"[{label}] 'today' reads as today at every hour",
              set(sweep["sameDay"]) == {0}, f"got {sweep['sameDay']}")
        check(f"[{label}] 'yesterday' reads as yesterday at every hour",
              set(sweep["dayBefore"]) == {1}, f"got {sweep['dayBefore']}")
        check(f"[{label}] two days ago reads as two at every hour",
              set(sweep["twoBefore"]) == {2}, f"got {sweep['twoBefore']}")
        check(f"[{label}] a 25-hour DST day still counts as one day",
              sweep["acrossDst"] == 1, f"got {sweep['acrossDst']}")
        check(f"[{label}] an unparseable date yields no claim",
              sweep["bad"] is None, f"got {sweep['bad']}")

        # An earlier check left the window slider at 10; put it back to the full
        # span, or this counts rows in a window rather than the whole history.
        frame.evaluate("""() => { const s = document.getElementById('window-range');
            s.value = s.max; s.dispatchEvent(new Event('input', {bubbles: true})); }""")
        page.wait_for_timeout(700)
        frame.query_selector('#tabs button[data-t="games"]').click()
        page.wait_for_timeout(500)
        listed, pills = frame.evaluate("""() => [
            document.querySelectorAll('#tbl-games tbody tr').length,
            [...document.querySelectorAll('#tbl-games .pill')].map(p => p.innerText.trim()),
        ]""")
        played = frame.evaluate("() => DATA.games.length")
        check(f"[{label}] every game played is listed, counting or not",
              listed == played, f"{listed} rows for {played} games")
        voided = frame.evaluate(
            "() => DATA.games.filter(g => g.st === 'no_contest').length")
        check(f"[{label}] games that count for nothing are labelled",
              sum("no contest" in p.lower() for p in pills) == voided,
              f"{voided} no contest(s) in the data")

        frame.query_selector('#tabs button[data-t="overview"]').click()
        page.wait_for_timeout(400)
        # The scoreboard has to reconcile on its face: wins + losses + ties
        # must equal the games count beside them, or the tile looks wrong.
        board = frame.evaluate("""() => {
            const r = record(viewer);
            const tile = [...document.querySelectorAll('.strip-item')]
                .find(e => e.querySelector('.strip-k')?.innerText.trim().toLowerCase() === 'games');
            return {w: r.w, l: r.l, ties: r.ties, voided: r.voided,
                    tile: tile ? +tile.querySelector('.strip-v').innerText.trim() : null};
        }""")
        check(f"[{label}] the scoreboard's own numbers reconcile",
              board["w"] + board["l"] + board["ties"] == board["tile"],
              f"{board['w']}W+{board['l']}L+{board['ties']}T vs Games {board['tile']}"
              f" ({board['voided']} no contest)")

        # The refresh button must SAY what happened. It used to end in
        # st.toast() immediately followed by st.rerun(), and rerun raises at
        # once and discards anything queued for display — so the message never
        # appeared, on success or failure, and a pull that was failing every
        # time looked exactly like one that worked. Only exercised locally:
        # against the deployed app this would crawl the API on every run.
        if URL.startswith("http://localhost") and label == "desktop":
            app = next((f for f in page.frames
                        if f.query_selector(".st-key-refresh")), None)
            check(f"[{label}] the refresh button exists", app is not None)
            if app:
                app.click(".st-key-refresh button", timeout=15_000)
                text = None
                for _ in range(180):
                    page.wait_for_timeout(500)
                    el = app.query_selector('[data-testid="stAlertContainer"], '
                                            '[data-testid="stAlert"]')
                    if el:
                        text = el.inner_text().strip()
                        break
                check(f"[{label}] the refresh button reports its outcome",
                      bool(text), (text or "nothing was shown to the user")[:90])

        # ignore 404s for favicons and similar static noise
        real = [e for e in errors if "Failed to load resource" not in e]
        check(f"[{label}] no JavaScript errors", not real, "; ".join(real[:3]))
        page.close()
    browser.close()

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
