#!/bin/bash
# Refresh press/harvest_cache.json from this Mac.
#
# Nineteen outlets refuse GitHub's runners (Substack, one shared nonprofit news
# host, The Real Deal), so the nightly CI build cannot read them. This job reads
# them from a residential connection and commits only public material --
# headlines, bylines, profile links, bios. build_press.py refuses to write the
# file if an address gets into it.
#
# It works in its own git worktree, never in the shared working copy other
# sessions edit, so it cannot stash or clobber anyone's uncommitted work.
set -euo pipefail
REPO="/Users/joshgreenman/Experiments/vital-city-catalogue"
WT="/Users/joshgreenman/Experiments/.press-cache-worktree"
LOG="$REPO/private/press_cache_refresh.log"
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M') ==="

cd "$REPO"
git fetch -q origin main
if [ ! -d "$WT" ]; then
  git worktree add -q --detach "$WT" origin/main
fi
cd "$WT"
git checkout -q --detach origin/main
git reset -q --hard origin/main

python3 build_press.py --cache-only

if git diff --quiet -- press/harvest_cache.json; then
  echo "no change"; exit 0
fi
git add press/harvest_cache.json
git -c user.name="Josh Greenman" -c user.email="josh.greenman@gmail.com" \
  commit -q -m "Press map: refresh the Mac harvest for outlets that refuse CI"
gh auth switch --user vitalcity-nyc >/dev/null 2>&1 || true
if git -c credential.helper='!gh auth git-credential' push -q origin HEAD:main; then
  echo "pushed"
else
  echo "WARNING: push failed; the cache will be retried tomorrow and stays valid for 14 days"
fi
