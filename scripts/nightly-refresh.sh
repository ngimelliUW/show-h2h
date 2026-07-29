#!/bin/bash
# Pull new games, verify them, publish the seed, push.
#
# This runs on a Mac rather than in CI because the Show API returns 403 to
# GitHub's runners — every User-Agent, so it's the datacenter IP range, not the
# client. A laptop's connection is the only one that can reach it.
#
# Scheduled by ~/Library/LaunchAgents/com.show-h2h.nightly-refresh.plist at
# 02:00 local. The machine is on America/Chicago and launchd follows DST, so
# that stays 2am Central without the twice-a-year drift a UTC cron would have.
#
# Safe to run by hand at any time; it publishes nothing unless the data changed
# and every check passed.

set -uo pipefail

REPO="/Users/Nic/projects/show-h2h"
LOG_DIR="$HOME/Library/Logs/show-h2h"
LOG="$LOG_DIR/refresh.log"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$LOG_DIR"
exec >> "$LOG" 2>&1

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*"; }
fail() { say "ABORTED — $*"; exit 1; }

say "=== nightly refresh starting"
cd "$REPO" || fail "cannot enter $REPO"

# A run can leave a commit stranded. On 2026-07-29 this job committed at 06:47
# and the machine slept during `git push`, killing the process before it could
# even log the failure — so the work was done, the site never saw it, and
# nothing said so. Clear any backlog first and the next run heals itself.
git fetch -q origin main 2>/dev/null
behind=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
if [ "${behind:-0}" -gt 0 ]; then
  say "pushing $behind commit(s) stranded by an earlier run"
  git push -q origin main && say "backlog pushed" || say "WARNING — backlog still unpushed"
fi

# Don't fight a dirty tree; a half-finished edit shouldn't be committed by a
# background job.
if ! git diff --quiet -- data/seed.db; then
  fail "data/seed.db already has uncommitted changes — resolve by hand"
fi

before=$(uv run python -m show_h2h.ingest counts) || fail "cannot read the database"
say "before: $before"

uv run python -m show_h2h.ingest refresh || fail "refresh failed (API unreachable?)"
uv run python -m show_h2h.ingest parse-logs || fail "play-by-play parse failed"

after=$(uv run python -m show_h2h.ingest counts) || fail "cannot read the database"
say "after:  $after"

if [ "$before" = "$after" ]; then
  say "no new games — nothing to publish"
  say "=== done"
  exit 0
fi

# Gates. Publishing wrong data unattended is worse than publishing nothing.
uv run python analysis/_verify.py || fail "verification failed — NOT publishing"
uv run python analysis/_flip.py   || fail "perspective mirror failed — NOT publishing"

# snapshot refuses to overwrite with a database that lost rows.
uv run python -m show_h2h.ingest snapshot || fail "snapshot refused — NOT publishing"
uv run python analysis/_smoke.py || fail "smoke failed after publishing — NOT committing"

git add data/seed.db
if git diff --cached --quiet; then
  say "seed unchanged after all — nothing to commit"
  say "=== done"
  exit 0
fi

summary=$(uv run python -m show_h2h.ingest status)
git -c user.name="show-h2h nightly" -c user.email="nicgimelli@gmail.com" \
    commit -q -m "Nightly refresh $(date '+%Y-%m-%d')" -m "$summary" || fail "commit failed"
git push -q origin main || fail "push failed"

say "published:"
echo "$summary"
say "=== done"
