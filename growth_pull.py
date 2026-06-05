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

    # Growth history — monthly *cumulative* sub + unsub counts going back ~58
    # months. From this we can derive REAL monthly new-signup counts (the
    # /activity feed is unreliable because it only sees direct-MC-form
    # signups, and the actual site cutover to Ghost was April 2026 — most
    # 2025 signups went through the prior Prismic-hosted form into Mailchimp
    # directly). Formula: new_signups[m] = (subs[m] - subs[m-1]) +
    # (unsubs[m] - unsubs[m-1]). Captures everyone added to the list,
    # whether through Ghost reconcile, MC form, or manual import.
    try:
        gh = mc_get(f"/lists/{list_id}/growth-history?count=72&sort_field=month&sort_dir=ASC",
                    key, dc).get("history", [])
        monthly_signups = []
        prev_subs = prev_unsubs = None
        for h in gh:
            month = h.get("month") or ""
            subs   = int(h.get("subscribed") or 0)
            unsubs = int(h.get("unsubscribed") or 0)
            if prev_subs is None:
                new = subs   # first month — total subs is the count of signups so far
            else:
                new = (subs - prev_subs) + (unsubs - prev_unsubs)
            monthly_signups.append({"month": month, "new_signups": max(0, new),
                                    "cum_subs": subs, "cum_unsubs": unsubs})
            prev_subs, prev_unsubs = subs, unsubs
        out["monthly_signups"] = monthly_signups
    except Exception as e:
        log(f"  mailchimp growth-history failed: {e}")
        out["monthly_signups"] = []

    # Daily activity (subs/unsubs by day) — last 180 days.
    # Subs: computed from people.json `since` dates (Mailchimp's /activity endpoint
    # only counts direct-MC-form signups and grossly understates the real number
    # because most VC signups arrive via the Ghost signup form). Unsubs/opens/clicks
    # are taken from Mailchimp /activity which is accurate for those.
    rows_by_day = {}
    try:
        # 730 days = 2 years, enough for year-over-year comparisons on
        # unsubscribes / opens / clicks (these signals are reliable in Mailchimp).
        act = mc_get(f"/lists/{list_id}/activity?count=730", key, dc).get("activity", [])
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

    # Signup + unsubscribe windows (YTD and YoY).
    # The Ghost subscription started Jan 2025 but the actual SITE cutover
    # (vitalcitynyc.org moving from Prismic to Ghost) was April 2026. So:
    #  - 2025 signups were captured via the prior site/Mailchimp form
    #  - 2026 signups (April onward) come via Ghost's form
    # Mailchimp's growth-history reflects all subscriber adds regardless of
    # which form they came through, so it's the YoY-fair source.
    from datetime import date as _date
    today = datetime.now(timezone.utc).date()
    y = today.year
    GHOST_CUTOVER = _date(2026, 4, 1)  # vitalcitynyc.org site moved to Ghost

    def _sum(rows, start, end, key):
        s, e = start.isoformat(), end.isoformat()
        return sum(int(r.get(key) or 0) for r in rows if s <= r["d"] <= e)

    rows = out["daily_activity"]
    ytd_start  = _date(y, 1, 1);   ytd_end = today
    py_start   = _date(y-1, 1, 1); py_end  = _date(y-1, today.month, today.day)

    # Derive YTD signup counts from Mailchimp's growth-history (cumulative
    # subscribers per month — the most complete record of net additions
    # regardless of which form the signup came through). For both current
    # and prior year, sum new_signups Jan→current_month.
    def _ytd_signups(monthly, year, through_month):
        return sum(int(m.get("new_signups") or 0) for m in monthly
                   if (m.get("month") or "").startswith(f"{year}-")
                   and (m.get("month") or "")[5:7] <= f"{through_month:02d}")
    monthly = out.get("monthly_signups") or []
    sig_ytd       = _ytd_signups(monthly, today.year,     today.month)
    sig_prior_ytd = _ytd_signups(monthly, today.year - 1, today.month)
    out["signup_windows"] = {
        "ytd":              sig_ytd,
        "prior_ytd":        sig_prior_ytd,
        "prior_ytd_ok":     sig_prior_ytd > 0,
        "prior_ytd_source": "Mailchimp growth-history (monthly subscriber counts) — counts every net addition to the list, whether the signup came in via Ghost form, the MC form, or a manual import.",
        "ghost_cutover":    GHOST_CUTOVER.isoformat(),
        "unsub_ytd":        _sum(rows, ytd_start, ytd_end, "unsubs"),
        "unsub_prior_ytd":  _sum(rows, py_start,  py_end,  "unsubs"),
    }

    # ALL sent campaigns ever — we use the full history for monthly trend lines
    # (Mailchimp goes back to ~March 2022) and for YoY comparisons. The recent‑12
    # table on the dashboard just slices the newest ones.
    try:
        camp = mc_get(
            f"/campaigns?status=sent&list_id={list_id}&count=500"
            f"&sort_field=send_time&sort_dir=DESC&fields=campaigns.id,campaigns.type,"
            f"campaigns.settings.subject_line,campaigns.send_time,campaigns.emails_sent,"
            f"campaigns.report_summary,campaigns.variate_settings.subject_lines",
            key, dc).get("campaigns", [])
        camp_out = []
        for c in camp:
            rs = c.get("report_summary") or {}
            # Variate (A/B) campaigns leave settings.subject_line empty on the
            # parent — the variant subjects live in variate_settings.subject_lines.
            # Pick those up so the dashboard doesn't show "(no subject)".
            variate_subjects = []
            if c.get("type") == "variate":
                variate_subjects = ((c.get("variate_settings") or {}).get("subject_lines") or [])
            camp_out.append({
                "id":       c.get("id"),
                "subject":  (c.get("settings") or {}).get("subject_line", ""),
                "variate_subjects": variate_subjects,
                "type":     c.get("type") or "regular",
                "sent":     (c.get("send_time") or "")[:10],
                "sent_to":  c.get("emails_sent") or 0,
                "open_pct": round((rs.get("open_rate")  or 0) * 100, 1),
                "click_pct":round((rs.get("click_rate") or 0) * 100, 1),
                "unsubs":   rs.get("unsubscribed") or rs.get("unsubscribes") or 0,
            })
        out["campaigns"] = camp_out

        # Monthly aggregates (recipient‑weighted rates) for the trend chart
        from collections import defaultdict as _dd
        mo = _dd(lambda: {"sends": 0, "recipients": 0, "wt_open": 0.0, "wt_click": 0.0, "unsubs": 0})
        for c in camp:
            sent = c.get("emails_sent") or 0
            rs = c.get("report_summary") or {}
            m = (c.get("send_time") or "")[:7]
            if not m: continue
            mo[m]["sends"] += 1
            mo[m]["recipients"] += sent
            mo[m]["wt_open"]  += float(rs.get("open_rate")  or 0) * sent
            mo[m]["wt_click"] += float(rs.get("click_rate") or 0) * sent
            mo[m]["unsubs"]   += int(rs.get("unsubscribed") or rs.get("unsubscribes") or 0)
        monthly = []
        for m in sorted(mo):
            r = mo[m]
            recs = r["recipients"] or 1
            monthly.append({
                "month": m,
                "sends": r["sends"],
                "recipients": r["recipients"],
                "open_pct":  round((r["wt_open"]  / recs) * 100, 1),
                "click_pct": round((r["wt_click"] / recs) * 100, 1),
                "unsubs":    r["unsubs"],
            })
        out["monthly_campaigns"] = monthly

        # Period buckets: window stats and YoY comparisons (Mailchimp send data
        # goes back to ~2022, so this is reliable for newsletter performance).
        # Signup YoY uses Mailchimp growth-history (canonical regardless of
        # which front-end form fed the list — Prismic pre-cutover, Ghost after).
        from datetime import date as _date
        today = datetime.now(timezone.utc).date()
        y, _ = today.year, today.month

        def _agg(items):
            recs = sum(i.get("emails_sent") or 0 for i in items)
            wt_open  = sum(float((i.get("report_summary") or {}).get("open_rate")  or 0) * (i.get("emails_sent") or 0) for i in items)
            wt_click = sum(float((i.get("report_summary") or {}).get("click_rate") or 0) * (i.get("emails_sent") or 0) for i in items)
            return {
                "sends": len(items),
                "recipients": recs,
                "open_pct":  round((wt_open  / recs) * 100, 1) if recs else 0,
                "click_pct": round((wt_click / recs) * 100, 1) if recs else 0,
                "unsubs":    sum(int((i.get("report_summary") or {}).get("unsubscribed") or 0) for i in items),
            }

        def _in(items, start, end):
            return [c for c in items if start.isoformat() <= (c.get("send_time") or "")[:10] <= end.isoformat()]

        ytd_start  = _date(y, 1, 1); ytd_end = today
        py_start   = _date(y-1, 1, 1); py_end = _date(y-1, today.month, today.day)
        last30_end = today; last30_start = today - timedelta(days=30)
        prev30_end = last30_start - timedelta(days=1); prev30_start = prev30_end - timedelta(days=30)
        yoy30_end  = _date(y-1, today.month, today.day); yoy30_start = yoy30_end - timedelta(days=30)

        out["windows"] = {
            "ytd":         _agg(_in(camp, ytd_start,  ytd_end)),
            "prior_ytd":   _agg(_in(camp, py_start,   py_end)),
            "last_30":     _agg(_in(camp, last30_start, last30_end)),
            "prev_30":     _agg(_in(camp, prev30_start, prev30_end)),
            "yoy_30":      _agg(_in(camp, yoy30_start,  yoy30_end)),
        }
    except Exception as e:
        log(f"  mailchimp campaigns failed: {e}")
        out["campaigns"] = []
        out["monthly_campaigns"] = []
        out["windows"] = {}

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

    # ---- Monthly + annual active users ---------------------------------
    # Real number, not a proxy: the UNION of unique email addresses that
    # opened at least one regular (non-A/B) send in the window.
    # Cost: one extra API call per campaign + ~1 per 1000 openers (pagination).
    # ~30-90 calls for the year — under a minute.
    def _union_openers(days_back):
        since_iso = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        url = (f"/campaigns?status=sent&list_id={list_id}"
               f"&since_send_time={urllib.parse.quote(since_iso)}"
               f"&count=500&sort_field=send_time&sort_dir=DESC"
               f"&fields=campaigns.id,campaigns.type,campaigns.send_time")
        try:
            cs = mc_get(url, key, dc).get("campaigns", [])
        except Exception as e:
            log(f"  active-users campaign list failed ({days_back}d): {e}"); return None
        regulars = [c for c in cs if c.get("type") == "regular"]
        variate  = [c for c in cs if c.get("type") == "variate"]
        openers = set()
        fail = 0
        for c in regulars:
            cid = c["id"]; offset = 0
            while True:
                try:
                    page = mc_get(
                        f"/reports/{cid}/open-details?count=1000&offset={offset}"
                        f"&fields=members.email_address,total_items",
                        key, dc)
                except Exception as e:
                    fail += 1; log(f"  open-details fail {cid}@{offset}: {e}"); break
                for m in page.get("members", []):
                    em = (m.get("email_address") or "").lower().strip()
                    if em: openers.add(em)
                total = int(page.get("total_items") or 0)
                offset += 1000
                if offset >= total: break
        return {
            "active_users":           len(openers),
            "regulars_counted":       len(regulars),
            "variate_excluded":       len(variate),
            "campaigns_in_window":    len(cs),
            "failed_fetches":         fail,
        }

    log("  computing MAU (30d) — unioning openers across recent sends…")
    out["mau"] = _union_openers(30)
    log("  computing AAU (365d) — unioning openers across last year's sends…")
    out["aau"] = _union_openers(365)
    return out


