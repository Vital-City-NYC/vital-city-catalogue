#!/usr/bin/env python3
"""
Weekly key indicators since the move to Ghost, with the longer monthly record
and industry norms beside them, written to a Google Sheet.

Tabs:
  weekly      one row per Monday-to-Sunday week from Jan. 6, 2025, through the
              last full week; the site moved from Prismic to Ghost on March 1,
              2026, and engaged time is comparable only from then
  monthly     the same measures by calendar month from January 2024, so the
              weekly numbers can be read against Vital City's own history
  benchmarks  published industry norms, with their sources
  events      dated initiatives and data breaks, marked on the charts
  signup_pages  the pages people signed up on most, last 4 weeks and since the move
  about       when the sheet was last refreshed

Every number comes straight from the source APIs on each run:
  Mailchimp   list size and net growth (rebuilt from each member's join and
              leave dates), active newsletter readers, open and click rates
  Donorbox    donors
  Ghost       the page each newsletter signup happened on
  GA4         website active users, average engaged time

The Claude dashboard reads the sheet through the Google Sheets connector,
because a dashboard page can't hold these keys or call these services itself.
Aggregate counts only: no names or addresses are written anywhere.

Runs from GitHub Actions every Monday (.github/workflows/kpi-weekly.yml).

Environment:
  MAILCHIMP_KEY, DONORBOX_KEY       (or private/.mailchimp_key, .donorbox_key)
  GHOST_ADMIN_KEY                   (or private/.ghost_admin_key)
  GA4_PROPERTY_ID, GA4_CREDS_JSON   the service account that also writes the sheet
  KPI_SHEET_ID                      the spreadsheet id

Local run without writing:  python3 kpi_weekly.py --dry-run [--out tabs.json]
"""
import argparse, base64, hashlib, json, os, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import growth_pull as gp

NY = ZoneInfo("America/New_York")
WEEK0 = date(2026, 3, 2)          # first Monday after the March 1, 2026 move to Ghost
WEEKS_FROM = date(2025, 1, 6)     # first full week of 2025; the weekly record starts here
HISTORY0 = date(2024, 1, 1)       # start of the monthly record
ACTIVE0 = date(2025, 1, 1)        # active readers need every send's openers; from 2025
LIST_ID = os.environ.get("MAILCHIMP_LIST", "ec30bf0c4b")

MEASURES = [
    "list_size", "list_net_change", "list_joined", "list_left",
    "active_readers", "active_share",
    "emails_sent", "open_rate", "click_rate",
    "donors", "new_donors", "gifts",
    "web_active_users", "avg_engaged_seconds",
]
WEEK_COLS = ["week_start", "week_end"] + MEASURES + ["donors_since_move", "engaged_time_comparable"]
MONTH_COLS = ["month", "month_start", "month_end"] + MEASURES + ["engaged_time_comparable"]

# Published norms, as the growth dashboard's industry-context table gives them
# (growth/index.html pulseBenchmarks, last reviewed June 2026). A measure with
# no reliable public standard says so rather than borrowing one.
BENCHMARKS = [
    ["kpi", "low", "high", "label", "note", "source"],
    ["open_rate", 0.28, 0.29, "Nonprofit average",
     "Apple Mail opens some emails automatically, which inflates every open rate, so read any open rate as an upper bound.",
     "M+R Benchmarks 2025"],
    ["click_rate", 0.03, 0.06, "Typical for media newsletters",
     "About 3.3% is the nonprofit average (M+R Benchmarks 2025) and 2.27% the all-industry average.",
     "Letterhead, ClickMinded and Brevo 2026 email compilations"],
    ["list_left_share", 0, 0.05, "Healthy monthly churn",
     "Healthy digital news publications lose under about 5% of their list a month.",
     "INMA 2025"],
    ["active_share", "", "", "No fixed standard",
     "Readers who regularly open a newsletter are about twice as likely to still be subscribed a year later.",
     "INMA 2025"],
    ["web_active_users", "", "", "No fixed standard",
     "Publisher search traffic fell by about a third globally in 2025, and small publishers lost more.",
     "Chartbeat data via Press Gazette"],
    ["avg_engaged_seconds", "", "", "No reliable public standard",
     "Analytics tools measure engaged time differently, so published averages don't carry over to Google Analytics.",
     ""],
    ["donors", "", "", "No reliable public standard",
     "Only about 20% of Americans pay for any online news; Vital City is free, so donations play that role.",
     "Reuters Institute Digital News Report 2025"],
]


