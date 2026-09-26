#!/usr/bin/env python3
"""Collect the raw evidence behind the Vital City influence index.

Every collector here asks the same question of Vital City and of a fixed set of
peer organizations, in the same way, over the same periods. That symmetry is the
point. Our own trackers (growth_pull.py) search only for Vital City, so a rising
count there can mean Vital City is cited more, or that Google indexes more, or
that we got better at looking. Asking the identical question about peers turns
each count into a share, and a share cancels whatever drift the source itself
has. Google News, for example, returns three times as many Politico items for
the Citizens Budget Commission in 2025 as in 2023; the commission did not triple.

Usage:
  python3 influence_pull.py press   [--years 2022-2026]
  python3 influence_pull.py wiki
  python3 influence_pull.py webgraph [--release cc-main-2026-jul-aug-sep ...]
  python3 influence_pull.py courts
  python3 influence_pull.py record   [--years 2022-2026]
  python3 influence_pull.py readers
  python3 influence_pull.py scholar-import FILE.json
  python3 influence_pull.py verify-press

Writes private/influence_raw.json. Each collector owns one top-level key and
replaces only the periods it re-pulled, so a partial or failed run never erases
history. A collector that gets nothing back where it expected something raises
instead of writing zeros (an empty fetch must fail loudly, not look like a
quiet year).

Methodology: influence/methodology.md.
"""
from __future__ import annotations

import argparse, gzip, html as html_mod, io, json, os, re, subprocess, sys, time
import urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
RAW = Path(os.environ.get("INFLUENCE_RAW") or PRIV / "influence_raw.json")
UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
UA_BOT = "VitalCityInfluenceIndex/1.0 (+https://www.vitalcitynyc.org; info@vitalcitynyc.org)"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# The comparison set. Chosen before any counts were pulled, on three tests:
# the organization publishes policy analysis or argument about New York City,
# New York City is its main subject rather than one market among many, and it
# is an independent nonprofit (government bodies such as the Independent Budget
# Office are left out because they are cited as authorities, not as voices).
# Two are publications (City Journal, Gotham Gazette), the rest research and
# advocacy shops, because Vital City is both. Changing this list changes every
# share, so a change belongs in methodology.md with a date.
#
# press: Google News phrase queries. None for City Limits, whose name is
# ordinary English ("within city limits") and cannot be counted by phrase.
# Vital City's own name has the same problem, which is why its press hits are
# checked page by page (verify-press) while peers' unambiguous names are not.
# domains: for link, Wikipedia, court and Scholar counts, which match URLs.
ORGS = [
    {"id": "vc",     "name": "Vital City",                     "press": ['"Vital City"'],
     "domains": ["vitalcitynyc.org"]},
    {"id": "cbc",    "name": "Citizens Budget Commission",     "press": ['"Citizens Budget Commission"'],
     "domains": ["cbcny.org"]},
    {"id": "cuf",    "name": "Center for an Urban Future",     "press": ['"Center for an Urban Future"'],
     "domains": ["nycfuture.org"]},
    {"id": "css",    "name": "Community Service Society",      "press": ['"Community Service Society"'],
     "domains": ["cssny.org"]},
    {"id": "fpi",    "name": "Fiscal Policy Institute",        "press": ['"Fiscal Policy Institute"'],
     "domains": ["fiscalpolicy.org"]},
    {"id": "furman", "name": "NYU Furman Center",              "press": ['"Furman Center"'],
     "domains": ["furmancenter.org"]},
    {"id": "rpa",    "name": "Regional Plan Association",      "press": ['"Regional Plan Association"'],
     "domains": ["rpa.org"]},
    {"id": "cj",     "name": "City Journal",                   "press": ['"City Journal"'],
     "domains": ["city-journal.org"]},
    {"id": "gg",     "name": "Gotham Gazette",                 "press": ['"Gotham Gazette"'],
     "domains": ["gothamgazette.com"]},
    {"id": "cl",     "name": "City Limits",                    "press": None,
     "domains": ["citylimits.org"]},
    {"id": "cji",    "name": "Center for Justice Innovation",
     "press": ['("Center for Justice Innovation" OR "Center for Court Innovation")'],
     "domains": ["innovatingjustice.org", "courtinnovation.org"]},
    {"id": "dcj",    "name": "Data Collaborative for Justice", "press": ['"Data Collaborative for Justice"'],
     "domains": ["datacollaborativeforjustice.org"]},
]
ORG = {o["id"]: o for o in ORGS}

# The press panel: outlets that cover New York City government and policy,
# in two tiers. "major": the national papers and magazines and the city's
# largest public-radio newsroom, the outlets Vital City's own ranking of
# evidence puts first (Times, New Yorker, Gothamist, Politico). "ny": the rest
# of the city's policy press. An outlet is skipped for the organization that
# publishes it (Gotham Gazette in Gotham Gazette), since a masthead is not a
# citation.
OUTLETS = [
    ("nytimes.com", "The New York Times", "major"), ("wsj.com", "The Wall Street Journal", "major"),
    ("washingtonpost.com", "The Washington Post", "major"), ("politico.com", "Politico", "major"),
    ("newyorker.com", "The New Yorker", "major"), ("nymag.com", "New York Magazine", "major"),
    ("bloomberg.com", "Bloomberg", "major"), ("theatlantic.com", "The Atlantic", "major"),
    ("npr.org", "NPR", "major"), ("economist.com", "The Economist", "major"),
    ("theguardian.com", "The Guardian", "major"), ("axios.com", "Axios", "major"),
    ("gothamist.com", "Gothamist", "major"), ("wnyc.org", "WNYC", "major"),
    ("thecity.nyc", "The City", "ny"), ("nydailynews.com", "New York Daily News", "ny"),
    ("nypost.com", "New York Post", "ny"), ("cityandstateny.com", "City & State", "ny"),
    ("ny1.com", "NY1", "ny"), ("amny.com", "amNewYork", "ny"), ("crainsnewyork.com", "Crain's New York", "ny"),
    ("streetsblog.org", "Streetsblog", "ny"), ("citylimits.org", "City Limits", "ny"),
    ("gothamgazette.com", "Gotham Gazette", "ny"), ("therealdeal.com", "The Real Deal", "ny"),
    ("hellgatenyc.com", "Hell Gate", "ny"), ("nysfocus.com", "New York Focus", "ny"),
    ("chalkbeat.org", "Chalkbeat", "ny"), ("silive.com", "Staten Island Advance", "ny"),
    ("brooklynpaper.com", "Brooklyn Paper", "ny"), ("documentedny.com", "Documented", "ny"),
    ("newsday.com", "Newsday", "ny"), ("timesunion.com", "Times Union", "ny"), ("law.com", "Law.com", "ny"),
]
TIER = {d: t for d, _, t in OUTLETS}
SELF_OUTLET = {"gg": "gothamgazette.com", "cl": "citylimits.org", "cj": "city-journal.org"}

