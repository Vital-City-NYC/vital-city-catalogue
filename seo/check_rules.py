#!/usr/bin/env python3
"""Refuse a redirects.json in which any rule can match its own target, or the
live feed path. This is the check that was missing when an unanchored "/rss"
rule matched "/commentary/rss/" and sent the feed into an infinite redirect.
Run before uploading."""
import json, re, sys
rules=json.load(open(sys.argv[1] if len(sys.argv)>1 else "seo/redirects.json"))
bad=[r["from"] for r in rules if re.search(r["from"], r["to"])]
feed=[r["from"] for r in rules if re.search(r["from"], "/commentary/rss/")]
if bad:  print("LOOP: rule matches its own target:", bad)
if feed: print("DANGER: rule would catch the live feed path:", feed)
print("ok" if not (bad or feed) else "REFUSE"); sys.exit(1 if (bad or feed) else 0)
