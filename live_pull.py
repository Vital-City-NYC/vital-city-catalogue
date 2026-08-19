#!/usr/bin/env python3
"""Pull the FAST signals for the live growth PWA, write private/live.json.

This is the real-time-ish companion to growth_pull.py. Where growth_pull makes
hundreds of API calls twice a day and builds the deep dashboard, this makes a
couple of dozen cheap calls every 20 minutes and answers four questions:

    what is happening on the site right now,
    how is today going against a normal day,
    how is this week going against last week,
    and what changed in the last 28 days.

Everything the deep dashboard already answers well (cohorts, benchmarks,
engagement leaderboards, press, donors by name) stays in growth.json; the PWA
reads both files and links into the full dashboard for the rest.

Sources
  GA4 (service account)   realtime active users + pages being read right now;
                          today so far vs the same weekday last week; 28 daily
                          rows of users/views; this week's posts with views
  Ghost admin             members total + new today/7d/28d by day; posts
                          published in the last 7 days; the latest post
  Mailchimp               list total; signups and unsubscribes by day (28d)
  Donorbox                gifts today / 7d / 28d (count + amount)
  Bluesky + LinkedIn      follower counts (public), vs data/social_history.json
  Google News RSS         mentions of "Vital City" in the last 48h

Every source is wrapped: a failure writes {available:false, reason} for that
block and the run still succeeds, so one dead API never blanks the app. The
run FAILS LOUD only if nothing at all came back — per house rule, an empty
pull must never exit 0.

Output: private/live.json  (encrypt_live.py turns it into live.enc)
"""
from __future__ import annotations
import base64, json, os, re, sys, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
OUT  = PRIV / "live.json"
SOCIAL_HISTORY = ROOT / "data" / "social_history.json"

# Reuse the battle-tested helpers rather than re-implement auth.
sys.path.insert(0, str(ROOT))
from growth_pull import (log, http_get, mailchimp_key, mc_get, _ghost_admin_token,
                         GHOST_ADMIN_API, _ga4_access_token, pull_bluesky_profile,
                         pull_linkedin_followers, donorbox_creds)

# All "today" logic is New York time — that is the day the newsroom lives in.
try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:          # pragma: no cover
    NY = timezone(timedelta(hours=-4))

NOW_UTC = datetime.now(timezone.utc)
NOW_NY  = NOW_UTC.astimezone(NY)
TODAY   = NOW_NY.date()
DAYS    = 28


def ny_day_bounds_utc(d: date):
    """UTC ISO bounds for a New York calendar day."""
    start = datetime(d.year, d.month, d.day, tzinfo=NY).astimezone(timezone.utc)
    end   = start + timedelta(days=1)
    return start, end


def day_list(n=DAYS):
    return [(TODAY - timedelta(days=i)) for i in range(n - 1, -1, -1)]


def safe(name, fn, *a, **kw):
    try:
        r = fn(*a, **kw)
        if isinstance(r, dict) and "available" not in r:
            r["available"] = True
        return r
    except Exception as e:
        log(f"  {name} failed: {type(e).__name__}: {str(e)[:160]}")
        return {"available": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}


# ------------------------------------------------------------------ GA4
def _ga4_creds():
    prop = os.environ.get("GA4_PROPERTY_ID", "").strip()
    raw  = os.environ.get("GA4_CREDS_JSON", "").strip()
    if not prop or not raw:
        raise RuntimeError("GA4_PROPERTY_ID / GA4_CREDS_JSON not configured")
    try:
        creds = json.loads(base64.b64decode(raw))
    except Exception:
        creds = json.loads(raw)
    return prop, creds


