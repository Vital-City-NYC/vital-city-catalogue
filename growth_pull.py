#!/usr/bin/env python3
"""Pull every signal that feeds the growth dashboard, write private/growth.json.

Signups-first. Sections that need credentials we don't have yet (GA4, Search
Console, social) are emitted as `{available:false, reason:"..."}` stubs so the
dashboard can render a "Connect this source" card without crashing.

Sources wired now (using existing keys):
  - Mailchimp: daily signups+unsubs (180d), recent campaigns (12) w/ stats,
               rating distribution, top email domains, total subscribers
  - Ghost:     posts (last 90d), publish cadence
  - Google News RSS: items mentioning "Vital City" + NYC disambiguator
  - Reddit RSS:      threads mentioning "Vital City" NYC

Stubbed for next iteration (need creds):
  - GA4 (service-account JSON + property id)
  - Google Search Console (service-account or OAuth refresh token)
  - X (@vitalcitynyc) — needs paid API or paid mention service
  - Instagram (@vitalcitynyc) — needs FB business token

Output: private/growth.json (consumed by encrypt_growth.py).
"""
from __future__ import annotations
import base64, hashlib, hmac, json, os, re, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
OUT  = PRIV / "growth.json"

UA = "VitalCityGrowthDashboard/1.0 (+https://www.vitalcitynyc.org)"


def log(msg): print(msg, file=sys.stderr)


