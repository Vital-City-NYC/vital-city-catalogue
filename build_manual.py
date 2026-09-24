#!/usr/bin/env python3
"""Build the staff manuals: the toolkit's Manuals pages and Josh's Desktop PDFs.

  website     private/manual/manual.html      -> manual/data.enc
              ~/Desktop/Vital City website manual.pdf
  newsletter  private/manual/newsletter.html  -> newsletter-manual/data.enc
              ~/Desktop/Vital City newsletter manual.pdf

Sources are plaintext and gitignored -- edit THOSE files, never the output.
Run after any edit:   python3 build_manual.py            (both)
                      python3 build_manual.py newsletter (just one)
Then commit the data.enc files and push, like any other tool's data.

What it fills in on every build:
  {{AS_OF}}      today's date in AP style, but only when the source (or, for the
                 website manual, the live site menu) changed since the last
                 build; otherwise the previous date stands
                 (state in private/manual/state.json, one entry per manual)
  {{NAV_TABLE}}  website manual only: the site's top menu, from the Ghost API
  {{TOC}}        the contents list, from the manual's own h2 headings

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
MAN = ROOT / "private" / "manual"
STATE = MAN / "state.json"
DOCS = {
    "website":    {"src": MAN / "manual.html", "out": ROOT / "manual" / "data.enc",
                   "pdf": "Vital City website manual.pdf", "nav": True},
    "newsletter": {"src": MAN / "newsletter.html", "out": ROOT / "newsletter-manual" / "data.enc",
                   "pdf": "Vital City newsletter manual.pdf", "nav": False},
}
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


def toc(html_src):
    import re
    heads = [h for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html_src)
             if "{{" not in h]
    return "".join(f"<li>{h}</li>" for h in heads)


def build(key, cfg, states):
    src_path = cfg["src"]
    if not src_path.exists():
        raise SystemExit(f"{src_path} missing")
    src = src_path.read_text()
    need = ["{{AS_OF}}"] + (["{{NAV_TABLE}}"] if cfg["nav"] else [])
    for ph in need:
        if ph not in src:
            raise SystemExit(f"{key}: source lost its {ph} placeholder; put it back before building")
    nav = live_nav() if cfg["nav"] else []

    # The date moves only when something a reader would see has changed.
    digest = hashlib.sha256((src + json.dumps(nav)).encode()).hexdigest()
    state = states.get(key, {})
    today = datetime.date.today()
    if state.get("hash") != digest:
        state = {"hash": digest, "as_of": ap_date(today), "as_of_iso": today.isoformat()}
        states[key] = state
        print(f"{key}: content changed -> dated {state['as_of']}")
    else:
        print(f"{key}: no content change -> keeps date {state['as_of']}")
    as_of = state["as_of"]

    filled = src.replace("{{AS_OF}}", as_of).replace("{{TOC}}", toc(src))
    if cfg["nav"]:
        filled = filled.replace("{{NAV_TABLE}}", nav_table(nav))
    if "{{" in filled:
        raise SystemExit(f"{key}: an unfilled {{{{placeholder}}}} remains")

    if "--no-pdf" not in sys.argv:
        render, pdf = MAN / f"_render_{key}.html", MAN / f"{key}.pdf"
        render.write_text(filled)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--virtual-time-budget=10000", f"--print-to-pdf={pdf}",
                        render.as_uri()], check=True, capture_output=True)
        render.unlink()
        if pdf.stat().st_size < 50_000:
            raise SystemExit(f"{key}: PDF looks empty ({pdf.stat().st_size} bytes)")
        shutil.copyfile(pdf, Path.home() / "Desktop" / cfg["pdf"])
        print(f"{key}: PDF -> ~/Desktop/{cfg['pdf']}")

    out = cfg["out"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(encrypt({
        "v": 1, "as_of": as_of, "as_of_iso": state["as_of_iso"],
        "built": datetime.datetime.now().isoformat(timespec="seconds"),
        "nav": nav, "html": filled})))
    print(f"{key}: web -> {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB encrypted)")


def main():
    states = json.loads(STATE.read_text()) if STATE.exists() else {}
    if "hash" in states:              # the single-manual format from Sept. 24, 2026
        states = {"website": states}
    wanted = [a for a in sys.argv[1:] if not a.startswith("--")] or list(DOCS)
    for key in wanted:
        if key not in DOCS:
            raise SystemExit(f"unknown manual {key!r}; choose from {', '.join(DOCS)}")
        build(key, DOCS[key], states)
    STATE.write_text(json.dumps(states, indent=1))
    print("Commit the data.enc files and push.")


if __name__ == "__main__":
    main()