def _ga4_post(prop, token, method, body):
    req = urllib.request.Request(
        f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:{method}",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _rows(rep):
    for row in rep.get("rows") or []:
        yield ([d["value"] for d in row.get("dimensionValues") or []],
               [m["value"] for m in row.get("metricValues") or []])


ARTICLE_SKIP = re.compile(r"^/(?:$|tag/|author/|about|search|page/|newsletter|members|signin|signup|subscribe|donate|events?|podcast|issues?/?$|category/|archive|privacy|contact)")

def _pretty_path(p):
    p = (p or "/").split("?")[0]
    return p if p.startswith("/") else "/" + p

def _is_article(p):
    return not ARTICLE_SKIP.match(p) and p.count("/") >= 2 and len(p) > 3


def pull_ga4_live():
    prop, creds = _ga4_creds()
    token = _ga4_access_token(creds)
    out = {"property": prop}

    # 1. Right now: active users in the last 30 minutes, and the pages they are on.
    rt = _ga4_post(prop, token, "runRealtimeReport", {
        "metrics": [{"name": "activeUsers"}],
        "dimensions": [{"name": "unifiedScreenName"}],
        "limit": 12,
        "orderBys": [{"metric": {"metricName": "activeUsers"}, "desc": True}],
    })
    pages = [{"title": d[0], "active": int(m[0])} for d, m in _rows(rt)]
    rt_tot = _ga4_post(prop, token, "runRealtimeReport", {"metrics": [{"name": "activeUsers"}]})
    active = sum(int(m[0]) for _, m in _rows(rt_tot)) or 0
    # 5-minute buckets so the app can draw the last half hour
    rt_min = _ga4_post(prop, token, "runRealtimeReport", {
        "metrics": [{"name": "activeUsers"}],
        "dimensions": [{"name": "minutesAgo"}],
    })
    mins = {int(d[0]): int(m[0]) for d, m in _rows(rt_min)}
    out["now"] = {"active_users": active,
                  "pages": pages,
                  "by_minute": [mins.get(i, 0) for i in range(29, -1, -1)]}   # oldest → newest

    # 2. Today so far, and the same weekday last week (whole day) for context.
    #    GA4 "today" is in the property's timezone (New York for this property).
    tod = _ga4_post(prop, token, "runReport", {
        "dateRanges": [{"startDate": "today", "endDate": "today"},
                       {"startDate": "7daysAgo", "endDate": "7daysAgo"},
                       {"startDate": "yesterday", "endDate": "yesterday"}],
        "metrics": [{"name": "totalUsers"}, {"name": "screenPageViews"}, {"name": "sessions"}],
    })
    ranges = {"today": (0, 0, 0), "same_day_last_week": (0, 0, 0), "yesterday": (0, 0, 0)}
    keymap = {"date_range_0": "today", "date_range_1": "same_day_last_week", "date_range_2": "yesterday"}
    for d, m in _rows(tod):
        k = keymap.get(d[0] if d else "date_range_0", "today")
        ranges[k] = (int(m[0]), int(m[1]), int(m[2]))
    out["today"] = {k: {"users": v[0], "views": v[1], "sessions": v[2]} for k, v in ranges.items()}

    # Hour-by-hour today vs the same weekday last week — lets the app say
    # "ahead of / behind a normal Tuesday at this hour" honestly.
    hrs = _ga4_post(prop, token, "runReport", {
        "dateRanges": [{"startDate": "today", "endDate": "today"},
                       {"startDate": "7daysAgo", "endDate": "7daysAgo"}],
        "dimensions": [{"name": "hour"}],
        "metrics": [{"name": "totalUsers"}],
        "limit": 100,
    })
    hb = {"today": [0] * 24, "same_day_last_week": [0] * 24}
    for d, m in _rows(hrs):
        h = int(d[0]) if d[0].isdigit() else None
        k = keymap.get(d[1] if len(d) > 1 else "date_range_0", "today")
        if h is not None and k in hb:
            hb[k][h] = int(m[0])
    out["today"]["by_hour"] = hb
    out["today"]["hour_now"] = NOW_NY.hour

    # 3. Daily series, 28 days: users + views.
    daily = _ga4_post(prop, token, "runReport", {
        "dateRanges": [{"startDate": f"{DAYS-1}daysAgo", "endDate": "today"}],
        "dimensions": [{"name": "date"}],
        "metrics": [{"name": "totalUsers"}, {"name": "screenPageViews"}],
        "limit": 100,
    })
    by = {d[0]: (int(m[0]), int(m[1])) for d, m in _rows(daily)}
    out["daily"] = [{"d": dd.isoformat(),
                     "users": by.get(dd.strftime("%Y%m%d"), (0, 0))[0],
                     "views": by.get(dd.strftime("%Y%m%d"), (0, 0))[1]} for dd in day_list()]

    # 4. Top pieces today and this week (views), for "what is being read".
    def top(start, end, n=10):
        rep = _ga4_post(prop, token, "runReport", {
            "dateRanges": [{"startDate": start, "endDate": end}],
            "dimensions": [{"name": "pagePath"}, {"name": "pageTitle"}],
            "metrics": [{"name": "screenPageViews"}, {"name": "totalUsers"}],
            "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
            "limit": 60,
        })
        acc = {}
        for d, m in _rows(rep):
            p = _pretty_path(d[0])
            if not _is_article(p): continue
            a = acc.setdefault(p, {"path": p, "title": d[1], "views": 0, "users": 0})
            a["views"] += int(m[0]); a["users"] += int(m[1])
        return sorted(acc.values(), key=lambda x: -x["views"])[:n]
    out["top_today"] = top("today", "today")
    out["top_week"]  = top("6daysAgo", "today")
    out["top_28d"]   = top(f"{DAYS-1}daysAgo", "today", n=15)
    return out


# ------------------------------------------------------------------ Ghost
def _ghost(path, tok):
    hdr = {"Authorization": "Ghost " + tok, "Accept-Version": "v5.0"}
    return json.loads(http_get(GHOST_ADMIN_API + path, headers=hdr, timeout=30))


def pull_ghost_live():
    tok = _ghost_admin_token()
    if not tok:
        raise RuntimeError("no Ghost admin key")
    out = {}
    # Members total + new by day (28 days). One filtered, paginated pull.
    since, _ = ny_day_bounds_utc(TODAY - timedelta(days=DAYS - 1))
    flt = urllib.parse.quote(f"created_at:>'{since.strftime('%Y-%m-%d %H:%M:%S')}'")
    rows, page = [], 1
    while True:
        j = _ghost(f"/members/?filter={flt}&fields=created_at,status&limit=100&page={page}&order=created_at%20desc", tok)
        rows += j.get("members") or []
        meta = (j.get("meta") or {}).get("pagination") or {}
        if not meta.get("next"): break
        page += 1
        if page > 30: break
    tot = _ghost("/members/?limit=1&fields=id", tok)
    out["members_total"] = ((tot.get("meta") or {}).get("pagination") or {}).get("total")
    per = Counter()
    for r in rows:
        try:
            d = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).astimezone(NY).date()
            per[d.isoformat()] += 1
        except Exception:
            pass
    out["new_by_day"] = [{"d": d.isoformat(), "n": per.get(d.isoformat(), 0)} for d in day_list()]
    out["new_today"] = per.get(TODAY.isoformat(), 0)
    out["new_7d"]    = sum(per.get(d.isoformat(), 0) for d in day_list(7))
    out["new_28d"]   = sum(per.values())

    # Posts published in the last 7 days, plus the latest post.
    since7, _ = ny_day_bounds_utc(TODAY - timedelta(days=6))
    pf = urllib.parse.quote(f"status:published+published_at:>'{since7.strftime('%Y-%m-%d %H:%M:%S')}'")
    pj = _ghost(f"/posts/?filter={pf}&fields=title,slug,url,published_at,primary_author,feature_image,visibility&include=authors&limit=40&order=published_at%20desc", tok)
    posts = []
    for p in pj.get("posts") or []:
        posts.append({"title": p.get("title"), "slug": p.get("slug"), "url": p.get("url"),
                      "published_at": p.get("published_at"),
                      "authors": [a.get("name") for a in (p.get("authors") or []) if a.get("name")],
                      "visibility": p.get("visibility")})
    out["posts_7d"] = posts
    latest = _ghost("/posts/?filter=status:published&fields=title,slug,url,published_at&limit=1&order=published_at%20desc", tok)
    lp = (latest.get("posts") or [None])[0]
    out["latest_post"] = lp
    out["posts_today"] = sum(1 for p in posts if p["published_at"] and
                             datetime.fromisoformat(p["published_at"].replace("Z", "+00:00")).astimezone(NY).date() == TODAY)
    return out


