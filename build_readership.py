#!/usr/bin/env python3
"""data/readership.enc -- how well each catalogue piece did with readers.

The public catalogue gets a Readers column, but only for someone signed in to
the toolkit: traffic is internal, so the figures ship encrypted with the shared
passphrase and the page shows nothing to anyone without it.

Two figures per piece, from Google Analytics' per-piece index in growth.json:

  views  lifetime page views across every URL the piece has lived at.
  tier   how it did against every other piece in its FIRST 30 DAYS. Lifetime
         views reward age -- a 2023 piece will always out-read a strong piece
         from last month -- so the tier compares debuts. Pieces older than
         Google Analytics' coverage of their debut are tiered on lifetime views
         against pieces published the same year instead, and say so. Pieces
         under 30 days old are not tiered yet.

Tiers: standout (top 5%), strong (next 15%), typical (middle 40%), quiet
(bottom 40%).

The passphrase comes only from VC_NETWORK_PASS. There is no fallback to
private/.netpass, because a stale local key once published unreadable payloads;
this runs in CI, where the secret is set.
"""
import base64, json, os, secrets, sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent
GROWTH = ROOT / "private" / "growth.json"
OUT = ROOT / "data" / "readership.enc"
ITERS = 600_000
TIERS = [(0.95, "standout"), (0.80, "strong"), (0.40, "typical"), (0.0, "quiet")]

def tier_for(pct):
    for floor, name in TIERS:
        if pct >= floor:
            return name
    return "quiet"

def percentiles(values):
    """value -> share of values strictly below it."""
    s = sorted(values)
    n = len(s)
    out = {}
    for i, v in enumerate(s):
        out.setdefault(v, i / n if n else 0)
    return out

def main():
    passphrase = (os.environ.get("VC_NETWORK_PASS") or "").strip()
    if not passphrase:
        sys.exit("VC_NETWORK_PASS not set; refusing to encrypt with anything else")
    g = json.loads(GROWTH.read_text())
    pi = ((g.get("ga4") or {}).get("piece_index") or {})
    pieces = pi.get("pieces") or []
    if len(pieces) < 100:
        sys.exit(f"REFUSING: piece index has {len(pieces)} pieces; fix the growth pull, do not publish a thin column")
    as_of = pi.get("as_of") or date.today().isoformat()
    asof_d = datetime.fromisoformat(as_of[:10]).date()

    debut = [p for p in pieces if p.get("views30") is not None]
    pct30 = percentiles([p["views30"] for p in debut])
    by_year = defaultdict(list)
    for p in pieces:
        by_year[(p.get("pub") or "")[:4]].append(p.get("views") or 0)
    pct_year = {y: percentiles(v) for y, v in by_year.items()}

    out = {}
    for p in pieces:
        pub = (p.get("pub") or "")[:10]
        age = (asof_d - datetime.fromisoformat(pub).date()).days if pub else None
        rec = {"v": p.get("views") or 0, "u": p.get("users") or 0}
        if age is not None and age < 30:
            rec["t"], rec["b"] = None, "new"
        elif p.get("views30") is not None:
            rec["v30"] = p["views30"]
            rec["t"], rec["b"] = tier_for(pct30[p["views30"]]), "debut"
        else:
            rec["t"], rec["b"] = tier_for(pct_year[pub[:4]][p.get("views") or 0]), "year"
        out[p["slug"]] = rec

    payload = json.dumps({"as_of": as_of, "n": len(out), "pieces": out}).encode()
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERS).derive(passphrase.encode())
    b = lambda x: base64.b64encode(x).decode()
    OUT.write_text(json.dumps({"v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS,
                               "salt": b(salt), "iv": b(iv), "ct": b(AESGCM(key).encrypt(iv, payload, None))}))
    counts = defaultdict(int)
    for r in out.values():
        counts[r["t"] or "new"] += 1
    print(f"readership: {len(out)} pieces as of {as_of} -> {OUT} · {dict(counts)}")

if __name__ == "__main__":
    main()
