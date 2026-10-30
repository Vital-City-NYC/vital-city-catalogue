#!/usr/bin/env python3
"""Encrypt the toolkit's cross-links -> data/links.enc

Reads  private/links.json  (plaintext, gitignored; build_links.py writes it)
Writes data/links.enc      (AES-256-GCM ciphertext)

Same scheme and same shared passphrase as the growth, contacts, prospects and
catalogue-analysis tools, so there is one password for the whole toolkit.

It is encrypted because it joins names and addresses to the press map,
funders and the Prospects lists. A password prompt in front of public JSON is decoration -- anyone can
request the JSON directly -- so the data itself is encrypted.
"""
import base64, json, os, secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "private" / "links.json"
OUT = ROOT / "data" / "links.enc"
ITERS = 600_000
PASS_FILE = ROOT / "private" / ".netpass"


def resolve_passphrase():
    p = os.environ.get("VC_NETWORK_PASS")
    if p:
        return p.strip()
    if PASS_FILE.exists() and PASS_FILE.read_text().strip():
        return PASS_FILE.read_text().strip()
    raise SystemExit("no passphrase: set VC_NETWORK_PASS or run encrypt_people.py "
                     "first to seed private/.netpass")


def main():
    if not SRC.exists():
        raise SystemExit(f"{SRC} missing — run build_links.py first")
    data = SRC.read_bytes()
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=ITERS).derive(resolve_passphrase().encode())
    ct = AESGCM(key).encrypt(iv, data, None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS,
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "ct": base64.b64encode(ct).decode(),
    }))
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB encrypted)")


if __name__ == "__main__":
    main()
