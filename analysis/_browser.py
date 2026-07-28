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
TABS = ["overview", "matchup", "hitters", "pitchers", "games"]

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


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

        check(f"[{label}] all tabs present",
              [b.inner_text().lower() for b in frame.query_selector_all("#tabs button")]
              == [t.upper().lower() for t in TABS])
        check(f"[{label}] feats populated",
              frame.evaluate("() => document.getElementById('feats').children.length") > 0)
        check(f"[{label}] form populated",
              frame.evaluate("() => document.getElementById('form').children.length") > 0)

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

        # the you-are switch must mirror the record
        frame.query_selector('#tabs button[data-t="overview"]').click()
        page.wait_for_timeout(400)
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

        # ignore 404s for favicons and similar static noise
        real = [e for e in errors if "Failed to load resource" not in e]
        check(f"[{label}] no JavaScript errors", not real, "; ".join(real[:3]))
        page.close()
    browser.close()

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
