#!/usr/bin/env python3
"""Citations shared in the #vc-mentions Slack channel, for the influence summary.

Writes private/slack_mentions.json: one row per link someone posted, with the
date, who posted it, the URL, any passage quoted from the outside source
("quote", safe to print) and any staff comment ("note", internal only).

Two sources, in order:
  1. Live: with SLACK_BOT_TOKEN set (a bot in the channel with channels:history),
     the channel history is read on every nightly build.
  2. Seed: otherwise prospects/slack_mentions.enc, an encrypted snapshot of the
     channel committed to the repo. Refresh it from a machine that can read the
     channel with:  python3 slack_mentions.py --seed path/to/snapshot.json

The seed is encrypted with the toolkit passphrase because the channel carries
staff chatter; the published summary prints only titles, outlets and quotes.
"""
import base64, json, os, re, secrets, sys, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "private" / "slack_mentions.json"
SEED = ROOT / "prospects" / "slack_mentions.enc"
CHANNEL = "C07TAQ5U27P"   # #vc-mentions
OLDEST = "2025-01-01"
ITERS = 600_000


def passphrase():
    p = os.environ.get("VC_NETWORK_PASS")
    if p:
        return p.strip()
    f = ROOT / "private" / ".netpass"
    if f.exists() and f.read_text().strip():
        return f.read_text().strip()
    raise SystemExit("no passphrase: set VC_NETWORK_PASS")


def _key(pw, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERS).derive(pw.encode())


def encrypt(data: bytes) -> dict:
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    ct = AESGCM(_key(passphrase(), salt)).encrypt(iv, data, None)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS, "salt": b(salt), "iv": b(iv), "ct": b(ct)}


def decrypt(blob: dict) -> bytes:
    d = lambda s: base64.b64decode(s)
    return AESGCM(_key(passphrase(), d(blob["salt"]))).decrypt(d(blob["iv"]), d(blob["ct"]), None)


URL = re.compile(r"<(https?://[^|>]+)(?:\|[^>]*)?>")


def parse_message(m, users):
    text = m.get("text") or ""
    urls = [u.replace("&amp;", "&") for u in URL.findall(text)]
    urls = [u for u in urls if "vitalcitynyc.org" not in u and "slack.com/files" not in u]
    if not urls:
        return []
    body = URL.sub(" ", text).replace("&amp;", "&").strip()
    body = re.sub(r"\s+", " ", body)
    # A passage in italics (_..._) or opening with a quotation mark is the
    # outside source's own words; anything else is a staff comment.
    quote, note = "", ""
    q = re.search(r"_(.{40,}?)_", body)
    if q:
        quote = q.group(1).strip()
    elif body[:1] in "\"“":
        quote = body
    else:
        note = body
    ts = datetime.fromtimestamp(float(m["ts"]), timezone.utc).astimezone()
    who = users.get(m.get("user"), "")
    return [{"date": ts.date().isoformat(), "who": who, "url": u, "quote": quote, "note": note} for u in urls[:1]]


def slack(method, token, **params):
    url = f"https://slack.com/api/{method}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    if not d.get("ok"):
        raise RuntimeError(f"Slack {method}: {d.get('error')}")
    return d


def live(token):
    users, cursor = {}, None
    while True:
        d = slack("users.list", token, limit=200, **({"cursor": cursor} if cursor else {}))
        for u in d.get("members", []):
            users[u["id"]] = (u.get("profile") or {}).get("real_name") or u.get("name") or ""
        cursor = (d.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    oldest = datetime.fromisoformat(OLDEST).replace(tzinfo=timezone.utc).timestamp()
    items, cursor = [], None
    while True:
        d = slack("conversations.history", token, channel=CHANNEL, limit=200, oldest=oldest,
                  **({"cursor": cursor} if cursor else {}))
        for m in d.get("messages", []):
            if m.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
                continue
            items.extend(parse_message(m, users))
        cursor = (d.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    # An empty read from a channel that has carried links for two years is a
    # broken token or a bot that was removed, not a quiet channel.
    if not items:
        raise RuntimeError("Slack returned no links from #vc-mentions")
    return {"channel": "vc-mentions", "source": "live", "items": items}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--seed":
        snap = json.loads(Path(sys.argv[2]).read_text())
        if not snap.get("items"):
            raise SystemExit("snapshot has no items")
        SEED.write_text(json.dumps(encrypt(json.dumps(snap, ensure_ascii=False).encode())))
        print(f"wrote {SEED} ({len(snap['items'])} links)")
        return
    data, token = None, os.environ.get("SLACK_BOT_TOKEN", "").strip()
    if token:
        try:
            data = live(token)
        except Exception as e:
            print(f"WARNING: live Slack read failed ({e}); falling back to the committed seed", file=sys.stderr)
    if data is None:
        if not SEED.exists():
            raise SystemExit("no Slack token and no seed; the influence summary will carry feed items only")
        data = json.loads(decrypt(json.loads(SEED.read_text())))
        data["source"] = data.get("source") or "seed"
    data["read_at"] = datetime.now(timezone.utc).isoformat()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"slack mentions: {len(data['items'])} links ({data['source']})")


if __name__ == "__main__":
    main()