# -------------------------------------------------------------------- Ghost
GHOST_CONTENT_KEY = "dd8e178e9ddfc883537e71dd07"   # public, same as scrape.py
GHOST_API = "https://vital-city.ghost.io/ghost/api/content"
GHOST_ADMIN_API = "https://vital-city.ghost.io/ghost/api/admin"

def _ghost_admin_token():
    """Sign a short-lived JWT for the Ghost Admin API using the id:secret in
    private/.ghost_admin_key (or env GHOST_ADMIN_KEY in workflow)."""
    import hashlib, hmac
    key = os.environ.get("GHOST_ADMIN_KEY") or ""
    if not key:
        f = PRIV / ".ghost_admin_key"
        if f.exists(): key = f.read_text().strip()
    if not key or ":" not in key:
        return None
    kid, secret = key.split(":", 1)
    def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b"=")
    iat = int(time.time())
    h = b64u(json.dumps({"alg":"HS256","typ":"JWT","kid":kid}).encode())
    p = b64u(json.dumps({"iat":iat,"exp":iat+300,"aud":"/admin/"}).encode())
    sig = hmac.new(bytes.fromhex(secret), h+b"."+p, hashlib.sha256).digest()
    return (h + b"." + p + b"." + b64u(sig)).decode()


def pull_ghost_signup_attribution(days_back=180):
    """REAL per-post signup attribution from Ghost's member-events feed.
    Each signup_event carries the exact page the person signed up on plus
    referrer_source/medium. This is the actual answer — not a 4-day
    post-publish window correlation. Replaces the older correlational
    proxy we used before this endpoint was wired in.
    """
    import time as _t
    tok = _ghost_admin_token()
    if not tok:
        return {"available": False, "reason": "no Ghost admin key"}
    since_iso = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    by_url = {}
    by_day = {}            # day -> count of signup events (canonical signup source-of-truth)
    by_source = {}         # referrer_source -> count (Direct, Google, newsletter, LinkedIn, etc.)
    by_medium = {}         # referrer_medium -> count (search, email, social, etc.)
    by_landing = {}        # attribution.type (post|page|url) -> count (where they signed up)
    fetched = 0
    stop = False
    cursor_id = None       # last event id from previous page (cursor pagination)
    pages = 0
    # Ghost's /members/events/ endpoint ignores `page=N` (always returns page 1).
    # It also rejects `created_at` in the filter ("Cannot filter by created_at").
    # The supported workaround is cursor pagination via `id:<lastId` — Ghost
    # event ids are lexicographically time-sortable, so this walks the feed
    # newest-first reliably.
    while not stop:
        flt_str = "type:signup_event"
        if cursor_id:
            flt_str += f"+id:<{cursor_id}"
        url = f"{GHOST_ADMIN_API}/members/events/?filter={urllib.parse.quote(flt_str)}&limit=100"
        try:
            data = json.loads(http_get(url, headers={
                "Authorization": f"Ghost {tok}", "Accept-Version": "v5.0",
            }, timeout=60))
        except Exception as e:
            log(f"  ghost member-events page {pages+1} failed: {e}")
            break
        events = data.get("events", []) or []
        if not events:
            break
        for e in events:
            d = e.get("data") or {}
            ts = (d.get("created_at") or "")
            if ts and ts < since_iso:
                stop = True
                continue
            # Daily total — every signup, regardless of attribution
            if ts:
                day = ts[:10]
                by_day[day] = by_day.get(day, 0) + 1
            att = d.get("attribution") or {}
            # Flat aggregates — capture every signup's source, not just the
            # ones that attributed to a specific post. Homepage signups are
            # the bulk of volume; they'd be invisible if we only looked at
            # per-URL counts.
            src = (att.get("referrer_source") or "(unknown)").strip() or "(unknown)"
            by_source[src] = by_source.get(src, 0) + 1
            med = (att.get("referrer_medium") or "(none)").strip() or "(none)"
            by_medium[med] = by_medium.get(med, 0) + 1
            ltype = (att.get("type") or "unknown")
            by_landing[ltype] = by_landing.get(ltype, 0) + 1
            post_url = (att.get("url") or "").rstrip("/")
            if not post_url: continue
            r = by_url.setdefault(post_url, {
                "signups": 0, "title": att.get("title") or "", "type": att.get("type") or "",
                "first_seen": "", "last_seen": "", "sources": {},
            })
            r["signups"] += 1
            src = att.get("referrer_source") or "(none)"
            r["sources"][src] = r["sources"].get(src, 0) + 1
            if not r["first_seen"] or ts < r["first_seen"]: r["first_seen"] = ts
            if not r["last_seen"]  or ts > r["last_seen"]:  r["last_seen"]  = ts
        fetched += len(events)
        pages += 1
        # Advance cursor to the last (oldest) event on this page
        cursor_id = (events[-1].get("data") or {}).get("id")
        if not cursor_id:
            break
        if pages > 250:        # safety — ~25,000 events
            break
        _t.sleep(0.05)         # gentle pacing
    # Normalize: pick top 3 sources per url
    for url, r in by_url.items():
        srcs = sorted(r["sources"].items(), key=lambda kv: -kv[1])[:3]
        r["top_sources"] = [{"src": s, "n": n} for s, n in srcs]
        r["first_seen"] = r["first_seen"][:10]
        r["last_seen"]  = r["last_seen"][:10]
        del r["sources"]
    log(f"  ghost signup attribution: {fetched} signup events across {len(by_url)} URLs, {len(by_day)} days, {len(by_source)} sources")
    return {
        "available":      True,
        "events_counted": fetched,
        "by_url":         by_url,
        "by_day":         [{"d": d, "subs": n} for d, n in sorted(by_day.items())],
        "by_source":      [{"src": s, "n": n} for s, n in sorted(by_source.items(), key=lambda kv: -kv[1])],
        "by_medium":      [{"med": m, "n": n} for m, n in sorted(by_medium.items(), key=lambda kv: -kv[1])],
        "by_landing":     [{"type": t, "n": n} for t, n in sorted(by_landing.items(), key=lambda kv: -kv[1])],
        "window_days":    days_back,
    }


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