# The official record: government and court sites, same query shapes.
RECORD_DOMAINS = [
    ("nyc.gov", "City of New York"), ("council.nyc.gov", "New York City Council"),
    ("comptroller.nyc.gov", "New York City Comptroller"), ("advocate.nyc.gov", "Public Advocate"),
    ("ibo.nyc.gov", "Independent Budget Office"), ("ny.gov", "New York State"),
    ("nysenate.gov", "New York State Senate"), ("nyassembly.gov", "New York State Assembly"),
    ("nycourts.gov", "New York State courts"),
]


# ---------------------------------------------------------------- raw store
def load_raw():
    if RAW.exists():
        return json.loads(RAW.read_text())
    return {}


def save_part(key, value):
    """Write one collector's section, re-reading the file first so collectors
    running side by side never overwrite each other's work."""
    import fcntl
    PRIV.mkdir(exist_ok=True)
    with open(PRIV / ".influence_raw.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        cur = load_raw()
        cur[key] = value
        tmp = RAW.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=1))
        tmp.replace(RAW)


def save_sub(key, sub, value):
    """Write one entry inside a section (one release of the link graph),
    re-reading the section under the lock, so two pulls of different
    releases running at once cannot erase each other."""
    import fcntl
    PRIV.mkdir(exist_ok=True)
    with open(PRIV / ".influence_raw.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        cur = load_raw()
        cur.setdefault(key, {})[sub] = value
        tmp = RAW.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=1))
        tmp.replace(RAW)


def http_get(url, headers=None, timeout=40, ua=UA_BROWSER):
    req = urllib.request.Request(url, headers={"User-Agent": ua, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def years_arg(s):
    a, _, b = s.partition("-")
    return list(range(int(a), int(b or a) + 1))


# ------------------------------------------------------------------- press
def _gn_items(query):
    """All Google News RSS items for one query (the feed stops at 100)."""
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
           + "&hl=en-US&gl=US&ceid=US:en")
    last = None
    for attempt in range(7):
        try:
            xml = http_get(url, timeout=30)
            root = ET.fromstring(xml)
            break
        except Exception as e:           # Google News 503s in bursts; back off up to ~2 min
            last = e
            time.sleep(min(120, 4 * 2 ** attempt))
    else:
        raise RuntimeError(f"Google News failed for {query!r}: {last}")
    out = []
    for it in root.findall(".//item"):
        title = html_mod.unescape(it.findtext("title") or "")
        src = html_mod.unescape(it.findtext("source") or "")
        if src and title.endswith(" - " + src):
            title = title[: -len(" - " + src)].rstrip()
        pub = it.findtext("pubDate") or ""
        try:
            dt = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        out.append({"title": re.sub(r"\s+", " ", title).strip(), "url": it.findtext("link") or "",
                    "source": src, "date": dt.date().isoformat()})
    return out


def _gn_window(shape, domain, start, end, depth=0):
    """Items for [start, end). A window that hits the 100-item ceiling is split
    in half and re-asked, so a busy organization is never silently truncated
    (truncation would shrink big peers and flatter Vital City's share)."""
    q = f"{shape} site:{domain} after:{start.isoformat()} before:{end.isoformat()}"
    items = _gn_items(q)
    time.sleep(0.9)
    if len(items) >= 100 and (end - start).days > 20 and depth < 6:
        mid = start + (end - start) / 2
        return _gn_window(shape, domain, start, mid, depth + 1) + \
               _gn_window(shape, domain, mid, end, depth + 1)
    return [i for i in items if start.isoformat() <= i["date"] < end.isoformat()]


def _collect_gn(section, jobs, fresh_days):
    """Run (org, shape, domain, year) Google News jobs for one section.

    Saves after every 25 cells, skips cells pulled within `fresh_days` (so an
    interrupted run resumes where it stopped), carries forward the page-check
    result of any item already seen, and never lets one failed cell sink the
    rest: failures are retried once at the end, and if any remain the run
    exits non-zero after saving everything that did succeed."""
    from datetime import date
    raw = load_raw()
    store = raw.setdefault(section, {"items": {}, "pulled": {}})
    today = date.today()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=fresh_days)).isoformat()
    todo = [j for j in jobs if store["pulled"].get(f"{j[0]}|{j[2]}|{j[3]}", "") < cutoff]
    log(f"{section}: {len(todo)} of {len(jobs)} cells to pull")

    def run(job):
        oid, shape, dom, y = job
        start, end = date(y, 1, 1), min(date(y + 1, 1, 1), today + timedelta(days=1))
        try:
            return job, _gn_window(shape, dom, start, end), None
        except Exception as e:
            return job, None, e

    def merge(job, items):
        oid, shape, dom, y = job
        key = f"{oid}|{dom}|{y}"
        prev = {i["title"].lower(): i for i in store["items"].get(key, [])}
        merged = {}
        for i in items:
            k = i["title"].lower()
            if k in merged:
                continue
            old = prev.get(k)
            if old:   # keep the page check already done on an item we have seen
                i = {**i, **{f: old[f] for f in ("status", "why", "resolved_url",
                                                  "context", "where", "checked") if f in old}}
            merged[k] = {**i, "domain": dom}
        store["items"][key] = list(merged.values())
        store["pulled"][key] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    failed, done, got = [], 0, 0
    for attempt in (1, 2):
        batch, failed = (todo if attempt == 1 else failed), []
        with ThreadPoolExecutor(max_workers=2) as ex:
            for job, items, err in ex.map(run, batch):
                if err is not None:
                    failed.append(job)
                    continue
                merge(job, items)
                got += len(items)
                done += 1
                if done % 25 == 0:
                    save_part(section, store)
                    log(f"  {done}/{len(todo)} cells, {got} items")
        save_part(section, store)
        if not failed:
            break
        log(f"{section}: {len(failed)} cells failed; waiting 3 minutes, then retrying them once")
        time.sleep(180)
    if todo and got == 0:
        raise SystemExit(f"{section}: every query came back empty; Google News is down or blocking.")
    if failed:
        raise SystemExit(f"{section}: {len(failed)} cells still failing (saved the rest); rerun to resume. "
                         f"First: {failed[0]}")
    log(f"{section}: {got} items across {done} cells")


