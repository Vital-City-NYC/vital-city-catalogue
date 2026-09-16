#!/usr/bin/env python3
"""Outlet phone lines, read off contact pages. Newsrooms publish a tip line and a
main number; individual reporters almost never publish a direct line, so this is
an outlet-level field and is labelled as one."""
import json, re, subprocess, html as H
import concurrent.futures as cf
from pathlib import Path
ROOT = Path("/Users/joshgreenman/Experiments/vital-city-catalogue")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
# A number only counts when it is punctuated like a phone number. Without this
# the pattern happily matched ten digits out of a tracking id and printed it as
# the Daily News newsroom line.
PHONE = re.compile(r"(?<![\d-])(?:\(([2-9]\d{2})\)\s?|([2-9]\d{2})[.\-\u2013 ])([2-9]\d{2})[.\-\u2013 ](\d{4})(?![\d-])")
LABEL = re.compile(r"(newsroom|news desk|tip|tips|hotline|main|phone|call us|switchboard|editorial|assignment)", re.I)

def curl(u):
    try:
        return subprocess.run(["curl","-sSL","--max-time","20","-A",UA,u],capture_output=True,timeout=35).stdout.decode("utf8","ignore")
    except Exception: return ""

def strip(s): return re.sub(r"\s+"," ",H.unescape(re.sub(r"<[^>]+>"," ",s))).strip()

def do(o):
    base = o["site"].rstrip("/")
    urls = [base+p for p in ("/contact/","/contact-us/","/about/","/about-us/","")]
    if o.get("staff_url"): urls.insert(0, o["staff_url"])
    found = {}
    for u in urls:
        s = curl(u)
        if not s or len(s) < 400: continue
        s = s.replace('\\"','"').replace('\\/','/')
        for m in re.finditer(r'href="tel:([+0-9().\s\-]{7,})"', s):
            d = re.sub(r"\D","",m.group(1))
            if len(d) in (10,11):
                d = d[-10:]
                ctx = strip(s[max(0,m.start()-220):m.start()])[-90:]
                found.setdefault(d, {"number":f"({d[:3]}) {d[3:6]}-{d[6:]}","source_url":u,"context":ctx,"kind":"tel: link"})
        for m in PHONE.finditer(strip(s)):
            ctx = strip(s)[max(0,m.start()-110):m.start()]
            if not LABEL.search(ctx[-45:]): continue
            d = "".join(g for g in m.groups() if g)
            if len(d) != 10: continue
            found.setdefault(d, {"number":f"({d[:3]}) {d[3:6]}-{d[6:]}","source_url":u,"context":ctx[-90:],"kind":"labelled on the page"})
        if found: break
    return o["id"], list(found.values())[:3]

outlets = json.load(open(ROOT/"press/outlets.json"))
out = {}
with cf.ThreadPoolExecutor(max_workers=8) as ex:
    for oid, ph in ex.map(do, outlets):
        if ph: out[oid] = ph
json.dump(out, open(ROOT/"press/phones.json","w"), indent=1)
print(f"{len(out)}/{len(outlets)} outlets with a published phone line")
for oid, ph in list(out.items())[:15]:
    print(f"  {oid:22s} {ph[0]['number']}  ({ph[0]['kind']})")
