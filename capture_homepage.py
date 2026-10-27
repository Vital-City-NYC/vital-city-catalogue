#!/usr/bin/env python3
"""Screenshot vitalcitynyc.org for the funder deck's "The publication" slide.

The slide used to frame the live homepage in an iframe. On screen that worked;
in print it did not: Chrome prints an iframe from whatever it has painted, so
the PDF came out with the lead photo and the "Recently published" column blank
(Josh, Oct. 27, 2026: "second page isn't showing current state of website").
A picture prints the same every time, so the nightly job takes one here and
the deck shows it with the date it was taken.

Writes prospects/homepage.jpg and prospects/homepage.json ({"captured_at"}).
On any failure the previous pair is left alone and the script exits non-zero,
so the deck keeps the last good picture and its caption still dates it.
"""
import json, os, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "prospects" / "homepage.jpg"
META = ROOT / "prospects" / "homepage.json"
URL = "https://www.vitalcitynyc.org/"
W, H = 1440, 1000      # the deck crops to the top half: the lead piece and the "Recently published" column


def chrome():
    for c in (os.environ.get("CHROME"), "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if c and (shutil.which(c) or Path(c).exists()):
            return shutil.which(c) or c
    return None


def main():
    exe = chrome()
    if not exe:
        sys.exit("homepage screenshot: no Chrome found (set CHROME)")
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "home.png"
        cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               "--no-default-browser-check", f"--user-data-dir={tmp}/profile", f"--window-size={W},{H}",
               # time for the lead photo and the recent-pieces thumbnails to arrive
               "--virtual-time-budget=20000", f"--screenshot={png}", URL]
        if os.environ.get("CI"):
            cmd.insert(1, "--no-sandbox")       # GitHub's runners
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        except Exception as e:
            sys.exit(f"homepage screenshot: Chrome failed ({e})")
        if not png.exists() or png.stat().st_size < 50_000:
            sys.exit("homepage screenshot: Chrome wrote no picture, or a nearly empty one")
        from PIL import Image, ImageStat
        im = Image.open(png).convert("RGB")
        # A page that has not painted is one flat color; a real homepage, with
        # its photos and black type, is anything but.
        spread = sum(ImageStat.Stat(im.convert("L")).stddev)
        if spread < 25:
            sys.exit(f"homepage screenshot: the picture is nearly blank (spread {spread:.0f}); keeping the last one")
        tmp_out = OUT.with_suffix(".tmp.jpg")
        im.save(tmp_out, "JPEG", quality=82, optimize=True, progressive=True)
        tmp_out.replace(OUT)
    META.write_text(json.dumps({"captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "url": URL, "width": W, "height": H}) + "\n")
    print(f"homepage screenshot: {OUT.stat().st_size // 1024} KB, spread {spread:.0f}")


if __name__ == "__main__":
    main()