# ------------------------------------------------------------------ Mailchimp
def pull_mailchimp_live():
    key = mailchimp_key()
    if not key: raise RuntimeError("no Mailchimp key")
    dc = key.split("-")[-1]
    list_id = os.environ.get("MAILCHIMP_LIST", "ec30bf0c4b")
    out = {}
    lst = mc_get(f"/lists/{list_id}?fields=stats.member_count,stats.unsubscribe_count,stats.cleaned_count", key, dc)
    st = lst.get("stats") or {}
    out["subscribers"] = st.get("member_count")
    since, _ = ny_day_bounds_utc(TODAY - timedelta(days=DAYS - 1))
    iso = since.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    def pull(params):
        acc, off = [], 0
        while True:
            j = mc_get(f"/lists/{list_id}/members?count=1000&offset={off}&{params}", key, dc)
            m = j.get("members") or []
            acc += m
            if len(m) < 1000 or off > 20000: break
            off += 1000
        return acc

    subs = pull(f"status=subscribed&since_timestamp_opt={urllib.parse.quote(iso)}&fields=members.timestamp_opt,members.email_address")
    unsubs = pull(f"status=unsubscribed&since_last_changed={urllib.parse.quote(iso)}&fields=members.last_changed")
    sc, uc = Counter(), Counter()
    for m in subs:
        try: sc[datetime.fromisoformat(m["timestamp_opt"].replace("Z", "+00:00")).astimezone(NY).date().isoformat()] += 1
        except Exception: pass
    for m in unsubs:
        try: uc[datetime.fromisoformat(m["last_changed"].replace("Z", "+00:00")).astimezone(NY).date().isoformat()] += 1
        except Exception: pass
    out["by_day"] = [{"d": d.isoformat(), "signups": sc.get(d.isoformat(), 0), "unsubs": uc.get(d.isoformat(), 0)}
                     for d in day_list()]
    out["signups_today"] = sc.get(TODAY.isoformat(), 0)
    out["signups_7d"]    = sum(sc.get(d.isoformat(), 0) for d in day_list(7))
    out["signups_prev7"] = sum(sc.get(d.isoformat(), 0) for d in day_list(14)[:7])
    out["unsubs_7d"]     = sum(uc.get(d.isoformat(), 0) for d in day_list(7))
    out["signups_28d"]   = sum(sc.values())
    out["unsubs_28d"]    = sum(uc.values())
    # The most recent campaign, so "Now" can say when the last send went out.
    camp = mc_get("/campaigns?count=60&status=sent&sort_field=send_time&sort_dir=DESC&fields=campaigns.send_time,campaigns.settings.subject_line,campaigns.variate_settings.subject_lines,campaigns.report_summary.open_rate,campaigns.report_summary.click_rate,campaigns.emails_sent", key, dc)
    # skip test sends and tiny segments: the newsletter goes to the whole list
    def subj(x):
        # A/B-tested sends keep their subjects in variate_settings
        return ((x.get("settings") or {}).get("subject_line")
                or " / ".join((x.get("variate_settings") or {}).get("subject_lines") or []) or "")
    c = next((x for x in camp.get("campaigns") or []
              if (x.get("emails_sent") or 0) >= 500
              and not re.match(r"\s*\[?test", subj(x), re.I)), None)
    if c:
        out["last_campaign"] = {"subject": subj(c),
                               "sent": c.get("send_time"), "emails": c.get("emails_sent"),
                               "open_rate": (c.get("report_summary") or {}).get("open_rate"),
                               "click_rate": (c.get("report_summary") or {}).get("click_rate")}
    return out