def collect_press(years, fresh_days=5):
    jobs = [(o["id"], shape, dom, y) for o in ORGS for shape in (o["press"] or [])
            for dom, _, _t in OUTLETS if SELF_OUTLET.get(o["id"]) != dom for y in years]
    _collect_gn("press", jobs, fresh_days)


# Capitalisation is the signal, so these are case-sensitive: our name is
# "Vital City" with both words capitalized, and generic English is "a vital
# city", "our vital city", "vital city services". Same rule as the growth
# dashboard's verify_citations (growth_pull.py), restated here because that
# one keeps it inside a closure.
_PROPER = re.compile(r"\bVital City\b")
_GENERIC_BEFORE = re.compile(
    r"\b(?:a|an|our|your|this|that|these|those|every|each|any|another|such|the)\s+"
    r"(?:truly\s+|really\s+|very\s+|so\s+|especially\s+)?$", re.I)
_GENERIC_AFTER = re.compile(
    r"^\s+(?:services?|agenc(?:y|ies)|employees?|workers?|staff|infrastructure|functions?|"
    r"departments?|operations?|programs?|budgets?|centres?|centers?|streets?|blocks?|neighou?rhoods?)\b",
    re.I)   # headlines are title case: "Protect Vital City Services" is the English phrase
# Outlets whose article text sits behind a hard paywall or bot wall. A page from
# one of these that does not show our name tells us nothing, so it is
# "unreadable", not "absent".
_WALLED = ("nytimes.com", "wsj.com", "newyorker.com", "nymag.com", "crainsnewyork.com",
           "newsday.com", "law.com", "timesunion.com", "bloomberg.com", "politico.com",
           "washingtonpost.com", "theatlantic.com", "economist.com")


# Words that make "Vital City" the organization whatever comes before it: "a
# Vital City analysis," "the Vital City report," "Vital City's founder." The
# earlier rule rejected any "a" or "the" before the name and so threw away
# exactly these references to the journal's work.
_ORG_AFTER = re.compile(
    r"^(?:'s|\u2019s|\s+(?:NYC|report|reports|analysis|analyses|piece|pieces|essay|essays|article|"
    r"articles|op-ed|column|story|study|studies|data|survey|podcast|newsletter|founder|co-founder|"
    r"cofounder|editor|editors|contributor|contributors|writer|writers|journal|magazine|publication|"
    r"team|staff|board|event|forum|panel|conference|fellow|series|issue|investigation|memo|"
    r"interview|findings|research|researchers|debate|poll))\b", re.I)


def first_us(text):
    """The first occurrence of "Vital City" used as the organization's name
    (a regex match), or None. Case-sensitive: our name is both words
    capitalized."""
    for m in _PROPER.finditer(text):
        before = text[max(0, m.start() - 60):m.start()]
        after = text[m.end():m.end() + 40]
        if _ORG_AFTER.match(after):
            return m
        if _GENERIC_BEFORE.search(before) or _GENERIC_AFTER.match(after):
            continue
        return m
    return None


def names_us(text):
    return first_us(text) is not None


def us_context(text):
    """About 380 characters around the reference that counted."""
    m = first_us(text) or re.search(r"vitalcitynyc\.org", text)
    return re.sub(r"\s+", " ", text[max(0, m.start() - 220):m.end() + 160]).strip() if m else ""


def check_page(item):
    """Resolve a Google News item to its article and classify the mention:
    confirmed  - the page names Vital City (proper noun) or links to it
    generic    - "vital city" appears, but as ordinary English
    absent     - a readable page with no such phrase at all
    unreadable - resolver, fetch, paywall or bot wall kept us from the text
    """
    sys.path.insert(0, str(ROOT))
    import growth_pull as gp
    url = item.get("resolved_url") or gp.resolve_gnews_url(item["url"])
    out = {"resolved_url": url}
    if "news.google.com" in url:
        return {**out, "status": "unreadable", "why": "Google News link did not resolve"}
    try:
        page = http_get(url, timeout=25).decode("utf8", "replace")
    except Exception as e:
        return {**out, "status": "unreadable", "why": f"fetch failed ({str(e)[:60]})"}
    raw = re.sub(r"<head\b.*?</head>", " ", page, flags=re.S | re.I)
    raw = re.sub(r"<a\b[^>]*\brel=[\"'](?:prev|next)[\"'][^>]*>.*?</a>", " ", raw, flags=re.S | re.I)
    body = re.sub(r"<(nav|aside|footer)\b.*?</\1>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    text = html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)))
    if "vitalcitynyc" in body.lower() or names_us(text):
        sent, where = gp.body_mention(raw, names_us)
        return {**out, "status": "confirmed", "context": sent, "where": where or ""}
    walled = any(w in url for w in _WALLED)
    if re.search(r"vital\s+city", text, re.I):
        return {**out, "status": "generic", "why": "phrase used as ordinary English"}
    if walled or len(text) < 2500:
        return {**out, "status": "unreadable", "why": "paywall or too little article text"}
    return {**out, "status": "absent", "why": "phrase not on the page"}


def _verify_section(section, workers=8, recheck=()):
    raw = load_raw()
    cells = raw.get(section, {}).get("items", {})
    todo = [i for k, v in cells.items() if k.startswith("vc|") for i in v
            if "status" not in i or i.get("status") in recheck]
    log(f"verify {section}: {len(todo)} Vital City items to check")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (item, res) in enumerate(zip(todo, ex.map(check_page, todo))):
            item.update(res)
            item["checked"] = datetime.now(timezone.utc).date().isoformat()
    save_part(section, raw[section])
    from collections import Counter
    log(f"verify {section}: " + ", ".join(f"{k} {v}" for k, v in Counter(i["status"] for i in todo).items()))


def verify_press(workers=8, recheck=()):
    """Check each Vital City press hit on the page itself. "Vital City" is
    ordinary English and Google's phrase match ignores case, so every hit is
    read. Peers' names are unambiguous and are not checked. recheck=("generic",)
    re-reads items an older, stricter name rule had set aside."""
    _verify_section("press", workers, recheck)


# ----------------------------------------------------------------- record
def collect_record(years, fresh_days=5):
    """Government and court web pages that name the organization (Google News
    index of official sites). Vital City hits are page-checked like press hits."""
    jobs = [(o["id"], s, d, y) for o in ORGS for s in (o["press"] or []) for d, _ in RECORD_DOMAINS
            for y in years]
    _collect_gn("record", jobs, fresh_days)


def verify_record(workers=8):
    _verify_section("record", workers)


# ------------------------------------------------------------------ courts
def collect_courts():
    """Federal court filings (CourtListener's RECAP archive, full text) that
    contain the organization's web address. Addresses, not names: a filing that
    cites a report almost always carries its URL, and a URL cannot be ordinary
    English. Dated by filing date."""
    raw = load_raw()
    out = {}
    for o in ORGS:
        docs = {}
        for dom in o["domains"]:
            url = ("https://www.courtlistener.com/api/rest/v4/search/?type=rd&q="
                   + urllib.parse.quote(f'"{dom}"'))
            pages = 0
            while url and pages < 20:
                for attempt in range(6):      # CourtListener answers bursts with 429
                    try:
                        d = json.loads(http_get(url, ua=UA_BOT, headers={"Accept": "application/json"}))
                        break
                    except urllib.error.HTTPError as e:
                        if e.code != 429 or attempt == 5:
                            raise
                        time.sleep(30 * (attempt + 1))
                for r in d.get("results", []):
                    key = r.get("id") or r.get("absolute_url")
                    docs[key] = {
                        "date": (r.get("entry_date_filed") or r.get("dateFiled") or "")[:10],
                        "case": r.get("caseName") or "", "court": r.get("court") or r.get("court_id") or "",
                        "desc": (r.get("description") or r.get("short_description") or "")[:200],
                        "url": "https://www.courtlistener.com" + (r.get("absolute_url") or ""),
                        "domain": dom}
                url = d.get("next")
                pages += 1
                time.sleep(3.0)
        out[o["id"]] = list(docs.values())
        log(f"courts: {o['id']} {len(docs)} filings")
    raw["courts"] = {"pulled": datetime.now(timezone.utc).isoformat(timespec="seconds"), "orgs": out}
    save_part("courts", raw["courts"])


# --------------------------------------------------------------- wikipedia
WIKI_API = "https://en.wikipedia.org/w/api.php"


def _wapi(params, tries=8):
    url = WIKI_API + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2,
                                                    "maxlag": 5})
    last = None
    for attempt in range(tries):
        try:
            d = json.loads(http_get(url, ua=UA_BOT, timeout=90))
            if d.get("error", {}).get("code") == "maxlag":
                raise RuntimeError("maxlag")
            return d
        except Exception as e:        # 429s and lag: back off, up to about two minutes
            last = e
            time.sleep(min(120, 3 * 2 ** attempt))
    raise RuntimeError(f"Wikipedia API failed ({last}): {url}")