# ----------------------------------------------- Media mentions (third-party press)
# Two distinct whitelists:
#   MEDIA_OUTLETS — actual news/policy publications that cover us. For these,
#     query "Vital City" + @ handle + URL-share. The brand-phrase search works
#     on press sites because they use the name intentionally.
#   SOCIAL_PLATFORMS — X, LinkedIn, Bluesky, Instagram. Here we DROP the
#     brand-phrase shape (people use "vital city" generically — "Karachi
#     remains Pakistan's most inclusive and economically vital city..." etc.)
#     and only search @vitalcitynyc + vitalcitynyc.org URL shares. Those are
#     unambiguous.
MEDIA_OUTLETS = [
    # NYC outlets
    ("gothamist.com",          "Gothamist"),
    ("nytimes.com",            "The New York Times"),
    ("ny1.com",                "NY1"),
    ("nyc.streetsblog.org",    "Streetsblog NYC"),
    ("streetsblog.org",        "Streetsblog"),
    ("wnyc.org",               "WNYC"),
    ("thecity.nyc",            "THE CITY"),
    ("nydailynews.com",        "New York Daily News"),
    ("nypost.com",             "New York Post"),
    ("nymag.com",              "New York Magazine"),
    ("city-journal.org",       "City Journal"),
    ("cityandstateny.com",     "City & State NY"),
    ("therealdeal.com",        "The Real Deal"),
    # Substacks frequently cited in the manual list
    ("johnkroman.substack.com",      "John Kroman (Substack)"),
    ("nyeditorialboard.substack.com","NY Editorial Board (Substack)"),
    ("probablecausation.substack.com","Probable Causation (Substack)"),
    # National outlets
    ("politico.com",           "Politico"),
    ("semafor.com",            "Semafor"),
    ("washingtonpost.com",     "Washington Post"),
    ("newyorker.com",          "The New Yorker"),
    ("bloomberg.com",          "Bloomberg"),
    ("theguardian.com",        "The Guardian"),
    ("newsweek.com",           "Newsweek"),
]
SOCIAL_PLATFORMS = [
    ("x.com",            "X"),
    ("twitter.com",      "X"),
    ("linkedin.com",     "LinkedIn"),
    ("bsky.app",         "Bluesky"),
    ("instagram.com",    "Instagram"),
]


