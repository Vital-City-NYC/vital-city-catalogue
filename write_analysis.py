#!/usr/bin/env python3
"""Publish the weekly written summaries for the growth dashboard's reports.

Takes a JSON file of the form
  {"written_at": "2026-09-29", "items": {"weeks:7": {"end": "2026-09-27",
   "period": "...", "text": "..."}, ...}}
(keys are "<weeks|days>:<7|28|56|91|ytd>", matching the report views) and
writes growth/analysis.enc, encrypted with the dashboard passphrase the same
way as the rest of the growth data. The dashboard shows each paragraph at the
top of its view, only with the period it was written about.

  python3 write_analysis.py path/to/analysis.json
Passphrase: $VC_NETWORK_PASS, else the macOS Keychain item vc-network-pass.
"""
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not os.environ.get("VC_NETWORK_PASS"):
    os.environ["VC_NETWORK_PASS"] = subprocess.check_output(
        ["/usr/bin/security", "find-generic-password", "-s", "vc-network-pass", "-w"]).decode().strip()
sys.path.insert(0, str(ROOT))
from slack_mentions import encrypt  # same AES-GCM/PBKDF2 scheme as growth/data.enc

def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    a = json.loads(Path(sys.argv[1]).read_text())
    items = a.get("items") or {}
    if not items:
        raise SystemExit("no items: nothing to publish")
    for k, v in items.items():
        if not (v.get("text") and v.get("end")):
            raise SystemExit(f"{k}: every item needs text and end")
    out = ROOT / "growth" / "analysis.enc"
    out.write_text(json.dumps(encrypt(json.dumps(a, ensure_ascii=False).encode())))
    print(f"wrote {out} ({len(items)} summaries, written {a.get('written_at')})")

if __name__ == "__main__":
    main()
