#!/usr/bin/env python3
"""Vital City — weekly growth report.

Fetches the published (encrypted) dashboard data, decrypts it, and writes a
Markdown summary of the last 7 days to the Desktop. Runs locally (it writes to
~/Desktop), scheduled via launchd each Friday morning.

Passphrase: read from $VC_NETWORK_PASS if set, else from the macOS Keychain
  (`security find-generic-password -s vc-network-pass -w`).
No secret is stored in this file.
"""
import json, base64, os, sys, subprocess, urllib.request
from datetime import datetime, timedelta, timezone
from collections import Counter
import statistics as st
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

BASE = "https://vitalcity-nyc.github.io/vital-city-catalogue"
DESKTOP = os.path.expanduser("~/Desktop")

def get_pass():
    p = os.environ.get("VC_NETWORK_PASS")
    if p:
        return p
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", "vc-network-pass", "-w"],
            text=True).strip()
    except Exception:
        sys.exit("No passphrase: set $VC_NETWORK_PASS or add a 'vc-network-pass' Keychain item.")

def fetch_decrypt(path, passphrase):
    raw = urllib.request.urlopen(f"{BASE}/{path}?cb={datetime.now(timezone.utc).timestamp()}", timeout=60).read()
    b = json.loads(raw)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=base64.b64decode(b["salt"]), iterations=b["iters"]).derive(passphrase.encode())
    return json.loads(AESGCM(key).decrypt(base64.b64decode(b["iv"]), base64.b64decode(b["ct"]), None))

def d(s):
    try: return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception: return None

def page_label(path):
    """'' for an article; otherwise a short label (issue/section pages are
    included in the top list, just tagged so they're not mistaken for stories)."""
    p = (path or "").lower()
    if p in ("/", ""): return "homepage"
    if p.startswith(("/issue", "/issues")): return "issue page"
    if p.startswith(("/tag/", "/author", "/contributor", "/data", "/explorer", "/about", "/search", "/privacy", "/terms")) or "/job" in p:
        return "section page"
    return ""

def fmtUSD(n): return "$" + format(round(n), ",")

def newsletter_learnings(mc, run_date):
    """Rolling newsletter learnings (trailing 12 months): fundraising-vs-newsletter
    unsubscribe cost, send-frequency/fatigue, and why people leave. Slow-moving —
    refreshed each week so the team always sees the current state."""
    camps = mc.get("campaigns", [])
    cut12 = (run_date - timedelta(days=365)).isoformat()
    rec = [c for c in camps if (c.get("sent") or "") >= cut12]
    def rate(rows):   # per 1,000 delivered (sent − bounces)
        S = sum((c.get("delivered") or c.get("sent_to") or 0) for c in rows)
        U = sum(c.get("unsubs") or 0 for c in rows)
        return S, U, (1000 * U / S if S else 0)
    out = []
    # 1) fundraising appeals vs the regular newsletter
    ap = [c for c in rec if c.get("kind") == "appeal"]
    nl = [c for c in rec if c.get("kind") == "newsletter"]
    _, _, ar = rate(ap); _, _, nr = rate(nl)
    if ap and nl and nr:
        out.append(f"- **Fundraising vs newsletter:** appeals unsubscribe at **{ar:.2f}/1,000** vs "
                   f"**{nr:.2f}/1,000** for the regular newsletter (**{ar/nr:.1f}×**). Modestly higher — "
                   f"appeals are not damaging the list. Spam complaints are the metric to watch on the hardest asks.")
    # 2) send frequency / fatigue
    wk = {}
    for c in rec:
        ds = d(c.get("sent"))
        if ds: wk.setdefault(ds.isocalendar()[:2], []).append(c)
    b1 = [c for cs in wk.values() if len(cs) == 1 for c in cs]
    bm = [c for cs in wk.values() if len(cs) >= 2 for c in cs]
    _, _, r1 = rate(b1); _, _, rm = rate(bm)
    if b1 and bm and r1:
        verdict = ("**no fatigue signal**" if rm <= r1 * 1.05
                   else "**watch — busier weeks are shedding more**")
        out.append(f"- **Send frequency:** single-send weeks unsubscribe at **{r1:.2f}/1,000** vs "
                   f"**{rm:.2f}/1,000** in multi-send weeks — {verdict}. (Correlational; busy weeks skew "
                   f"toward appeals and special sends, so read as 'frequency isn't hurting us,' not 'send more.')")
    # 3) why people leave
    ur = mc.get("unsub_reasons", {})
    allr = {}
    for kind in ("appeal", "newsletter", "other"):
        for reason, n in (ur.get(kind) or {}).items():
            allr[reason] = allr.get(reason, 0) + n
    if allr:
        tot = sum(allr.values())
        NONE = {"None given", "No reason given"}
        given = {r: n for r, n in allr.items() if r not in NONE}
        gtot = sum(given.values())
        if gtot:
            top = sorted(given.items(), key=lambda x: -x[1])[:3]
            parts = "; ".join(f"{r} ({round(100*n/gtot)}%)" for r, n in top)
            out.append(f"- **Why people leave** (of {tot} unsubscribes in the last 12 months, "
                       f"{round(100*gtot/tot)}% gave a reason): {parts}.")
    return out