def _wiki_pages(domain):
    """Articles (main namespace) that link to the domain today."""
    titles = set()
    for proto in ("https", "http"):
        for q in (domain, "*." + domain):
            cont = {}
            while True:
                d = _wapi({"action": "query", "list": "exturlusage", "euquery": q, "euprotocol": proto,
                           "eunamespace": 0, "eulimit": 500, **cont})
                titles |= {x["title"] for x in d["query"]["exturlusage"]}
                if "continue" not in d:
                    break
                cont = d["continue"]
    return titles


def _wiki_checkpoints():
    today = datetime.now(timezone.utc).date()
    cps = []
    for y in range(2021, today.year + 1):
        for m in (1, 7):
            d = datetime(y, m, 1).date()
            if d <= today:
                cps.append(d.isoformat())
    cps.append(today.isoformat())
    return cps


def collect_wiki():
    """How many Wikipedia articles cite each organization, at checkpoints.

    Starts from the articles that cite the domain today, then finds, for each
    article, the first checkpoint (the first of January and of July each year)
    at which the article's text already contained the domain. That is a binary
    search over the checkpoints, so about four reads per article rather than
    thirteen. It assumes a citation, once added, stays; one that was added,
    removed and re-added is dated from its last arrival at the latest
    checkpoint the search lands on, and citations removed for good are not
    seen at all. Both errors apply to every organization alike."""
    raw = load_raw()
    old = raw.get("wiki", {})
    cache = old.get("rev_cache", {})       # "title|checkpoint" -> domains present
    cps = _wiki_checkpoints()
    past = cps[:-1]                        # the last checkpoint is today: present by definition
    pages = {}
    for o in ORGS:
        t = set()
        for dom in o["domains"]:
            t |= _wiki_pages(dom)
        pages[o["id"]] = sorted(t)
        log(f"wiki: {o['id']} cites today on {len(t)} articles")
    if not pages["vc"]:
        raise SystemExit("wiki: no article cites vitalcitynyc.org; the API query is broken. Nothing written.")
    all_doms = [d for o in ORGS for d in o["domains"]]
    lock = __import__("threading").Lock()
    reads = [0]

    def present(title, cp):
        key = f"{title}|{cp}"
        with lock:
            if key in cache:
                return cache[key]
        d = _wapi({"action": "query", "prop": "revisions", "titles": title, "rvlimit": 1,
                   "rvdir": "older", "rvstart": cp + "T00:00:00Z", "rvprop": "content|ids",
                   "rvslots": "main"})
        pg = (d.get("query", {}).get("pages") or [{}])[0]
        revs = pg.get("revisions") or []
        text = (revs[0].get("slots", {}).get("main", {}).get("content") or "").lower() if revs else ""
        doms = [dm for dm in all_doms if dm in text]
        with lock:
            cache[key] = doms
            reads[0] += 1
            if reads[0] % 250 == 0:
                log(f"  {reads[0]} reads")
                save_part("wiki", {**raw.get("wiki", {}), "rev_cache": cache})
        return doms

    first = {}                             # (org, title) -> first checkpoint present

    def search(job):
        oid, title = job
        doms = ORG[oid]["domains"]
        lo, hi = 0, len(past)              # answer in [0, len(past)]; len(past) = only today
        while lo < hi:
            mid = (lo + hi) // 2
            if any(dm in present(title, past[mid]) for dm in doms):
                hi = mid
            else:
                lo = mid + 1
        return job, cps[lo]

    jobs = [(oid, t) for oid, ts in pages.items() for t in ts]
    log(f"wiki: {len(jobs)} article-organization pairs, {len(past)} past checkpoints")
    with ThreadPoolExecutor(max_workers=2) as ex:
        for job, cp in ex.map(search, jobs):
            first[job] = cp
    series = {oid: {cp: sum(1 for t in pages[oid] if first[(oid, t)] <= cp) for cp in cps} for oid in pages}
    raw["wiki"] = {"pulled": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "checkpoints": cps, "pages": pages, "series": series, "rev_cache": cache,
                   "first_checkpoint": {f"{o}|{t}": cp for (o, t), cp in first.items()},
                   **{k: v for k, v in old.items() if k.startswith("first_adds_")}}
    save_part("wiki", raw["wiki"])
    log("wiki: " + ", ".join(f"{o} {series[o][cps[-1]]}" for o in series))


