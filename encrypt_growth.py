#!/usr/bin/env python3
"""Encrypt the growth-dashboard data for publishing.

Reads  private/growth.json   (plaintext, gitignored)
Writes growth/data.enc       (AES-256-GCM ciphertext)

Reuses the same passphrase as the contact tool (VC_NETWORK_PASS) so there's
only one shared password to remember.
"""
import base64, json, os, secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent
SRC  = ROOT / "private" / "growth.json"
OUT  = ROOT / "growth" / "data.enc"
ITERS = 600_000

PASS_FILE = ROOT / "private" / ".netpass"


def resolve_passphrase():
    p = os.environ.get("VC_NETWORK_PASS")
    if p: return p.strip()
    if PASS_FILE.exists() and PASS_FILE.read_text().strip():
        return PASS_FILE.read_text().strip()
    raise SystemExit("no passphrase: set VC_NETWORK_PASS or run encrypt_people.py first to seed private/.netpass")


def main():
    data = SRC.read_bytes()
    passphrase = resolve_passphrase()
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERS)
    key = kdf.derive(passphrase.encode())
    ct = AESGCM(key).encrypt(iv, data, None)
    blob = {
        "v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS,
        "salt": base64.b64encode(salt).decode(),
        "iv":   base64.b64encode(iv).decode(),
        "ct":   base64.b64encode(ct).decode(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(blob))
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB encrypted)")


if __name__ == "__main__":
    main()
