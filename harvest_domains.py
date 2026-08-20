#!/usr/bin/env python3
"""Name unnamed readers by harvesting the staff pages of the organisations they work for.

THE LESSON THIS ENCODES
An outside review (Polar, Aug 2026) identified 423 readers where this project
had done 35. The gap was not tooling. It was three judgement errors worth
writing down so they are not repeated:

  1. The scope was never sized. 1,651 engaged readers have never had a
     confirmed name, on 1,156 domains. The first pass researched 37 and
     reported as though that were the task. ALWAYS COUNT THE POOL FIRST and say
     what full coverage costs.
  2. One malformed query became a claim about the world. Searching
     '"addr@x.com" OR "Surname" New York policy' lets the engine satisfy the OR
     and never match the address; "no results" meant nothing. It was reported
     as "no public footprint".
  3. The work was done one person at a time. 1,651 people is 1,651 searches
     against a search engine that cuts you off after about 28. But those people
     sit on 1,156 domains, and 194 of those domains hold 689 of them — so
     fetching ONE staff page can name a dozen readers at once, with no search
     engine involved. Attack the structure, not the list.

WHAT IT DOES
For every domain with unnamed engaged readers, tries the usual staff-page
paths, and pulls out both email addresses and name/title pairs. Then:

  exact      the page prints an address we hold        -> the name beside it
  pattern    the page names a person whose name fits   -> our local part
             our local-part convention

Evidence (page URL, and the text the name was read from) is recorded per row.
Nothing is written into people.json; proposals land in
private/domain_harvest.json for review, same discipline as the rest.

    python3 harvest_domains.py                 # domains with 2+ unnamed readers
    python3 harvest_domains.py --min 1         # every domain, singletons too
    python3 harvest_domains.py --limit 40
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
OUT = PRIV / "domain_harvest.json"
CACHE = PRIV / "domain_harvest_cache.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

PATHS = ["", "/team", "/our-team", "/about/team", "/staff", "/our-staff", "/about/staff",
         "/people", "/our-people", "/about-us", "/about", "/leadership", "/who-we-are",
         "/contact", "/directory", "/about/leadership", "/team-members", "/experts",
         "/who-we-are/people", "/about/our-team", "/about/people", "/our-staff-2", "/bios"]

# Links whose own text says "our team" / "staff" / "people" — following these
# one level finds staff pages that live at paths worth guessing.
STAFF_LINK = re.compile(r'<a[^>]+href="([^"#?]+)"[^>]*>\s*([^<]{2,40}?)\s*</a>', re.I)
STAFF_WORDS = re.compile(r"\b(our team|meet the team|staff|our people|leadership|who we are|"
                         r"board|directory|team members|our experts)\b", re.I)

CONSUMER = re.compile(r"(gmail|yahoo|hotmail|outlook|live\.|msn|aol|icloud|me\.com|mac\.com|"
                      r"comcast|verizon|att\.net|sbcglobal|optonline|earthlink|rcn\.com|proton|"
                      r"fastmail|hey\.com|mail\.com|ymail|googlemail|juno|rr\.com|cox\.net|"
                      r"charter\.net|gmx|pobox|zoho|duck\.com)", re.I)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# A person's name as it appears in staff-page markup: two or three capitalised
# words, allowing O'Neill, van der Lugt, Fader-Towe, initials.
NAME_RE = re.compile(r"\b((?:[A-Z][A-Za-z'’.-]+|(?:van|von|de|del|di|da|la|le)\s)"
                     r"(?:\s+(?:[A-Z]\.|[A-Z][A-Za-z'’.-]+|van|von|de|del|di|da|la|le)){1,3})\b")

STOP_NAMES = re.compile(r"^(New York|United States|Privacy Policy|Terms Of|Contact Us|Our Team|"
                        r"Read More|Learn More|Skip To|All Rights|Site Map|Sign Up|Log In|Main Menu|"
                        r"Board Of|Press Release|Annual Report|Get Involved|Donate Now)", re.I)


def get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ct = (r.headers.get("Content-Type") or "").lower()
        if "html" not in ct and "text" not in ct:
            return ""
        return r.read(1_500_000).decode("utf-8", "replace")


def visible_text(html):
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<br\s*/?>|</(p|div|li|h[1-6]|td|tr)>", "\n", html, flags=re.I)
    return re.sub(r"[ \t]+", " ", unescape(re.sub(r"<[^>]+>", " ", html)))


# A staff page marks a person's name up as a heading, a link, or an element whose
# class says so. Reading names out of raw body text instead just harvests the
# navigation menu — the first version of this returned "Strategic Priorities Get
# Involved" as a person.
NAME_HOLDER = re.compile(
    r"<(h[1-5]|a|span|div|p|strong|td)\b([^>]*)>\s*([^<>{}]{3,44}?)\s*</\1>", re.I | re.S)
NAMEISH_ATTR = re.compile(r"(name|person|staff|member|bio|profile|team|author|title|card)", re.I)
PERSON_NAME = re.compile(
    r"^(?:(?:Dr|Mr|Ms|Mrs|Prof)\.?\s+)?"
    r"[A-Z][a-z'’\-]{1,15}(?:\s+[A-Z]\.?)?"
    r"(?:\s+(?:van|von|de|del|di|da|la|le|der|den))*"
    r"\s+[A-Z][A-Za-z'’\-]{1,20}(?:,?\s+(?:Jr|Sr|II|III|PhD|JD|MD|Esq)\.?)?$")
NAV_WORDS = re.compile(r"\b(home|about|contact|donate|news|events|search|menu|login|sign|privacy|"
                       r"terms|careers|blog|press|media|resources|programs|projects|reports|"
                       r"publications|our|the|we|what|who|how|why|read|learn|view|more|all)\b", re.I)


FIRST_NAMES = set()

def load_first_names(people):
    """The only reliable way to tell "Daniela Gilbert" from "Reducing Incarceration"
    is to know that Daniela is a first name and Reducing is not. The database
    already holds 2,500+ confirmed names; use them as the dictionary."""
    for r in people:
        if r.get("ns") == "given":
            w = (r.get("n") or "").split()
            if len(w) >= 2 and w[0].isalpha():
                FIRST_NAMES.add(w[0].lower())
    return FIRST_NAMES


def extract_names(html):
    """(name, context) pairs from the markup a staff page actually uses."""
    out, seen = [], set()
    for m in NAME_HOLDER.finditer(html):
        tag, attrs, text = m.group(1).lower(), m.group(2) or "", unescape(m.group(3)).strip()
        text = re.sub(r"\s+", " ", text)
        if not text or text in seen:
            continue
        heading = tag in ("h1", "h2", "h3", "h4", "h5")
        marked = bool(NAMEISH_ATTR.search(attrs))
        if not (heading or marked or tag == "a"):
            continue
        if not PERSON_NAME.match(text) or NAV_WORDS.search(text):
            continue
        first = re.split(r"[^A-Za-z]+", text)[0].lower()
        if FIRST_NAMES and first not in FIRST_NAMES:
            continue          # "Reducing Incarceration" is not a person
        seen.add(text)
        ctx = re.sub(r"\s+", " ", visible_text(html[m.start(): m.end() + 300]))[:260]
        out.append((text, ctx))
    return out


def norm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def local_shapes(first, last):
    """The local parts an organisation plausibly builds from a name."""
    f, l = first.lower(), last.lower()
    return {f"{f[0]}{l}", f"{f}.{l}", f"{f}{l}", f"{f}_{l}", f"{l}{f[0]}", f"{l}.{f}",
            f"{f}{l[0]}", f, l, f"{f[0]}.{l}", f"{f}-{l}"}


def fetch_one(url):
    try:
        return url, get(url)
    except Exception:
        return url, ""


def harvest(domain, workers=10):
    """Fetch the candidate staff pages in parallel — 20 sequential guesses per
    domain, most of them 404s, is what made the first version unusably slow."""
    found_emails, found_names, pages = {}, [], []
    urls = [f"https://{domain}{p}" for p in PATHS]

    def absorb(url, html):
        if not html:
            return
        pages.append(url)
        for m in EMAIL_RE.finditer(html):
            a = m.group(0).lower()
            if a.endswith((".png", ".jpg", ".gif", ".svg", ".webp")) or "sentry" in a or "example" in a:
                continue
            found_emails.setdefault(a, re.sub(r"\s+", " ", visible_text(
                html[max(0, m.start() - 220):m.end() + 60]))[-260:])
        found_names.extend(extract_names(html))
        return html

    home_html = ""
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for url, html in ex.map(fetch_one, urls):
            absorb(url, html)
            if url.rstrip("/") == f"https://{domain}":
                home_html = html

    # follow links whose own text says "our team" / "staff"
    if home_html:
        follow = []
        for m in STAFF_LINK.finditer(home_html):
            href, label = m.group(1), m.group(2)
            if not STAFF_WORDS.search(label):
                continue
            nxt = href if href.startswith("http") else \
                  f"https://{domain}" + (href if href.startswith("/") else "/" + href)
            if domain in nxt and nxt not in pages and nxt not in follow:
                follow.append(nxt)
        if follow:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for url, html in ex.map(fetch_one, follow[:10]):
                    absorb(url, html)

    return {"emails": found_emails, "names": found_names[:600], "pages": pages[:10]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=2, help="minimum unnamed readers on a domain")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()

    people = json.loads((PRIV / "people.json").read_text())
    load_first_names(people)

    def weak(r):
        return r.get("ns") == "guess" or not (r.get("n") or "").strip()

    def engaged(r):
        return (not r.get("unsub")) and not r.get("gw") and \
               ((r.get("eclick") or 0) > 0 or (r.get("eopen") or 0) >= 50 or (r.get("erate") or 0) >= 3)

    by_dom = defaultdict(list)
    for r in people:
        e = (r.get("e") or "").lower()
        if not e or not engaged(r) or not weak(r):
            continue
        dom = e.split("@")[-1]
        if CONSUMER.search(dom):
            continue
        by_dom[dom].append(r)

    targets = sorted([(d, rs) for d, rs in by_dom.items() if len(rs) >= a.min],
                     key=lambda x: -len(x[1]))
    if a.limit:
        targets = targets[:a.limit]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    print(f"{sum(len(r) for r in by_dom.values())} unnamed readers on {len(by_dom)} domains; "
          f"working {len(targets)} domains covering {sum(len(r) for _, r in targets)} people",
          file=sys.stderr)

    proposals = json.loads(OUT.read_text()) if OUT.exists() else []
    seen = {p["email"] for p in proposals}

    for i, (dom, records) in enumerate(targets, 1):
        if dom in cache:
            h = cache[dom]
        else:
            try:
                h = harvest(dom)
            except Exception as e:
                h = {"emails": {}, "names": [], "pages": [], "error": str(e)[:80]}
            cache[dom] = h
            CACHE.write_text(json.dumps(cache))
            time.sleep(a.sleep)

        page = (h.get("pages") or [""])[0]
        hits = 0
        for r in records:
            email = (r.get("e") or "").lower()
            if email in seen:
                continue
            lp = email.split("@")[0]
            # 1. the page prints this exact address
            if email in h["emails"]:
                ctx = h["emails"][email]
                cand = [n for n in re.findall(r"[A-Z][a-z'’\-]{1,15}\s+[A-Z][A-Za-z'’\-]{1,20}", ctx)
                        if not STOP_NAMES.match(n) and not NAV_WORDS.search(n)]
                proposals.append({"email": email, "current": r.get("n") or "", "domain": dom,
                                  "proposed": cand[-1] if cand else "", "basis": "exact address on page",
                                  "conf": "confirmed" if cand else "address-on-page",
                                  "evidence": ctx[:240], "url": page,
                                  "open": r.get("eopen"), "click": r.get("eclick")})
                seen.add(email); hits += 1
                continue
            # 2. a person named on the page whose name fits our local part
            match = None
            for nm, ctx in h["names"]:
                w = [x for x in re.split(r"[^A-Za-z']+", nm) if len(x) > 1]
                if len(w) < 2:
                    continue
                if norm(lp) in {norm(s) for s in local_shapes(w[0], w[-1])}:
                    match = (nm, ctx); break
            if match:
                proposals.append({"email": email, "current": r.get("n") or "", "domain": dom,
                                  "proposed": match[0], "basis": "named on the organisation's own page, "
                                  "matching its local-part convention", "conf": "high",
                                  "evidence": match[1][:240], "url": page,
                                  "open": r.get("eopen"), "click": r.get("eclick")})
                seen.add(email); hits += 1
        if hits:
            print(f"  [{i}/{len(targets)}] {dom:<34} {len(records):>2} unnamed -> {hits} named", file=sys.stderr)
        OUT.write_text(json.dumps(proposals, indent=1, ensure_ascii=False))

    conf = sum(1 for p in proposals if p["conf"] == "confirmed")
    print(f"\n{len(proposals)} proposals ({conf} from an address printed on the page)", file=sys.stderr)
    print(f"wrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