def wiki_first_adds(org_id="vc"):
    """For one organization, the revision, date and editor that first added
    the domain to each article (binary search over the revision history). Used
    to disclose who put Vital City links on Wikipedia and when."""
    raw = load_raw()
    doms = ORG[org_id]["domains"]
    out = []
    for title in raw["wiki"]["pages"][org_id]:
        revs, cont = [], {}
        while True:
            d = _wapi({"action": "query", "prop": "revisions", "titles": title, "rvlimit": 500,
                       "rvprop": "ids|timestamp|user", "rvdir": "newer", **cont})
            pg = d["query"]["pages"][0]
            revs += pg.get("revisions", [])
            if "continue" not in d:
                break
            cont = d["continue"]

        def has(i):
            dd = _wapi({"action": "query", "prop": "revisions", "revids": revs[i]["revid"],
                        "rvprop": "content", "rvslots": "main"})
            txt = dd["query"]["pages"][0]["revisions"][0]["slots"]["main"].get("content", "").lower()
            return any(dm in txt for dm in doms)
        lo, hi = 0, len(revs) - 1
        if not has(hi):
            continue
        while lo < hi:                  # first revision containing the domain
            mid = (lo + hi) // 2
            if has(mid):
                hi = mid
            else:
                lo = mid + 1
        r = revs[lo]
        out.append({"title": title, "revid": r["revid"], "date": r["timestamp"][:10], "user": r.get("user", "")})
        log(f"  {r['timestamp'][:10]} {title} ({r.get('user','')})")
    raw.setdefault("wiki", {})["first_adds_" + org_id] = sorted(out, key=lambda x: x["date"])
    save_part("wiki", raw["wiki"])


# --------------------------------------------------------------- web graph
CC_BASE = "https://data.commoncrawl.org/projects/hyperlinkgraph/"


_MON = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def release_end(name):
    """(year, month) of the last crawl month in a release name.
    cc-main-2025-aug-sep-oct -> (2025, 10); cc-main-2025-26-nov-dec-jan -> (2026, 1)."""
    m = re.match(r"cc-main-(\d{4})(?:-(\d{2}))?-([a-z]{3})-([a-z]{3})-([a-z]{3})", name)
    y1, y2, *mons = m.groups()
    last = _MON[mons[-1]]
    if y2:
        return (int(y1[:2] + y2), last)
    return (int(y1) + (1 if last < _MON[mons[0]] else 0), last)


def cc_releases():
    """Release names listed on Common Crawl's web-graph page, oldest first.
    cc-main-2024-nov-feb-apr overlaps its neighbours (a re-run over a
    non-contiguous span) and is left out so each period is counted once."""
    page = http_get("https://commoncrawl.org/web-graphs").decode("utf8", "replace")
    names = set(re.findall(r"cc-main-\d{4}(?:-\d{2})?-[a-z]{3}-[a-z]{3}-[a-z]{3}", page))
    names.discard("cc-main-2024-nov-feb-apr")
    return sorted(names, key=release_end)


def collect_webgraph(releases):
    """Each organization's standing in Common Crawl's domain-level web graph.

    Common Crawl publishes, every few months, a ranking of roughly 100 million
    web domains by harmonic centrality and PageRank computed from the links in
    its crawl. PageRank rewards being linked to by domains that are themselves
    linked to; it is the classic measure of standing in the link graph. The
    ranks file is 2-3.5 GB compressed, so it is streamed and filtered on the
    fly, never stored."""
    raw = load_raw()
    store = raw.setdefault("webgraph", {})
    want = {}
    for o in ORGS:
        for dom in o["domains"]:
            want[".".join(reversed(dom.split(".")))] = (o["id"], dom)
    pat = "|".join(re.escape(k) for k in want)
    for rel in releases:
        if rel in store and store[rel].get("rows"):
            continue
        url = f"{CC_BASE}{rel}/domain/{rel}-domain-ranks.txt.gz"
        log(f"webgraph: streaming {rel}")
        t0 = time.time()
        cmd = (f"curl -sf {url} | gunzip -c | "
               f"awk -F'\\t' '$5 ~ /^({pat})$/'")
        res = subprocess.run(["bash", "-o", "pipefail", "-c", cmd], capture_output=True, text=True)
        if res.returncode not in (0,):
            raise SystemExit(f"webgraph: {rel} failed ({res.returncode}): {res.stderr[:300]}")
        rows = {}
        for line in res.stdout.splitlines():
            hc_pos, hc_val, pr_pos, pr_val, rev, n_hosts = line.split("\t")[:6]
            oid, dom = want[rev]
            rows[dom] = {"org": oid, "hc_pos": int(hc_pos), "hc_val": float(hc_val),
                         "pr_pos": int(pr_pos), "pr_val": float(pr_val), "n_hosts": int(n_hosts)}
        if not rows:
            raise SystemExit(f"webgraph: {rel} returned no rows for any organization")
        store[rel] = {"rows": rows, "pulled": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "seconds": round(time.time() - t0)}
        save_part("webgraph", raw["webgraph"])
        log(f"  {rel}: {len(rows)} domains in {round(time.time() - t0)}s")


# Linking domains that signal policy attention. Government and universities
# by their suffixes; news by a fixed list (the press panel plus other outlets
# that cover cities and policy). Applied identically to every organization.
NEWS_DOMAINS = {d for d, _, _ in OUTLETS} | {
    "cbsnews.com", "nbcnews.com", "abc7ny.com", "nbcnewyork.com", "pix11.com", "cnn.com", "foxnews.com",
    "usatoday.com", "latimes.com", "bostonglobe.com", "vox.com", "slate.com", "reuters.com", "apnews.com",
    "semafor.com", "thetrace.org", "themarshallproject.org", "propublica.org", "bloomberg.com", "nextcity.org",
    "fastcompany.com", "newsweek.com", "thenation.com", "nationalreview.com", "reason.com", "theintercept.com",
    "motherjones.com", "time.com", "forbes.com", "businessinsider.com", "huffpost.com", "thedailybeast.com",
    "thecityreporter.nyc", "bklyner.com", "brownstoner.com", "patch.com", "spectrumnews.com",
    "news12.com", "westsiderag.com", "commercialobserver.com", "bisnow.com", "governing.com",
    "route-fifty.com", "citylandnyc.org", "queenseagle.com", "brooklyneagle.com", "bronxtimes.com",
    "riverdalepress.com", "nj.com", "northjersey.com", "courthousenews.com", "niemanlab.org",
    "washingtonmonthly.com", "prospect.org", "newrepublic.com", "theverge.com", "wired.com"}