# ------------------------------------------------------------------ Donorbox
def pull_donorbox_live():
    key, email = donorbox_creds()
    if not key: raise RuntimeError("no Donorbox key")
    auth = base64.b64encode(f"{email}:{key}".encode()).decode()
    hdr = {"Authorization": "Basic " + auth, "Accept": "application/json"}
    since = (TODAY - timedelta(days=DAYS - 1)).isoformat()
    rows, page = [], 1
    while True:
        batch = json.loads(http_get(f"https://donorbox.org/api/v1/donations?page={page}&per_page=100&date_from={since}",
                                    headers=hdr, timeout=60))
        if not batch: break
        rows += batch
        if len(batch) < 100 or page > 10: break
        page += 1
    paid = [d for d in rows if (d.get("status") or "").lower() == "paid"]
    per_n, per_amt = Counter(), defaultdict(float)
    for d in paid:
        try:
            dd = datetime.fromisoformat(d["donation_date"].replace("Z", "+00:00")).astimezone(NY).date().isoformat()
        except Exception:
            dd = (d.get("donation_date") or "")[:10]
        per_n[dd] += 1
        try: per_amt[dd] += float(d.get("amount") or 0)
        except Exception: pass
    def span(days):
        ds = [d.isoformat() for d in day_list(days)]
        return {"gifts": sum(per_n.get(x, 0) for x in ds), "amount": round(sum(per_amt.get(x, 0) for x in ds), 2)}
    return {"today": span(1), "d7": span(7), "d28": span(28),
            "by_day": [{"d": d.isoformat(), "gifts": per_n.get(d.isoformat(), 0),
                        "amount": round(per_amt.get(d.isoformat(), 0), 2)} for d in day_list()],
            "recent": [{"date": (d.get("donation_date") or "")[:10], "amount": d.get("amount"),
                        "recurring": bool(d.get("recurring")),
                        "campaign": ((d.get("campaign") or {}).get("name") or "")} for d in paid[:8]]}