# Dated events for the charts: the growth dashboard's own list, plus two
# since its last update.
EVENTS = gp.INITIATIVES + [
    {"from": "2026-10-08", "label": "Some new pieces go members-only", "kind": "site"},
    {"from": "2026-10-28", "label": "Signup boxes added inside and at the end of articles", "kind": "site"},
]


def log(m): print(m, file=sys.stderr, flush=True)


def periods():
    """Full weeks since WEEKS_FROM and full calendar months since HISTORY0,
    each ending no later than last Sunday or the end of last month."""
    today = datetime.now(NY).date()
    last_sun = today - timedelta(days=today.weekday() + 1)
    weeks, m = [], WEEKS_FROM
    while m + timedelta(days=6) <= last_sun:
        weeks.append((m, m + timedelta(days=6)))
        m += timedelta(days=7)
    months, s = [], HISTORY0
    while True:
        nxt = date(s.year + (s.month == 12), s.month % 12 + 1, 1)
        if nxt > today: break
        months.append((s, nxt - timedelta(days=1)))
        s = nxt
    return weeks, months


def ny_date(ts):
    if not ts: return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(NY).date()


def hashed(email):
    em = (email or "").lower().strip()
    return hashlib.sha256(em.encode()).hexdigest()[:16] if em else None


# ---------------------------------------------------------------- Mailchimp
def mc_members(key, dc):
    """(joined, left) dates for every member who has ever been on the list.
    Status as of today; a member who left and came back counts once, from
    their latest join."""
    rows = []
    for status in ("subscribed", "unsubscribed", "cleaned", "archived"):
        offset = 0
        while True:
            page = gp.mc_get(f"/lists/{LIST_ID}/members?status={status}&count=1000&offset={offset}"
                             f"&fields=total_items,members.timestamp_opt,members.timestamp_signup,"
                             f"members.last_changed", key, dc)
            for m in page.get("members", []):
                joined = ny_date(m.get("timestamp_opt") or m.get("timestamp_signup") or m.get("last_changed"))
                left = None if status == "subscribed" else ny_date(m.get("last_changed"))
                if joined: rows.append((joined, left))
            offset += 1000
            if offset >= int(page.get("total_items") or 0): break
    log(f"  mailchimp: {len(rows):,} members read")
    return rows


def list_size_on(members, d):
    return sum(1 for j, l in members if j <= d and (l is None or l > d))


def mc_campaigns(key, dc, since):
    since_iso = datetime(since.year, since.month, since.day, tzinfo=timezone.utc).isoformat()
    cs = gp.mc_get(f"/campaigns?status=sent&list_id={LIST_ID}&count=1000"
                   f"&since_send_time={urllib.parse.quote(since_iso)}"
                   f"&fields=campaigns.id,campaigns.type,campaigns.send_time,campaigns.emails_sent,"
                   f"campaigns.settings.subject_line,campaigns.variate_settings.subject_lines,"
                   f"campaigns.report_summary", key, dc).get("campaigns", [])
    out = []
    for c in cs:
        sent = ny_date(c.get("send_time"))
        if not sent or (c.get("emails_sent") or 0) < 100:   # tests and internal sends
            continue
        rs = c.get("report_summary") or {}
        entry = {"subject": (c.get("settings") or {}).get("subject_line", ""),
                 "variate_subjects": (c.get("variate_settings") or {}).get("subject_lines") or [],
                 "sent": sent.isoformat()}
        out.append({"id": c["id"], "type": c.get("type"), "sent": sent,
                    "kind": gp._campaign_kind(entry),
                    "unique_opens": int(rs.get("unique_opens") or 0),
                    "subscriber_clicks": int(rs.get("subscriber_clicks") or 0),
                    "open_rate": float(rs.get("open_rate") or 0)})
    log(f"  mailchimp: {len(out)} sends to readers since {since}")
    return out


