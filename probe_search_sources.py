#!/usr/bin/env python3
"""Probe what search-demand data is actually available to us.

READ-ONLY. Writes nothing, changes nothing, touches no dashboard file. It asks
each source a question and prints what came back, so we decide what to build on
real answers instead of on what the documentation implies.

Two questions:

  1. SEARCH CONSOLE — we currently pull only the `query` dimension of web
     search. Which other report types and dimensions actually return rows for
     this property? Discover and Google News only report if Google has surfaced
     the site there, and a URL-prefix property covers less than a domain
     property, so this cannot be answered from the docs.

  2. GOOGLE TRENDS — Search Console has a structural blind spot: it only shows
     searches Vital City ALREADY ranks for. A subject the site has never covered
     is invisible to it by construction. Trends does not have that limit. It has
     no official API, so this probe tests whether the unofficial endpoints
     respond and whether New York City geography is available.

USAGE
    GA4_CREDS_JSON='<service-account json>' python3 probe_search_sources.py
"""
import json, os, sys, base64, time, urllib.request, urllib.parse, urllib.error
from datetime import date, timedelta

SITE = "https://www.vitalcitynyc.org/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"}


def ok(m):   print(f"  [OK]    {m}")
def none(m): print(f"  [EMPTY] {m}")
def bad(m):  print(f"  [FAIL]  {m}")


# ---------------------------------------------------------------- Search Console
def sc_token():
    raw = os.environ.get("GA4_CREDS_JSON") or ""
    if not raw:
        return None
    if not raw.lstrip().startswith("{"):
        try: raw = base64.b64decode(raw).decode()
        except Exception: return None
    creds = json.loads(raw)
    import hmac, hashlib
    now = int(time.time())
    hdr = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
    claim = base64.urlsafe_b64encode(json.dumps({
        "iss": creds["client_email"],
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600, "iat": now}).encode()).rstrip(b"=")
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        key = serialization.load_pem_private_key(creds["private_key"].encode(), password=None)
        sig = base64.urlsafe_b64encode(
            key.sign(hdr + b"." + claim, padding.PKCS1v15(), hashes.SHA256())).rstrip(b"=")
    except Exception as e:
        bad(f"could not sign the JWT: {e}"); return None
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": (hdr + b"." + claim + b"." + sig).decode()}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                "https://oauth2.googleapis.com/token", data=body), timeout=30) as r:
            return json.loads(r.read())["access_token"]
    except Exception as e:
        bad(f"token exchange failed: {e}"); return None


def sc_query(token, body):
    enc = urllib.parse.quote(SITE, safe="")
    req = urllib.request.Request(
        f"https://searchconsole.googleapis.com/webmasters/v3/sites/{enc}/searchAnalytics/query",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read()).get("rows", []) or []


