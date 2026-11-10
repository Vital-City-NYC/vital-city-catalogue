#!/usr/bin/env python3
"""Extract for the Vital City analytics dashboard (Claude Dashboard artifact).

Run by .github/workflows/dashboard-data.yml after each growth refresh. Reads the
growth dashboard's payload (growth/data.enc, rebuilt twice a day by
network-refresh.yml from Mailchimp, Ghost, Donorbox, GA4 and App Store Connect)
and writes aggregate-only CSVs. No names, emails or per-donor rows leave this
script.

THE OUTPUT IS PRIVATE. The CSVs hold donation totals and subscriber counts, and
this repository is public, so nothing this script writes may be committed here.
Everything it reads and writes besides the payload lives in a separate private
repository (vitalcity-nyc/vc-dashboard-data), named by the VC_DASH_DIR
environment variable:
    out/                         the CSVs the dashboard reads
    history/                     daily snapshots the script adds to; never pruned
    follower_overrides.json      hand-checked follower counts (weekly task)
    signup_quality_interim.csv   corrected signup-quality figures, used until
                                 the payload reads Mailchimp status directly
    signup_notes.json            event-list signup counts and notes by month

Passphrase: the VC_NETWORK_PASS environment variable (a repository secret in
Actions), else private/.netpass on a laptop. It is never printed.
"""
import base64, collections, csv, json, os, sys, urllib.request
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("VC_DASH_DIR") or HERE.parent / "vc-dashboard-data").resolve()
if DATA == HERE or HERE in DATA.parents:
    raise SystemExit("VC_DASH_DIR points inside this public repository; the output must go to the private one")
if not DATA.is_dir():
    raise SystemExit(f"no data folder at {DATA}: check out vitalcity-nyc/vc-dashboard-data there, or set VC_DASH_DIR")
OUT = DATA / "out"; OUT.mkdir(exist_ok=True)
URL = "https://raw.githubusercontent.com/vitalcity-nyc/vital-city-catalogue/main/growth/data.enc"
IN_CI = bool(os.environ.get("GITHUB_ACTIONS"))

def _passphrase():
    p = (os.environ.get("VC_NETWORK_PASS") or "").strip()
    if p: return p
    f = HERE / "private" / ".netpass"
    if f.exists() and f.read_text().strip(): return f.read_text().strip()
    raise SystemExit("no passphrase: set VC_NETWORK_PASS (the Actions secret) or keep private/.netpass")

def _payload():
    # In Actions, a job that has just built private/growth.json can hand it over as is.
    # On a laptop that file is often stale or partly blank (local pulls lack the CI-only
    # keys), so a local run always reads what was published.
    plain = HERE / "private" / "growth.json"
    if IN_CI and plain.exists() and plain.stat().st_size > 1000:
        return json.loads(plain.read_text()), "private/growth.json"
    enc = HERE / "growth" / "data.enc"
    if IN_CI and enc.exists():
        raw, src = enc.read_bytes(), "growth/data.enc in this checkout"
    else:
        raw, src = urllib.request.urlopen(URL, timeout=90).read(), "growth/data.enc as published"
    blob = json.loads(raw)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(blob["salt"]),
                     iterations=blob["iters"]).derive(_passphrase().encode())
    return json.loads(AESGCM(key).decrypt(base64.b64decode(blob["iv"]), base64.b64decode(blob["ct"]), None)), src

d, _src = _payload()
asof = d.get("generated_at", "")
if not asof: raise SystemExit("payload has no generated_at; refusing to write")