def mc_openers(c, key, dc):
    """Hashed addresses of everyone who opened one send. An A/B send keeps its
    opens on hidden child campaigns (see growth_pull.variate_children)."""
    got = set()
    for rid in gp.report_ids(c["id"], c["type"], key, dc):
        offset = 0
        while True:
            page = gp.mc_get(f"/reports/{rid}/open-details?count=1000&offset={offset}"
                             f"&fields=members.email_address,total_items", key, dc)
            for m in page.get("members", []):
                h = hashed(m.get("email_address"))
                if h: got.add(h)
            offset += 1000
            if offset >= int(page.get("total_items") or 0): break
    return got


def pull_mailchimp(weeks, months):
    key = gp.mailchimp_key()
    if not key: raise SystemExit("MAILCHIMP_KEY not set")
    dc = key.split("-")[-1]
    members = mc_members(key, dc)
    camps = mc_campaigns(key, dc, HISTORY0)
    for c in camps:
        c["openers"] = mc_openers(c, key, dc) if c["sent"] >= ACTIVE0 - timedelta(days=30) else None
    log("  mailchimp: openers read")

    def measures(ps):
        out = {}
        prev = list_size_on(members, ps[0][0] - timedelta(days=1))
        for s, e in ps:
            size = list_size_on(members, e)
            active = None
            if e >= ACTIVE0:
                active = set()
                for c in camps:
                    if e - timedelta(days=29) <= c["sent"] <= e and c["openers"]:
                        active |= c["openers"]
                active = len(active)
            # Every email to readers except fundraising appeals
            em = [c for c in camps if s <= c["sent"] <= e and c["kind"] != "appeal"]
            delivered = sum(c["unique_opens"] / c["open_rate"] for c in em if c["open_rate"] > 0)
            out[s] = {
                "list_size": size, "list_net_change": size - prev,
                "list_joined": sum(1 for j, _ in members if s <= j <= e),
                "list_left": sum(1 for j, l in members if l and s <= l <= e and j <= l),
                "active_readers": active,
                "active_share": round(active / size, 4) if active is not None and size else None,
                "emails_sent": len(em),
                "open_rate": round(sum(c["unique_opens"] for c in em) / delivered, 4) if delivered else None,
                "click_rate": round(sum(c["subscriber_clicks"] for c in em) / delivered, 4) if delivered else None,
            }
            prev = size
        return out

    # Check the rebuilt list sizes against Mailchimp's own month-end counts
    try:
        hist = gp.mc_get(f"/lists/{LIST_ID}/growth-history?count=72&sort_field=month&sort_dir=ASC",
                         key, dc).get("history", [])
        mine = measures(months)
        for h in hist:
            s = date.fromisoformat(h["month"] + "-01")
            if s in mine and s >= date(2025, 1, 1):
                diff = mine[s]["list_size"] - int(h.get("subscribed") or 0)
                if abs(diff) > 0.01 * int(h.get("subscribed") or 1):
                    log(f"  check: {h['month']} rebuilt {mine[s]['list_size']} vs Mailchimp {h.get('subscribed')}")
    except Exception as ex:
        log(f"  check against growth-history skipped: {ex}")
        mine = measures(months)
    return measures(weeks), mine


# ---------------------------------------------------------------- Donorbox
def pull_donorbox(weeks, months):
    key, email = gp.donorbox_creds()
    if not key: raise SystemExit("DONORBOX_KEY not set")
    auth = base64.b64encode(f"{email}:{key}".encode()).decode()
    headers = {"Authorization": "Basic " + auth, "Accept": "application/json"}
    gifts, page = [], 1
    while page <= 200:
        batch = json.loads(gp.http_get(f"https://donorbox.org/api/v1/donations?page={page}&per_page=100",
                                       headers=headers, timeout=120))
        if not batch: break
        for d in batch:
            if (d.get("status") or "").lower() != "paid": continue
            who, day = hashed((d.get("donor") or {}).get("email")), ny_date(d.get("donation_date"))
            if who and day: gifts.append((day, who))
        if len(batch) < 100: break
        page += 1
    log(f"  donorbox: {len(gifts):,} paid gifts read")
    first = {}
    for day, who in sorted(gifts):
        first.setdefault(who, day)
    start = min(first.values()) if first else None

    def measures(ps):
        out = {}
        for s, e in ps:
            if not start or e < start: continue      # before Donorbox history begins
            g = [(d, w) for d, w in gifts if s <= d <= e]
            donors = {w for _, w in g}
            out[s] = {"donors": len(donors),
                      "new_donors": sum(1 for w in donors if s <= first[w] <= e),
                      "gifts": len(g),
                      "donors_since_move": len({w for d, w in gifts if WEEK0 <= d <= e}) if e >= WEEK0 else None}
        return out
    return measures(weeks), measures(months)


