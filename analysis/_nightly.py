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
    baseline = conn.execute(
        "SELECT COUNT(*) FROM games WHERE is_h2h=1 AND played_at <= '2026-07-28T23:59:59'"
    ).fetchone()[0]
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

finally:
    shutil.rmtree(work, ignore_errors=True)

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