def pull_news_mentions():
    """Search Google News RSS for Vital City references, scoped per outlet.

    Two outlet groups with different query shapes:
      - MEDIA_OUTLETS (news publications): three shapes — "Vital City",
        @vitalcitynyc, vitalcitynyc.org — because brand-phrase matches on
        press sites are intentional references to the publication.
      - SOCIAL_PLATFORMS (X, LinkedIn, Bluesky, Instagram): only two shapes —
        @vitalcitynyc, vitalcitynyc.org — DROPPING the brand-phrase search
        because on social platforms "vital city" is used generically
        ("Karachi remains Pakistan's most inclusive and economically vital
        city...") and produces high-volume false positives.

    Each result is tagged with `kind: 'media' | 'social'` so the dashboard
    can route them into the right card without re-filtering by domain.
    """
    import time as _t
    out = []
    seen = set()
    UA_local = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    MEDIA_SHAPES  = ['"Vital City"', "@vitalcitynyc", "vitalcitynyc.org"]
    SOCIAL_SHAPES = ["@vitalcitynyc", "vitalcitynyc.org"]
    targets = (
        [(d, label, "media",  MEDIA_SHAPES)  for d, label in MEDIA_OUTLETS] +
        [(d, label, "social", SOCIAL_SHAPES) for d, label in SOCIAL_PLATFORMS]
    )
    for domain, label, kind, shapes in targets:
        for shape in shapes:
            q = f'{shape} site:{domain}'
            url = (f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}"
                   f"&hl=en-US&gl=US&ceid=US:en")
            try:
                xml = http_get(url, headers={"User-Agent": UA_local}, timeout=20)
            except Exception as e:
                log(f"  news mentions {domain} ({shape}) failed: {e}"); continue
            try:
                root = ET.fromstring(xml)
            except Exception as e:
                continue
            for it in root.findall(".//item"):
                title = _xml_text(it, "title")
                link  = _xml_text(it, "link")
                src   = _xml_text(it, "source") or label
                pub   = _xml_text(it, "pubDate")
                snip  = re.sub(r"<[^>]+>", "", _xml_text(it, "description"))[:240]
                if not title or not link: continue
                key = (domain, title.lower())
                if key in seen: continue
                seen.add(key)
                out.append({
                    "title": title, "url": link, "source": src, "published": pub,
                    "snippet": snip, "domain": domain, "match_shape": shape,
                    "kind": kind,
                    "is_url_share": (shape == "vitalcitynyc.org"),
                })
            _t.sleep(0.15)   # polite pacing across many outlets × shapes

    # Parse pub dates, drop items older than 24 months, sort newest first
    cutoff = datetime.now(timezone.utc) - timedelta(days=730)
    def _parse(p):
        for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z",
                    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(p, fmt).astimezone(timezone.utc)
            except Exception:
                pass
        return None
    for it in out:
        dt = _parse(it.get("published", ""))
        it["published_iso"] = dt.isoformat() if dt else ""
        it["_dt"] = dt
    out = [it for it in out if it.get("_dt") and it["_dt"] >= cutoff]

    # Note on verification: Google's site-restricted exact-phrase query
    # ('"Vital City" site:DOMAIN') already requires the phrase to appear in
    # the article body. We trust that — fetching every page just to re-check
    # title/snippet (which is only the first 240 chars) would discard valid
    # hits where "Vital City" appears deeper in the body. Outlet whitelist
    # carries most of the precision; rare lexical false positives can sneak
    # through (Google's phrase matching has slight leniency) but they're
    # easy to spot in a reverse-chron list.

    # Dedup PER-DOMAIN — the same article on Streetsblog vs an X share of
    # that same article are distinct signals; keep both.
    titles_seen = set(); deduped = []
    for it in sorted(out, key=lambda x: x["_dt"], reverse=True):
        key = (it["domain"], it["title"].lower()[:80])
        if key in titles_seen: continue
        titles_seen.add(key); deduped.append(it)
    for it in deduped: it.pop("_dt", None)

    # Per-kind caps so the high-volume social stream doesn't crowd press out
    media  = [it for it in deduped if it.get("kind") == "media"][:200]
    social = [it for it in deduped if it.get("kind") == "social"][:120]
    out    = media + social
    log(f"  news mentions: {len(out)} items ({len(media)} media + {len(social)} social) across {len(set(i['domain'] for i in out))} outlets")
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


