#!/usr/bin/env python3
"""Encrypt the catalogue-analysis payload -> catalogue-analysis/data.enc

The page used to fetch data/catalogue_analysis.json and data/subject_analysis.json
as plaintext over the open web. Adding reader and signup counts to it made that
untenable: those are audience and conversion figures, not published editorial
facts. A password prompt in front of public JSON is decoration -- anyone can
request the JSON directly -- so the data itself is encrypted here, with the same
AES-256-GCM + PBKDF2 scheme and the same shared passphrase as the growth,
contacts and prospects dashboards.

The two analysis files stay in data/ because the build writes them there, but
they are gitignored so only the encrypted bundle ships.
"""
import base64, json, os, secrets, subprocess, sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT  = Path(__file__).resolve().parent
OUT   = ROOT / "catalogue-analysis" / "data.enc"
ITERS = 600_000


PASS_FILE = ROOT / "private" / ".netpass"


def resolve_passphrase():
    """Same resolution order as encrypt_growth.py / encrypt_people.py.

    Deliberately identical: an encryptor that reads a different variable name
    silently produces a bundle nobody can open, or fails only in CI where the
    secret is the sole source.
    """
    p = os.environ.get("VC_NETWORK_PASS")
    if p:
        return p.strip()
    if PASS_FILE.exists() and PASS_FILE.read_text().strip():
        return PASS_FILE.read_text().strip()
    try:
        return subprocess.run(["security", "find-generic-password", "-s",
                               "vc-network-pass", "-w"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        sys.exit("no passphrase: set VC_NETWORK_PASS or run encrypt_people.py "
                 "first to seed private/.netpass")


def main():
    payload = {}
    # The two editorial aggregates are derived wholly from the public website
    # and stay in data/ because the growth dashboard reads them too. The reach
    # file is audience data and lives only in private/.
    for key, name, where in (("catalogue", "catalogue_analysis.json", "data"),
                             ("subjects",  "subject_analysis.json",  "data"),
                             ("reach",     "catalogue_reach.json",   "private")):
        f = ROOT / where / name
        if f.exists():
            payload[key] = json.loads(f.read_text())
        elif key != "reach":
            sys.exit(f"missing required input: data/{name}")
        else:
            # Reach is optional: it needs a growth pull, and the catalogue
            # refresh can legitimately run without one.
            print("  note: private/catalogue_reach.json absent — page will hide the reach section")

    data = json.dumps(payload).encode()
    passphrase = resolve_passphrase()
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=ITERS).derive(passphrase.encode())
    ct = AESGCM(key).encrypt(iv, data, None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS,
                               "salt": base64.b64encode(salt).decode(),
                               "iv":   base64.b64encode(iv).decode(),
                               "ct":   base64.b64encode(ct).decode()}))
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB encrypted, "
          f"sections: {', '.join(sorted(payload))})")


if __name__ == "__main__":
    main()
