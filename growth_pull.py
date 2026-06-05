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
            op = (rs.get("open_rate")  or 0) * 100
            cl = (rs.get("click_rate") or 0) * 100
            ctor = (cl / op * 100) if op > 0 else 0
            camp_out.append({
                "id":       c.get("id"),
                "subject":  (c.get("settings") or {}).get("subject_line", ""),
                "variate_subjects": variate_subjects,
                "type":     c.get("type") or "regular",
                "sent":     (c.get("send_time") or "")[:10],
                "sent_to":  c.get("emails_sent") or 0,
                "open_pct": round(op, 1),
                "click_pct":round(cl, 1),
                "ctor_pct": round(ctor, 1),   # click-to-open ratio = honest engagement
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
            op_pct = (r["wt_open"]  / recs) * 100
            cl_pct = (r["wt_click"] / recs) * 100
            monthly.append({
                "month": m,
                "sends": r["sends"],
                "recipients": r["recipients"],
                "open_pct":  round(op_pct, 1),
                "click_pct": round(cl_pct, 1),
                "ctor_pct":  round((cl_pct / op_pct) * 100, 1) if op_pct > 0 else 0,
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
            op_pct = (wt_open  / recs) * 100 if recs else 0
            cl_pct = (wt_click / recs) * 100 if recs else 0
            return {
                "sends": len(items),
                "recipients": recs,
                "open_pct":  round(op_pct, 1),
                "click_pct": round(cl_pct, 1),
                "ctor_pct":  round((cl_pct / op_pct) * 100, 1) if op_pct > 0 else 0,
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

    # The _union_openers function returns just a count; for lifecycle analysis
    # we need the actual opener SET to cross-reference against signup dates.
    # Re-issue the pulls but capture the sets too (re-uses Mailchimp data we
    # already paid the API cost for; about doubles AAU pull time, but worth
    # it since lifecycle is the single highest-leverage analysis).
    def _union_openers_with_set(days_back):
        since_iso = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        url = (f"/campaigns?status=sent&list_id={list_id}"
               f"&since_send_time={urllib.parse.quote(since_iso)}"
               f"&count=500&sort_field=send_time&sort_dir=DESC"
               f"&fields=campaigns.id,campaigns.type,campaigns.send_time")
        try:
            cs = mc_get(url, key, dc).get("campaigns", [])
        except Exception as e:
            log(f"  lifecycle openers ({days_back}d) failed: {e}"); return (set(), {})
        regulars = [c for c in cs if c.get("type") == "regular"]
        variate  = [c for c in cs if c.get("type") == "variate"]
        openers = set()
        for c in regulars:
            cid = c["id"]; offset = 0
            while True:
                try:
                    page = mc_get(
                        f"/reports/{cid}/open-details?count=1000&offset={offset}"
                        f"&fields=members.email_address,total_items", key, dc)
                except Exception as e: break
                for m in page.get("members", []):
                    em = (m.get("email_address") or "").lower().strip()
                    if em: openers.add(em)
                total = int(page.get("total_items") or 0)
                offset += 1000
                if offset >= total: break
        return (openers, {"regulars_counted": len(regulars), "variate_excluded": len(variate)})

    log("  computing MAU (30d) openers set…")
    mau_set, mau_meta = _union_openers_with_set(30)
    log("  computing AAU (365d) openers set…")
    aau_set, aau_meta = _union_openers_with_set(365)
    out["mau"] = {"active_users": len(mau_set), **mau_meta}
    out["aau"] = {"active_users": len(aau_set), **aau_meta}
    # Stash the sets internally so build_lifecycle() can use them
    out["_mau_set"] = mau_set
    out["_aau_set"] = aau_set
    return out


def _last_name_key(row):
    """Sort key for subset lists in the dashboard: alphabetical by last name,
    then first. Mirrors how the Contact tool sorts by last name — split on
    whitespace, the last token is the last name. Single-word names sort by
    the whole thing. Empty names sort last."""
    n = (row.get("name") or "").strip()
    if not n: return ("zzz", "")
    parts = n.split()
    if len(parts) == 1:
        return (parts[0].lower(), "")
    return (parts[-1].lower(), " ".join(parts[:-1]).lower())


def build_engagement_extras(mc, signup_attr, donorbox):
    """Four newer metrics that publishers (Atlantic, Pico-using sites, Stratechery)
    use to get past Apple Mail privacy noise:
      - mailbox_engagement: avg open rate by email provider (gmail vs Apple vs ...)
      - power_readers: top decile of Mailchimp rating + open rate (your reliable readers)
      - channel_ltv: subscriber→donor conversion by acquisition source
      - influence_weighted_reach: opens weighted by reader importance
                                  (rating + Wikipedia "notable" + government domain)
    All from data we already pull. Heuristic but defensible.
    """
    import csv
    out = {"available": True}
    eng_path = PRIV / "engagement_source.csv"
    pj_path  = PRIV / "people.json"

    # ---- 1. Mailbox-provider engagement -----------------------------------
    provider_buckets = {
        "Gmail":         ["gmail.com", "googlemail.com"],
        "Yahoo":         ["yahoo.com", "ymail.com", "rocketmail.com"],
        "Apple iCloud":  ["icloud.com", "me.com", "mac.com"],
        "Microsoft":     ["hotmail.com", "outlook.com", "live.com", "msn.com"],
        "AOL":           ["aol.com"],
        "Comcast":       ["comcast.net"],
        "Government":    [".gov"],    # any .gov subdomain
        "Academic":      [".edu"],
        "Other":         None,        # catch-all
    }
    def _provider(email):
        em = (email or "").lower()
        for label, doms in provider_buckets.items():
            if doms is None: continue
            for d in doms:
                if d.startswith("."):
                    if em.endswith(d) or f"{d}." in em: return label
                elif em.endswith("@"+d):
                    return label
        return "Other"

    by_prov = {label: {"label": label, "subs": 0, "wt_open_sum": 0.0} for label in provider_buckets}

    # ---- 2. Power readers ------------------------------------------------
    # Top-decile readers by composite engagement score: rating × 20 + open_rate
    rows = []     # (email, rating, open_rate)
    if eng_path.exists():
        with open(eng_path) as f:
            for r in csv.DictReader(f):
                em = (r.get("Email") or "").lower().strip()
                if not em: continue
                try:
                    rating = int(r.get("Rating") or 0)
                    op     = int(r.get("Open Rate") or 0)
                except: continue
                rows.append((em, rating, op))
                prov = _provider(em)
                by_prov[prov]["subs"] += 1
                by_prov[prov]["wt_open_sum"] += op   # avg of per-member rates within provider

    for d in by_prov.values():
        d["avg_open_pct"] = round(d["wt_open_sum"]/d["subs"], 1) if d["subs"] else 0
        d.pop("wt_open_sum")
    # Sort by sub count descending; drop empty
    out["mailbox_engagement"] = [d for d in sorted(by_prov.values(), key=lambda x: -x["subs"]) if d["subs"] >= 5]

    # Power-readers: composite score, take top 10%
    if rows:
        scored = sorted(rows, key=lambda r: -(r[1] * 20 + r[2]))
        decile = max(1, len(scored) // 10)
        power = scored[:decile]
        # Provider breakdown of power readers
        pp = {}
        for em, _, _ in power:
            p = _provider(em)
            pp[p] = pp.get(p, 0) + 1
        out["power_readers"] = {
            "count": len(power),
            "as_pct_of_list": round((len(power) / max(len(rows), 1)) * 100, 1),
            "by_provider": [{"label": p, "n": n} for p, n in sorted(pp.items(), key=lambda kv: -kv[1])],
            "avg_open_pct": round(sum(r[2] for r in power) / len(power), 1) if power else 0,
            "avg_rating":   round(sum(r[1] for r in power) / len(power), 2) if power else 0,
        }
    else:
        out["power_readers"] = {"count": 0, "by_provider": [], "as_pct_of_list": 0,
                                "avg_open_pct": 0, "avg_rating": 0}

    # ---- 3. Channel LTV (subscriber → donor by acquisition source) -------
    # For each acquisition source recorded in Ghost's signup attribution,
    # find which subscribers became donors (join via email) and sum their
    # donation totals. Caveat: limited to subscribers whose signup events
    # are in the Ghost feed (post April-2026 site cutover, ~800 signups
    # captured here). Pre-cutover donors won't have a source we can attribute.
    src_email = (signup_attr or {}).get("_by_email") or {}
    if src_email and pj_path.exists():
        try:
            people_for_ltv = json.loads(pj_path.read_text())
        except Exception: people_for_ltv = []
        # email → person; capture donor totals
        em_to_person = {}
        for p in people_for_ltv:
            for em in (p.get("emails") or []):
                em_to_person[em.lower().strip()] = p
        chan = {}     # source label → {signups, donors, total_amt, gifts}
        for em, info in src_email.items():
            src = info.get("source") or "(unknown)"
            chan.setdefault(src, {"signups": 0, "donors": 0, "total_amt": 0.0, "gifts": 0})
            chan[src]["signups"] += 1
            p = em_to_person.get(em)
            if p and p.get("don"):
                chan[src]["donors"]    += 1
                chan[src]["total_amt"] += float(p.get("damt") or 0)
                chan[src]["gifts"]     += int(p.get("dcnt") or 0)
        # Roll up tiny channels (<5 signups) into "Other" to keep the chart readable
        chan_rows = []   # renamed from `rows` to avoid shadowing the engagement tuples list above
        other = {"signups": 0, "donors": 0, "total_amt": 0.0, "gifts": 0}
        for src, d in chan.items():
            if d["signups"] < 5:
                other["signups"] += d["signups"]
                other["donors"]  += d["donors"]
                other["total_amt"] += d["total_amt"]
                other["gifts"]     += d["gifts"]
                continue
            chan_rows.append({
                "source":      src,
                "signups":     d["signups"],
                "donors":      d["donors"],
                "donor_rate":  round((d["donors"] / d["signups"]) * 100, 1) if d["signups"] else 0,
                "total_raised":round(d["total_amt"], 2),
                "ltv_per_signup": round(d["total_amt"] / d["signups"], 2) if d["signups"] else 0,
                "ltv_per_donor":  round(d["total_amt"] / d["donors"], 2)  if d["donors"]  else 0,
            })
        if other["signups"] > 0:
            chan_rows.append({
                "source":      "Other (small channels)",
                "signups":     other["signups"],
                "donors":      other["donors"],
                "donor_rate":  round((other["donors"] / other["signups"]) * 100, 1) if other["signups"] else 0,
                "total_raised":round(other["total_amt"], 2),
                "ltv_per_signup": round(other["total_amt"] / other["signups"], 2) if other["signups"] else 0,
                "ltv_per_donor":  round(other["total_amt"] / other["donors"], 2)  if other["donors"]  else 0,
            })
        chan_rows.sort(key=lambda r: -r["signups"])
        # Totals row for context
        tot = {
            "signups":     sum(r["signups"] for r in chan_rows),
            "donors":      sum(r["donors"]  for r in chan_rows),
            "total_raised":round(sum(r["total_raised"] for r in chan_rows), 2),
        }
        tot["donor_rate"] = round((tot["donors"] / tot["signups"]) * 100, 1) if tot["signups"] else 0
        tot["ltv_per_signup"] = round(tot["total_raised"] / tot["signups"], 2) if tot["signups"] else 0
        out["channel_ltv"] = {
            "available": True,
            "window_days": (signup_attr or {}).get("window_days", 180),
            "channels": chan_rows,
            "total": tot,
        }
    else:
        out["channel_ltv"] = {"available": False,
            "reason": "No per-email signup data available — needs Ghost member-events feed."}

    # ---- 4. Influence-weighted reach -------------------------------------
    # Score each subscriber by their likely influence in NYC policy circles:
    #   rating-based engagement + wiki "notable" bonus + gov/edu bonus
    # Sum across all subscribers in MAU → influence-weighted reach
    # Convert rows (list of tuples) into email→rating dict for fast lookup
    rating_by_email = {r[0]: r[1] for r in rows} if rows else {}
    if pj_path.exists() and rows:
        try:
            people = json.loads(pj_path.read_text())
        except Exception: people = []
        # Map email → person (for is_notable, types, etc.)
        em2p = {}
        for p in people:
            if not p.get("mem") or p.get("unsub"): continue
            for em in (p.get("emails") or []):
                em2p[em.lower().strip()] = p
        # MAU emails (need set passed in — fall back to high-rating subscribers as proxy)
        mau_set = mc.get("_mau_set") or set()
        def _score(p, rating):
            s = 1.0 + (rating or 0) * 0.4
            if p.get("wiki"): s += 2.0
            types = set(p.get("types") or [])
            if any(t in types for t in ("current nyc.gov", "city gov", "state gov", "fed gov", "judge")):
                s += 1.5
            return s

        weighted_total = 0.0
        unweighted_total = 0
        notable_list = []
        gov_list     = []
        GOV_TYPES = {"current nyc.gov", "city gov", "state gov", "fed gov", "judge"}
        for em, p in em2p.items():
            if mau_set and em not in mau_set: continue
            rating = rating_by_email.get(em, 0)
            weighted_total += _score(p, rating)
            unweighted_total += 1
            types = set(p.get("types") or [])
            row = {
                "name":  p.get("n") or "(no name)",
                "email": em,
                "inst":  p.get("inst") or "",
                "types": list(types)[:6],
                "rating": rating,
            }
            if p.get("wiki"): notable_list.append({**row, "wiki": True})
            if any(t in types for t in GOV_TYPES): gov_list.append(row)
        # Alphabetical by last name — matches how the Contact tool sorts and
        # makes it easy to scan / find specific people.
        notable_list.sort(key=_last_name_key)
        gov_list.sort(    key=_last_name_key)
        out["influence_weighted_reach"] = {
            "score":            round(weighted_total, 1),
            "raw_mau":          unweighted_total,
            "notable_in_mau":   len(notable_list),
            "gov_in_mau":       len(gov_list),
            "score_per_reader": round(weighted_total / unweighted_total, 2) if unweighted_total else 0,
            "notable_list":     notable_list,
            "gov_list":         gov_list,
        }
    else:
        out["influence_weighted_reach"] = {"available": False, "reason": "no people.json or engagement data"}

    # Also include a power-readers list (top 200 by composite engagement score)
    # so the count there is clickable too. Stored separately to keep the
    # power_readers summary block backward-compatible.
    if rows:
        scored2 = sorted(rows, key=lambda r: -(r[1] * 20 + r[2]))
        top = scored2[: min(200, max(1, len(scored2) // 10))]   # top 10% capped at 200
        # Lookup person info for each
        pj_path2 = PRIV / "people.json"
        em2p2 = {}
        if pj_path2.exists():
            try:
                _people = json.loads(pj_path2.read_text())
                for p in _people:
                    for em in (p.get("emails") or []):
                        em2p2[em.lower().strip()] = p
            except Exception: pass
        prl = [{
            "name":   (em2p2.get(em, {}).get("n") or "(no name)"),
            "email":  em,
            "inst":   em2p2.get(em, {}).get("inst") or "",
            "rating": rating,
            "open_pct": op,
        } for em, rating, op in top]
        prl.sort(key=_last_name_key)
        out["power_readers_list"] = prl

    return out


def build_lifecycle(mc):
    """Retention curves + sunset + at-risk analysis from the MAU/AAU sets
    + people.json signup dates + engagement-source ratings.

    Outputs the four core lifecycle metrics:
      - cohort_retention: % of each signup cohort that's in MAU today
      - activation_rate: % of new-30-day subscribers in MAU
      - sunset_candidates: low-engagement + tenured subscribers (count + sample)
      - at_risk: AAU minus MAU = lapsed-but-once-engaged
    """
    if not mc or not mc.get("_mau_set"):
        return {"available": False, "reason": "no MAU/AAU sets available"}
    mau_set = mc["_mau_set"]
    aau_set = mc["_aau_set"]
    today = datetime.now(timezone.utc).date()

    # Load people.json for subscriber list + signup dates
    pj = PRIV / "people.json"
    if not pj.exists():
        return {"available": False, "reason": "no people.json yet"}
    try:
        people = json.loads(pj.read_text())
    except Exception as e:
        return {"available": False, "reason": f"people.json read failed: {e}"}

    # Load Mailchimp member ratings (1-5 stars) from cached engagement CSV
    ratings = {}   # email -> rating int
    eng = PRIV / "engagement_source.csv"
    if eng.exists():
        import csv
        with open(eng) as f:
            for row in csv.DictReader(f):
                em = (row.get("Email") or "").lower().strip()
                if em:
                    try: ratings[em] = int(row.get("Rating") or 0)
                    except: pass

    # Cohort buckets (days since signup)
    BUCKETS = [
        ("0-7 days",      0,   7),
        ("8-14 days",     8,   14),
        ("15-30 days",    15,  30),
        ("31-60 days",    31,  60),
        ("61-90 days",    61,  90),
        ("91-180 days",   91,  180),
        ("181-365 days",  181, 365),
        ("366-730 days",  366, 730),
        ("731+ days",     731, 99999),
    ]
    cohort = {lab: {"label": lab, "subs": 0, "engaged": 0, "lo": lo, "hi": hi} for lab, lo, hi in BUCKETS}

    sunset = []
    at_risk = []
    new_30 = 0
    new_30_engaged = 0
    total_subs = 0

    for p in people:
        if not p.get("mem"): continue
        if p.get("unsub"): continue
        total_subs += 1
        # Subscriber's earliest signup date — use `since`
        since = (p.get("since") or "")[:10]
        if not since: continue
        try:
            y, m, d = (int(x) for x in since.split("-"))
            from datetime import date as _date
            signup = _date(y, m, d)
        except Exception: continue
        days_since = (today - signup).days
        # Which buckets does this person belong to (use the first matching)
        for lab, lo, hi in BUCKETS:
            if lo <= days_since <= hi:
                cohort[lab]["subs"] += 1
                # Is any of this person's emails in MAU?
                em_list = [e.lower().strip() for e in (p.get("emails") or [p.get("e","")]) if e]
                engaged = any(em in mau_set for em in em_list)
                if engaged: cohort[lab]["engaged"] += 1
                break

        # Activation: did new-30-day subscribers open anything?
        if days_since <= 30:
            new_30 += 1
            em_list = [e.lower().strip() for e in (p.get("emails") or [p.get("e","")]) if e]
            if any(em in mau_set for em in em_list):
                new_30_engaged += 1

        # Sunset candidates: rating ≤ 2 AND tenured > 180 days AND NOT in MAU
        em_list = [e.lower().strip() for e in (p.get("emails") or [p.get("e","")]) if e]
        worst_rating = min((ratings.get(em, 5) for em in em_list if em in ratings), default=None)
        in_mau = any(em in mau_set for em in em_list)
        in_aau = any(em in aau_set for em in em_list)
        if (worst_rating is not None and worst_rating <= 2
            and days_since > 180 and not in_mau):
            sunset.append({
                "name":  p.get("n") or "(no name)",
                "email": em_list[0] if em_list else "",
                "rating": worst_rating,
                "since":  since,
                "tenure_days": days_since,
            })
        # At-risk: was in AAU but not in MAU (opened in last year but not last 30d)
        if in_aau and not in_mau:
            at_risk.append({
                "name":  p.get("n") or "(no name)",
                "email": em_list[0] if em_list else "",
                "rating": worst_rating,
                "since":  since,
                "tenure_days": days_since,
            })

    # Compute retention rate per cohort
    for lab, d in cohort.items():
        d["retention_pct"] = round((d["engaged"] / d["subs"]) * 100, 1) if d["subs"] else None

    activation_rate = round((new_30_engaged / new_30) * 100, 1) if new_30 else 0

    return {
        "available": True,
        "total_subscribers_counted": total_subs,
        "cohort_retention": [cohort[lab] for lab, lo, hi in BUCKETS],
        "activation_30d": {
            "cohort_size": new_30,
            "engaged":     new_30_engaged,
            "pct":         activation_rate,
        },
        "sunset_candidates": {
            "count": len(sunset),
            # Sample sticks with longest-tenure-first (the inline preview in
            # the lifecycle card surfaces the longest-lapsed first as a
            # nudge), but the modal list is alphabetical by last name.
            "sample": sorted(sunset, key=lambda x: -x["tenure_days"])[:20],
            "list":   sorted(sunset, key=_last_name_key)[:500],
        },
        "at_risk": {
            "count": len(at_risk),
            # Sample stays sorted by star rating (highest-engagement first) so
            # the inline preview leads with your highest-value reachable
            # subscribers. The modal list is alphabetical by last name.
            "sample": sorted(at_risk, key=lambda x: -(x.get("rating") or 0))[:20],
            "list":   sorted(at_risk, key=_last_name_key)[:500],
        },
    }


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
    by_email  = {}         # email -> {source, medium, landing_url, ts} (for channel-LTV join)
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
            # Per-email source map (for channel-LTV join with donor data).
            # First-touch attribution: if a user re-signs up later, keep the
            # earliest recorded source.
            mem = d.get("member") or {}
            mem_em = ((mem.get("email") or "")).lower().strip()
            if mem_em and mem_em not in by_email:
                by_email[mem_em] = {"source": src, "medium": med, "type": ltype, "ts": ts}
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
    log(f"  ghost signup attribution: {fetched} signup events across {len(by_url)} URLs, {len(by_day)} days, {len(by_source)} sources, {len(by_email)} per-email entries")
    return {
        "available":      True,
        "events_counted": fetched,
        "by_url":         by_url,
        "by_day":         [{"d": d, "subs": n} for d, n in sorted(by_day.items())],
        "by_source":      [{"src": s, "n": n} for s, n in sorted(by_source.items(), key=lambda kv: -kv[1])],
        "by_medium":      [{"med": m, "n": n} for m, n in sorted(by_medium.items(), key=lambda kv: -kv[1])],
        "by_landing":     [{"type": t, "n": n} for t, n in sorted(by_landing.items(), key=lambda kv: -kv[1])],
        "window_days":    days_back,
        "_by_email":      by_email,   # internal — used for channel-LTV join, stripped before JSON write
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
    ("facebook.com",     "Facebook"),
    ("threads.net",      "Threads"),
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
    # Google News RSS hard-caps at 100 results per query. For high-volume
    # platforms we hit that ceiling and lose older items. Mitigation: also
    # query each social platform's vitalcitynyc.org share by year, which
    # multiplies our depth by 3-4x without changing the shape of the data.
    cur_year = datetime.now(timezone.utc).year
    targets = []
    for d, label in MEDIA_OUTLETS:
        for s in MEDIA_SHAPES:
            targets.append((d, label, "media", s, None))
    for d, label in SOCIAL_PLATFORMS:
        # Brand-tag shape (no year split)
        targets.append((d, label, "social", "@vitalcitynyc", None))
        # URL-share shape, split by year for depth (cur..cur-5 inclusive)
        for yr in range(cur_year, cur_year - 6, -1):
            targets.append((d, label, "social", "vitalcitynyc.org", yr))
    for domain, label, kind, shape, year in targets:
        q = f'{shape} site:{domain}'
        if year is not None:
            # Constrain to a single calendar year using Google's "after:" /
            # "before:" operators — works inside news.google.com queries.
            q += f' after:{year}-01-01 before:{year+1}-01-01'
        url = (f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}"
               f"&hl=en-US&gl=US&ceid=US:en")
        # Indent the rest of the loop body
        if True:
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

    # Parse pub dates. For PRESS mentions we drop anything older than 24
    # months (old press isn't actionable). For URL SHARES on social we keep
    # everything Google indexed — those are organic distribution signals
    # that don't go stale the same way.
    cutoff_press = datetime.now(timezone.utc) - timedelta(days=730)
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
    out = [it for it in out
           if it.get("_dt") and (it.get("kind") == "social" or it["_dt"] >= cutoff_press)]

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

    # Per-kind caps. Press capped tight (recent 200), social much higher
    # since URL shares are the headline social signal and we want depth.
    media  = [it for it in deduped if it.get("kind") == "media"][:200]
    social = [it for it in deduped if it.get("kind") == "social"][:1500]
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
            # Keep all syndication tweets (up to 100) so flag_own_url_shares
            # has a deeper matching set. The dashboard's social card still
            # slices to the most recent ~10 for display.
            "recent_tweets": tweets[:100],
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
def pull_all_ghost_titles():
    """All-time Ghost article titles via the Content API. Used for own-post
    detection — matching a share's title against the full title catalog
    catches LinkedIn/Facebook/Instagram VC-account reposts that use the
    article title verbatim. Fast — only titles, ~10 KB total."""
    titles = set()
    page = 1
    while True:
        try:
            url = (f"{GHOST_API}/posts/?key={GHOST_CONTENT_KEY}"
                   f"&limit=100&page={page}&fields=title")
            data = json.loads(http_get(url, timeout=30))
        except Exception as e:
            log(f"  ghost title catalog page {page} failed: {e}"); break
        for p in data.get("posts", []):
            t = (p.get("title") or "").strip()
            if t and len(t) > 8: titles.add(t)
        meta = (data.get("meta") or {}).get("pagination") or {}
        if not meta.get("next"): break
        page = meta["next"]
        if page > 30: break   # safety
    log(f"  ghost title catalog: {len(titles)} titles")
    return titles


def pull_own_social_posts():
    """Query Google News restricted to VC's own social-account paths
    (x.com/VitalCityNYC, linkedin.com/company/vitalcitynyc). Returns
    per-domain sets of post titles that are KNOWN to be VC's own — used
    as a stronger own-vs-third-party signal than article-title matching,
    which only catches LinkedIn company-page reposts.
    """
    UA_local = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    # Site paths that Google News will accept. We search each path with three
    # query shapes to gather as many VC-own titles as possible (the brand
    # phrase, the URL, and a wildcard).
    sources = [
        ("x.com",        ["site:x.com/VitalCityNYC",
                          "site:twitter.com/VitalCityNYC",
                          'site:x.com/VitalCityNYC "vitalcitynyc.org"']),
        ("linkedin.com", ["site:linkedin.com/company/vitalcitynyc",
                          'site:linkedin.com/company/vitalcitynyc "vitalcitynyc"']),
    ]
    out = {}
    for dom, qs in sources:
        titles = []
        for q in qs:
            try:
                url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en"
                xml = http_get(url, headers={"User-Agent": UA_local}, timeout=20)
                root = ET.fromstring(xml)
                for it in root.findall(".//item"):
                    t = _xml_text(it, "title").strip()
                    if t and len(t) > 8: titles.append(t)
            except Exception as e:
                log(f"  own-social ({dom}/{q[:40]}) failed: {e}")
        out[dom] = list(set(titles))   # dedup within domain
    log(f"  VC own social posts: {sum(len(v) for v in out.values())} titles ({', '.join(f'{k}={len(v)}' for k,v in out.items())})")
    return out


def flag_own_url_shares(news_mentions, all_titles, vc_tweets=None, own_social=None):
    """For each URL-share item, classify it and decide whether to keep it.

    Two-stage filter:
      1. KEEP-OR-DROP: the title or snippet must actually look like a VC
         reference (brand phrase or known article title substring). Filters
         out Facebook Page false positives like "Model Cities Initiative".
      2. OWN vs THIRD-PARTY: a share is flagged as VC's own social post if
         (a) its title matches a known VC article title verbatim or substring
         (catches LinkedIn company-page reposts), OR
         (b) its title matches text from a recent @VitalCityNYC tweet pulled
         via the syndication feed (catches X tweets where VC's promotional
         copy is original and doesn't repeat the article title — "Amid the
         seemingly endless news...", "Left: Vital City in January..." etc.).
    """
    if not news_mentions:
        return
    norm = lambda s: re.sub(r"[\W_]+", "", (s or "").lower())
    titles_n = {norm(t) for t in (all_titles or set())}
    substr_titles = [t for t in titles_n if len(t) > 20]
    # Normalize VC's own recent tweets for matching X shares. We strip URLs
    # and handles before normalizing because Google News titles often drop
    # the trailing t.co links that VC tweets include.
    vc_tweets_n = set()
    if vc_tweets:
        for t in vc_tweets:
            cleaned = re.sub(r"https?://\S+", "", t or "")
            cleaned = re.sub(r"@\w+", "", cleaned)
            n = norm(cleaned)
            if len(n) > 25:    # ignore very short tweets to avoid bad matches
                vc_tweets_n.add(n)
    # Per-domain own-social-post titles (from pull_own_social_posts —
    # Google News restricted to x.com/VitalCityNYC and
    # linkedin.com/company/vitalcitynyc). Stronger signal than vc_tweets
    # because it doesn't depend on the syndication feed's quirks.
    own_titles_by_dom = {}
    if own_social:
        for dom, titles in own_social.items():
            normd = set()
            PLATFORM_TAILS_pre = re.compile(r"\s*[-–—]\s*[\w\.]+\s*$")
            for t in titles:
                t2 = PLATFORM_TAILS_pre.sub("", t).strip()
                t2 = re.sub(r"https?://\S+", "", t2)
                t2 = re.sub(r"@\w+", "", t2)
                n = norm(t2)
                if len(n) > 20: normd.add(n)
            own_titles_by_dom[dom] = normd
    PLATFORM_TAILS = re.compile(
        r"\s*[-–—]\s*(LinkedIn|Facebook|Instagram|X|Twitter|Bluesky|Threads|"
        r"x\.com|twitter\.com|bsky\.app|facebook\.com|instagram\.com)\s*$", re.I)
    BRAND = re.compile(r"(?i)\bvital\s*city\b|vitalcitynyc")

    def looks_like_vc(it):
        # Brand phrase or domain in title or snippet → clearly about us
        if BRAND.search(it.get("title", "")) or BRAND.search(it.get("snippet", "")):
            return True
        # Otherwise require a long-enough match against a known VC article title
        t_norm = norm(PLATFORM_TAILS.sub("", it.get("title", "")).strip())
        if len(t_norm) < 15: return False
        for ti in substr_titles:
            if ti in t_norm or t_norm in ti: return True
        return False

    kept = []
    for it in news_mentions:
        if it.get("is_url_share"):
            if not looks_like_vc(it):
                continue  # drop the false positive
            t = it.get("title") or ""
            stripped = PLATFORM_TAILS.sub("", t).strip()
            s_norm = norm(stripped)
            # Strip URLs/handles from the title before matching against VC's
            # own X tweets — Google often drops the t.co link from the end
            # while VC's tweet text includes one.
            s_norm_x = norm(re.sub(r"@\w+", "", re.sub(r"https?://\S+", "", stripped)))
            domain_lc = (it.get("domain") or "").lower()
            is_x = ("x.com" in domain_lc or "twitter" in domain_lc)
            if s_norm in titles_n:
                it["own_post"] = True
            elif any(ti in s_norm or (len(s_norm) > 20 and s_norm in ti) for ti in substr_titles):
                it["own_post"] = True
            elif is_x and vc_tweets_n and len(s_norm_x) > 25 and any(
                tw in s_norm_x or s_norm_x in tw for tw in vc_tweets_n
            ):
                # Title matches one of @VitalCityNYC's recent tweets — own post
                it["own_post"] = True
            else:
                # Check against per-domain own-social-post titles from Google
                # News (site:x.com/VitalCityNYC etc.) — the strongest signal
                # for X & LinkedIn own posts that aren't article-title reposts.
                own = False
                for dom, normd in own_titles_by_dom.items():
                    if dom not in domain_lc: continue
                    if len(s_norm_x) > 20 and any(t in s_norm_x or s_norm_x in t for t in normd):
                        own = True; break
                it["own_post"] = own
        else:
            it["own_post"] = False
        kept.append(it)
    # Mutate the list in place so callers using the same reference see the result
    news_mentions[:] = kept


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
    # News mentions need to be pulled here (was at the bottom of out) so we
    # can post-process URL-share items for own-post flagging.
    news_mentions = pull_news_mentions()
    all_titles = pull_all_ghost_titles()
    # Pull VC's own X tweets to recognize URL shares that are reposts from
    # @VitalCityNYC's own account (where VC's tweet copy doesn't match an
    # article title verbatim — promotional text, contextual one-liners, etc.).
    xprof = pull_x()
    vc_tweets = [t.get("text","") for t in (xprof.get("recent_tweets") or [])] if xprof.get("available") else []
    own_social = pull_own_social_posts()
    flag_own_url_shares(news_mentions, all_titles, vc_tweets=vc_tweets, own_social=own_social)
    # Capture MAU/AAU sets BEFORE they're popped, for the people.json enrich pass
    mau_set_for_enrich = mc.get("_mau_set") or set()
    aau_set_for_enrich = mc.get("_aau_set") or set()
    lifecycle = build_lifecycle(mc)
    engagement_extras = build_engagement_extras(mc, signup_attr, db)
    # Strip internal-only fields from in-memory objects before JSON write
    mc.pop("_mau_set", None); mc.pop("_aau_set", None)
    signup_attr.pop("_by_email", None)

    # ---- Enrich people.json with engagement flags --------------------
    # Add mau / aau / power_reader / at_risk / sunset booleans to each
    # subscriber's record so the Contact tool can filter to these exact
    # subsets that the Growth dashboard surfaces. encrypt_people.py runs
    # after this in the workflow (we update workflow ordering separately),
    # so the next network/data.enc will carry these flags.
    pj_path = PRIV / "people.json"
    if pj_path.exists():
        try:
            people = json.loads(pj_path.read_text())
        except Exception as e:
            log(f"  enrich people.json: read failed: {e}")
            people = None
        if people is not None:
            # Pull the engagement subsets we computed
            power_emails = {r["email"] for r in (engagement_extras.get("power_readers_list") or [])}
            at_risk_emails = {r["email"] for r in (lifecycle.get("at_risk", {}).get("list") or []) if r.get("email")}
            sunset_emails  = {r["email"] for r in (lifecycle.get("sunset_candidates", {}).get("list") or []) if r.get("email")}
            updated = 0
            for p in people:
                em_list = [e.lower().strip() for e in (p.get("emails") or [p.get("e","")]) if e]
                old_mau = p.get("mau"); old_aau = p.get("aau")
                old_pr = p.get("power_reader"); old_ar = p.get("at_risk"); old_sc = p.get("sunset_candidate")
                p["mau"] = bool(any(em in mau_set_for_enrich for em in em_list))
                p["aau"] = bool(any(em in aau_set_for_enrich for em in em_list))
                p["power_reader"]     = bool(any(em in power_emails   for em in em_list))
                p["at_risk"]          = bool(any(em in at_risk_emails for em in em_list))
                p["sunset_candidate"] = bool(any(em in sunset_emails  for em in em_list))
                if (old_mau, old_aau, old_pr, old_ar, old_sc) != (p["mau"], p["aau"], p["power_reader"], p["at_risk"], p["sunset_candidate"]):
                    updated += 1
            pj_path.write_text(json.dumps(people, indent=2))
            log(f"  enriched people.json with engagement flags ({updated} rows changed)")
            # Re-encrypt people.json so the Contact tool picks up the new flags.
            # We do this directly (not via subprocess) to avoid a workflow round-trip.
            try:
                import encrypt_people
                encrypt_people.main()
                log(f"  re-encrypted network/data.enc with engagement flags")
            except Exception as e:
                log(f"  could not re-encrypt people.json: {e}")

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
        "news_mentions": news_mentions,
        "lifecycle":     lifecycle,
        "engagement_extras": engagement_extras,
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
        "x_profile":  xprof,
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
