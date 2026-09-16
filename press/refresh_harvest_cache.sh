#!/bin/bash
# Weekly: read, from this Mac, the outlets that refuse GitHub's servers.
#
# The press map rebuilds nightly on GitHub, and nineteen outlets turn GitHub
# away (every Substack, one host several nonprofit newsrooms share, The Real
# Deal). This visits them from a home connection and hands two files to the
# nightly build:
#
#   press/harvest_cache.json   headlines, bylines, profile links, bios. Public,
#                              so it can sit in the public repository; the build
#                              refuses to write it if an address gets in.
#   press/blocked_contacts.enc the ~36 addresses found at those outlets, locked
#                              with the toolkit passphrase. Written only after
#                              the passphrase proves it opens a payload GitHub
#                              itself locked -- so a stale key can never ship.
#
# Runs in its own git worktree, never in the working copy other sessions edit.
# First run: from Terminal, so macOS can ask whether this may use the Keychain
# passphrase. Click "Always Allow"; the weekly runs then happen unattended.
set -euo pipefail
REPO="/Users/joshgreenman/Experiments/vital-city-catalogue"
WT="$HOME/.vital-city/press-cache-worktree"   # outside ~/Experiments, which is its own repo
LOG="$REPO/private/press_cache_refresh.log"
if [ -t 1 ]; then exec > >(tee -a "$LOG") 2>&1; else exec >>"$LOG" 2>&1; fi
echo "=== $(date '+%Y-%m-%d %H:%M') ==="

cd "$REPO"
git fetch -q origin main
mkdir -p "$(dirname "$WT")"
[ -d "$WT" ] || git worktree add -q --detach "$WT" origin/main
cd "$WT"
git checkout -q --detach origin/main
git reset -q --hard origin/main

# The passphrase lives in the Keychain entry the toolkit already uses. It goes
# to the build in the environment of this one process and is never written down.
if VC_NETWORK_PASS="$(security find-generic-password -s vc-network-pass -w 2>/dev/null)"; then
  export VC_NETWORK_PASS
else
  echo "No Keychain entry vc-network-pass: headlines will refresh, addresses will not."
fi

python3 build_press.py --cache-only
unset VC_NETWORK_PASS

git add press/harvest_cache.json
[ -f press/blocked_contacts.enc ] && git add press/blocked_contacts.enc
if git diff --cached --quiet; then echo "no change"; exit 0; fi
git -c user.name="Josh Greenman" -c user.email="josh.greenman@gmail.com" \
  commit -q -m "Press map: weekly Mac harvest for the outlets that refuse GitHub"
gh auth switch --user vitalcity-nyc >/dev/null 2>&1 || true
if git -c credential.helper='!gh auth git-credential' push -q origin HEAD:main; then
  echo "pushed"
else
  echo "WARNING: push failed. Nothing is lost: the files stay valid for two weeks and next week's run tries again."
fi
