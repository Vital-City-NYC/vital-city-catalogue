#!/usr/bin/env python3
"""Build the website manual: the toolkit's Manual page and Josh's Desktop PDF.

Source   private/manual/manual.html   (plaintext, gitignored -- edit THIS file)
Writes   manual/data.enc              (encrypted; the Manual page in the toolkit)
         private/manual/manual.pdf    (rendered with headless Chrome)
         ~/Desktop/Vital City website manual.pdf   (a copy for Josh)

Run it after any edit to the source:   python3 build_manual.py
Then commit manual/data.enc and push, like any other tool's data.

What it fills in on every build:
  {{AS_OF}}      today's date in AP style, but only when the source or the live
                 site menu changed since the last build; otherwise the previous
                 date stands (state in private/manual/state.json)
  {{NAV_TABLE}}  the site's top menu, pulled live from the Ghost Content API

The manual carries internal details (contacts, the contributor-address pattern,
admin steps), so the page's content is encrypted with the suite passphrase, the
same scheme as every other tool. A password prompt over public HTML would be
decoration.

Flags:  --no-pdf   skip Chrome (web page only)
"""
import base64, datetime, hashlib, html, json, os, secrets, shutil, subprocess, sys, urllib.request
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "private" / "manual" / "manual.html"
STATE = ROOT / "private" / "manual" / "state.json"
RENDER = ROOT / "private" / "manual" / "_render.html"
PDF = ROOT / "private" / "manual" / "manual.pdf"
DESKTOP_PDF = Path.home() / "Desktop" / "Vital City website manual.pdf"
OUT = ROOT / "manual" / "data.enc"
PASS_FILE = ROOT / "private" / ".netpass"
ITERS = 600_000
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# Ghost's public Content API key: read-only, published content only, and already
# embedded in vitalcitynyc.org's own search widget.
CONTENT_API = ("https://vital-city.ghost.io/ghost/api/content/settings/"
               "?key=dd8e178e9ddfc883537e71dd07")
AP_MON = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.",
          "Sept.", "Oct.", "Nov.", "Dec."]


def ap_date(d):
    return f"{AP_MON[d.month - 1]} {d.day}, {d.year}"


def live_nav():
    with urllib.request.urlopen(CONTENT_API, timeout=60) as r:
        nav = json.load(r)["settings"]["navigation"]
    nav = [[n["label"], n["url"]] for n in nav]
    if len(nav) < 3:  # fail loud: an empty menu means the fetch went wrong
        raise SystemExit(f"live menu came back with {len(nav)} items; refusing to build")
    return nav


def nav_table(nav):
    rows, parent = [], None
    for i, (label, _url) in enumerate(nav):
        is_sub = label.startswith("-")
        nxt_sub = i + 1 < len(nav) and nav[i + 1][0].startswith("-")
        prev_sub = i > 0 and nav[i - 1][0].startswith("-")
        if is_sub:
            shows = f"In the {html.escape(parent or 'top')} dropdown"
            cell = f'<span class="t ty">{html.escape(label)}</span>'
        else:
            if nxt_sub:
                shows = "Top menu, with a dropdown"
            elif prev_sub:
                shows = f"Top menu. It has no hyphen, so the {html.escape(parent)} dropdown ends above it."
            else:
                shows = "Top menu"
            parent = label
            cell = html.escape(label)
        rows.append(f"<tr><td>{cell}</td><td>{shows}</td></tr>\n")
    return "".join(rows)


def passphrase():
    p = os.environ.get("VC_NETWORK_PASS")
    if p:
        return p.strip()
    if PASS_FILE.exists() and PASS_FILE.read_text().strip():
        return PASS_FILE.read_text().strip()
    raise SystemExit("no passphrase: set VC_NETWORK_PASS or seed private/.netpass")


def encrypt(obj):
    data = json.dumps(obj).encode()
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=ITERS).derive(passphrase().encode())
    ct = AESGCM(key).encrypt(iv, data, None)
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS,
            "salt": base64.b64encode(salt).decode(),
            "iv": base64.b64encode(iv).decode(),
            "ct": base64.b64encode(ct).decode()}


def main():
    if not SRC.exists():
        raise SystemExit(f"{SRC} missing")
    src = SRC.read_text()
    for ph in ("{{AS_OF}}", "{{NAV_TABLE}}"):
        if ph not in src:
            raise SystemExit(f"source lost its {ph} placeholder; put it back before building")
    nav = live_nav()

    # The date moves only when something a reader would see has changed.
    digest = hashlib.sha256((src + json.dumps(nav)).encode()).hexdigest()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    today = datetime.date.today()
    if state.get("hash") != digest:
        as_of = ap_date(today)
        state = {"hash": digest, "as_of": as_of, "as_of_iso": today.isoformat()}
        STATE.write_text(json.dumps(state, indent=1))
        print(f"content changed -> dated {as_of}")
    else:
        as_of = state["as_of"]
        print(f"no content change -> keeps date {as_of}")

    filled = src.replace("{{AS_OF}}", as_of).replace("{{NAV_TABLE}}", nav_table(nav))
    if "{{" in filled:
        raise SystemExit("an unfilled {{placeholder}} remains")

    if "--no-pdf" not in sys.argv:
        RENDER.write_text(filled)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--virtual-time-budget=10000", f"--print-to-pdf={PDF}",
                        RENDER.as_uri()], check=True, capture_output=True)
        RENDER.unlink()
        if PDF.stat().st_size < 50_000:
            raise SystemExit(f"PDF looks empty ({PDF.stat().st_size} bytes)")
        shutil.copyfile(PDF, DESKTOP_PDF)
        print(f"PDF -> {DESKTOP_PDF}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(encrypt({
        "v": 1, "as_of": as_of, "as_of_iso": state["as_of_iso"],
        "built": datetime.datetime.now().isoformat(timespec="seconds"),
        "nav": nav, "html": filled})))
    print(f"web -> {OUT} ({OUT.stat().st_size // 1024} KB encrypted). Commit and push it.")


if __name__ == "__main__":
    main()