# ---------------------------------------------------------------- Ghost
SIGNUP_COLS = ["period", "start", "end", "rank", "title", "url", "kind", "signups", "period_signups"]


def pull_signup_pages(weeks, top=12):
    """Where people signed up, from Ghost's signup events: each carries the
    page the person was on. Bulk imports (event registration lists) are left
    out, since they have no page. Ghost became the signup record on
    March 3, 2026, so this starts at the move."""
    tok = gp._ghost_admin_token()
    if not tok: raise SystemExit("GHOST_ADMIN_KEY not set")
    end = weeks[-1][1]
    since = WEEK0
    events, cursor = [], None
    while True:
        flt = "type:signup_event" + (f"+id:<{cursor}" if cursor else "")
        data = json.loads(gp.http_get(f"{gp.GHOST_ADMIN_API}/members/events/?filter={urllib.parse.quote(flt)}&limit=100",
                                      headers={"Authorization": f"Ghost {tok}", "Accept-Version": "v5.0"}, timeout=60))
        batch = data.get("events") or []
        if not batch: break
        done = False
        for e in batch:
            d = e.get("data") or {}
            day = ny_date(d.get("created_at"))
            if not day: continue
            if day < since: done = True; break
            if day > end or d.get("source") == "import": continue
            a = d.get("attribution") or {}
            # Ghost records the homepage both as "/" and as the full address
            path = urllib.parse.urlparse(a.get("url") or "").path.rstrip("/")
            kind = a.get("type") or "unknown"
            if not path: title, kind = "Homepage", "homepage"
            else: title = a.get("title") or path
            events.append((day, path or "/", title, kind))
        cursor = batch[-1].get("data", {}).get("id") or batch[-1].get("id")
        if done or not cursor: break
    log(f"  ghost: {len(events):,} signups with a page since {since}")
    rows = [SIGNUP_COLS]
    four = weeks[-4][0]
    for name, s0 in (("last_4_weeks", four), ("since_move", since)):
        ev = [e for e in events if s0 <= e[0] <= end]
        counts = {}
        for _, url, title, kind in ev:
            c = counts.setdefault(url, {"title": title, "kind": kind, "n": 0})
            c["n"] += 1
        ranked = sorted(counts.items(), key=lambda kv: -kv[1]["n"])[:top]
        for i, (url, c) in enumerate(ranked, 1):
            rows.append([name, s0.isoformat(), end.isoformat(), i, c["title"], url, c["kind"], c["n"], len(ev)])
    return rows


# ---------------------------------------------------------------- GA4
def ga4_creds():
    raw = os.environ.get("GA4_CREDS_JSON", "").strip()
    if not raw: return None
    return json.loads(raw if raw.startswith("{") else base64.b64decode(raw))


