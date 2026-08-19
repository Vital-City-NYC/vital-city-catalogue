#!/usr/bin/env python3
"""Encrypt private/live.json → live.enc for the live growth PWA.

Same AES-256-GCM / PBKDF2 scheme and the same passphrase as the rest of the
suite, so the app unlocks with the one shared password. Output path defaults
to ./live.enc (the workflow publishes it on the `live` branch, NOT under
growth/ on main — a 20-minute cadence must not spam main or Pages deploys).
"""
import base64, json, os, secrets, sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent
SRC  = ROOT / "private" / "live.json"
OUT  = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "live.enc"
ITERS = 600_000
PASS_FILE = ROOT / "private" / ".netpass"

def resolve_passphrase():
    p = os.environ.get("VC_NETWORK_PASS")
    if p: return p.strip()
    if PASS_FILE.exists() and PASS_FILE.read_text().strip():
        return PASS_FILE.read_text().strip()
    raise SystemExit("no passphrase: set VC_NETWORK_PASS or seed private/.netpass")

def main():
    data = SRC.read_bytes()
    if len(data) < 500:
        raise SystemExit(f"refusing to encrypt a suspiciously small live.json ({len(data)} bytes)")
    passphrase = resolve_passphrase()
    salt = secrets.token_bytes(16); iv = secrets.token_bytes(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERS).derive(passphrase.encode())
    ct = AESGCM(key).encrypt(iv, data, None)
    OUT.write_text(json.dumps({"v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS,
                               "salt": base64.b64encode(salt).decode(),
                               "iv": base64.b64encode(iv).decode(),
                               "ct": base64.b64encode(ct).decode()}))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")

if __name__ == "__main__":
    main()
