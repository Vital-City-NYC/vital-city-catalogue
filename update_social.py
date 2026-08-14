#!/usr/bin/env python3
"""Record a follower count for a login-walled platform (X, Instagram, Facebook).

    python3 update_social.py x 4484
    python3 update_social.py instagram 765 --asof 2026-08-14

Appends one row to data/social_history.json (idempotent per platform+date) and
updates the MANUAL_FOLLOWERS block in growth_pull.py so the next nightly run
carries the new number. Commit and push after running, or let the next session
do it. LinkedIn and Bluesky never need this — they are fetched live nightly.
"""
import json, re, sys, argparse
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("platform", choices=["x", "instagram", "facebook"])
ap.add_argument("count", type=lambda s: int(s.replace(",", "")))
ap.add_argument("--asof", default=date.today().isoformat())
a = ap.parse_args()

hp = ROOT / "data" / "social_history.json"
h = json.load(open(hp))
h["rows"] = [r for r in h["rows"] if not (r["p"] == a.platform and r["d"] == a.asof)]
h["rows"].append({"d": a.asof, "p": a.platform, "n": a.count, "src": "manual"})
h["rows"].sort(key=lambda r: (r["d"], r["p"]))
json.dump(h, open(hp, "w"), indent=1)

gp = ROOT / "growth_pull.py"
s = gp.read_text()
pat = rf'"{a.platform}":\s*{{"followers": \d+,\s*"as_of": "[0-9-]+"}}'
new = f'"{a.platform}":         {{"followers": {a.count}, "as_of": "{a.asof}"}}'
if re.search(pat, s):
    s = re.sub(pat, new, s, count=1)
    gp.write_text(s)
    print(f"{a.platform}: {a.count:,} as of {a.asof} — history + growth_pull updated")
else:
    print(f"{a.platform}: {a.count:,} as of {a.asof} — history updated "
          f"(no MANUAL_FOLLOWERS entry in growth_pull.py for this platform; add one if it should feed the dashboard)")