def build(growth, people, run_date):
    g = growth; gt = g.get("ghost_traffic", {}); mc = g.get("mailchimp", {}); db = g.get("donorbox", {})
    l7 = (run_date - timedelta(days=6), run_date)
    p7 = (run_date - timedelta(days=13), run_date - timedelta(days=7))
    def inwin(ds, win):
        x = d(ds); return bool(x and win[0] <= x <= win[1])

    # Newsletter signups / unsubs from the merged people dataset (authoritative)
    sign7 = sum(1 for p in people if inwin(p.get("since"), l7))
    signP = sum(1 for p in people if inwin(p.get("since"), p7))
    unsub7 = sum(1 for p in people if p.get("unsub") and inwin(p.get("udate"), l7))
    unsubP = sum(1 for p in people if p.get("unsub") and inwin(p.get("udate"), p7))
    wk = Counter()
    for p in people:
        x = d(p.get("since"))
        if x and 0 <= (run_date - x).days <= 56: wk[x.isocalendar()[:2]] += 1
    avg_wk = round(st.mean(list(wk.values()))) if wk else 0

    # Email campaigns sent in the window
    camps = [c for c in mc.get("campaigns", []) if inwin(c.get("sent", ""), l7)]

    # Traffic (weekly buckets)
    ts = gt.get("traffic_series", [])
    last_complete = ts[-2] if len(ts) >= 2 else (ts[-1] if ts else None)
    cur = ts[-1] if ts else None
    avg_v = round(st.mean([p["visitors"] for p in ts[:-1][-8:]])) if len(ts) > 1 else 0

    # Online giving in the window
    gifts = [x for x in (db.get("recent_gifts") or db.get("latest_gifts") or []) if inwin(x.get("date") or x.get("d"), l7)]
    gift_total = sum(x.get("amount", 0) for x in gifts)
    ytd = (db.get("windows", {}) or {}).get("ytd", {})

    # Top pages of the week (Ghost, unique visitors) — articles plus issue/
    # section pages, with the non-articles labeled.
    top = (gt.get("top_pages_7d") or [])[:7]
    top_articles = [p for p in top if not page_label(p.get("path"))]

    # Notable joins / departures this week (Wikipedia-notable or .gov inbox)
    def gov(p):
        e = (p.get("e") or "").lower(); return ".gov" in (e.split("@")[-1] if "@" in e else "")
    def notable(p): return bool(p.get("wiki")) or gov(p)
    def person_line(p):
        nm = p.get("n") or "(no confirmed name)"
        inst = p.get("inst") or ((p.get("e","").split("@")[-1]) if "@" in (p.get("e") or "") else "")
        tag = "Wikipedia-notable" if p.get("wiki") else "government" if gov(p) else ""
        bits = [nm] + ([inst] if inst else []) + ([tag] if tag else [])
        return " · ".join(bits)
    notable_join = [p for p in people if inwin(p.get("since"), l7) and notable(p)]
    notable_left = [p for p in people if p.get("unsub") and inwin(p.get("udate"), l7) and notable(p)]

    # Search queries (Search Console; shortest window available is 28 days)
    sc = g.get("search_console", {})
    win28 = ((sc.get("windows", {}) or {}).get("28", {})) if sc.get("available") else {}
    queries = (win28.get("top_queries") or sc.get("top_queries") or [])[:6]

    # Returning vs new readers (GA4; 30-day cut, no clean 7-day in the data)
    ret = ((g.get("ga4", {}).get("returning", {}) or {}).get("d30", {})) or {}

    # Largest single online gift of the week
    biggest = max(gifts, key=lambda x: x.get("amount", 0)) if gifts else None

    # ---- 30-day trend: last 30 days vs the 30 before ----
    l30 = (run_date - timedelta(days=29), run_date)
    p30 = (run_date - timedelta(days=59), run_date - timedelta(days=30))
    s30  = sum(1 for p in people if inwin(p.get("since"), l30))
    s30p = sum(1 for p in people if inwin(p.get("since"), p30))
    u30  = sum(1 for p in people if p.get("unsub") and inwin(p.get("udate"), l30))
    u30p = sum(1 for p in people if p.get("unsub") and inwin(p.get("udate"), p30))
    vis30, vis30p = gt.get("visitors_30d"), gt.get("visitors_prev_30d")
    pv30,  pv30p  = gt.get("pageviews_30d"), gt.get("pageviews_prev_30d")
    ds = db.get("daily_series", [])
    give30  = sum(x.get("amt", 0) for x in ds if inwin(x.get("d"), l30))
    give30c = sum(x.get("gifts", 0) for x in ds if inwin(x.get("d"), l30))
    give30p = sum(x.get("amt", 0) for x in ds if inwin(x.get("d"), p30))
    # weekly visitor trajectory (shape of the trend)
    traj = [f"{round(p['visitors']/1000,1)}k" for p in ts[-6:]]

    def chg(now, prev):
        if not prev or now is None: return "—"
        p = round((now - prev) / prev * 100)
        return f"{'+' if p>=0 else ''}{p}%"

    def delta(now, prev):
        if not prev: return "no prior-week baseline"
        pct = round((now - prev) / prev * 100)
        return f"{'+' if pct>=0 else ''}{pct}% vs prior week"

    lines = []
    lines.append(f"# Vital City — weekly report")
    lines.append(f"**Seven days ending {run_date.strftime('%B %-d, %Y')}** · data snapshot {str(g.get('generated_at',''))[:10]}\n")
    # TL;DR — "most-read piece" means the top actual article
    top1 = (top_articles[0]["title"] if top_articles else (top[0]["title"] if top else "—"))
    lines.append(f"**In a line:** {sign7} new signups (net {('+' if sign7-unsub7>=0 else '')}{sign7-unsub7}), "
                 f"{(last_complete or {}).get('visitors',0):,} visitors in the last full week, and "
                 f"{fmtUSD(gift_total)} in online gifts. Most-read piece: “{top1}.”\n")

    lines.append("## The 30-day trend")
    lines.append("*The longer view — last 30 days vs the 30 before. Less noise than a single week.*")
    lines.append(f"- **Signups:** {s30} ({chg(s30, s30p)} vs prior 30d) · **unsubscribes:** {u30} → **net {('+' if s30-u30>=0 else '')}{s30-u30}**")
    lines.append(f"- **Website visitors:** {(vis30 or 0):,} ({chg(vis30, vis30p)}) · **page views:** {(pv30 or 0):,} ({chg(pv30, pv30p)})")
    if traj:
        lines.append(f"  - Weekly visitors, last 6 weeks: {' → '.join(traj)} *(last is partial)*")
    lines.append(f"- **Online giving:** {fmtUSD(give30)} from {give30c} gifts ({chg(give30, give30p)} vs prior 30d).")
    lines.append("*Note: one outsized week in either 30-day window can swing these deltas — the weekly trajectory above shows the real shape.*\n")

    lines.append("## Newsletter list")
    lines.append(f"- **New signups: {sign7}** — {delta(sign7, signP)}; ~{avg_wk}/week is the 8-week average.")
    lines.append(f"- **Unsubscribes: {unsub7}** (vs {unsubP} prior week) → **net {('+' if sign7-unsub7>=0 else '')}{sign7-unsub7}**.\n")

    lines.append("## Notable joins & departures")
    lines.append("*Wikipedia-notable people or government inboxes, this week.*")
    if notable_join:
        lines.append("**Joined:**")
        for p in notable_join: lines.append(f"- {person_line(p)}")
    if notable_left:
        lines.append("**Left:**")
        for p in notable_left: lines.append(f"- {person_line(p)}")
    if not notable_join and not notable_left:
        lines.append("- None flagged this week.")
    lines.append("")

    lines.append("## Email")
    if camps:
        for c in camps:
            un = c.get("unsubs")
            unln = f" · {un} unsub" + ("s" if (un or 0) != 1 else "") if un is not None else ""
            extra = ""
            if c.get("kind") == "appeal":
                extra += " · *fundraising appeal*"
            if c.get("type") == "variate" and c.get("winner_subject"):
                losers = [s for s in (c.get("variate_subjects") or []) if s != c.get("winner_subject")]
                extra += f" · A/B winner: “{c.get('winner_subject')}”" + (f" (beat “{losers[0]}”)" if losers else "")
            lines.append(f"- Sent {c.get('sent')} to ~{c.get('sent_to',0):,}: **{c.get('open_pct','?')}% open / {c.get('click_pct','?')}% click**{unln}{extra}.")
        lines.append("*Recent sends keep accruing opens for days, so treat a just-sent campaign as preliminary; click rate is the cleaner read.*")
    else:
        lines.append("- No campaigns sent this week.")
    lines.append("")

    learn = newsletter_learnings(mc, run_date)
    if learn:
        lines.append("## Newsletter learnings (rolling)")
        lines.append("*Slow-moving patterns over the trailing 12 months, refreshed each week.*")
        lines += learn
        lines.append("")

    lines.append("## Website traffic")
    if last_complete:
        lines.append(f"- Last full week ({last_complete.get('wk')}): **{last_complete.get('visitors',0):,} visitors / {last_complete.get('pageviews',0):,} page views** "
                     f"— vs a ~{avg_v:,}/week eight-week average.")
    if cur:
        lines.append(f"- Current in-progress week ({cur.get('wk')}): {cur.get('visitors',0):,} so far.")
    lines.append("")

    lines.append("## Returning vs new readers")
    if ret.get("new") or ret.get("returning"):
        lines.append(f"- **{ret.get('returning_pct',0):.0f}% returning** over the last 30 days "
                     f"({ret.get('returning',0):,} returning vs {ret.get('new',0):,} new). A loyalty signal — "
                     "people choosing to come back, not one-and-done arrivals. (30-day cut; GA4 has no clean 7-day window. "
                     "Cookie-based, so it's a floor.)")
    else:
        lines.append("- Returning-reader data not available this run.")
    lines.append("")

    if queries:
        lines.append("## Top search queries")
        lines.append("*What people Googled to reach Vital City (last 28 days — Search Console has no 7-day window).*\n")
        for q in queries:
            lines.append(f"- “{q.get('query')}” — {q.get('clicks',0):,} clicks · pos {q.get('position','?')}")
        lines.append("")

    lines.append("## Fundraising (online)")
    lines.append(f"- **{len(gifts)} gifts, {fmtUSD(gift_total)}** in the last seven days. YTD: **{fmtUSD(ytd.get('amount',0))} from {ytd.get('donors',0)} donors**.")
    if biggest:
        lines.append(f"- Largest gift this week: **{fmtUSD(biggest.get('amount',0))}** from {biggest.get('donor') or '(anonymous)'}.")
    lines.append("- *Online Donorbox gifts only — no checks, wires or grants.*\n")

    lines.append("## Top performers of the week")
    lines.append("*(unique visitors, last 7 days; issue/section pages are tagged)*\n")
    for i, p in enumerate(top, 1):
        lab = page_label(p.get("path"))
        tag = f" · *{lab}*" if lab else ""
        lines.append(f"{i}. {p.get('title')}{tag} — **{p.get('visits',0):,}**")
    lines.append("")

    lines.append("---")
    lines.append("*Seven-day numbers are the noisiest cut — one strong piece or a quiet news week moves them more "
                 "than anything we do. Read this as a pulse-check; the dashboard's long-run trendlines are the real signal. "
                 "Signups are the merged Ghost+Mailchimp count; giving is online-only.*")
    return "\n".join(lines)

def main():
    passphrase = get_pass()
    growth = fetch_decrypt("growth/data.enc", passphrase)
    people = fetch_decrypt("network/data.enc", passphrase)
    run_date = datetime.now().date()
    md = build(growth, people, run_date)
    out = os.path.join(DESKTOP, f"Vital-City-Weekly-{run_date.isoformat()}.md")
    with open(out, "w") as f:
        f.write(md)
    print("wrote", out)

if __name__ == "__main__":
    main()