# --------------------------------------------------------------- Donorbox
def donorbox_creds():
    key = os.environ.get("DONORBOX_KEY") or ""
    if not key:
        f = PRIV / ".donorbox_key"
        if f.exists(): key = f.read_text().strip()
    email = os.environ.get("DONORBOX_EMAIL", "info@vitalcitynyc.org").strip()
    return key.strip(), email


def pull_donorbox():
    key, email = donorbox_creds()
    if not key:
        return {"available": False, "reason": "DONORBOX_KEY not set"}
    auth = base64.b64encode(f"{email}:{key}".encode()).decode()
    headers = {
        "Authorization": "Basic " + auth,
        "User-Agent": "VitalCity-GrowthDashboard/1.0",
        "Accept": "application/json",
    }
    donations, page = [], 1
    while True:
        try:
            url = f"https://donorbox.org/api/v1/donations?page={page}&per_page=100"
            batch = json.loads(http_get(url, headers=headers, timeout=120))
        except Exception as e:
            log(f"  donorbox page {page} failed: {e}")
            break
        if not batch: break
        donations.extend(batch)
        if len(batch) < 100: break
        page += 1
        if page > 200: break   # safety cap

    paid = [d for d in donations if (d.get("status") or "").lower() == "paid"]
    if not paid:
        return {"available": True, "donations_paid": 0, "reason": "no paid donations in account"}

    # Normalize fields we'll use
    def _amt(d):
        try: return float(d.get("amount") or 0)
        except: return 0.0
    def _net(d):
        try: return float(d.get("net_amount") or 0)
        except: return 0.0
    def _day(d):  return (d.get("donation_date") or "")[:10]
    def _mon(d):  return (d.get("donation_date") or "")[:7]
    def _email(d): return ((d.get("donor") or {}).get("email") or "").strip().lower()
    def _recurring(d): return bool(d.get("recurring"))
    def _campaign(d): return ((d.get("campaign") or {}).get("name") or "(no campaign)").strip()

    from datetime import date as _date
    from collections import defaultdict as _dd, Counter as _C
    today = datetime.now(timezone.utc).date()
    y = today.year
    ytd_start = _date(y, 1, 1); py_start = _date(y-1, 1, 1)
    py_end = _date(y-1, today.month, today.day)
    d30 = today - timedelta(days=30); d90 = today - timedelta(days=90); d7 = today - timedelta(days=7)
    yoy30_end = _date(y-1, today.month, today.day); yoy30_start = yoy30_end - timedelta(days=30)

    def _agg(items):
        if not items: return {"count": 0, "amount": 0.0, "net": 0.0, "donors": 0,
                              "recurring_amount": 0.0, "onetime_amount": 0.0, "avg_gift": 0.0}
        emails = set()
        amt = net = rec_amt = one_amt = 0.0
        new_donors = 0
        for d in items:
            a = _amt(d); n = _net(d)
            amt += a; net += n
            if _recurring(d): rec_amt += a
            else: one_amt += a
            em = _email(d)
            if em: emails.add(em)
        return {
            "count": len(items),
            "amount": round(amt, 2),
            "net": round(net, 2),
            "donors": len(emails),
            "recurring_amount": round(rec_amt, 2),
            "onetime_amount":   round(one_amt, 2),
            "avg_gift": round(amt / len(items), 2) if items else 0.0,
        }

    def _in(items, start, end):
        s, e = start.isoformat(), end.isoformat()
        return [d for d in items if s <= _day(d) <= e]

    # Daily series (last 365 days for the trend chart)
    daily = _dd(lambda: {"d": "", "amt": 0.0, "n": 0, "donors": set()})
    cutoff = (today - timedelta(days=365)).isoformat()
    for d in paid:
        day = _day(d)
        if day < cutoff or day > today.isoformat(): continue
        r = daily[day]; r["d"] = day
        r["amt"] += _amt(d); r["n"] += 1
        em = _email(d)
        if em: r["donors"].add(em)
    daily_series = [{"d": r["d"], "amt": round(r["amt"], 2), "gifts": r["n"], "donors": len(r["donors"])}
                    for r in sorted(daily.values(), key=lambda x: x["d"])]

    # Monthly series (24 months for YoY trend)
    monthly = _dd(lambda: {"m": "", "amt": 0.0, "n": 0, "donors": set(), "recurring_amt": 0.0})
    for d in paid:
        m = _mon(d)
        if not m: continue
        r = monthly[m]; r["m"] = m
        a = _amt(d); r["amt"] += a; r["n"] += 1
        if _recurring(d): r["recurring_amt"] += a
        em = _email(d)
        if em: r["donors"].add(em)
    monthly_series = [{"m": r["m"], "amt": round(r["amt"], 2), "gifts": r["n"],
                       "donors": len(r["donors"]), "recurring_amt": round(r["recurring_amt"], 2)}
                      for r in sorted(monthly.values(), key=lambda x: x["m"])]

    # Top campaigns YTD + all-time
    camp_ytd = _C(); camp_all = _C()
    for d in paid:
        a = _amt(d); name = _campaign(d)
        camp_all[name] += a
        if _day(d) >= ytd_start.isoformat(): camp_ytd[name] += a
    top_campaigns = [{"name": n, "amount": round(a, 2)} for n, a in camp_ytd.most_common(6)]

    # Top recent gifts (last 30d)
    recent = sorted(_in(paid, d30, today), key=_amt, reverse=True)[:8]
    top_recent = [{
        "amount": _amt(d),
        "net": _net(d),
        "date": _day(d),
        "donor": ((d.get("donor") or {}).get("name") or "").strip() or "Anonymous",
        "recurring": _recurring(d),
        "campaign": _campaign(d),
        "comment": (d.get("comment") or "")[:240],
    } for d in recent]

    # Active recurring donors + MRR estimate
    rec_donors = set(); mrr = 0.0
    last90 = _in(paid, d90, today)
    for d in last90:
        if _recurring(d):
            em = _email(d)
            if em: rec_donors.add(em)
    # MRR: sum recurring gifts in last 30d (rough proxy)
    for d in _in(paid, d30, today):
        if _recurring(d): mrr += _amt(d)

    # Earliest paid gift in this account — honest signal for YoY validity
    oldest = min((_day(d) for d in paid if _day(d)), default="")
    yoy_ok = bool(oldest and oldest < py_start.isoformat())

    return {
        "available": True,
        "donations_paid": len(paid),
        "history_starts": oldest,
        "yoy_ok": yoy_ok,
        "windows": {
            "ytd":       _agg(_in(paid, ytd_start, today)),
            "prior_ytd": _agg(_in(paid, py_start,  py_end)),
            "last_30":   _agg(_in(paid, d30, today)),
            "yoy_30":    _agg(_in(paid, yoy30_start, yoy30_end)),
            "last_7":    _agg(_in(paid, d7, today)),
            "all_time":  _agg(paid),
        },
        "daily_series":   daily_series,
        "monthly_series": monthly_series,
        "top_campaigns":  top_campaigns,
        "top_recent":     top_recent,
        "active_recurring_donors": len(rec_donors),
        "mrr_estimate":   round(mrr, 2),
    }


