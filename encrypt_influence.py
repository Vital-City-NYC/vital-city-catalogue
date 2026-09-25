#!/usr/bin/env python3
"""Seal and unseal the influence index's files.

  python3 encrypt_influence.py            private/influence.json     -> influence/data.enc
                                          private/influence_raw.json -> influence/raw.enc
  python3 encrypt_influence.py unpack     influence/raw.enc          -> private/influence_raw.json
                                          network/data.enc           -> private/people.json (if absent)

data.enc is what the page decrypts. raw.enc is the full evidence store (every
counted story, filing, checkpoint and Scholar cell), published encrypted so the
cloud refresh can pick up where the last run stopped instead of re-pulling five
years of history. Same scheme and passphrase as every other toolkit file
(AES-256-GCM, PBKDF2-SHA256 600k), so one shared password opens it all.
"""
import base64, json, os, secrets, sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
ITERS = 600_000
PAIRS = [(PRIV / "influence.json", ROOT / "influence" / "data.enc"),
         (PRIV / "influence_raw.json", ROOT / "influence" / "raw.enc")]


def passphrase():
    p = os.environ.get("VC_NETWORK_PASS")
    if p:
        return p.strip()
    f = PRIV / ".netpass"
    if f.exists() and f.read_text().strip():
        return f.read_text().strip()
    raise SystemExit("no passphrase: set VC_NETWORK_PASS or seed private/.netpass")


def key_for(pw, salt, iters=ITERS):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters).derive(pw.encode())


def seal(src, out, pw):
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    ct = AESGCM(key_for(pw, salt)).encrypt(iv, src.read_bytes(), None)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS,
                               "salt": base64.b64encode(salt).decode(),
                               "iv": base64.b64encode(iv).decode(),
                               "ct": base64.b64encode(ct).decode()}))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB encrypted)")


def unseal(src, out, pw):
    blob = json.loads(src.read_text())
    key = key_for(pw, base64.b64decode(blob["salt"]), blob.get("iters", ITERS))
    plain = AESGCM(key).decrypt(base64.b64decode(blob["iv"]), base64.b64decode(blob["ct"]), None)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(plain)
    print(f"unpacked {src} -> {out}")


def main():
    pw = passphrase()
    if len(sys.argv) > 1 and sys.argv[1] == "unpack":
        raw_enc = ROOT / "influence" / "raw.enc"
        if raw_enc.exists():
            unseal(raw_enc, PRIV / "influence_raw.json", pw)
        people = PRIV / "people.json"
        if not people.exists() and (ROOT / "network" / "data.enc").exists():
            unseal(ROOT / "network" / "data.enc", people, pw)
        return
    for src, out in PAIRS:
        if src.exists():
            seal(src, out, pw)


if __name__ == "__main__":
    main()