def link_kind(d):
    if re.search(r"\.gov$|\.gov\.[a-z]{2}$|\.mil$|\.[a-z]{2}\.us$", d):
        return "gov"
    if re.search(r"\.edu$|\.edu\.[a-z]{2}$|\.ac\.[a-z]{2}$", d):
        return "edu"
    if d in NEWS_DOMAINS:
        return "news"
    return "other"


def collect_weblinks(release):
    """Which domains link to each organization's site, from Common Crawl's
    domain-level link graph (vertices = domains, edges = "this domain links to
    that one somewhere in the crawl"). Three streamed passes over about 10 GB:
    find the organizations' vertex ids, keep the edges pointing at them, then
    name the domains those edges come from. Stored per release as the list of
    linking domains, so the build can sort them into government, universities,
    news outlets and the rest."""
    import tempfile
    raw = load_raw()
    store = raw.setdefault("weblinks", {})
    if release in store and store[release].get("orgs"):
        return
    base = f"{CC_BASE}{release}/domain/{release}-domain-"
    want = {".".join(reversed(d.split("."))): (o["id"], d) for o in ORGS for d in o["domains"]}
    pat = "|".join(re.escape(k) for k in want)
    t0 = time.time()
    run = lambda cmd: subprocess.run(["bash", "-o", "pipefail", "-c", cmd], capture_output=True, text=True)
    r = run(f"curl -sf {base}vertices.txt.gz | gunzip -c | awk -F'\\t' '$2 ~ /^({pat})$/ {{print $1\"\\t\"$2}}'")
    if r.returncode or not r.stdout.strip():
        raise SystemExit(f"weblinks: vertex pass failed for {release}: {r.stderr[:200]}")
    ids = dict(line.split("\t") for line in r.stdout.strip().splitlines())      # id -> reversed domain
    log(f"weblinks {release}: {len(ids)} target ids ({round(time.time() - t0)}s)")
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".ids") as f:
        f.write("\n".join(ids))
        idfile = f.name
    r = run(f"curl -sf {base}edges.txt.gz | gunzip -c | "
            f"awk -F'\\t' 'NR==FNR {{t[$1]=1; next}} ($2 in t) {{print $1\"\\t\"$2}}' {idfile} -")
    if r.returncode:
        raise SystemExit(f"weblinks: edge pass failed for {release}: {r.stderr[:200]}")
    edges = [line.split("\t") for line in r.stdout.strip().splitlines() if line]
    log(f"weblinks {release}: {len(edges)} edges ({round(time.time() - t0)}s)")
    with open(idfile, "w") as f:
        f.write("\n".join(sorted({a for a, _ in edges})))
    r = run(f"curl -sf {base}vertices.txt.gz | gunzip -c | "
            f"awk -F'\\t' 'NR==FNR {{t[$1]=1; next}} ($1 in t) {{print $1\"\\t\"$2}}' {idfile} -")
    names = dict(line.split("\t") for line in r.stdout.strip().splitlines() if line)
    os.unlink(idfile)
    orgs = {}
    for a, b in edges:
        oid, _ = want[ids[b]]
        src = ".".join(reversed(names.get(a, "").split(".")))
        if src:
            orgs.setdefault(oid, set()).add(src)
    # an organization's own domains are not links from elsewhere
    own = {d for o in ORGS for d in o["domains"]}
    store[release] = {"pulled": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "seconds": round(time.time() - t0),
                      "orgs": {k: sorted(v - own) for k, v in orgs.items()}}
    save_sub("weblinks", release, store[release])
    log(f"weblinks {release}: " + ", ".join(f"{k} {len(v)}" for k, v in store[release]["orgs"].items()))


def import_webgraph_tsv(folder):
    """Load release files already filtered by the same awk pattern (backfill)."""
    raw = load_raw()
    store = raw.setdefault("webgraph", {})
    want = {".".join(reversed(d.split("."))): (o["id"], d) for o in ORGS for d in o["domains"]}
    for f in sorted(Path(folder).glob("cc_cc-main-*.tsv")):
        rel = f.stem[3:]
        rows = {}
        for line in f.read_text().splitlines():
            if line.startswith("#"):
                continue
            hc_pos, hc_val, pr_pos, pr_val, rev, n_hosts = line.split("\t")[:6]
            if rev not in want:
                continue
            oid, dom = want[rev]
            rows[dom] = {"org": oid, "hc_pos": int(hc_pos), "hc_val": float(hc_val),
                         "pr_pos": int(pr_pos), "pr_val": float(pr_val), "n_hosts": int(n_hosts)}
        if rows:
            store[rel] = {"rows": rows, "pulled": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)
                          .isoformat(timespec="seconds"), "source": "backfill"}
    save_part("webgraph", raw["webgraph"])
    log(f"webgraph: {len(store)} releases stored")


# ----------------------------------------------------------------- city hall
# Exact, capitalized names for full-text sources (City Hall, Council hearings).
# Case-sensitive, so "within city limits" does not count for City Limits;
# Vital City additionally goes through names_us() to drop "a Vital City ..."
TEXT_NAMES = {
    "cbc": r"Citizens Budget Commission", "cuf": r"Center for an Urban Future",
    "css": r"Community Service Society", "fpi": r"Fiscal Policy Institute",
    "furman": r"Furman Center", "rpa": r"Regional Plan Association", "cj": r"City Journal",
    "gg": r"Gotham Gazette", "cl": r"City Limits",
    "cji": r"Center for (?:Justice|Court) Innovation", "dcj": r"Data Collaborative for Justice",
}


def orgs_named(text):
    """Organizations a text names, with a snippet for Vital City."""
    found = [k for k, p in TEXT_NAMES.items() if re.search(p, text)]
    ctx = ""
    if names_us(text) or "vitalcitynyc.org" in text:
        found.append("vc")
        ctx = us_context(text)
    return found, ctx


