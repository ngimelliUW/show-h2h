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

# How long the whole run may take, and how long any single network command may
# block. Both are wall-clock, so they still expire across a system sleep.
MAX_RUNTIME=${MAX_RUNTIME:-3600}
NET_TIMEOUT=${NET_TIMEOUT:-180}

# A dropped TCP connection is invisible to ssh unless it is told to probe. On
# 2026-08-02 the Mac slept mid-`git push`; GitHub had already taken the objects,
# but the socket never returned and ssh blocked on read for 28 hours. These make
# it give up after ~a minute of silence instead.
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh} -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o ConnectTimeout=20"

mkdir -p "$LOG_DIR"
exec >> "$LOG" 2>&1

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*"; }
fail() { say "ABORTED — $*"; exit 1; }

# Run a command with a wall-clock deadline. macOS ships no timeout(1), and the
# deadline is compared against date(1) rather than counting sleeps so that time
# spent with the machine asleep still counts against it.
with_timeout() {
  local secs="$1" label="$2"; shift 2
  "$@" &
  local pid=$! deadline=$(( $(date +%s) + secs ))
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      say "TIMEOUT — $label exceeded ${secs}s, killing it"
      kill -TERM "$pid" 2>/dev/null
      sleep 5
      kill -KILL "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      return 124
    fi
    sleep 2
  done
  wait "$pid"
}

say "=== nightly refresh starting"
cd "$REPO" || fail "cannot enter $REPO"

# Self-watchdog. launchd will not start a second copy of a job whose label is
# already running, so ONE wedged run silently cancels every night that follows —
# which is exactly what happened after the 08-02 push hung: the 08-03 run never
# fired at all and two days of games went missing with nothing in the log.
# Capping our own lifetime means a stuck run can lose its own night, never the
# next one.
(
  deadline=$(( $(date +%s) + MAX_RUNTIME ))
  while kill -0 $$ 2>/dev/null; do
    [ "$(date +%s)" -ge "$deadline" ] && {
      say "WATCHDOG — run still alive after ${MAX_RUNTIME}s, killing it so tomorrow can run"
      pkill -KILL -P $$ 2>/dev/null
      kill -KILL $$ 2>/dev/null
      exit 0
    }
    sleep 10
  done
) &
WATCHDOG=$!
trap 'kill "$WATCHDOG" 2>/dev/null' EXIT

# A run can leave a commit stranded. On 2026-07-29 this job committed at 06:47
# and the machine slept during `git push`, killing the process before it could
# even log the failure — so the work was done, the site never saw it, and
# nothing said so. Clear any backlog first and the next run heals itself.
with_timeout "$NET_TIMEOUT" "git fetch" git fetch -q origin main 2>/dev/null
behind=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
if [ "${behind:-0}" -gt 0 ]; then
  say "pushing $behind commit(s) stranded by an earlier run"
  if with_timeout "$NET_TIMEOUT" "backlog push" git push -q origin main; then
    say "backlog pushed"
  else
    say "WARNING — backlog still unpushed"
  fi
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
# The season layer decides what the front page says the two of them are playing
# for, and a new game is exactly what moves it. A series that closed on the
# wrong game, or a rotation violation claimed against a legal start, would go
# out unattended otherwise.
uv run python analysis/_seasons_check.py || fail "season derivation failed — NOT publishing"

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
# A timeout here is not the same as a failure: GitHub may well have taken the
# objects before the socket stalled. Say so rather than guessing — the next
# run's backlog push settles it either way.
if ! with_timeout "$NET_TIMEOUT" "git push" git push -q origin main; then
  fail "push did not complete — the commit is local; the next run will push it"
fi

say "published:"
echo "$summary"
say "=== done"
