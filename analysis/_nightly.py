"""Rehearse the nightly refresh exactly as CI runs it, in a throwaway copy.

The job runs unattended and commits to main, so the failure modes that matter
are the silent ones: a half-failed crawl publishing fewer games, a verification
gate that can never pass, a "nothing changed" run committing anyway. This drives
the real commands against a scratch clone and asserts each of those.

Run:  uv run python analysis/_nightly.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


def run(*args, cwd: Path, expect: int | None = 0) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(cwd / "src")}
    proc = subprocess.run([sys.executable, "-m", "show_h2h.ingest", *args],
                          cwd=cwd, capture_output=True, text=True, env=env)
    if expect is not None and proc.returncode != expect:
        print(f"    ({' '.join(args)} exited {proc.returncode})")
        print("   ", (proc.stdout or proc.stderr)[-400:])
    return proc


def gate(cwd: Path, script: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(cwd / "src")}
    return subprocess.run([sys.executable, f"analysis/{script}"],
                          cwd=cwd, capture_output=True, text=True, env=env)


work = Path(tempfile.mkdtemp(prefix="nightly-"))
sandbox = work / "repo"
# Copy only what the job needs; the real checkout has no data/show.db either.
shutil.copytree(ROOT, sandbox, ignore=shutil.ignore_patterns(
    ".git", ".venv", "dist", "__pycache__", "*.db-wal", "*.db-shm", "show.db"))
(sandbox / "data" / "show.db").unlink(missing_ok=True)

try:
    print(f"sandbox: {sandbox}\n")

    # --- the job's own steps -------------------------------------------------
    check("a fresh checkout has no working database",
          not (sandbox / "data" / "show.db").exists())
    check("but it does ship a seed", (sandbox / "data" / "seed.db").exists())

    shutil.copy2(sandbox / "data" / "seed.db", sandbox / "data" / "show.db")
    before = json.loads(run("counts", cwd=sandbox).stdout)
    check("seeding gives the job the existing history", before["games"] > 0,
          f"{before['games']} games")

    refresh = run("refresh", cwd=sandbox)
    check("refresh succeeds against the live API", refresh.returncode == 0,
          (refresh.stdout or "").strip().splitlines()[-1] if refresh.stdout else "")
    run("parse-logs", cwd=sandbox)
    after = json.loads(run("counts", cwd=sandbox).stdout)

    check("refresh never loses rows",
          all(after[t] >= before[t] for t in before),
          ", ".join(f"{t} {before[t]}->{after[t]}" for t in before if after[t] != before[t])
          or "identical")

    changed = before != after
    print(f"    (this run {'found new games' if changed else 'found nothing new'})")

    # --- the gates -----------------------------------------------------------
    v = gate(sandbox, "_verify.py")
    check("verification passes on refreshed data", v.returncode == 0,
          [l for l in (v.stdout or "").splitlines() if l.startswith("FAIL")][:2] or "")
    f = gate(sandbox, "_flip.py")
    check("perspective mirror passes", f.returncode == 0)

    # Assert the baseline before the deliberate damage below, or this reads a
    # database this test broke on purpose.
    conn = sqlite3.connect(sandbox / "data" / "show.db")
    # Cut on the API's own UTC date, not played_at. played_at is local now, and
    # the conversion slides three late-evening games back across a midnight —
    # which made this fixed historical count read 114.
    baseline = conn.execute("""
        SELECT COUNT(*) FROM games WHERE is_h2h = 1
          AND substr(display_date, 7, 4) || '-' || substr(display_date, 1, 2)
              || '-' || substr(display_date, 4, 2) <= '2026-07-28'
    """).fetchone()[0]
    total_h2h = conn.execute("SELECT COUNT(*) FROM games WHERE is_h2h=1").fetchone()[0]
    conn.close()
    check("the baseline is asserted as a prefix, not a total", baseline == 111,
          f"{baseline} on or before 2026-07-28, {total_h2h} in total")
    check("new games land after the baseline, not inside it", total_h2h >= baseline,
          f"{total_h2h - baseline} played since the backfill")

    snap = run("snapshot", cwd=sandbox)
    check("snapshot publishes", snap.returncode == 0,
          (snap.stdout or "").strip()[:90])
    s = gate(sandbox, "_smoke.py")
    check("smoke passes after publishing", s.returncode == 0,
          [l for l in (s.stdout or "").splitlines() if l.startswith("FAIL")][:2] or "")

    # --- the failure modes that matter ---------------------------------------
    # A crawl that dies halfway must not publish a smaller database over a good one.
    conn = sqlite3.connect(sandbox / "data" / "show.db")
    conn.execute("DELETE FROM games WHERE game_uuid IN (SELECT game_uuid FROM games LIMIT 5)")
    conn.commit(); conn.close()
    damaged = run("snapshot", cwd=sandbox, expect=1)
    check("a shrunken database is refused", damaged.returncode == 1,
          (damaged.stdout or "").splitlines()[0] if damaged.stdout else "")
    check("the published seed survives the refusal",
          json.loads(run("counts", cwd=sandbox).stdout)["games"]
          < sqlite3.connect(sandbox / "data" / "seed.db")
              .execute("SELECT COUNT(*) FROM games").fetchone()[0],
          "seed still has the full set")

    # ...unless someone explicitly says so.
    forced = run("snapshot", "--force", cwd=sandbox)
    check("--force overrides the guard", forced.returncode == 0)

    # And the gate must actually catch corrupted data, or it is decoration. The
    # database is short 5 games now, so the prefix assertion should fail.
    broken = gate(sandbox, "_verify.py")
    check("verification FAILS on a damaged database", broken.returncode != 0,
          "the gate would have blocked this commit")

    # --- the job must not be able to wedge the schedule ------------------------
    # launchd will not start a second copy of a job whose label is already
    # running, so a single hung run cancels every night after it — which is how
    # 2026-08-03 was lost. These assert the guards against that, against the real
    # script rather than a copy, since a copy is free to drift.
    script = (ROOT / "scripts" / "nightly-refresh.sh").read_text()

    body, taking = [], False
    for line in script.splitlines():
        if line.startswith("with_timeout() {"):
            taking = True
        if taking:
            body.append(line)
            if line == "}":
                break
    check("with_timeout is defined in the script", bool(body) and body[-1] == "}",
          f"{len(body)} lines extracted")

    harness = "\n".join([
        "set -uo pipefail", 'say() { :; }', *body,
        # a command that finishes returns its own status, success or failure
        'with_timeout 10 quick true || exit 91',
        'with_timeout 10 quick bash -c "exit 3"; [ $? -eq 3 ] || exit 92',
        # the case that actually happened: a command that never returns
        'start=$(date +%s)',
        'with_timeout 3 hang sleep 300; [ $? -eq 124 ] || exit 93',
        '[ $(( $(date +%s) - start )) -lt 30 ] || exit 94',
        # and it must be killed, not orphaned to run forever
        'pgrep -f "sleep 300" >/dev/null && exit 95',
        'exit 0',
    ])
    t = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    reason = {91: "a fast success did not return 0",
              92: "the wrapped command's exit status was swallowed",
              93: "a hang did not return 124", 94: "a hang was not killed promptly",
              95: "the killed child was left running"}
    check("with_timeout kills a hang and preserves real exit statuses",
          t.returncode == 0, reason.get(t.returncode, ""))

    check("a stalled ssh connection is made to time out",
          "ServerAliveInterval" in script and "GIT_SSH_COMMAND" in script,
          "git push blocked for 28h on 08-02 without this")
    check("the run caps its own lifetime", "WATCHDOG" in script and "MAX_RUNTIME" in script,
          "so a stuck run loses its own night, not the next one")
    # Every git call that touches the network must go through with_timeout. Match
    # on "contains", not "starts with" — these lines begin with `if` or the
    # wrapper itself, so an anchored test would pass on an empty set and assert
    # nothing at all.
    bare = [l.strip() for l in script.splitlines()
            if ("git push" in l or "git fetch" in l)
            and not l.strip().startswith("#") and "with_timeout" not in l]
    check("every network command is wrapped", not bare,
          f"unwrapped: {bare}" if bare else "no bare git push/fetch left")

    # The installed copy is what actually runs; the tracked copy is what survives
    # a rebuild. Drift between them means the fix exists only in one place.
    installed = Path.home() / "Library/LaunchAgents/com.show-h2h.nightly-refresh.plist"
    tracked = ROOT / "scripts" / "com.show-h2h.nightly-refresh.plist"
    if installed.exists():
        check("the installed plist matches the tracked one",
              installed.read_text() == tracked.read_text(),
              "cp scripts/*.plist ~/Library/LaunchAgents/ if this fails")
        check("the job runs under caffeinate", "caffeinate" in installed.read_text(),
              "or the Mac sleeps mid-run, as it did on 08-02")

finally:
    shutil.rmtree(work, ignore_errors=True)

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
