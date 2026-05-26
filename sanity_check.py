#!/usr/bin/env python3
"""Refuse to publish a gutted dataset.

Runs in the daily job AFTER build_network.py and BEFORE encrypt_people.py.
Compares the freshly built counts against the LAST published dataset and exits
non-zero (failing the job, so nothing is encrypted/committed/pushed) if the new
data has shrunk catastrophically — the symptom of a silent API failure (a Ghost
timeout returning a partial list, an empty members file, a Donorbox format shift).

  new counts   <- private/network_stats.json   (written by build_network.py)
  prev counts  <- network/data.enc             (the last good publish, decrypted)

Passphrase from $VC_NETWORK_PASS (same AES-256-GCM / PBKDF2-SHA256 scheme as
encrypt_people.py). If there's no prior data.enc or it can't be decrypted
(first run, rotated passphrase), we pass with a notice rather than block.
"""
import base64, json, os, sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent
STATS = ROOT / "private" / "network_stats.json"
ENC = ROOT / "network" / "data.enc"

# --- thresholds (easy to tune) ---
MAX_DROP = 0.15        # fail if total people OR members fall >15% vs last publish
MEMBERS_FLOOR = 5000   # fail if members fall below this absolute floor (we run ~10.5k)
DONOR_WARN_DROP = 0.25 # donors are noisier/smaller — warn (don't fail) past this


def derive(pw, salt, iters):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                      iterations=iters).derive(pw.encode())


def prev_counts():
    """Decrypt the currently published data.enc and count people/members/donors.
    Returns None if there's no readable baseline (don't block on that)."""
    if not ENC.exists():
        print("sanity_check: no prior network/data.enc — first publish, skipping comparison.")
        return None
    pw = os.environ.get("VC_NETWORK_PASS")
    if not pw:
        print("sanity_check: VC_NETWORK_PASS not set — cannot read baseline, skipping comparison.")
        return None
    try:
        blob = json.loads(ENC.read_text())
        key = derive(pw, base64.b64decode(blob["salt"]), blob.get("iters", 600_000))
        plain = AESGCM(key).decrypt(base64.b64decode(blob["iv"]),
                                    base64.b64decode(blob["ct"]), None)
        people = json.loads(plain)
    except Exception as e:
        print(f"sanity_check: could not decrypt prior data.enc ({e}); skipping comparison.")
        return None
    return {
        "total_people": len(people),
        "members": sum(1 for p in people if p.get("mem")),
        "donors": sum(1 for p in people if p.get("don")),
    }


def main():
    if not STATS.exists():
        sys.exit("sanity_check: private/network_stats.json missing — did build_network.py run?")
    new = json.loads(STATS.read_text())
    new_total = int(new.get("total_people", 0))
    new_members = int(new.get("members", 0))
    new_donors = int(new.get("donors", 0))
    print(f"sanity_check: new build — people={new_total:,} members={new_members:,} donors={new_donors:,}")

    # Absolute floor catches a near-empty publish even with no baseline.
    if new_members < MEMBERS_FLOOR:
        sys.exit(f"ABORT: only {new_members:,} subscribers (floor {MEMBERS_FLOOR:,}). "
                 f"Likely a bad Ghost pull — refusing to publish.")

    prev = prev_counts()
    if prev is None:
        print("sanity_check: PASS (no baseline to compare; floor check passed).")
        return

    print(f"sanity_check: last publish — people={prev['total_people']:,} "
          f"members={prev['members']:,} donors={prev['donors']:,}")

    fail = []
    if prev["total_people"] and new_total < prev["total_people"] * (1 - MAX_DROP):
        fail.append(f"total people {new_total:,} < {(1-MAX_DROP)*100:.0f}% of "
                    f"last {prev['total_people']:,}")
    if prev["members"] and new_members < prev["members"] * (1 - MAX_DROP):
        fail.append(f"subscribers {new_members:,} < {(1-MAX_DROP)*100:.0f}% of "
                    f"last {prev['members']:,}")
    if fail:
        sys.exit("ABORT: dataset shrank unexpectedly — refusing to publish:\n  - "
                 + "\n  - ".join(fail))

    # Donors: warn only.
    if prev["donors"] and new_donors < prev["donors"] * (1 - DONOR_WARN_DROP):
        print(f"sanity_check: WARNING — donors dropped from {prev['donors']:,} to "
              f"{new_donors:,} (>{DONOR_WARN_DROP*100:.0f}%). Publishing anyway; "
              f"check the Donorbox pull.")

    print("sanity_check: PASS — dataset size is within tolerance of the last publish.")


if __name__ == "__main__":
    main()
