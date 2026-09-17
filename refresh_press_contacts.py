#!/usr/bin/env python3
"""Refresh missing press emails from the current encrypted live dataset in CI.

Never rebuild the roster from a laptop snapshot. Plaintext stays in private/;
the separate encrypt_press.py step uses GitHub's existing repository secret.
"""
import json
import os
from datetime import datetime, timezone

import build_press as press


def enrich(payload):
    contacts = press.read_contact_sources(payload["people"])
    added = press.apply_contact_sources(payload["people"], contacts)
    payload["counts"]["with_email"] = sum(bool(p.get("email")) for p in payload["people"])
    if added:
        now = datetime.now(timezone.utc).isoformat()
        payload["report"].setdefault("notes", []).append(
            f"{now}: added {added} published addresses from reviewed contact pages; "
            "the roster and full-harvest timestamp are unchanged.")
    return added


def main():
    passphrase = os.environ["VC_NETWORK_PASS"].strip()
    payload = json.loads(press.decrypt_blob(
        json.loads((press.PRESS / "data.enc").read_text()), passphrase))
    before = payload["counts"]["with_email"]
    added = enrich(payload)
    press.PRIV.mkdir(exist_ok=True)
    (press.PRIV / "press.json").write_text(json.dumps(payload, indent=1))
    print(f"Contact-only refresh: {added} added; {before} -> "
          f"{payload['counts']['with_email']} addresses; "
          f"{len(payload['people'])} people retained.")


if __name__ == "__main__":
    main()
