#!/usr/bin/env python3
"""Test every historical /articles/ URL against the live site.

Run before uploading redirects.json to see the damage, and after to confirm the
fix. Reads the URL list from the Google Analytics history in private/growth.json
rather than a hardcoded list, so it stays accurate as more history accumulates.
"""
import json, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://www.vitalcitynyc.org"


def old_urls():
    g = json.loads((ROOT / "private" / "growth.json").read_text()).get("ga4") or {}
    rows = list(g.get("engagement_alltime") or []) + list(g.get("engagement") or [])
    for v in (g.get("engagement_by_year") or {}).values():
        rows += v
    seen = {}
    for r in rows:
        p = (r.get("path") or "").split("?")[0]
        if p.startswith("/articles/"):
            seen[p] = max(seen.get(p, 0), int(r.get("views") or 0))
    return sorted(seen.items(), key=lambda kv: -kv[1])


def status(path):
    try:
        req = urllib.request.Request(BASE + path, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=20).status
    except Exception as e:
        return getattr(e, "code", 0)


def main():
    urls = old_urls()
    if not urls:
        sys.exit("No /articles/ paths found — is private/growth.json present?")
    with ThreadPoolExecutor(max_workers=12) as ex:
        codes = list(ex.map(lambda kv: status(kv[0]), urls))
    ok = [(u, v) for (u, v), c in zip(urls, codes) if c == 200]
    dead = [(u, v, c) for (u, v), c in zip(urls, codes) if c != 200]
    print(f"{len(urls)} historical /articles/ URLs tested")
    print(f"  resolve: {len(ok)}  ({sum(v for _, v in ok):,} views)")
    print(f"  broken:  {len(dead)} ({sum(v for _, v, _ in dead):,} views)")
    for u, v, c in dead[:15]:
        print(f"     {c}  {v:>7,}  {u}")
    sys.exit(1 if dead else 0)


if __name__ == "__main__":
    main()