def probe_search_console():
    print("\n" + "=" * 72)
    print("1. GOOGLE SEARCH CONSOLE — what does this property actually return?")
    print("=" * 72)
    token = sc_token()
    if not token:
        bad("no credentials. Set GA4_CREDS_JSON (the service-account key).")
        return
    end = (date.today() - timedelta(days=3)).isoformat()      # SC lags ~2-3 days
    start = (date.today() - timedelta(days=93)).isoformat()
    print(f"  window {start} -> {end}\n")

    # Which sites can this service account even see? A mismatch here (URL-prefix
    # vs domain property) silently limits everything downstream.
    try:
        req = urllib.request.Request("https://searchconsole.googleapis.com/webmasters/v3/sites",
                                     headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=30) as r:
            sites = json.loads(r.read()).get("siteEntry", [])
        print("  properties visible to this service account:")
        for s in sites:
            mark = "  <-- the one we query" if s.get("siteUrl") == SITE else ""
            print(f"    {s.get('permissionLevel',''):<22} {s.get('siteUrl')}{mark}")
        if not any(s.get("siteUrl") == SITE for s in sites):
            bad(f"{SITE} is NOT in this list — we may be querying the wrong property")
        print()
    except Exception as e:
        bad(f"could not list properties: {e}\n")

    # (label, request body). Each is a thing we do not currently pull.
    TESTS = [
        ("web / query  (what we pull today — baseline)",
         {"startDate": start, "endDate": end, "dimensions": ["query"], "rowLimit": 5}),
        ("DISCOVER  (whole channel, currently invisible to us)",
         {"startDate": start, "endDate": end, "type": "discover", "rowLimit": 5}),
        ("DISCOVER / page  (which pieces Discover surfaces)",
         {"startDate": start, "endDate": end, "type": "discover",
          "dimensions": ["page"], "rowLimit": 5}),
        ("GOOGLE NEWS  (news tab)",
         {"startDate": start, "endDate": end, "type": "googleNews", "rowLimit": 5}),
        ("news search appearance",
         {"startDate": start, "endDate": end, "type": "news", "rowLimit": 5}),
        ("web / page  (search performance per piece)",
         {"startDate": start, "endDate": end, "dimensions": ["page"], "rowLimit": 5}),
        ("web / query+page  (fixes the fuzzy title matcher)",
         {"startDate": start, "endDate": end, "dimensions": ["query", "page"], "rowLimit": 5}),
        ("web / query+date  (is a search rising or fading?)",
         {"startDate": start, "endDate": end, "dimensions": ["query", "date"], "rowLimit": 5}),
        ("web / country  (is the demand actually New York?)",
         {"startDate": start, "endDate": end, "dimensions": ["country"], "rowLimit": 5}),
        ("web / device",
         {"startDate": start, "endDate": end, "dimensions": ["device"], "rowLimit": 5}),
        ("web / searchAppearance",
         {"startDate": start, "endDate": end, "dimensions": ["searchAppearance"], "rowLimit": 5}),
    ]
    for label, body in TESTS:
        try:
            rows = sc_query(token, body)
            if not rows:
                none(f"{label} — request succeeded, zero rows")
                continue
            ok(f"{label} — {len(rows)} row(s)")
            for r in rows[:3]:
                keys = " | ".join(str(k) for k in (r.get("keys") or ["(totals)"]))
                print(f"            {keys[:70]:<70} clicks={int(r.get('clicks',0)):>6} "
                      f"impr={int(r.get('impressions',0)):>8}")
        except urllib.error.HTTPError as e:
            bad(f"{label} — HTTP {e.code}: {e.read().decode('utf-8','ignore')[:120]}")
        except Exception as e:
            bad(f"{label} — {type(e).__name__}: {e}")
        time.sleep(0.4)


# --------------------------------------------------------------- Google Trends
def probe_trends():
    print("\n" + "=" * 72)
    print("2. GOOGLE TRENDS — demand we have never ranked for")
    print("=" * 72)
    print("  Search Console only reports searches Vital City already appears for.")
    print("  A subject the site has never covered cannot show up there at all.")
    print("  Trends has no official API; these are the unofficial endpoints.\n")

    # a. Trending-now RSS. Officially documented geo values are countries and
    #    some regions; whether New York state resolves is the open question.
    for geo, label in [("US", "United States"), ("US-NY", "New York state")]:
        url = f"https://trends.google.com/trending/rss?geo={geo}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                body = r.read().decode("utf-8", "ignore")
            import re
            items = re.findall(r"<title>(.*?)</title>", body)[1:]     # first is the feed title
            if items:
                ok(f"trending RSS geo={geo} ({label}) — {len(items)} terms")
                print("            " + "; ".join(i[:28] for i in items[:8]))
            else:
                none(f"trending RSS geo={geo} ({label}) — responded, no items")
        except Exception as e:
            bad(f"trending RSS geo={geo} ({label}) — {type(e).__name__}: {e}")
        time.sleep(0.5)

    # b. The interest-over-time endpoint, which is what would let us compare a
    #    topic's trajectory. Frequently rate-limited (429) without a session
    #    cookie; a failure here is informative, not fatal.
    try:
        payload = {"comparisonItem": [{"keyword": "nyc housing", "geo": "US-NY", "time": "today 3-m"}],
                   "category": 0, "property": ""}
        url = ("https://trends.google.com/trends/api/explore?hl=en-US&tz=240&req="
               + urllib.parse.quote(json.dumps(payload)))
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            txt = r.read().decode("utf-8", "ignore")
        ok(f"explore endpoint responded ({len(txt)} bytes) — a token flow would work from here")
    except urllib.error.HTTPError as e:
        bad(f"explore endpoint — HTTP {e.code} (429 = rate-limited, the usual answer without a cookie)")
    except Exception as e:
        bad(f"explore endpoint — {type(e).__name__}: {e}")

    print("\n  If the RSS works but explore does not, the practical options are:")
    print("    - trending-now RSS for a daily 'what is spiking' signal (free, no key)")
    print("    - Google Keyword Planner for absolute volumes (free, needs an Ads account)")
    print("    - a paid tool (Semrush/Ahrefs) for volumes plus trend, no scraping")


if __name__ == "__main__":
    print("PROBE — read-only. Nothing is written and no dashboard file is touched.")
    probe_search_console()
    probe_trends()
    print("\nDone. Nothing was changed.")