# ----------------------------------------------------- X (Twitter) — free path
# Uses Twitter's public syndication endpoint (the same one their embed widgets
# hit). Returns follower/following/tweet counts + the 100 most recent tweets
# with per-tweet likes/retweets/replies. NO auth required. Caveats: it's
# unofficial, so it can break at any time; we treat it as best-effort.
def pull_x():
    import re as _re
    url = "https://syndication.twitter.com/srv/timeline-profile/screen-name/vitalcitynyc"
    ua  = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    try:
        html = http_get(url, headers={"User-Agent": ua}, timeout=20).decode("utf-8", "ignore")
        m = _re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, _re.S)
        if not m: raise RuntimeError("no embedded JSON")
        d = json.loads(m.group(1))
        entries = d["props"]["pageProps"]["timeline"]["entries"]
        tweets = []
        user = None
        for e in entries:
            if e.get("type") != "tweet": continue
            t = e.get("content", {}).get("tweet", {})
            if not t: continue
            if user is None: user = t.get("user", {}) or {}
            tweets.append({
                "id":         t.get("id_str") or str(t.get("id") or ""),
                "created_at": t.get("created_at"),
                "text":       (t.get("text") or t.get("full_text") or "")[:280],
                "likes":      int(t.get("favorite_count") or 0),
                "retweets":   int(t.get("retweet_count")  or 0),
                "replies":    int(t.get("reply_count")    or 0) if t.get("reply_count") is not None else None,
            })
        if user is None:
            return {"available": False, "reason": "syndication endpoint returned no tweets"}
        # ISO-normalize tweet timestamps for sort + UI
        def _iso(p):
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(p).astimezone(timezone.utc).isoformat()
            except Exception: return ""
        for t in tweets: t["created_iso"] = _iso(t.get("created_at") or "")
        tweets.sort(key=lambda t: t["created_iso"] or "", reverse=True)
        avg_likes = round(sum(t["likes"] for t in tweets[:20]) / max(len(tweets[:20]), 1), 1)
        return {
            "available": True,
            "source": "syndication.twitter.com (unofficial, no API key)",
            "handle": user.get("screen_name"),
            "name":   user.get("name"),
            "followers": int(user.get("followers_count") or 0),
            "following": int(user.get("friends_count")   or 0),
            "tweets_total": int(user.get("statuses_count") or 0),
            "avg_likes_recent_20": avg_likes,
            "recent_tweets": tweets[:20],
        }
    except Exception as e:
        return {"available": False, "reason": f"X scrape failed: {e}"}


# ------------------------------------------------------- Instagram — free path
# Uses the same web_profile_info endpoint Instagram's own web app calls.
# Needs the X-IG-App-ID header (a public constant) and a browser User-Agent.
# Same best-effort framing as X.
def pull_instagram():
    url = "https://www.instagram.com/api/v1/users/web_profile_info/?username=vitalcitynyc"
    headers = {
        "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                       "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1 "
                       "Instagram 285.0.0.16.119"),
        "X-IG-App-ID": "936619743392459",
        "Accept": "application/json",
    }
    try:
        d = json.loads(http_get(url, headers=headers, timeout=20))
        u = (d.get("data") or {}).get("user") or {}
        if not u: return {"available": False, "reason": "empty user data"}
        posts_out = []
        for edge in (u.get("edge_owner_to_timeline_media") or {}).get("edges", [])[:12]:
            n = edge.get("node") or {}
            cap_edges = (n.get("edge_media_to_caption") or {}).get("edges") or []
            cap = (cap_edges[0].get("node", {}).get("text", "") if cap_edges else "")[:240]
            posts_out.append({
                "id":        n.get("id"),
                "shortcode": n.get("shortcode"),
                "url":       f"https://www.instagram.com/p/{n.get('shortcode')}/" if n.get("shortcode") else None,
                "timestamp": n.get("taken_at_timestamp"),
                "iso":       (datetime.fromtimestamp(int(n["taken_at_timestamp"]), tz=timezone.utc).isoformat()
                              if n.get("taken_at_timestamp") else ""),
                "likes":     int((n.get("edge_liked_by") or {}).get("count") or 0),
                "comments":  int((n.get("edge_media_to_comment") or {}).get("count") or 0),
                "caption":   cap,
                "type":      n.get("__typename") or n.get("product_type") or "",
            })
        avg_likes = round(sum(p["likes"] for p in posts_out[:10]) / max(len(posts_out[:10]), 1), 1) if posts_out else 0
        return {
            "available": True,
            "source": "instagram.com web_profile_info (unofficial, no API key)",
            "handle": u.get("username"),
            "name":   u.get("full_name"),
            "bio":    (u.get("biography") or "")[:240],
            "followers": int((u.get("edge_followed_by") or {}).get("count") or 0),
            "following": int((u.get("edge_follow")      or {}).get("count") or 0),
            "posts_total": int((u.get("edge_owner_to_timeline_media") or {}).get("count") or 0),
            "avg_likes_recent_10": avg_likes,
            "recent_posts": posts_out,
        }
    except Exception as e:
        return {"available": False, "reason": f"Instagram scrape failed: {e}"}


