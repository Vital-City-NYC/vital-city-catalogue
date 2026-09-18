#!/usr/bin/env python3
"""Encrypt the people dataset for the password-protected network explorer.

Reads  private/people.json   (plaintext, gitignored)
Writes network/data.enc      (AES-256-GCM ciphertext — safe to publish)

The passphrase is taken from $VC_NETWORK_PASS if set, otherwise a strong one is
generated. The passphrase is printed once and NEVER written to disk or git.
Share it with coworkers out-of-band; rotate by re-running with a new value.
"""
import base64, json, os, secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "private" / "people.json"
OUT = ROOT / "network" / "data.enc"
ITERS = 600_000

WORDS = ("amber anchor atlas basin beacon birch borough bridge canyon cedar cipher "
         "cobalt copper cyan delta ember falcon fjord garnet harbor hazel indigo ivory "
         "jasper kelp lantern lattice lumen maple meadow mica north onyx opal orchard "
         "pewter quartz quill raven ridge river saffron slate spruce summit tundra umber "
         "vault verde willow zephyr").split()


def make_passphrase():
    return "-".join(secrets.choice(WORDS) for _ in range(5))


NETPASS = ROOT / "private" / ".netpass"


def resolve_passphrase():
    """Stable passphrase so re-publishing doesn't change the shared password:
    $VC_NETWORK_PASS  >  private/.netpass  >  freshly generated (then saved)."""
    p = os.environ.get("VC_NETWORK_PASS")
    if p:
        return p, "env"
    if NETPASS.exists() and NETPASS.read_text().strip():
        return NETPASS.read_text().strip(), "file"
    p = make_passphrase()
    NETPASS.parent.mkdir(parents=True, exist_ok=True)
    NETPASS.write_text(p)
    return p, "generated"


# The content catalogue shows a contributor's contact details beside their
# pieces. It is a public page, so it gets a small separate payload holding only
# contributors and only the fields a contact panel needs, sealed with the same
# passphrase, instead of pulling the 15 MB people file for one card.
AUTHORS_OUT = ROOT / "network" / "authors.enc"
AUTHOR_FIELDS = ("aname", "n", "e", "emails", "inst", "role", "types", "topics", "arts",
                 "alast", "mem", "since", "don", "senior", "wiki", "ptw")


def seal(data, passphrase):
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERS)
    key = kdf.derive(passphrase.encode())
    ct = AESGCM(key).encrypt(iv, data, None)
    return {
        "v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS,
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "ct": base64.b64encode(ct).decode(),
    }


def write_authors(data, passphrase):
    people = json.loads(data)
    authors = [{k: p[k] for k in AUTHOR_FIELDS if p.get(k) not in (None, "", [], 0)}
               for p in people if p.get("auth")]
    if not authors:
        raise SystemExit("encrypt_people: no contributors in people.json; refusing to write an empty authors.enc")
    AUTHORS_OUT.write_text(json.dumps(seal(json.dumps(authors, ensure_ascii=False).encode(), passphrase)))
    print(f"Wrote {AUTHORS_OUT} ({len(authors)} contributors, {AUTHORS_OUT.stat().st_size//1024} KB encrypted)")


def main():
    data = SRC.read_bytes()
    passphrase, source = resolve_passphrase()

    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERS)
    key = kdf.derive(passphrase.encode())
    ct = AESGCM(key).encrypt(iv, data, None)

    blob = {
        "v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS,
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "ct": base64.b64encode(ct).decode(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(blob))
    print(f"Wrote {OUT} ({OUT.stat().st_size//1024} KB encrypted)")
    write_authors(data, passphrase)
    if source == "generated":
        print("\n" + "=" * 52)
        print("  NEW PASSPHRASE (saved to private/.netpass; share out-of-band):")
        print(f"      {passphrase}")
        print("=" * 52)
    else:
        print(f"  (reused passphrase from {source}; unchanged)")


if __name__ == "__main__":
    main()