# ------------------------------------------------------------------ social + press
def pull_social_live():
    bsky = pull_bluesky_profile()
    li = pull_linkedin_followers()
    hist = {}
    try:
        hist = json.loads(SOCIAL_HISTORY.read_text())
    except Exception:
        pass
    rows = hist.get("rows") or []
    def back(platform, days):
        """follower count on or before `days` ago, from data/social_history.json"""
        target = (TODAY - timedelta(days=days)).isoformat()
        best = None
        for r in rows:
            if r.get("p") == platform and (r.get("d") or "") <= target:
                if best is None or r["d"] > best["d"]: best = r
        return best.get("n") if best else None
    # the login-walled platforms, latest manual reading
    manual = {}
    for r in rows:
        if r.get("p") in ("x", "instagram", "facebook"):
            if r["p"] not in manual or r["d"] > manual[r["p"]]["d"]: manual[r["p"]] = r
    return {"bluesky": {"followers": bsky.get("followers"), "available": bsky.get("available", False),
                        "d7": back("bluesky", 7), "d28": back("bluesky", 28)},
            "linkedin": {"followers": li.get("followers"), "available": li.get("available", False),
                         "as_of": li.get("as_of"), "d7": back("linkedin", 7), "d28": back("linkedin", 28)},
            "manual": {k: {"followers": v.get("n"), "as_of": v.get("d")} for k, v in manual.items()}}


def pull_news_live():
    q = urllib.parse.quote('"Vital City" (NYC OR "New York")')
    xml = http_get(f"https://news.google.com/rss/search?q={q}+when:2d&hl=en-US&gl=US&ceid=US:en", timeout=20)
    root = ET.fromstring(xml)
    items = []
    for it in root.iter("item"):
        t = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        src = it.find("source")
        source = (src.text if src is not None else "") or ""
        if re.search(r"vital\s*city", source, re.I) or "vitalcitynyc.org" in link:
            continue            # Google News indexes our own site; that is not press
        items.append({"title": t, "url": link, "published": pub, "source": source})
    return {"count_48h": len(items), "items": items[:10]}


# ------------------------------------------------------------------ main
def main():
    log(f"live_pull @ {NOW_NY.isoformat()} (NY)")
    out = {
        "generated_at": NOW_UTC.isoformat(),
        "generated_at_ny": NOW_NY.isoformat(),
        "today_ny": TODAY.isoformat(),
        "window_days": DAYS,
        "site":     safe("ga4", pull_ga4_live),
        "ghost":    safe("ghost", pull_ghost_live),
        "list":     safe("mailchimp", pull_mailchimp_live),
        "giving":   safe("donorbox", pull_donorbox_live),
        "social":   safe("social", pull_social_live),
        "press":    safe("news", pull_news_live),
    }
    ok = [k for k in ("site", "ghost", "list", "giving", "social", "press") if out[k].get("available")]
    out["sources_ok"] = ok
    if not ok:
        log("ERROR: every source failed — refusing to write an empty live.json")
        sys.exit(2)
    PRIV.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False))
    log(f"wrote {OUT} ({OUT.stat().st_size:,} bytes) — sources ok: {', '.join(ok)}")
    for k in ("site", "ghost", "list", "giving", "social", "press"):
        if not out[k].get("available"):
            log(f"  NOTE {k}: {out[k].get('reason')}")


if __name__ == "__main__":
    main()