# ------------------------------------------------------------------------ main
def attribute_signups_to_posts(mc, gh, signup_attr=None, window_days=4):
    """Per-post newsletter signup attribution.

    If we have Ghost's real per-event attribution feed (passed as `signup_attr`),
    we use the *exact* count of signups whose attribution.url matches the post —
    no correlation needed, no shared-day ambiguity. Otherwise we fall back to
    the old correlational approach: sum signups on publish_day + window_days,
    compare against the typical active X-day window.
    """
    # ---------- REAL attribution path (Ghost member-events) ------------
    if signup_attr and signup_attr.get("available") and signup_attr.get("by_url"):
        by_url = signup_attr["by_url"]
        # Collect raw counts so we can compute a meaningful baseline
        counts = sorted((r["signups"] for r in by_url.values()), reverse=True)
        if counts:
            # "Typical" post on the list (median of all attributed-to-a-post URLs)
            median_real = counts[len(counts)//2] if counts else 0
            for p in gh["posts"]:
                u = (p.get("url") or "").rstrip("/")
                r = by_url.get(u)
                if not r:
                    p["direct_signups"] = 0
                    continue
                p["direct_signups"] = r["signups"]
                p["direct_sources"] = r.get("top_sources", [])
                # A post is a "mover" if it directly attracted notably more
                # signups than a typical attributed-to-a-post URL (3× median),
                # and the absolute floor is at least 8 signups.
                # Threshold tuned for direct-attribution counts: a post is a
                # "mover" if it directly attracted at least 4 signups AND at
                # least 3× the median post. (Direct attribution is stricter
                # than the old correlational window — homepage-routed signups
                # don't land on the post URL, so post-level numbers are
                # naturally smaller. ~4 is the practical floor for "this
                # piece converted on its own page.")
                p["mover"] = p["direct_signups"] >= 4 and p["direct_signups"] >= median_real * 3
                # Keep these fields consistent with the old surface so the
                # dashboard rendering doesn't need to change much.
                p["signups_window"] = p["direct_signups"]
                p["signups_window_days"] = signup_attr.get("window_days") or window_days
                if median_real:
                    p["lift"] = round(p["direct_signups"] / median_real, 2)
            gh["signup_attribution_mode"] = "real"
            gh["signup_baseline_xd"] = median_real
            gh["signup_attribution_window_days"] = signup_attr.get("window_days") or window_days
            return
    # ---------- Correlational fallback ---------------------------------
    if not (mc and mc.get("daily_activity") and gh and gh.get("posts")):
        return
    daily = {r["d"]: int(r.get("subs") or 0) for r in mc["daily_activity"] if r.get("d")}
    if not daily: return

    # Compute a baseline: median X-day rolling sum across the whole window.
    days = sorted(daily)
    sums = []
    for i in range(len(days) - window_days + 1):
        sums.append(sum(daily[days[j]] for j in range(i, i + window_days)))
    if not sums: return
    # Use the median of *active* windows (sum > 0) — the dataset is zero-rich
    # because the daily signup data is only present where people.json has a
    # subscriber whose Ghost `since` date hits that day, so plain median is
    # dragged to zero and lift would explode meaninglessly.
    active = sorted(s for s in sums if s > 0)
    if not active: return
    median_xd = active[len(active) // 2]
    # A robust "spike" threshold: at least 1.5x median AND at least 12 absolute
    # signups in the window (so small post-day signup counts don't ping).
    LIFT_THRESHOLD = 1.35
    MIN_ABS = 12

    earliest = days[0]; latest = days[-1]

    for p in gh["posts"]:
        d0 = (p.get("published") or "")[:10]
        if not d0 or d0 < earliest or d0 > latest:
            p["signups_window"] = None
            continue
        # Sum the [d0, d0 + window_days) window — clamp to data range
        from datetime import date as _date
        try:
            y, m, dd = (int(x) for x in d0.split("-"))
            start = _date(y, m, dd)
        except Exception:
            p["signups_window"] = None
            continue
        s = 0; valid = False
        for k in range(window_days):
            day = (start + timedelta(days=k)).isoformat()
            if day in daily:
                s += daily[day]; valid = True
        if not valid:
            p["signups_window"] = None
            continue
        p["signups_window"] = s
        p["signups_window_days"] = window_days
        if median_xd > 0:
            p["lift"] = round(s / median_xd, 2)
        else:
            p["lift"] = None
        p["mover"] = bool(p.get("lift") and p["lift"] >= LIFT_THRESHOLD and s >= MIN_ABS)

    gh["signup_baseline_xd"] = median_xd
    gh["signup_window_days"] = window_days
    gh["signup_attribution_mode"] = "correlational"


def attribute_donations_to_posts(db, gh, window_days=14):
    """Donor attribution: for each post, sum donations + dollars received in
    the X-day window after publish, compare to the typical active X-day
    donation window. Correlational only — Donorbox doesn't track which page
    a donor was on when they gave. Same caveats as the (old) signup version:
    multiple posts in a window share the lift, outside drivers exist, last
    couple of days under-count.
    """
    if not (db and db.get("available") and gh and gh.get("posts")):
        return
    daily = {r["d"]: r for r in (db.get("daily_series") or [])}
    if not daily:
        return
    days = sorted(daily)
    sums_amt = []
    for i in range(len(days) - window_days + 1):
        sums_amt.append(sum(daily[days[j]]["amt"] for j in range(i, i + window_days)))
    if not sums_amt:
        return
    active = sorted(s for s in sums_amt if s > 0)
    if not active:
        return
    median_amt = active[len(active) // 2]
    LIFT_THRESHOLD = 1.5
    MIN_GIFTS = 3
    MIN_AMT = 100.0
    earliest = days[0]; latest = days[-1]

    from datetime import date as _date
    for p in gh["posts"]:
        d0 = (p.get("published") or "")[:10]
        if not d0 or d0 < earliest or d0 > latest:
            p["donations_window"] = None
            continue
        try:
            y, m, dd = (int(x) for x in d0.split("-"))
            start = _date(y, m, dd)
        except Exception:
            p["donations_window"] = None
            continue
        amt = 0.0; n = 0; valid = False
        for k in range(window_days):
            day = (start + timedelta(days=k)).isoformat()
            if day in daily:
                amt += daily[day]["amt"]; n += daily[day]["gifts"]; valid = True
        if not valid:
            p["donations_window"] = None
            continue
        p["donations_window_amt"]  = round(amt, 2)
        p["donations_window_n"]    = n
        p["donations_window_days"] = window_days
        if median_amt > 0:
            p["donor_lift"] = round(amt / median_amt, 2)
        p["donor_mover"] = bool(
            n >= MIN_GIFTS and amt >= MIN_AMT
            and p.get("donor_lift", 0) >= LIFT_THRESHOLD
        )
    gh["donation_baseline_xd"] = round(median_amt, 2)
    gh["donation_window_days"] = window_days


def main():
    PRIV.mkdir(parents=True, exist_ok=True)
    mc = pull_mailchimp()
    gh = pull_ghost()
    signup_attr = pull_ghost_signup_attribution(days_back=180)
    db = pull_donorbox()
    attribute_signups_to_posts(mc, gh, signup_attr=signup_attr)
    attribute_donations_to_posts(db, gh)

    # Ghost is the source of truth for signups (the public newsletter form
    # writes to Ghost first; Mailchimp is reconciled in weekly batches). Use
    # the Ghost signup_event stream to overwrite the `subs` field in the
    # Mailchimp daily activity series — that's why the dashboard's last-2-days
    # signup count was reading zero (people.json rebuilds daily and lags).
    if signup_attr.get("available") and signup_attr.get("by_day"):
        by_day_ghost = {r["d"]: r["subs"] for r in signup_attr["by_day"]}
        # Replace the subs field with Ghost's authoritative count
        for row in (mc.get("daily_activity") or []):
            if row.get("d") in by_day_ghost:
                row["subs"] = by_day_ghost[row["d"]]
        # Add any days Ghost has that Mailchimp activity doesn't (the last
        # day or two, typically)
        existing_days = {row["d"] for row in (mc.get("daily_activity") or [])}
        for d, n in by_day_ghost.items():
            if d not in existing_days:
                mc.setdefault("daily_activity", []).append({
                    "d": d, "subs": n, "unsubs": 0, "opens": 0, "clicks": 0,
                })
        mc["daily_activity"] = sorted(mc.get("daily_activity") or [], key=lambda r: r["d"])
        # Note this in the data so the dashboard can label it
        mc["signup_source"] = "ghost_events"
        # Also recompute the signup_windows ytd/prior_ytd totals based on the
        # corrected activity series.
        from datetime import date as _date
        today = datetime.now(timezone.utc).date()
        y = today.year
        rows = mc["daily_activity"]
        def _sum(start, end, key):
            s, e = start.isoformat(), end.isoformat()
            return sum(int(r.get(key) or 0) for r in rows if s <= r["d"] <= e)
        ytd_start = _date(y, 1, 1); ytd_end = today
        py_start  = _date(y-1, 1, 1); py_end = _date(y-1, today.month, today.day)
        mc.setdefault("signup_windows", {})
        # When Mailchimp's net change for a month is zero/negative (list
        # cleanup wiped out the gross signups), patch that month's signup
        # count from Ghost's per-event count instead — Ghost only sees real
        # form signups so it's not affected by cleanups.
        from collections import defaultdict as _dd2
        ghost_month = _dd2(int)
        for row in (mc.get("daily_activity") or []):
            if row.get("subs", 0) > 0:
                ghost_month[row["d"][:7]] += int(row["subs"])
        for m in (mc.get("monthly_signups") or []):
            mo = m.get("month") or ""
            if m.get("new_signups", 0) == 0 and ghost_month.get(mo, 0) > 0:
                m["new_signups"] = ghost_month[mo]
                m["source_note"] = "Ghost events (Mailchimp net was zero/negative this month from a list cleanup)"
        # Re-compute YTD totals after the patch
        from datetime import date as _date2
        _today = datetime.now(timezone.utc).date()
        def _ytd2(year, m_through, ms):
            return sum(int(x.get("new_signups") or 0) for x in ms
                       if (x.get("month") or "").startswith(f"{year}-")
                       and (x.get("month") or "")[5:7] <= f"{m_through:02d}")
        _ms = mc.get("monthly_signups") or []
        mc["signup_windows"]["ytd"]       = _ytd2(_today.year,     _today.month, _ms)
        mc["signup_windows"]["prior_ytd"] = _ytd2(_today.year - 1, _today.month, _ms)
        mc["signup_windows"]["prior_ytd_ok"] = mc["signup_windows"]["prior_ytd"] > 0
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mailchimp": mc,
        "ghost":     gh,
        "donorbox":  db,
        "ghost_signup_attribution": {
            "available":      signup_attr.get("available", False),
            "events_counted": signup_attr.get("events_counted", 0),
            "window_days":    signup_attr.get("window_days", 0),
        },
        "press":     pull_press(),
        "news_mentions": pull_news_mentions(),
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
        "x_profile":  pull_x(),
        "instagram":  pull_instagram(),
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
