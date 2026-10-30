#!/usr/bin/env python3
"""Join the toolkit's tools to one another -> data/links.enc

Each tool is built from its own sources, and until now none of them knew what
the others held: the catalogue didn't know which pieces brought in signups or
were cited, the contact card didn't know who was on the press map or worked at
a funder, and four pages counted press citations by four slightly different
rules. This runs last in the nightly refresh, after every tool is built, and
writes one small encrypted file the pages read alongside their own data:

  citations  the one record of who cites Vital City: the Prospects impact
             ledger's rows (the strictest checks: page read, roundups and
             passing mentions dropped, duplicates merged), counted by month
             and kind. Also written into private/growth.json so the growth
             dashboard counts by the same rule.
  pieces     per catalogue piece: members-only or not, signups it brought in,
             newsletter clicks, citations that name it, upcoming reshare dates
  people     per email address: the page they signed up on, their press-map
             record, the funder they work at, the Prospects lists they're on,
             appearances logged under their name
  week       the toolkit home page's Monday summary

Reads (all plaintext, gitignored, written earlier in the same run):
  private/growth.json  private/prospects.json  private/press.json
  private/resharing.json  private/people.json  data/catalogue.json
  private/signup_by_email.json (optional; growth_pull writes it)

Usage:
  python3 build_links.py                  # build, write private/links.json, inject citations into growth.json
  python3 build_links.py --no-inject      # leave growth.json alone
  python3 build_links.py --src DIR        # read the inputs from DIR (testing against decrypted copies)
Then encrypt_links.py writes data/links.enc.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
OUT = PRIV / "links.json"
LOG_SHEET = "https://docs.google.com/spreadsheets/d/1OlElkNQYaZEl4kYU2EexoU52MBgqTjkmdfGEkHwLWzc/edit"

# Kinds in the impact ledger that are someone else citing or featuring Vital
# City. "reader" (a decision-maker subscribed) and "outcome" (a funder's
# receipt) are evidence of reach, not citations, and stay on the Prospects page.
CITE_KINDS = ("press", "government", "policy", "republished", "appearance", "scholarly")
# The growth dashboard's "press and policy citations" indicator: written
# citations only, so a podcast appearance or a scholarly paper is not counted
# twice against the press tracker's own history.
INDICATOR_KINDS = ("press", "government", "policy", "republished")

TIER_LABELS = {
    "advisors": "Advisors, never asked", "researched": "Newly identified",
    "leads": "Introduction leads", "upgrade": "Upgrade candidates", "second": "The second gift",
    "notables": "Notable, never asked", "principals": "Principals",
    "foundation_staff": "Foundation staff", "lybunt": "Gave before, not this year",
    "party": "Nov. 2025 party",
}
_HONORIFIC = {"dr", "mr", "ms", "mrs", "prof", "jr", "sr", "ii", "iii", "phd"}


def log(m):
    print(m, file=sys.stderr, flush=True)


def load(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception as e:
        log(f"  links: {Path(path).name} not read ({type(e).__name__}); that join is skipped")
        return default


def norm(s):
    s = (s or "").lower().replace("’", "'")
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", s)).strip()


def name_key(s):
    """'Dr. Jane Q. Doe Jr.' -> 'jane doe': a bucket for candidates, always
    confirmed with same_person() before two names are joined."""
    w = [x for x in norm(s).split() if x not in _HONORIFIC]
    return f"{w[0]} {w[-1]}" if len(w) >= 2 else ""


def same_person(a, b):
    """Two spellings of one name: same last name, first names equal or one a
    short form of the other (Jeff, Jeffery), and no conflicting middle names
    (Rachel Meade Smith is not Rachel Holliday Smith)."""
    wa = [x for x in norm(a).split() if x not in _HONORIFIC]
    wb = [x for x in norm(b).split() if x not in _HONORIFIC]
    if len(wa) < 2 or len(wb) < 2 or wa[-1] != wb[-1]:
        return False
    fa, fb = wa[0], wb[0]
    if not (fa == fb or (min(len(fa), len(fb)) >= 3 and (fa.startswith(fb) or fb.startswith(fa)))):
        return False
    ma, mb = [x for x in wa[1:-1] if len(x) > 1], [x for x in wb[1:-1] if len(x) > 1]
    return not (ma and mb and ma != mb)


def slug_of(url):
    u = (url or "").split("?")[0].rstrip("/")
    return u.rsplit("/", 1)[-1].lower() if "vitalcitynyc.org" in u else ""


def day(s):
    return str(s or "")[:10]


def emails_of(r):
    return [e.lower() for e in (r.get("emails") or [r.get("e")]) if e]


# ----- citations ------------------------------------------------------------

def build_citations(prospects, today):
    rows = [{k: r.get(k) for k in ("date", "kind", "source", "title", "url", "detail", "who", "area", "context") if r.get(k)}
            for r in ((prospects.get("impact_ledger") or {}).get("rows") or []) if r.get("kind") in CITE_KINDS]
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    for i, r in enumerate(rows):
        r["id"] = i          # the row's position: pieces, people and the week refer to rows by it
    monthly = Counter(day(r.get("date"))[:7] for r in rows if r["kind"] in INDICATOR_KINDS and len(day(r.get("date"))) >= 7)
    counts = {}
    for k in CITE_KINDS:
        ds = [day(r.get("date")) for r in rows if r["kind"] == k]
        counts[k] = {w: sum(1 for d in ds if d and d >= (today - timedelta(days=n)).isoformat())
                     for w, n in (("d7", 7), ("d30", 30), ("d90", 90), ("d365", 365))}
        counts[k]["all"] = len(ds)
    return {"asof": today.isoformat(), "rule": "Prospects impact ledger", "rows": rows,
            "monthly": dict(sorted(monthly.items())), "counts": counts, "indicator_kinds": list(INDICATOR_KINDS)}


# ----- pieces ---------------------------------------------------------------

def build_pieces(catalogue, growth, resharing, cites):
    pidx = ((growth.get("ga4") or {}).get("piece_index") or {})
    idx = {p.get("slug"): p for p in (pidx.get("pieces") or [])}
    # Titles long enough to identify a piece when a citation quotes them.
    by_title = {}
    for c in catalogue:
        t = norm(c.get("title"))
        if len(t) > 18:
            by_title[t] = c.get("slug")
    cite_by = defaultdict(set)
    for r in cites["rows"]:
        text = norm(" ".join(str(r.get(k) or "") for k in ("title", "detail", "context")))
        hit = {slug_of(r.get("url"))} - {""}
        hit |= {s for t, s in by_title.items() if t in text}
        for s in hit:
            cite_by[s].add(r["id"])
    reshare = defaultdict(list)
    for u in resharing.get("upcoming") or []:
        for pk in u.get("picks") or []:
            reshare[pk.get("slug")].append({"date": u.get("post_on") or u.get("date"),
                                            "label": u.get("label") or (u.get("event") or {}).get("title")})
    always = {p.get("slug") for p in (resharing.get("always_on") or [])}

    out = {}
    for c in catalogue:
        s = c.get("slug")
        if not s:
            continue
        p = idx.get(s) or {}
        rec = {}
        if (c.get("visibility") or "public") != "public":
            rec["mo"] = 1
        for k_out, k_in in (("su", "signups"), ("su30", "signups30"), ("nlc", "nl_clicks"), ("nlu", "nl_unique"),
                            ("nls", "nl_sends"), ("v", "views"), ("v30", "views30"), ("u", "users")):
            if p.get(k_in) is not None:
                rec[k_out] = p[k_in]
        if p.get("views") and p.get("secs"):
            rec["sec"] = round(p["secs"] / p["views"])
        qs = [q.get("q") or q.get("query") for q in (p.get("queries") or [])[:3]]
        if any(qs):
            rec["q"] = [q for q in qs if q]
        if cite_by.get(s):
            rec["c"] = sorted(cite_by[s])
        if reshare.get(s):
            rec["rs"] = sorted(reshare[s], key=lambda x: x["date"] or "")[:4]
        if s in always:
            rec["ao"] = 1
        if rec:
            out[s] = rec
    return out, pidx.get("signups_since") or ""


# ----- people ---------------------------------------------------------------

def build_people(people, growth, prospects, press, signup_by_email, cites):
    out = defaultdict(dict)

    # 1. The page each subscriber signed up on (Ghost records it), last 180 days.
    recent = {(r.get("email") or "").lower(): r for r in ((growth.get("ghost_signup_attribution") or {}).get("recent_signups") or [])}
    for em, r in list(signup_by_email.items()) + list(recent.items()):
        em = (em or "").lower().strip()
        if not em:
            continue
        url = r.get("landing_url") or ""
        out[em]["sp"] = {"t": r.get("landing_title") or "", "u": url, "d": day(r.get("ts") or r.get("date")),
                         "src": r.get("source") or "", "slug": slug_of(url)}

    # 2. The press map: by published address, else by name for people the
    #    contact tool already marks as press or journalists.
    press_by_email, press_by_name = {}, defaultdict(list)
    outlet_name = {o.get("id"): o.get("name") or o.get("id") for o in press.get("outlets") or []}
    for p in press.get("people") or []:
        beats = sorted(p.get("beats") or [], key=lambda b: -(b.get("count") or 0))[:3]
        rec = {"id": p.get("id"), "n": p.get("name"), "o": outlet_name.get(p.get("outlet"), p.get("outlet")), "sc": p.get("story_count"),
               "l": day(p.get("latest")), "b": [[b.get("label"), b.get("count")] for b in beats],
               "act": bool(p.get("active"))}
        if p.get("email"):
            press_by_email[p["email"].lower()] = rec
        k = name_key(p.get("name"))
        if k:
            press_by_name[k].append((p.get("name"), rec))
    for r in people:
        ems = emails_of(r)
        hit = next((press_by_email[e] for e in ems if e in press_by_email), None)
        if not hit and (r.get("press") or "journalist" in (r.get("types") or [])):
            cands = [rec for nm, rec in press_by_name.get(name_key(r.get("n")), []) if same_person(nm, r.get("n"))]
            if len(cands) == 1:
                hit = cands[0]
        if hit:
            for e in ems:
                out[e]["pm"] = hit

    # 3. Funders: an address at a funder's domain. Two entries can share a
    #    domain (a foundation and one of its programs); the current funder
    #    wins, else the first listed.
    funders = {}
    for f in prospects.get("funders") or []:
        d = (f.get("domain") or "").lower().strip()
        if d and (d not in funders or (f.get("current") and not funders[d]["cur"])):
            funders[d] = {"k": f.get("key"), "n": f.get("name"), "cur": bool(f.get("current"))}
    # 4. Prospects lists.
    tiers = defaultdict(list)
    for key, rows in (prospects.get("tiers") or {}).items():
        for p in rows or []:
            if p.get("e"):
                tiers[p["e"].lower()].append({"k": key, "l": TIER_LABELS.get(key, key), "w": p.get("why") or ""})
    for r in people:
        ems = emails_of(r)
        f = next((funders[e.split("@")[-1]] for e in ems if e.split("@")[-1] in funders), None)
        t = [x for e in ems for x in tiers.get(e, [])]
        for e in ems:
            if f:
                out[e]["fu"] = f
            if t:
                out[e]["pt"] = t

    # 5. Appearances and citations logged under the person's name, for people
    #    who write for Vital City (a name match alone is too loose for anyone else).
    by_name = defaultdict(list)
    for c in cites["rows"]:
        k = name_key(c.get("who"))
        if k:
            by_name[k].append((c.get("who"), c["id"]))
    for r in people:
        if not (r.get("auth") or r.get("senior")):
            continue
        ids = [i for who, i in by_name.get(name_key(r.get("n")), []) if same_person(who, r.get("n"))]
        if ids:
            for e in emails_of(r):
                out[e]["c"] = ids
    return {k: v for k, v in out.items() if v}


# ----- the Monday summary ---------------------------------------------------

def build_week(growth, prospects, resharing, cites, initiatives, today):
    ga4 = growth.get("ga4") or {}
    as_of = day(ga4.get("as_of")) or today.isoformat()
    # The last full Monday-to-Sunday week before the data's as-of date.
    weeks = [w for w in (ga4.get("traffic_weekly") or []) if w.get("wk") and
             (date.fromisoformat(w["wk"]) + timedelta(days=6)).isoformat() < as_of]
    res = {"asof": as_of}
    if weeks:
        wk = weeks[-1]
        s = date.fromisoformat(wk["wk"]); e = s + timedelta(days=6)
        res["from"], res["to"] = s.isoformat(), e.isoformat()
        prior = weeks[-5:-1]
        pw = [(date.fromisoformat(w["wk"]), date.fromisoformat(w["wk"]) + timedelta(days=6)) for w in prior]
        act = {r["d"]: r for r in ((growth.get("mailchimp") or {}).get("daily_activity") or [])}
        gifts = {r.get("d"): r for r in ((growth.get("donorbox") or {}).get("daily_series") or [])}

        def span(rows, a, b, k):
            return sum((rows.get((a + timedelta(days=i)).isoformat()) or {}).get(k, 0) or 0 for i in range((b - a).days + 1))

        def avg(vals):
            vals = [v for v in vals if v is not None]
            return round(sum(vals) / len(vals)) if vals else None
        res["n"] = {
            "visits": [wk.get("visits"), avg([w.get("visits") for w in prior])],
            "signups": [span(act, s, e, "subs"), avg([span(act, a, b, "subs") for a, b in pw])],
            "unsubs": [span(act, s, e, "unsubs"), avg([span(act, a, b, "unsubs") for a, b in pw])],
            "gifts": [span(gifts, s, e, "gifts"), avg([span(gifts, a, b, "gifts") for a, b in pw])],
        }
        res["cites"] = [c["id"] for c in cites["rows"] if s.isoformat() <= day(c.get("date")) <= e.isoformat()]
    rf = (growth.get("role_flows") or {}).get("week") or {}
    j, lv = rf.get("join") or {}, rf.get("leave") or {}
    res["join"] = {"from": j.get("from"), "to": j.get("to"), "total": j.get("total"), "notable": (j.get("notable") or [])[:8]}
    res["leave"] = {"total": lv.get("total"), "notable": (lv.get("notable") or [])[:5]}
    top = ((growth.get("ghost_traffic") or {}).get("top_pages_7d") or [])[:5]
    res["top"] = [{"t": p.get("title"), "p": p.get("path") or p.get("pathname"),
                   "v": p.get("visits") or p.get("visitors") or p.get("views")} for p in top]
    horizon = (today + timedelta(days=8)).isoformat()
    res["reshare"] = [{"date": u.get("post_on"), "label": u.get("label"),
                       "picks": [{"t": p.get("title"), "u": p.get("url"), "slug": p.get("slug")} for p in (u.get("picks") or [])[:2]]}
                      for u in (resharing.get("upcoming") or []) if today.isoformat() <= (u.get("post_on") or "") <= horizon][:5]
    since7 = (today - timedelta(days=7)).isoformat()
    res["gifts"] = [{"d": g.get("d"), "n": g.get("n"), "a": g.get("a"), "rec": g.get("rec"), "inst": g.get("inst")}
                    for g in ((prospects.get("gifts") or {}).get("rows") or []) if (g.get("d") or "") >= since7][:8]
    res["log"] = (initiatives.get("items") or [])[-4:]          # the latest entries, newest last
    res["log_url"] = initiatives.get("sheet_url") or LOG_SHEET
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="read inputs from this folder instead of private/ (testing)")
    ap.add_argument("--no-inject", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    src = Path(a.src) if a.src else PRIV
    today = datetime.now(timezone.utc).date()

    growth = load(src / "growth.json", {})
    prospects = load(src / "prospects.json", {})
    press = load(src / "press.json", {})
    resharing = load(src / "resharing.json", {})
    people = load(src / "people.json", [])
    signup_by_email = load(src / "signup_by_email.json", {})
    catalogue = load(ROOT / "data" / "catalogue.json", [])
    if not growth or not catalogue:
        raise SystemExit("links: growth.json or the catalogue is missing; nothing to join")

    cites = build_citations(prospects, today)
    pieces, signup_since = build_pieces(catalogue, growth, resharing, cites)
    persons = build_people(people, growth, prospects, press, signup_by_email, cites)
    week = build_week(growth, prospects, resharing, cites, growth.get("initiatives") or {}, today)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "citations": cites, "pieces": pieces, "signups_since": signup_since,
           "people": persons, "week": week, "tiers": TIER_LABELS}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    log(f"links: {len(cites['rows'])} citations, {len(pieces)} pieces, {len(persons)} addresses -> {a.out} "
        f"({Path(a.out).stat().st_size // 1024} KB)")

    # One rule for citations: the growth dashboard counts the same rows.
    if not a.no_inject and cites["rows"]:
        growth["citations"] = {k: cites[k] for k in ("asof", "rule", "monthly", "counts", "indicator_kinds")}
        growth["citations"]["rows"] = [{k: r.get(k) for k in ("date", "kind", "source", "title", "url")} for r in cites["rows"]]
        (src / "growth.json").write_text(json.dumps(growth, indent=2))
        log(f"links: citations written into {src / 'growth.json'}")


if __name__ == "__main__":
    main()