def _flatten(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and k in ("text", "description", "title"):
                out.append(v)
            else:
                _flatten(v, out)
    elif isinstance(o, list):
        for v in o:
            _flatten(v, out)
    return out


def collect_cityhall():
    """Every item in the mayor's office newsroom since 2022 (press releases and
    verbatim transcripts; nyc.gov's own index), read in full and checked for
    each organization's name. Unit: one item. Transcripts and releases are kept
    apart in the store so the page can show which is which."""
    raw = load_raw()
    store = raw.setdefault("cityhall", {"items": {}, "done": []})
    done = set(store["done"])
    idx = json.loads(http_get("https://www.nyc.gov/bin/nyc/articlesearch.json?path=/content/nycgov/"
                              "mayors-office/en/news&page=0&limit=5&year=2023", timeout=120))
    res = idx.get("results") or []
    if len(res) < 1000:
        raise SystemExit(f"cityhall: the newsroom index returned {len(res)} items; expected thousands")
    todo = []
    for r in res:
        try:
            d = datetime.strptime(r["articleDate"].strip(), "%B %d, %Y").date()
        except (KeyError, ValueError):
            continue
        if d.year >= 2022 and r["link"] not in done:
            todo.append((r["link"], d.isoformat(), r.get("title", "")))
    log(f"cityhall: {len(res)} newsroom items, {len(todo)} to read")
    fails = [0]

    def read(job):
        link, day, title = job
        path = link.split("/mayors-office/news/", 1)[-1].rsplit(".html", 1)[0]
        url = f"https://www.nyc.gov/content/nycgov/mayors-office/en/news/{path}.model.json"
        for attempt in range(3):
            try:
                txt = " ".join(_flatten(json.loads(http_get(url, timeout=40)), []))
                txt = html_mod.unescape(re.sub(r"<[^>]+>", " ", txt))
                return job, orgs_named(txt)
            except Exception:
                time.sleep(2 * (attempt + 1))
        fails[0] += 1
        return job, None

    n = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for (link, day, title), got in ex.map(read, todo):
            n += 1
            if got is None:
                continue
            found, ctx = got
            done.add(link)
            if found:
                store["items"][link] = {"date": day, "title": title, "orgs": found,
                                        "kind": "transcript" if "ranscript" in title else "release",
                                        "context": ctx, "url": "https://www.nyc.gov" + link}
            if n % 250 == 0:
                store["done"] = sorted(done)
                save_part("cityhall", store)
                log(f"  {n}/{len(todo)} read")
    store["done"] = sorted(done)
    store["pulled"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_part("cityhall", store)
    if todo and fails[0] > 0.2 * len(todo):
        raise SystemExit(f"cityhall: {fails[0]} of {len(todo)} items could not be read")
    log(f"cityhall: {len(store['items'])} items name at least one organization; {fails[0]} unreadable")


# -------------------------------------------------------------- comptroller
def collect_comptroller():
    """The New York City Comptroller's site (reports, testimony, statements),
    searched through its own WordPress index for each organization's exact
    name, then confirmed in the post's text with the same case-sensitive test
    used for City Hall. Unit: one post, dated by publication."""
    raw = load_raw()
    out = {}
    base = "https://comptroller.nyc.gov/wp-json/wp/v2/"
    for o in ORGS:
        pat = TEXT_NAMES.get(o["id"])
        phrases = {"cji": ['"Center for Justice Innovation"', '"Center for Court Innovation"']}.get(
            o["id"], ['"' + (o["name"].replace("NYU ", "")) + '"'])
        seen = {}
        for ph in phrases:
            for kind in ("posts", "pages"):
                page = 1
                while True:
                    url = (f"{base}{kind}?search={urllib.parse.quote(ph)}&per_page=100&page={page}"
                           "&_fields=date,link,title,content")
                    try:
                        items = json.loads(http_get(url, timeout=60))
                    except urllib.error.HTTPError as e:
                        if e.code == 400:      # past the last page
                            break
                        raise
                    for it in items:
                        text = html_mod.unescape(re.sub(r"<[^>]+>", " ", it["content"]["rendered"]))
                        if o["id"] == "vc":
                            hit = names_us(text) or "vitalcitynyc.org" in text
                        else:
                            hit = bool(re.search(pat, text))
                        if hit:
                            ctx = us_context(text) if o["id"] == "vc" else ""
                            seen[it["link"]] = {"date": it["date"][:10], "url": it["link"], "context": ctx.strip(),
                                                "title": html_mod.unescape(it["title"]["rendered"])}
                    if len(items) < 100:
                        break
                    page += 1
                    time.sleep(0.5)
        out[o["id"]] = sorted(seen.values(), key=lambda x: x["date"])
        log(f"comptroller: {o['id']} {len(seen)} posts")
    if not any(out.values()):
        raise SystemExit("comptroller: nothing found for any organization; the search is broken")
    raw["comptroller"] = {"pulled": datetime.now(timezone.utc).isoformat(timespec="seconds"), "orgs": out}
    save_part("comptroller", raw["comptroller"])


# ----------------------------------------------------------------- council
def collect_council(corpus=None):
    """City Council hearings: every transcript and written-testimony file in
    the nyc-council-hearings corpus (Legistar, 2024 session onward), checked
    for each organization's exact name. Unit: one hearing (all of its files),
    dated by the hearing. Stated meetings are left out; they are the Council's
    floor votes, not hearings. Runs on the Mac, where the corpus lives."""
    corpus = Path(corpus or ROOT.parent / "nyc-council-hearings")
    hearings = json.loads((corpus / "docs" / "data" / "hearings.json").read_text())
    by_file = {}
    for h in hearings:
        if h.get("stated"):
            continue
        for d in h["docs"]:
            m = re.search(r"ID=(\d+)", d["u"])
            if m:
                by_file.setdefault(m.group(1), []).append((h, d))
    hits = {}
    for f in (corpus / "data" / "text").glob("*.txt"):
        fid = f.name.split(".")[0]
        if fid not in by_file:
            continue
        found, ctx = orgs_named(f.read_text(errors="replace"))
        for h, d in by_file[fid]:
            for oid in found:
                row = hits.setdefault(oid, {}).setdefault(h["id"], {
                    "date": h["date"], "subject": h.get("subject", ""), "committees": h.get("committees", []),
                    "kinds": [], "url": d["u"], "context": ""})
                if d["k"] not in row["kinds"]:
                    row["kinds"].append(d["k"])
                if oid == "vc" and ctx and not row["context"]:
                    row["context"] = ctx
    years = sorted({h["date"][:4] for h in hearings if not h.get("stated")})
    raw = load_raw()
    raw["council"] = {"pulled": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "coverage": {y: sum(1 for h in hearings if h["date"][:4] == y and not h.get("stated"))
                                   for y in years},
                      "orgs": {k: sorted(v.values(), key=lambda x: x["date"]) for k, v in hits.items()}}
    save_part("council", raw["council"])
    log("council: " + ", ".join(f"{k} {len(v)}" for k, v in hits.items()))


# ----------------------------------------------------------------- scholar
def import_scholar(path):
    """Google Scholar counts, gathered in a browser (Scholar refuses scripts).

    Input: {"<domain>|<year>": {"n": int, "t": "About 40 results"}, ...} from
    the query "\\"<domain>\\"" limited to one publication year. The raw result
    line is kept so every number can be traced to what Scholar printed."""
    raw = load_raw()
    data = json.loads(Path(path).read_text())
    store = raw.setdefault("scholar", {"cells": {}, "pulled": {}})
    stamp = re.search(r"(\d{4}-\d{2}-\d{2})", Path(path).name)
    for k, v in data.items():
        store["cells"][k] = {"n": int(v["n"]), "t": v.get("t", "")}
        store["pulled"][k] = v.get("pulled") or (stamp.group(1) if stamp else
                                                 datetime.now(timezone.utc).date().isoformat())
    # the citing works themselves, for the evidence list: the growth
    # dashboard's own Scholar pull already reads Vital City's result pages
    g = PRIV / "growth.json"
    if g.exists():
        sc = json.loads(g.read_text()).get("scholar_citations") or {}
        works = [{"title": c.get("title", ""), "by": c.get("authors", ""), "confidence": c.get("confidence", "")}
                 for c in sc.get("citations", []) if c.get("title")]
        if works:
            store["list"] = works
    save_part("scholar", raw["scholar"])
    log(f"scholar: {len(data)} cells imported")


# ----------------------------------------------------------------- readers
# New York government only: city agencies and the Council (nyc.gov and its
# subdomains), the state (ny.gov, the Legislature, the old state.ny.us
# addresses), the state courts, the five district attorneys, the NYPD's own
# domain and the regional authorities. Federal and other cities' .gov
# addresses are left out: the question is reach into New York's government.
GOV_EMAIL = re.compile(
    r"@(?:[\w-]+\.)*(?:nyc\.gov|ny\.gov|nysenate\.gov|nyassembly\.gov|state\.ny\.us|"
    r"nycourts\.gov|nypd\.org|manhattanda\.org|brooklynda\.org|queensda\.org|"
    r"mta\.info|panynj\.gov|nyccfb\.info)$", re.I)
NYC_EMAIL = re.compile(r"@(?:[\w-]+\.)*(?:nyc\.gov|nypd\.org|manhattanda\.org|brooklynda\.org|"
                       r"queensda\.org|nyccfb\.info)$", re.I)


def collect_readers():
    """Government readers of the newsletter over time (Vital City only).

    Counted from the subscriber file the contact tool builds: every address on
    a government domain, with the day it subscribed and, if it left, the day it
    unsubscribed. A person counts in a month if they had subscribed by its last
    day and had not unsubscribed by then. Work addresses only: officials who
    read on a personal address are invisible here, which undercounts but does
    so steadily."""
    src = PRIV / "people.json"
    if not src.exists():
        raise SystemExit("readers: private/people.json missing (run build_network.py)")
    people = json.loads(src.read_text())
    if isinstance(people, dict):
        people = people.get("people") or people.get("rows") or []
    rows = []
    for p in people:
        emails = p.get("emails") or ([p["e"]] if p.get("e") else [])
        gov = [e for e in emails if GOV_EMAIL.search(e or "")]
        # subscribers only, past or present: a contact-list entry with a
        # government address but no subscription date never received anything
        if not gov or not p.get("since") or not (p.get("mem") or p.get("unsub")):
            continue
        rows.append({"since": p["since"][:10], "unsub": bool(p.get("unsub")),
                     "unsub_date": (p.get("udate") or "")[:10],
                     "nyc": any(NYC_EMAIL.search(e) for e in gov)})
    if len(rows) < 50:
        raise SystemExit(f"readers: only {len(rows)} government subscribers found; the source looks wrong")
    raw = load_raw()
    raw["readers"] = {"pulled": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows}
    save_part("readers", raw["readers"])
    log(f"readers: {len(rows)} government addresses")


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what")
    ap.add_argument("arg", nargs="*")
    ap.add_argument("--years", default=f"2022-{datetime.now().year}")
    a = ap.parse_args()
    ys = years_arg(a.years)
    if a.what == "press":
        collect_press(ys)
    elif a.what == "verify-press":
        verify_press(recheck=tuple(a.arg))
    elif a.what == "record":
        collect_record(ys)
    elif a.what == "verify-record":
        verify_record()
    elif a.what == "courts":
        collect_courts()
    elif a.what == "wiki":
        collect_wiki()
    elif a.what == "wiki-first-adds":
        wiki_first_adds(*(a.arg or ["vc"]))
    elif a.what == "webgraph":
        rels = a.arg or cc_releases()[-1:]
        collect_webgraph(rels)
    elif a.what == "webgraph-new":
        # only releases newer than the newest one stored: the backfill took
        # one release per quarter on purpose, and a monthly refresh should not
        # quietly fill in the months between
        stored = load_raw().get("webgraph", {})
        newest = max((release_end(r) for r in stored), default=(2021, 1))
        collect_webgraph([r for r in cc_releases() if release_end(r) > newest])
    elif a.what == "weblinks":
        for rel in a.arg:
            collect_weblinks(rel)
    elif a.what == "weblinks-new":
        # the newest release, if it is not stored yet: the build uses the
        # latest release ending in each year, so this keeps the current year fresh
        newest = cc_releases()[-1]
        if newest not in load_raw().get("weblinks", {}):
            collect_weblinks(newest)
    elif a.what == "webgraph-import":
        import_webgraph_tsv(a.arg[0])
    elif a.what == "scholar-import":
        import_scholar(a.arg[0])
    elif a.what == "comptroller":
        collect_comptroller()
    elif a.what == "cityhall":
        collect_cityhall()
    elif a.what == "council":
        collect_council(a.arg[0] if a.arg else None)
    elif a.what == "readers":
        collect_readers()
    else:
        raise SystemExit(f"unknown collector {a.what}")


if __name__ == "__main__":
    main()