def ga4_report(prop, token, start, end, dim):
    body = {"dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
            "dimensions": [{"name": dim}],
            "metrics": [{"name": "activeUsers"}, {"name": "userEngagementDuration"}],
            "limit": 1000}
    req = urllib.request.Request(
        f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rep = json.loads(r.read())
    out = {}
    for row in rep.get("rows") or []:
        v = row["dimensionValues"][0]["value"]                 # 202610 (ISO week) or 202603 (month)
        s = date.fromisocalendar(int(v[:4]), int(v[4:]), 1) if dim == "isoYearIsoWeek" \
            else date(int(v[:4]), int(v[4:]), 1)
        users, secs = int(row["metricValues"][0]["value"]), float(row["metricValues"][1]["value"])
        # GA4's "average engagement time per active user"
        out[s] = {"web_active_users": users,
                  "avg_engaged_seconds": round(secs / users, 1) if users else None}
    return out


def pull_ga4(weeks, months):
    prop, creds = os.environ.get("GA4_PROPERTY_ID", "").strip(), ga4_creds()
    if not (prop and creds):
        log("  ga4: no credentials here, website columns left blank")
        return {}, {}
    token = gp._ga4_access_token(creds)
    w = ga4_report(prop, token, weeks[0][0], weeks[-1][1], "isoYearIsoWeek")
    m = ga4_report(prop, token, months[0][0], months[-1][1], "yearMonth")
    log(f"  ga4: {len(w)} weeks, {len(m)} months read")
    return w, m


# ---------------------------------------------------------------- sheet
def write_sheet(sheet_id, tabs):
    token = gp._sa_access_token(ga4_creds(), "https://www.googleapis.com/auth/spreadsheets")
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + token,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")

    have = {s["properties"]["title"] for s in call("GET", "?fields=sheets.properties.title")["sheets"]}
    add = [{"addSheet": {"properties": {"title": t}}} for t in tabs if t not in have]
    if add: call("POST", ":batchUpdate", {"requests": add})
    for t, rows in tabs.items():
        call("POST", f"/values/{t}:clear", {})
        call("PUT", f"/values/{t}!A1?valueInputOption=RAW", {"values": rows})


def table(cols, ps, key_fn, *sources):
    rows = [cols]
    for s, e in ps:
        r = key_fn(s, e)
        for src in sources: r.update(src.get(s, {}))
        rows.append(["" if r.get(c) is None else r[c] for c in cols])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()

    weeks, months = periods()
    log(f"{len(weeks)} weeks from {weeks[0][0]}; {len(months)} months from {months[0][0]}")
    (mw, mm), (dw, dm), (gw, gm) = pull_mailchimp(weeks, months), pull_donorbox(weeks, months), pull_ga4(weeks, months)
    signup_pages = pull_signup_pages(weeks)

    weekly = table(WEEK_COLS, weeks, lambda s, e: {"week_start": s.isoformat(), "week_end": e.isoformat(),
                                                   # Prismic and Ghost recorded engaged time differently
                                                   "engaged_time_comparable": "yes" if s >= WEEK0 else "no"},
                   mw, dw, gw)
    monthly = table(MONTH_COLS, months,
                    lambda s, e: {"month": s.strftime("%Y-%m"), "month_start": s.isoformat(),
                                  "month_end": e.isoformat(),
                                  # Prismic and Ghost recorded engaged time differently
                                  "engaged_time_comparable": "yes" if s >= date(2026, 3, 1) else "no"},
                    mm, {s: {k: v for k, v in r.items() if k != "donors_since_move"} for s, r in dm.items()}, gm)

    # Fail loud rather than publish a sheet of blanks
    li = WEEK_COLS.index("list_size")
    if not all(row[li] for row in weekly[1:]):
        raise SystemExit("list sizes missing; not writing")

    stamp = datetime.now(NY).strftime("%Y-%m-%d %H:%M %Z")
    about = [["field", "value"], ["refreshed_at", stamp],
             ["periods", "Monday to Sunday weeks and calendar months, New York time, full periods only"],
             ["website_source", "GA4" if gw else "missing on this run"]]
    events = [["from", "to", "label", "kind"]] + [[e["from"], e.get("to", ""), e["label"], e.get("kind", "")]
                                                  for e in EVENTS]
    tabs = {"weekly": weekly, "monthly": monthly, "benchmarks": BENCHMARKS, "events": events, "signup_pages": signup_pages, "about": about}

    if a.out:
        with open(a.out, "w") as f: json.dump(tabs, f)
    if a.dry_run:
        for row in weekly[:2] + weekly[-2:] + monthly[:2] + monthly[-2:]: log(str(row))
        return
    sheet_id = os.environ.get("KPI_SHEET_ID", "").strip()
    if not sheet_id: raise SystemExit("KPI_SHEET_ID not set")
    if not gw: raise SystemExit("GA4 credentials missing; not overwriting the sheet without website numbers")
    write_sheet(sheet_id, tabs)
    log(f"wrote {len(weekly) - 1} weeks and {len(monthly) - 1} months to the sheet")


if __name__ == "__main__":
    main()