def write(name, cols, rows):
    with open(OUT / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for r in rows: w.writerow(r)

mc, db, ga, gt, ap = d["mailchimp"], d["donorbox"], d["ga4"], d["ghost_traffic"], d["app_store"]
sw = mc.get("signup_windows", {}); mw = mc.get("windows", {}); dw = db.get("windows", {})

# ---- app store daily
rep = ap.get("reports", {})
days = set()
for r in rep.values(): days |= set(r.get("days", {}))
sig = {x["d"]: x["n"] for x in ap.get("app_signups_by_day", [])}
days |= set(sig)
app_rows = []
for day in sorted(days):
    dl = rep.get("downloads", {}).get("days", {}).get(day, {})
    st = rep.get("store", {}).get("days", {}).get(day, {})
    wb = rep.get("web", {}).get("days", {}).get(day, {})
    app_rows.append({"day": day,
        "downloads": int(sum(v.get("Counts", 0) for k, v in dl.items() if "download" in k.lower() and "first" in k.lower())),
        "redownloads": int(sum(v.get("Counts", 0) for k, v in dl.items() if "redownload" in k.lower())),
        "impressions": int(st.get("Impression", {}).get("Counts", 0)),
        "store_page_views": int(st.get("Page view", {}).get("Counts", 0)) + int(wb.get("Page view", {}).get("Counts", 0)),
        "newsletter_signups": sig.get(day, 0)})
write("app_daily.csv", ["day","downloads","redownloads","impressions","store_page_views","newsletter_signups"], app_rows)
app_dl = sum(r["downloads"] for r in app_rows)
app_imp30 = sum(r["impressions"] for r in app_rows[-30:])

# ---- headline numbers
k = [
 ("web_users_30","Google Analytics","Website users, last 30 days", ga.get("mau"), None),
 ("web_pageviews_30","Google Analytics","Pageviews, last 30 days", ga.get("pageviews_30"), None),
 ("web_users_365","Google Analytics","Website users, last 365 days", ga.get("aau"), None),
 ("web_returning_pct","Google Analytics","Returning visitors, last 30 days (%); prior = all of last year", ga.get("returning",{}).get("d30",{}).get("returning_pct"), (ga.get("returning",{}).get("by_year",{}).get(str(int(asof[:4])-1)) or {}).get("returning_pct")),
 ("ghost_visitors_30","Ghost","Site visitors, last 30 days (Ghost)", gt.get("visitors_30d"), gt.get("visitors_prev_30d")),
 ("ghost_pageviews_30","Ghost","Pageviews, last 30 days (Ghost)", gt.get("pageviews_30d"), gt.get("pageviews_prev_30d")),
 ("subscribers","Mailchimp","Newsletter subscribers", mc.get("total_subscribers"), None),
 ("signups_ytd","Ghost","New newsletter signups through site forms, year to date", sw.get("ytd_ghost"), None),
 ("signups_30","Ghost","New newsletter signups, last 30 days", sw.get("last30_ghost"), None),
 ("unsubs_ytd","Mailchimp","Unsubscribes, year to date", sw.get("unsub_ytd"), sw.get("unsub_prior_ytd")),
 ("open_rate_30","Mailchimp","Open rate, last 30 days (%)", mw.get("last_30",{}).get("open_pct"), mw.get("prev_30",{}).get("open_pct")),
 ("click_rate_30","Mailchimp","Click rate, last 30 days (%)", mw.get("last_30",{}).get("click_pct"), mw.get("prev_30",{}).get("click_pct")),
 ("email_active_30","Mailchimp","Subscribers who opened or clicked, last 30 days", mc.get("mau",{}).get("active_users"), None),
 ("raised_ytd","Donorbox","Raised, year to date ($)", dw.get("ytd",{}).get("amount"), None),
 ("raised_30","Donorbox","Raised, last 30 days ($)", dw.get("last_30",{}).get("amount"), None),
 ("donors_ytd","Donorbox","Donors, year to date", dw.get("ytd",{}).get("donors"), None),
 ("gifts_ytd","Donorbox","Gifts, year to date", dw.get("ytd",{}).get("count"), None),
 ("avg_gift_ytd","Donorbox","Average gift, year to date ($)", dw.get("ytd",{}).get("avg_gift"), None),
 ("recurring_donors","Donorbox","Active recurring donors", db.get("active_recurring_donors"), None),
 ("mrr","Donorbox","Monthly recurring revenue ($)", db.get("mrr_estimate"), None),
 ("raised_all","Donorbox","Raised since Nov. 2025 ($)", dw.get("all_time",{}).get("amount"), None),
 ("search_clicks_28","Google Search","Clicks from Google Search, last 28 days", (d.get("search_console",{}).get("totals") or {}).get("clicks"), None),
 ("search_impr_28","Google Search","Times shown in Google Search, last 28 days", (d.get("search_console",{}).get("totals") or {}).get("impressions"), None),
 ("search_position_28","Google Search","Average position in Google results, last 28 days", (d.get("search_console",{}).get("totals") or {}).get("position"), None),
 ("activation_pct","Mailchimp","New subscribers (last 30 days) who opened or clicked (%)", (d.get("lifecycle",{}).get("activation_30d") or {}).get("pct"), None),
 ("activation_cohort","Mailchimp","New subscribers in the last 30 days", (d.get("lifecycle",{}).get("activation_30d") or {}).get("cohort_size"), None),
 ("activation_engaged","Mailchimp","New subscribers in the last 30 days who opened or clicked", (d.get("lifecycle",{}).get("activation_30d") or {}).get("engaged"), None),
 ("gov_active","Mailchimp","Government readers active in the last 30 days", (d.get("engagement_extras",{}).get("influence_weighted_reach") or {}).get("gov_in_mau"), None),
 ("notable_active","Mailchimp","Notable figures active in the last 30 days", (d.get("engagement_extras",{}).get("influence_weighted_reach") or {}).get("notable_in_mau"), None),
 ("app_downloads","App Store","iPhone app first-time downloads, since launch", app_dl, None),
 ("app_impressions_30","App Store","App Store impressions, last 30 days of data", app_imp30, None),
]
write("kpis.csv", ["metric","source","label","value","prior","as_of"],
      [{"metric":a,"source":b,"label":c,"value":"" if v is None else round(v,2) if isinstance(v,float) else v,
        "prior":"" if p is None else round(p,2) if isinstance(p,float) else p,"as_of":asof} for a,b,c,v,p in k])

# ---- web weekly (GA4 + Ghost); drop the week still in progress
from datetime import date, timedelta
cutoff = (date.fromisoformat(ga.get("as_of") or asof[:10]) - timedelta(days=7)).isoformat()
gh = {r["wk"]: r for r in gt.get("traffic_series", [])}
write("web_weekly.csv", ["week","ga4_visits","ga4_pageviews","ghost_visitors"],
      [{"week": r["wk"], "ga4_visits": r["visits"], "ga4_pageviews": r["pageviews"],
        "ghost_visitors": gh.get(r["wk"], {}).get("visitors", "")} for r in ga.get("traffic_weekly", []) if r["wk"] <= cutoff])

# ---- email monthly
mcm = {r["month"]: r for r in mc.get("monthly_campaigns", [])}
# Signup origins (Josh's Oct. 21 corrections): before March 3, 2026 signups came through the old
# site's Mailchimp form (copied into Ghost); some months also took in an event's registration
# list. These are real signups and stay in the totals; they're labeled, and event-list signups
# are left out of website comparisons. A count the payload supplies wins over these. The
# event-list counts and their notes are figures, so they sit in the private data folder
# (signup_notes.json: {"event_signups": {"YYYY-MM": n}, "notes": {"YYYY-MM": "..."}}).
try: _sn = json.loads((DATA / "signup_notes.json").read_text())
except FileNotFoundError: _sn = {}
EVENT_SIGNUPS = _sn.get("event_signups", {})
def signup_note(r):
    m = r["month"]
    if r.get("signup_note"): return r["signup_note"]
    if m < "2026-03": return "Through the old site's Mailchimp form"
    if m == "2026-03": return "Old site's form through March 2, Ghost's from March 3"
    return _sn.get("notes", {}).get(m, "")
def event_n(r):
    for k in ("event_signups", "event_list_signups", "events"):
        if isinstance(r.get(k), (int, float)): return r[k]
    return EVENT_SIGNUPS.get(r["month"], 0)
write("email_monthly.csv", ["month","new_signups","ghost_signups","event_signups","signup_note","sends","recipients","open_pct","click_pct","unsubs"],
      [{"month": r["month"], "new_signups": r["new_signups"], "ghost_signups": r.get("ghost_signups", ""),
        "event_signups": event_n(r), "signup_note": signup_note(r),
        "sends": mcm.get(r["month"], {}).get("sends", ""), "recipients": mcm.get(r["month"], {}).get("recipients", ""), "open_pct": mcm.get(r["month"], {}).get("open_pct", ""),
        "click_pct": mcm.get(r["month"], {}).get("click_pct", ""), "unsubs": mcm.get(r["month"], {}).get("unsubs", "")}
       for r in mc.get("monthly_signups", [])][-24:])

# ---- every send, one row each. A/B (variate) sends: Mailchimp's parent
# campaign already totals ALL waves (both test groups plus the winner rollout),
# so sent_to/open/click/unsubs here are the whole send, not one test arm.
send_rows = []
for x in sorted(mc.get("campaigns", []), key=lambda c: c.get("sent", ""), reverse=True):
    n = x.get("sent_to") or 0
    if n < 100: continue  # test sends and empty drafts
    ab = x.get("type") == "variate"
    subj = (x.get("winner_subject") or x.get("subject") or "") if ab else (x.get("subject") or "")
    others = [v for v in (x.get("variate_subjects") or []) if v != subj] if ab else []
    dl = x.get("delivered") or n
    send_rows.append({"campaign_id": x.get("id"), "sent": x.get("sent"), "kind": x.get("kind", ""), "subject": subj.strip(),
        "ab_test": "yes" if ab else "no", "tested_against": " / ".join(o.strip() for o in others),
        "test_pct": round(100 * (x.get("test_n") or 0) / n) if ab and n else "",
        "recipients": n, "delivered": dl, "open_pct": x.get("open_pct"), "click_pct": x.get("click_pct"),
        "ctor_pct": x.get("ctor_pct"), "unsubs": x.get("unsubs", 0),
        "unsub_pct": round(100 * (x.get("unsubs") or 0) / dl, 2) if dl else ""})
write("newsletter_sends.csv", ["campaign_id","sent","kind","subject","ab_test","tested_against","test_pct","recipients","delivered",
      "open_pct","click_pct","ctor_pct","unsubs","unsub_pct"], send_rows)

# ---- donations monthly
write("donations_monthly.csv", ["month","raised","gifts","donors","recurring"],
      [{"month": r["m"], "raised": round(r["amt"], 2), "gifts": r["gifts"], "donors": r["donors"],
        "recurring": round(r.get("recurring_amt", 0), 2)} for r in db.get("monthly_series", [])])

# ---- top pages and signup sources
write("top_pages_30d.csv", ["title","path","visits","prev"], gt.get("top_pages_30d", []))
bs = d.get("ghost_signup_attribution", {}).get("by_source", [])
if isinstance(bs, dict): bs = [{"src": k2, "n": v} for k2, v in bs.items()]
write("signup_sources.csv", ["source","signups"], [{"source": r["src"], "signups": r["n"]} for r in bs[:12]])


# ---- traffic sources and long-run trends
write("web_monthly.csv", ["month","users","pageviews","sessions"],
      [{"month": r["m"], "users": r["users"], "pageviews": r["pageviews"], "sessions": r["sessions"]} for r in ga.get("by_year", {}).get("months", [])])
MAJOR = {"Organic Search","Direct","Organic Social","Referral","Email","AI Assistant"}
ch = collections.defaultdict(lambda: {"sessions": 0, "engaged": 0})
for r in ga.get("monthly_channels", []):
    c = r["ch"] if r["ch"] in MAJOR else "Other"
    ch[(r["m"], c)]["sessions"] += r["sessions"]; ch[(r["m"], c)]["engaged"] += r["engaged"]
write("channels_monthly.csv", ["month","channel","sessions","engaged"],
      [{"month": m, "channel": c, **v} for (m, c), v in sorted(ch.items())])
def ai_name(s):
    s = s.rstrip(")").lower()
    for k, v in (("perplexity","Perplexity"),("chatgpt","ChatGPT"),("claude","Claude"),("gemini","Gemini"),("copilot","Copilot"),("grok","Grok"),("deepseek","DeepSeek"),("meta.ai","Meta AI")):
        if k in s: return v
    return "Other"
ai = collections.Counter()
for r in ga.get("ai_referrals", []): ai[(r["m"], ai_name(r["src"]))] += r["sessions"]
write("ai_monthly.csv", ["month","assistant","sessions"], [{"month": m, "assistant": a, "sessions": n} for (m, a), n in sorted(ai.items())])
write("traffic_sources_30d.csv", ["source","visits","prev"], gt.get("top_sources_30d", [])[:15])

# ---- which pages drew signups (counts only, no names or emails)
sa = d.get("ghost_signup_attribution", {})
rs = sa.get("recent_signups", [])
if rs:
    lo, hi = min(r["date"] for r in rs), max(r["date"] for r in rs)
    cnt = collections.Counter()
    for r in rs:
        t = r.get("landing_type") or "unknown"
        title = r.get("landing_title") or ""
        if t == "url" and title == "homepage": title = "Homepage"
        if not title: title = "(not recorded)" if t in ("", "unknown") else (r.get("landing_url") or "(not recorded)")
        kind = {"post": "Piece", "page": "Page", "url": "Page", "tag": "Topic page", "author": "Author page"}.get(t, "Unknown")
        cnt[(title, kind)] += 1
    write("signup_pages_recent.csv", ["page","kind","signups","from","to"],
          [{"page": a, "kind": k, "signups": n, "from": lo, "to": hi} for (a, k), n in cnt.most_common()])
pidx = ga.get("piece_index", {})
since = pidx.get("signups_since", "")
pieces = sorted([x for x in pidx.get("pieces", []) if (x.get("signups") or 0) > 0], key=lambda x: -x["signups"])
write("signups_by_piece.csv", ["path","title","published","signups","readers","signups_since"],
      [{"path": "/" + x["url"].split("vitalcitynyc.org/", 1)[-1].strip("/") + "/", "title": x["title"], "published": x.get("pub", ""),
        "signups": x["signups"], "readers": x.get("users", ""), "signups_since": since} for x in pieces])
bt = (sa.get("by_topic") or {}).get("rows", [])[:15]
write("signups_by_topic.csv", ["topic","signups","pct"], [{"topic": r["topic"], "signups": r["n"], "pct": r["pct"]} for r in bt])

# ---- Google Search, reach across platforms, reading time
sc = d.get("search_console", {})
write("search_queries.csv", ["query","clicks","impressions","ctr","position"], sc.get("top_queries", [])[:20])
reach = [("Newsletter", mc.get("total_subscribers"), asof[:10])]
for key, label in (("x_profile","X"),("linkedin","LinkedIn"),("bluesky","Bluesky"),("instagram","Instagram"),("facebook","Facebook")):
    b = d.get(key, {})
    if b.get("followers"): reach.append((label, b["followers"], b.get("as_of") or asof[:10]))
# Weekly hand-checked counts (follower_overrides.json) win only when newer than the pull's.
try: ov = json.loads((DATA / "follower_overrides.json").read_text())
except Exception: ov = {}
seen = set()
for i, (a, n, w) in enumerate(reach):
    seen.add(a); o = ov.get(a)
    if isinstance(o, dict) and o.get("followers") and str(o.get("as_of", "")) > str(w): reach[i] = (a, o["followers"], o["as_of"])
for a, o in ov.items():
    if a not in seen and isinstance(o, dict) and o.get("followers"): reach.append((a, o["followers"], o.get("as_of", "")))
write("reach.csv", ["platform","followers","as_of"], [{"platform": a, "followers": n, "as_of": w} for a, n, w in reach])
eng = sorted(ga.get("engagement", []), key=lambda r: -(r.get("total_secs") or 0))[:15]
write("reading_time.csv", ["path","title","views","avg_secs","hours"],
      [{"path": r["path"], "title": r["title"], "views": r["views"], "avg_secs": r["avg_secs"], "hours": round(r["total_secs"] / 3600, 1)} for r in eng])

# ---- signup quality, policy reach, new-piece scorecard (counts only: no names or emails)
from datetime import date as _date, timedelta as _td
lc = d.get("lifecycle", {}); act = lc.get("activation_30d") or {}
cl = (d.get("engagement_extras", {}).get("channel_ltv") or {})
LIVE_KEYS = ("subscribed", "unsubscribed", "bounced", "mailchimp_status")
rows_cl = cl.get("channels", [])
if any(any(k in r for k in LIVE_KEYS) for r in rows_cl):
    sq = [{"source": r["source"], "signups": r.get("matched", r["signups"]),
           "stayed": r.get("subscribed", r.get("matched", r["signups"]) - r.get("left", 0)),
           "left": r.get("unsubscribed", r.get("left", 0)), "stayed_pct": r.get("stayed_pct"),
           "basis": f"Signups in the last {cl.get('window_days', 180)} days that have reached Mailchimp, and the share still subscribed there (Mailchimp status now)"}
          for r in rows_cl[:12]]
else:
    # The payload's flag missed unsubscribes made in Mailchimp, so it overstated who stayed.
    # Use the corrected figures from Josh's Oct. 21 note until the growth dashboard ships the fix.
    with open(DATA / "signup_quality_interim.csv") as f: sq = list(csv.DictReader(f))
    for r in sq: r["basis"] = ("Ghost signups from March 3 through Oct. 20, 2026 that had reached Mailchimp, by their Mailchimp status on Oct. 20. "
                               "Corrected figures: the automatic feed missed unsubscribes and switches back once it reads Mailchimp directly")
write("signup_quality.csv", ["source","signups","stayed","left","stayed_pct","basis"], sq)
ee = d.get("engagement_extras", {})
write("policy_reach.csv", ["date","gov_in_mau","notable_in_mau","active_mau","power_readers"],
      [{k: r.get(k) for k in ("date","gov_in_mau","notable_in_mau","active_mau","power_readers")} for r in ee.get("policy_history", [])])
iw = ee.get("influence_weighted_reach") or {}
rf = d.get("role_flows", {}); labels = rf.get("labels", {})
rows = []
for r in rf.get("monthly", [])[-13:]:
    for k in rf.get("keys", []):
        rows.append({"month": r["m"], "group": labels.get(k, k), "joined": r["join"].get(k, 0), "left": r["leave"].get(k, 0)})
write("audience_groups_monthly.csv", ["month","group","joined","left"], rows)
write("open_by_address.csv", ["address_type","subscribers","avg_open_pct"],
      [{"address_type": r["label"], "subscribers": r["subs"], "avg_open_pct": r["avg_open_pct"]} for r in ee.get("mailbox_engagement", [])])
pbm = ga.get("piece_benchmarks", {})
write("benchmarks.csv", ["stat","value"], [{"stat": k, "value": v} for k, v in (pbm.get("bands") or {}).items()] +
      [{"stat": "window_start", "value": pbm.get("window_start")}, {"stat": "window_end", "value": pbm.get("window_end")}, {"stat": "n_pieces", "value": pbm.get("n_pieces")}])
swk = ga.get("story_weekly", {}); idx = {pg["p"].strip("/").split("/")[-1]: i for i, pg in enumerate(swk.get("pages", []))}
weekly = collections.defaultdict(list)
for i, wk, v, _ in swk.get("rows", []): weekly[i].append((wk, v))
today = _date.fromisoformat(ga.get("as_of") or asof[:10])
sc_rows = []
for x in pidx.get("pieces", []):
    pub = x.get("pub") or ""
    if not pub or x.get("date_suspect"): continue
    pd_ = _date.fromisoformat(pub); age = (today - pd_).days
    if age < 0 or age > 120: continue
    if age < 30: v, how = x.get("views30") or x.get("views") or 0, "so far"
    elif x["slug"] in idx: v, how = sum(n for wk, n in weekly[idx[x["slug"]]] if pd_ - _td(days=6) <= _date.fromisoformat(wk) < pd_ + _td(days=30)), "weekly"
    else: v, how = x.get("views") or 0, "all time"
    sc_rows.append({"path": "/" + x["url"].split("vitalcitynyc.org/", 1)[-1].strip("/") + "/", "title": x["title"], "published": pub, "days_live": age,
                    "type": x.get("type", ""), "views_first_30": v, "method": how, "signups": x.get("signups") or 0, "readers": x.get("users") or ""})
sc_rows.sort(key=lambda r: r["published"], reverse=True)
write("piece_scorecard.csv", ["path","title","published","days_live","type","views_first_30","method","signups","readers"], sc_rows)

# --- "Latest" module: the freshest daily figures in the payload (Ghost daily traffic and signups, GA4 views so far for new pieces)
_gen = asof[:10]
_kr = sorted(gt.get("kpi_rows_30d", []), key=lambda r: r["date"])
_sc = collections.Counter(r["date"][:10] for r in sa.get("recent_signups", []) if r.get("date"))
_sd = sorted(_sc)
_full = set(_sd[1:])  # the earliest day in the capped list may be cut off
_days = sorted(set(r["date"] for r in _kr) | _full)
_kd = {r["date"]: r for r in _kr}
now_daily = []
for day in _days:
    k = _kd.get(day, {})
    now_daily.append({"date": day, "ghost_visits": k.get("visits", ""), "ghost_pageviews": k.get("pageviews", ""),
                      "signups": _sc.get(day, 0) if day in _full else "",
                      "note": "today so far" if day == _gen else ""})
write("now_daily.csv", ["date","ghost_visits","ghost_pageviews","signups","note"], now_daily)
def _avg(vals):
    vals = [v for v in vals if v not in ("", None)]
    return round(sum(vals) / len(vals), 1) if vals else ""
_last = _kr[-1] if _kr else {}
_prev7 = _kr[-8:-1]
_sfull = [r for r in now_daily if r["signups"] != "" and r["date"] < _gen]
_yday = _sfull[-1] if _sfull else {}
now_k = [
 ("signups_today", "Ghost", "Newsletter signups today so far", _sc.get(_gen, 0) if _gen in _full else "", _avg([r["signups"] for r in _sfull[-7:]]), "a day, last seven full days", _gen),
 ("signups_yday", "Ghost", "Newsletter signups, last full day", _yday.get("signups", ""), _avg([r["signups"] for r in _sfull[-8:-1]]), "a day, the seven days before", _yday.get("date", "")),
 ("visits_yday", "Ghost", "Site visits, last full day", _last.get("visits", ""), _avg([r["visits"] for r in _prev7]), "a day, the seven days before", _last.get("date", "")),
 ("pageviews_yday", "Ghost", "Pageviews, last full day", _last.get("pageviews", ""), _avg([r["pageviews"] for r in _prev7]), "a day, the seven days before", _last.get("date", "")),
 ("pieces_7d", "Ghost", "Pieces published, last 7 days", d.get("ghost", {}).get("count_7", ""), "", "", _gen),
]
write("now_kpis.csv", ["metric","source","label","value","compare","compare_label","as_of"],
      [dict(zip(["metric","source","label","value","compare","compare_label","as_of"], r)) for r in now_k])
write("now_pages_7d.csv", ["title","path","visits"], [{"title": r["title"], "path": r["path"], "visits": r["visits"]} for r in gt.get("top_pages_7d", [])])
_cut = (_date.fromisoformat(_gen) - _td(days=14)).isoformat()
_np = sorted([x for x in pidx.get("pieces", []) if (x.get("pub") or "") >= _cut and not x.get("date_suspect")], key=lambda x: (x["pub"], x.get("views") or 0), reverse=True)
write("now_new_pieces.csv", ["path","title","published","type","views","readers","avg_secs","signups","ga_as_of"],
      [{"path": "/" + x["url"].split("vitalcitynyc.org/", 1)[-1].strip("/") + "/", "title": x["title"], "published": x["pub"], "type": x.get("type", ""),
        "views": x.get("views") or 0, "readers": x.get("users") or 0,
        "avg_secs": round((x.get("secs") or 0) / x["views"]) if x.get("views") else "", "signups": x.get("signups") or 0,
        "ga_as_of": pidx.get("as_of", "")} for x in _np])

# ---- per-day details behind the "Latest" daily bars (counts only: no names or emails)
_dset = set(r["date"] for r in now_daily)
dd = []
for day in sorted(_dset):
    k = _kd.get(day, {})
    if k.get("bounce_rate") not in (None, ""): dd.append({"date": day, "kind": "site", "label": "bounce_rate", "n": k["bounce_rate"], "extra": ""})
    if k.get("avg_session_sec") not in (None, ""): dd.append({"date": day, "kind": "site", "label": "avg_session_sec", "n": round(k["avg_session_sec"]), "extra": ""})
_ss, _sp = collections.Counter(), collections.Counter()
for r in sa.get("recent_signups", []):
    day = (r.get("date") or "")[:10]
    if day not in _full: continue
    _ss[(day, r.get("source") or "(unknown)")] += 1
    t = r.get("landing_type") or ""
    title = r.get("landing_title") or ""
    if t == "url" and title == "homepage": title = "Homepage"
    if not title: title = "(not recorded)"
    _sp[(day, title)] += 1
for (day, src), n in sorted(_ss.items(), key=lambda x: (x[0][0], -x[1])): dd.append({"date": day, "kind": "signup_source", "label": src, "n": n, "extra": ""})
for (day, t), n in sorted(_sp.items(), key=lambda x: (x[0][0], -x[1])): dd.append({"date": day, "kind": "signup_page", "label": t, "n": n, "extra": ""})
for x in pidx.get("pieces", []):
    if (x.get("pub") or "") in _dset and not x.get("date_suspect"):
        dd.append({"date": x["pub"], "kind": "published", "label": x["title"], "n": x.get("views") or 0,
                   "extra": "/" + x["url"].split("vitalcitynyc.org/", 1)[-1].strip("/") + "/"})
for r in mc.get("daily_activity", []):
    if r.get("d") in _dset and r.get("unsubs") is not None: dd.append({"date": r["d"], "kind": "unsubs", "label": "Unsubscribes", "n": r["unsubs"], "extra": ""})
for r in db.get("daily_series", []):
    if r.get("d") in _dset: dd.append({"date": r["d"], "kind": "gifts", "label": "Gifts", "n": r.get("gifts", 0), "extra": round(r.get("amt", 0), 2)})
try:
    with open(OUT / "newsletter_sends.csv") as f:
        for r in csv.DictReader(f):
            if r["sent"] in _dset: dd.append({"date": r["sent"], "kind": "send", "label": r["subject"], "n": r["open_pct"], "extra": r["kind"] + "|" + r["recipients"] + "|" + r["click_pct"]})
except FileNotFoundError: pass
dd.sort(key=lambda r: r["date"])
write("day_detail.csv", ["date","kind","label","n","extra"], dd)

# ---- per-piece detail for the click-through panel (counts only)
def _path(u): return "/" + u.split("vitalcitynyc.org/", 1)[-1].strip("/") + "/"
_all = [x for x in pidx.get("pieces", []) if x.get("url")]
def _pct_rank(vals, v):
    if not vals: return ""
    return round(100 * sum(1 for a in vals if a <= v) / len(vals))
_uv = sorted((x.get("users") or 0) for x in _all)
_sv = sorted((x.get("signups") or 0) for x in _all)
_vw = {}
_sw_pages = ga.get("story_weekly", {}).get("pages", [])
for i, wk, v, sec in ga.get("story_weekly", {}).get("rows", []):
    _vw.setdefault(i, []).append((wk, v, sec))
_lc = (mc.get("link_clicks") or {}).get("by_slug", {})
pd_rows = []
for x in _all:
    u = x.get("users") or 0; sg = x.get("signups") or 0; vws = x.get("views") or 0
    l = _lc.get(x["slug"], {})
    pd_rows.append({"path": _path(x["url"]), "slug": x["slug"], "title": x["title"], "url": x["url"], "published": x.get("pub", ""),
        "date_suspect": 1 if x.get("date_suspect") else 0, "type": x.get("type", ""), "author": ", ".join(x.get("authors") or [x.get("author", "")]),
        "topics": "; ".join(x.get("topics") or []), "words": x.get("words") or "",
        "views": vws, "readers": u, "avg_secs": round((x.get("secs") or 0) / vws) if vws else "",
        "views30": x.get("views30", ""), "signups": sg, "signups30": x.get("signups30", ""),
        "per_1000": round(1000 * sg / u, 1) if u >= 200 else "",
        "nl_clicks": x.get("nl_clicks", l.get("clicks", "")), "nl_unique": x.get("nl_unique", l.get("unique", "")), "nl_sends": x.get("nl_sends", l.get("sends", "")),
        "search_impr": x.get("search_impr", ""), "readers_pct": _pct_rank(_uv, u), "signups_pct": _pct_rank(_sv, sg) if sg else "",
        "n_pieces": len(_all), "signups_since": pidx.get("signups_since", ""), "ga_as_of": pidx.get("as_of", "")})
write("piece_detail.csv", list(pd_rows[0].keys()) if pd_rows else ["path"], pd_rows)
pw = []
for i, pg in enumerate(_sw_pages):
    for wk, v, sec in sorted(_vw.get(i, [])):
        pw.append({"path": pg["p"] if pg["p"].endswith("/") else pg["p"] + "/", "slug": pg["p"].strip("/").split("/")[-1], "week": wk, "views": v, "avg_secs": round(sec / v) if v else ""})
write("piece_weekly.csv", ["path","slug","week","views","avg_secs"], pw)
px = []
for x in _all:
    for q in x.get("queries") or []:
        px.append({"slug": x["slug"], "kind": "query", "label": q.get("q", ""), "n": q.get("clicks", ""), "extra": f'{q.get("impr","")}|{q.get("pos","")}'})
for g in d.get("ghost", {}).get("posts", []):
    sl = g["url"].rstrip("/").split("/")[-1]
    for ds in g.get("direct_sources") or []:
        px.append({"slug": sl, "kind": "signup_source", "label": ds.get("src", ""), "n": ds.get("n", 0), "extra": ""})
for r in gt.get("top_pages_30d", []):
    px.append({"slug": r["path"].strip("/").split("/")[-1], "kind": "ghost_30d", "label": "Ghost visits, last 30 days", "n": r.get("visits", ""), "extra": r.get("prev", "")})
for r in gt.get("top_pages_7d", []):
    px.append({"slug": r["path"].strip("/").split("/")[-1], "kind": "ghost_7d", "label": "Ghost visits, last 7 days", "n": r.get("visits", ""), "extra": r.get("prev", "")})
for r in sa.get("recent_signups", []):
    sl = (r.get("landing_url") or "").split("?")[0].rstrip("/").split("/")[-1]
    if r.get("landing_type") == "post" and sl:
        px.append({"slug": sl, "kind": "recent_signup", "label": r.get("source") or "(unknown)", "n": 1, "extra": (r.get("date") or "")[:10]})
write("piece_extra.csv", ["slug","kind","label","n","extra"], px)

# ---- history kept in the private data folder (history/), so limits in the growth payload lift over time
HIST = DATA / "history"; HIST.mkdir(exist_ok=True)
def _read(pth):
    try:
        with open(pth, newline="") as f: return list(csv.DictReader(f))
    except FileNotFoundError: return []
def _save(pth, cols, rows):
    with open(pth, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
# headline numbers, one row per metric per day
_kh = {(r["date"], r["metric"]): r for r in _read(HIST / "kpi_daily.csv")}
with open(OUT / "kpis.csv", newline="") as f:
    for r in csv.DictReader(f):
        if r["value"] != "": _kh[(_gen, r["metric"])] = {"date": _gen, "metric": r["metric"], "label": r["label"], "value": r["value"]}
_khr = sorted(_kh.values(), key=lambda r: (r["date"], r["metric"]))
_save(HIST / "kpi_daily.csv", ["date","metric","label","value"], _khr)
write("kpi_history.csv", ["date","metric","label","value"], _khr)
# visits and signups by day: keep every full day ever seen
_dh = {r["date"]: r for r in _read(HIST / "daily.csv")}
for r in now_daily:
    old = _dh.get(r["date"], {})
    m = dict(r)
    for k2 in ("ghost_visits","ghost_pageviews","signups"):
        if m.get(k2) in ("", None) and old.get(k2) not in ("", None) and not old.get("note"): m[k2] = old[k2]
    _dh[r["date"]] = m
_dhr = [_dh[k2] for k2 in sorted(_dh)]
_save(HIST / "daily.csv", ["date","ghost_visits","ghost_pageviews","signups","note"], _dhr)
now_daily = _dhr[-120:]
write("now_daily.csv", ["date","ghost_visits","ghost_pageviews","signups","note"], now_daily)
# per-day details: newest version of each day wins, older days are kept.
# One exception. The payload lists only the most recent signups, so once a day is older than
# that list a new build has no signup breakdown for it. The breakdown saved while the day was
# still in the list is the only copy, so it is kept rather than replaced with nothing.
_new_days = set(r["date"] for r in dd)
_SIGNUP_KINDS = ("signup_source", "signup_page")
_ddh = [r for r in _read(HIST / "day_detail.csv")
        if r["date"] not in _new_days or (r["kind"] in _SIGNUP_KINDS and r["date"] not in _full)]
_ddh += [{k2: str(v) for k2, v in r.items()} for r in dd]
_KIND_ORDER = {k2: i for i, k2 in enumerate(("site", "signup_source", "signup_page", "published", "unsubs", "gifts", "send"))}
_ddh.sort(key=lambda r: (r["date"], _KIND_ORDER.get(r["kind"], 99)))
_save(HIST / "day_detail.csv", ["date","kind","label","n","extra"], _ddh)
_cut120 = (_date.fromisoformat(_gen) - _td(days=120)).isoformat()
write("day_detail.csv", ["date","kind","label","n","extra"], [r for r in _ddh if r["date"] >= _cut120])
# every piece's running totals, recorded when they change
_ps = _read(HIST / "piece_snap.csv")
_lastp = {}
for r in _ps: _lastp[r["slug"]] = r
_have_today = any(r["date"] == _gen for r in _ps)
for x in _all:
    cur = {"date": _gen, "slug": x["slug"], "views": str(x.get("views") or 0), "readers": str(x.get("users") or 0), "signups": str(x.get("signups") or 0)}
    lp = _lastp.get(x["slug"])
    if lp is None or (lp["date"] != _gen and (lp["views"], lp["signups"]) != (cur["views"], cur["signups"])):
        _ps.append(cur)
    elif lp["date"] == _gen:
        lp.update(cur)
_save(HIST / "piece_snap.csv", ["date","slug","views","readers","signups"], _ps)
_cut90 = (_date.fromisoformat(_gen) - _td(days=90)).isoformat()
_firstp = {}
for r in _ps: _firstp.setdefault(r["slug"], r["date"])
write("piece_daily.csv", ["slug","date","views","readers","signups"], [r for r in _ps if r["date"] >= _cut90])

# ---- the written brief: plain sentences built only from numbers in this pull
_MON = ["Jan.","Feb.","March","April","May","June","July","Aug.","Sept.","Oct.","Nov.","Dec."]
def _d(day): 
    y, m, dy = day.split("-"); return f"{_MON[int(m)-1]} {int(dy)}"
def _n(v): return f"{int(round(float(v))):,}"
def _times(a, b): return a / b if b else None
brief = []
_fullS = [r for r in now_daily if r["signups"] not in ("", None) and not r.get("note")]
if len(_fullS) >= 8:
    last = _fullS[-1]; prev = [float(r["signups"]) for r in _fullS[-8:-1]]; avg = sum(prev) / len(prev); n = float(last["signups"])
    det = [r for r in dd if r["date"] == last["date"]]
    srcs = sorted([r for r in det if r["kind"] == "signup_source"], key=lambda r: -float(r["n"]))
    pgs = sorted([r for r in det if r["kind"] == "signup_page" and r["label"] not in ("(not recorded)",)], key=lambda r: -float(r["n"]))
    w7 = sum(float(r["signups"]) for r in _fullS[-7:]); p7 = sum(float(r["signups"]) for r in _fullS[-14:-7]) if len(_fullS) >= 14 else None
    t = f"Newsletter signups: {_n(n)} on {_d(last['date'])}, against {avg:.1f} a day over the week before"
    if avg and n >= 1.5 * avg and n >= 8:
        t += f" (about {n/avg:.1f} times a typical day)"
    t += "."
    if srcs and pgs and n >= 5:
        t += f" The largest source was {srcs[0]['label']} ({_n(srcs[0]['n'])}), and the page that drew the most was “{pgs[0]['label']}” ({_n(pgs[0]['n'])})."
    if p7 is not None:
        t += f" The last seven full days brought {_n(w7)}, compared with {_n(p7)} the seven before."
    brief.append(("signups", t))
_fullV = [r for r in now_daily if r["ghost_visits"] not in ("", None)]
if len(_fullV) >= 14:
    w7 = sum(float(r["ghost_visits"]) for r in _fullV[-7:]); p7 = sum(float(r["ghost_visits"]) for r in _fullV[-14:-7])
    chg = (w7 - p7) / p7 * 100 if p7 else 0
    t = f"Site visits: {_n(w7)} over the last seven full days, {'up' if chg >= 0 else 'down'} {abs(chg):.0f}% from the seven before."
    tp = gt.get("top_pages_7d", [])
    if tp: t += f" The most-read piece was “{tp[0]['title']}” ({_n(tp[0]['visits'])} visits)."
    brief.append(("visits", t))
_c7 = (_date.fromisoformat(_gen) - _td(days=7)).isoformat()
_newp = [x for x in _all if (x.get("pub") or "") >= _c7 and not x.get("date_suspect")]
_p50 = (pbm.get("bands") or {}).get("p50"); _p90 = (pbm.get("bands") or {}).get("p90"); _p95 = (pbm.get("bands") or {}).get("p95")
if _newp:
    best = max(_newp, key=lambda x: x.get("views") or 0)
    t = f"New pieces: {len(_newp)} published in the last seven days. “{best['title']}” leads with {_n(best.get('views') or 0)} views so far"
    if best.get("signups"): t += f" and {_n(best['signups'])} signups"
    t += "."
    if _p50:
        over = [x for x in _newp if (x.get("views") or 0) >= _p50]
        t += f" {len(over)} of the {len(_newp)} {'has' if len(over) == 1 else 'have'} already passed {_n(_p50)} views, what the median piece gets in its first 30 days."
    brief.append(("pieces", t))
try:
    _sends = sorted([r for r in _read(OUT / "newsletter_sends.csv") if r.get("kind") == "newsletter" and r.get("open_pct") not in ("", None)], key=lambda r: r["sent"])
    if _sends and _sends[-1]["sent"] >= (_date.fromisoformat(_gen) - _td(days=8)).isoformat() and len(_sends) >= 6:
        ls = _sends[-1]; pv = sorted(float(r["open_pct"]) for r in _sends[-9:-1]); med = pv[len(pv)//2] if len(pv) % 2 else (pv[len(pv)//2-1] + pv[len(pv)//2]) / 2
        diff = float(ls["open_pct"]) - med
        brief.append(("newsletter", f"Latest newsletter: “{ls['subject']}” ({_d(ls['sent'])}) was opened by {float(ls['open_pct']):.1f}% and clicked by {float(ls['click_pct']):.1f}%; the open rate is {abs(diff):.1f} points {'above' if diff >= 0 else 'below'} the median of the eight sends before it."))
except Exception as e: log(f"brief: newsletter sentence skipped ({e})") if "log" in globals() else None
_g7 = [r for r in db.get("daily_series", []) if r.get("d", "") >= _c7]
if _g7:
    brief.append(("gifts", f"Donations: {_n(sum(r.get('gifts', 0) for r in _g7))} gift{'' if sum(r.get('gifts', 0) for r in _g7) == 1 else 's'} totaling ${_n(sum(r.get('amt', 0) for r in _g7))} in the last seven days."))
write("brief.csv", ["n","topic","text","as_of"], [{"n": i, "topic": a, "text": b, "as_of": asof} for i, (a, b) in enumerate(brief)])

# ---- alerts: a piece breaking out, or a signup spike. Only with --alerts are they marked as sent.
# out/alerts_new.json is a running list of {"as_of", "text"}, newest last, kept for 14 days, so an
# alert survives a second build landing before the task that sends notifications has read the first.
# That task sends the entries whose as_of is later than the last one it sent.
_sent_p = HIST / "alerts_sent.json"
try: _sent = set(json.loads(_sent_p.read_text()))
except Exception: _sent = set()
alerts = []
_c30 = (_date.fromisoformat(_gen) - _td(days=30)).isoformat()
for x in _all:
    if (x.get("pub") or "") < _c30 or x.get("date_suspect"): continue
    if _p95 and (x.get("views") or 0) >= _p95 and f"piece:{x['slug']}:p95" not in _sent:
        alerts.append((f"piece:{x['slug']}:p95", f"“{x['title']}” has {_n(x['views'])} views since {_d(x['pub'])}, which puts it in the top 5% of pieces for a first month ({_n(_p95)}+)."))
    if (x.get("signups") or 0) >= 20 and f"piece:{x['slug']}:signups20" not in _sent:
        alerts.append((f"piece:{x['slug']}:signups20", f"“{x['title']}” has drawn {_n(x['signups'])} newsletter signups since {_d(x['pub'])}."))
_allS = [r for r in now_daily if r["signups"] not in ("", None)]
for r in _allS[-2:]:
    before = [float(q["signups"]) for q in _fullS if q["date"] < r["date"]][-7:]
    if len(before) >= 5:
        avg = sum(before) / len(before); n = float(r["signups"])
        if n >= max(15, 2 * avg) and f"signups:{r['date']}" not in _sent:
            det = [q for q in dd if q["date"] == r["date"] and q["kind"] == "signup_page"]
            top = max(det, key=lambda q: float(q["n"])) if det else None
            alerts.append((f"signups:{r['date']}", f"{_n(n)} newsletter signups on {_d(r['date'])}{' so far' if r.get('note') else ''}, against {avg:.1f} a day the week before." + (f" Most came from “{top['label']}” ({_n(top['n'])})." if top else "")))
if "--alerts" in sys.argv:
    try: _old = json.loads((OUT / "alerts_new.json").read_text())
    except Exception: _old = []
    _keep = (_date.fromisoformat(_gen) - _td(days=14)).isoformat()
    _old = [a for a in _old if isinstance(a, dict) and a.get("as_of", "") >= _keep]
    json.dump(_old + [{"as_of": asof, "text": b} for a, b in alerts], open(OUT / "alerts_new.json", "w"), ensure_ascii=False, indent=1)
    _sent_p.write_text(json.dumps(sorted(_sent | set(a for a, b in alerts))))

json.dump({"as_of": asof}, open(OUT / "as_of.json", "w"))
# File names and the as-of time only: this prints into a public Actions log.
print("ok", asof, "from", _src, sorted(p.name for p in OUT.iterdir()))