def http_get(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------------------------------------------------------- Mailchimp
def mailchimp_key():
    k = os.environ.get("MAILCHIMP_KEY")
    if k: return k.strip()
    f = PRIV / ".mailchimp_key"
    return f.read_text().strip() if f.exists() else ""


def mc_get(path, key, dc):
    url = f"https://{dc}.api.mailchimp.com/3.0{path}"
    auth = base64.b64encode(f"anystring:{key}".encode()).decode()
    return json.loads(http_get(url, headers={"Authorization": "Basic " + auth}, timeout=120))


def pull_mailchimp():
    key = mailchimp_key()
    if not key:
        return {"available": False, "reason": "MAILCHIMP_KEY not set"}
    dc = key.split("-")[-1]
    list_id = os.environ.get("MAILCHIMP_LIST", "ec30bf0c4b")
    out: dict = {"available": True}

    # List summary (total subs + recent stats)
    try:
        lst = mc_get(f"/lists/{list_id}", key, dc)
        out["total_subscribers"] = lst.get("stats", {}).get("member_count", 0)
        out["unsubscribed_total"] = lst.get("stats", {}).get("unsubscribe_count", 0)
        out["avg_open_rate"]  = round((lst.get("stats", {}).get("open_rate")  or 0), 2)
        out["avg_click_rate"] = round((lst.get("stats", {}).get("click_rate") or 0), 2)
    except Exception as e:
        log(f"  mailchimp list summary failed: {e}")

    # Daily activity (subs/unsubs by day) — last 180 days.
    # Subs: computed from people.json `since` dates (Mailchimp's /activity endpoint
    # only counts direct-MC-form signups and grossly understates the real number
    # because most VC signups arrive via the Ghost signup form). Unsubs/opens/clicks
    # are taken from Mailchimp /activity which is accurate for those.
    rows_by_day = {}
    try:
        act = mc_get(f"/lists/{list_id}/activity?count=180", key, dc).get("activity", [])
        for a in act:
            d = a.get("day")
            if not d: continue
            rows_by_day[d] = {
                "d": d, "subs": 0,
                "unsubs": int(a.get("unsubs") or 0),
                "opens":  int(a.get("unique_opens") or 0),
                "clicks": int(a.get("recipient_clicks") or 0),
            }
    except Exception as e:
        log(f"  mailchimp activity failed: {e}")

    # Overlay accurate signup counts from people.json (canonical merged dataset)
    pj = PRIV / "people.json"
    if pj.exists():
        try:
            people = json.loads(pj.read_text())
            today = datetime.now(timezone.utc).date()
            cutoff = (today - timedelta(days=180)).isoformat()
            for p in people:
                # mem==1 and a real signup date within window
                if not p.get("mem"): continue
                if p.get("unsub"): continue
                s = (p.get("since") or "")[:10]
                if not s or s < cutoff: continue
                row = rows_by_day.setdefault(s, {"d": s, "subs": 0, "unsubs": 0, "opens": 0, "clicks": 0})
                row["subs"] += 1
        except Exception as e:
            log(f"  people.json overlay failed: {e}")

    out["daily_activity"] = sorted(rows_by_day.values(), key=lambda r: r["d"])

    # Recent campaigns (last 12 sends) with per-send stats
    try:
        camp = mc_get(
            f"/campaigns?status=sent&list_id={list_id}&count=12"
            f"&sort_field=send_time&sort_dir=DESC&fields=campaigns.id,"
            f"campaigns.settings.subject_line,campaigns.send_time,campaigns.emails_sent,"
            f"campaigns.report_summary",
            key, dc).get("campaigns", [])
        camp_out = []
        for c in camp:
            rs = c.get("report_summary") or {}
            camp_out.append({
                "id":       c.get("id"),
                "subject":  (c.get("settings") or {}).get("subject_line", ""),
                "sent":     (c.get("send_time") or "")[:10],
                "sent_to":  c.get("emails_sent") or 0,
                "open_pct": round((rs.get("open_rate")  or 0) * 100, 1),
                "click_pct":round((rs.get("click_rate") or 0) * 100, 1),
                "unsubs":   rs.get("unsubscribed") or rs.get("unsubscribes") or 0,
            })
        out["campaigns"] = camp_out
    except Exception as e:
        log(f"  mailchimp campaigns failed: {e}")
        out["campaigns"] = []

    # Rating distribution + top email domains — read from cached engagement CSV
    eng = PRIV / "engagement_source.csv"
    rating, domains = Counter(), Counter()
    open_buckets = Counter()    # 0-25-50-75-100 open-rate bands
    if eng.exists():
        import csv
        with open(eng) as f:
            r = csv.DictReader(f)
            for row in r:
                em = (row.get("Email") or "").lower().strip()
                if "@" in em: domains[em.split("@", 1)[1]] += 1
                try: rating[int(row.get("Rating") or 0)] += 1
                except: pass
                try:
                    op = int(row.get("Open Rate") or 0)
                    if op == 0: open_buckets["0%"] += 1
                    elif op <= 25: open_buckets["1-25%"] += 1
                    elif op <= 50: open_buckets["26-50%"] += 1
                    elif op <= 75: open_buckets["51-75%"] += 1
                    else:          open_buckets["76-100%"] += 1
                except: pass
    out["rating_dist"]  = {str(k): rating[k] for k in sorted(rating)}
    out["open_buckets"] = {k: open_buckets[k] for k in ["0%", "1-25%", "26-50%", "51-75%", "76-100%"]}
    out["top_domains"]  = [{"d": d, "n": n} for d, n in domains.most_common(12)]
    out["engaged_share"] = round(((rating.get(4, 0) + rating.get(5, 0)) / max(sum(rating.values()), 1)), 3)
    return out


# -------------------------------------------------------------------- Ghost
GHOST_CONTENT_KEY = "dd8e178e9ddfc883537e71dd07"   # public, same as scrape.py
GHOST_API = "https://vital-city.ghost.io/ghost/api/content"


def pull_ghost():
    out = {"available": True, "posts": []}
    since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    flt = urllib.parse.quote(f"published_at:>={since}")
    page = 1
    while True:
        try:
            url = (f"{GHOST_API}/posts/?key={GHOST_CONTENT_KEY}&filter={flt}"
                   f"&include=authors,tags&limit=100&page={page}&fields=id,title,slug,url,published_at,reading_time")
            data = json.loads(http_get(url))
        except Exception as e:
            log(f"  ghost posts failed: {e}")
            break
        for p in data.get("posts", []):
            out["posts"].append({
                "title": p.get("title"),
                "url":   p.get("url"),
                "published": (p.get("published_at") or "")[:10],
                "reading_time": p.get("reading_time") or 0,
                "primary_author": ((p.get("primary_author") or {}).get("name")) or "",
                "tags": [t.get("name") for t in (p.get("tags") or []) if t.get("name")],
            })
        meta = (data.get("meta") or {}).get("pagination") or {}
        if not meta.get("next"): break
        page = meta["next"]
    out["posts"].sort(key=lambda p: p["published"], reverse=True)
    # Counts
    today = datetime.now(timezone.utc).date()
    def _cnt(days):
        cut = (today - timedelta(days=days)).isoformat()
        return sum(1 for p in out["posts"] if p["published"] >= cut)
    out["count_7"]  = _cnt(7)
    out["count_30"] = _cnt(30)
    out["count_90"] = len(out["posts"])
    return out


# ------------------------------------------------------------- Press / Reddit (free RSS)
def _xml_text(el, tag):
    e = el.find(tag)
    return (e.text or "").strip() if e is not None and e.text else ""


def pull_press():
    # Google News RSS — quoted brand + NYC disambiguation; -site exclusions reduce false hits
    queries = [
        # The brand spelled out (with NYC disambiguator)
        ('"Vital City" (NYC OR "New York" OR Mamdani OR Adams OR Bragg OR NYCHA)', "google-news"),
        # Direct links to the site
        ('site:vitalcitynyc.org', "google-news-direct"),
    ]
    items = []
    for q, src in queries:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en"
        try:
            xml = http_get(url, timeout=30)
            root = ET.fromstring(xml)
            for it in root.findall(".//item"):
                items.append({
                    "title":   _xml_text(it, "title"),
                    "url":     _xml_text(it, "link"),
                    "source":  _xml_text(it, "source") or "Google News",
                    "published": _xml_text(it, "pubDate"),
                    "snippet": re.sub(r"<[^>]+>", "", _xml_text(it, "description"))[:240],
                    "channel": src,
                })
        except Exception as e:
            log(f"  google news ({src}) failed: {e}")

    # Reddit search RSS — same brand, NYC disambiguator
    try:
        rq = urllib.parse.quote('"Vital City" NYC')
        rurl = f"https://www.reddit.com/search.rss?q={rq}&sort=new"
        xml = http_get(rurl, timeout=30, headers={"User-Agent": UA})
        root = ET.fromstring(xml)
        ns = "{http://www.w3.org/2005/Atom}"
        for it in root.findall(f".//{ns}entry"):
            link_el = it.find(f"{ns}link")
            items.append({
                "title":   _xml_text(it, f"{ns}title"),
                "url":     (link_el.get("href") if link_el is not None else ""),
                "source":  "Reddit",
                "published": _xml_text(it, f"{ns}updated"),
                "snippet": "",
                "channel": "reddit",
            })
    except Exception as e:
        log(f"  reddit rss failed: {e}")

    # Drop self-references — we want mentions OF Vital City IN other outlets,
    # not Vital City's own articles (Google News indexes vitalcitynyc.org too).
    def _is_self(it):
        blob = (it.get("source", "") + " " + it.get("url", "")).lower()
        return ("vitalcitynyc" in blob
                or blob.endswith("vital city")
                or "source>vital city<" in blob
                or it.get("source", "").strip().lower() == "vital city")
    # Require an external outlet to actually mention "vital city" by name.
    def _mentions_us(it):
        blob = (it.get("title", "") + " " + it.get("snippet", "")).lower()
        return "vital city" in blob
    items = [it for it in items if not _is_self(it) and _mentions_us(it)]

    # De-dupe by URL, keep newest
    seen, dedup = set(), []
    for it in items:
        u = it.get("url", "").split("?", 1)[0]
        if u in seen: continue
        seen.add(u); dedup.append(it)

    # Parse published into sortable ISO; keep both
    def _parse(p):
        for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z",
                    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(p, fmt)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                pass
        return ""
    for it in dedup:
        it["published_iso"] = _parse(it.get("published", ""))
    dedup.sort(key=lambda it: it.get("published_iso") or "", reverse=True)
    return dedup[:60]


# ------------------------------------------------------------------------ main
def main():
    PRIV.mkdir(parents=True, exist_ok=True)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mailchimp": pull_mailchimp(),
        "ghost":     pull_ghost(),
        "press":     pull_press(),
        # Sources blocked on credentials Josh hasn't set up yet — dashboard renders
        # a "Connect this source" placeholder card with the exact setup steps.
        "ga4": {
            "available": False,
            "reason": "GA4 service-account JSON + property ID not configured",
            "setup": [
                "1) In Google Cloud, enable the Google Analytics Data API.",
                "2) Create a service account; download the JSON key.",
                "3) Add the service account email (xx@yy.iam.gserviceaccount.com) to GA4 with Viewer role.",
                "4) Copy the GA4 property numeric ID (Admin -> Property Settings).",
                "5) Add GA4_CREDS_JSON (base64-encoded JSON) and GA4_PROPERTY_ID as GitHub secrets.",
            ],
        },
        "search_console": {
            "available": False,
            "reason": "Search Console service-account not configured",
            "setup": [
                "1) Same service account as GA4 (or a separate one) — enable Search Console API.",
                "2) In Search Console, add the service-account email as a user on www.vitalcitynyc.org.",
                "3) Add GSC_CREDS_JSON and GSC_SITE_URL (e.g. sc-domain:vitalcitynyc.org) as GitHub secrets.",
            ],
        },
        "x_mentions": {
            "available": False,
            "reason": "X API requires a paid plan (~$100/mo); no reliable free option",
            "setup": [
                "Options: (a) pay for X Basic API and add X_BEARER_TOKEN; ",
                "(b) use a paid social-listening service (Brand24, Mention, Notify) and feed via RSS; ",
                "(c) skip and monitor manually.",
            ],
        },
        "instagram": {
            "available": False,
            "reason": "Instagram Graph API token not configured",
            "setup": [
                "1) Convert @vitalcitynyc to an Instagram Business account linked to a Facebook Page.",
                "2) In Meta for Developers, create an app, get a long-lived Page access token with instagram_basic.",
                "3) Add IG_ACCESS_TOKEN and IG_USER_ID as GitHub secrets.",
            ],
        },
    }
    OUT.write_text(json.dumps(out, indent=2))
    size_kb = OUT.stat().st_size // 1024
    mc = out["mailchimp"]; gh = out["ghost"]
    log(f"wrote {OUT.name} ({size_kb} KB)")
    if mc.get("available"):
        log(f"  mailchimp: {mc.get('total_subscribers'):,} subs · {len(mc.get('daily_activity', []))} activity days · {len(mc.get('campaigns', []))} campaigns")
    if gh.get("available"):
        log(f"  ghost:     {gh.get('count_90')} posts in last 90d ({gh.get('count_7')} in 7d)")
    log(f"  press:     {len(out['press'])} items")


if __name__ == "__main__":
    main()
