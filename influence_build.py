#!/usr/bin/env python3
"""Turn the raw evidence (private/influence_raw.json) into the influence index.

Reads  private/influence_raw.json   (written by influence_pull.py)
Writes private/influence.json       (the page payload; encrypt_influence.py
                                     turns it into influence/data.enc)

The index in one paragraph. For each of six kinds of evidence, count Vital
City and each of eleven peer organizations over the same calendar year, the
same way. Divide Vital City's count by the peers' median count: 1.0 means Vital
City drew as much of that kind of attention as the typical peer, 2.0 twice as
much. Combine the six ratios with a weighted geometric mean. Every formula,
weight and exclusion is written out in influence/methodology.md; this file is
the reference implementation, and the two must agree.
"""
from __future__ import annotations

import json, math, random, re, statistics, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from influence_pull import ORGS, OUTLETS, TIER, release_end, link_kind, RAW  # noqa: E402

OUT = ROOT / "private" / "influence.json"
FIRST_YEAR = 2022           # Vital City's first full year of publishing
PEERS = [o["id"] for o in ORGS if o["id"] != "vc"]
NAME = {o["id"]: o["name"] for o in ORGS}

# Weights: how much each kind of evidence says about influence on New York
# City policy, not how easy it is to count. They follow the ranking of evidence
# Vital City already uses with funders: scholarship (permanent, cannot be
# lobbied for) and use in government and the courts first, then major outlets,
# then the rest of the press, then general prominence on the web. See
# methodology.md, "Weights".
COMPONENTS = [
    {"id": "major",   "label": "Major outlets",   "weight": 0.15, "group": "noticed",
     "what": "Stories naming the organization in 14 national and major outlets, from the Times to Gothamist"},
    {"id": "nypress", "label": "New York press",  "weight": 0.15, "group": "noticed",
     "what": "Stories naming it in 20 New York City news outlets, from the Daily News to City & State"},
    {"id": "record",  "label": "Official record", "weight": 0.25, "group": "used",
     "what": "Mayor's office releases and transcripts, Comptroller publications and federal court cases that name or cite it"},
    {"id": "scholar", "label": "Scholarship",     "weight": 0.25, "group": "used",
     "what": "Academic and legal works, by year published, that cite its website"},
    {"id": "wiki",    "label": "Wikipedia",       "weight": 0.10, "group": "noticed",
     "what": "English Wikipedia articles citing its website at year's end"},
    {"id": "links",   "label": "Links from policy sites", "weight": 0.10, "group": "noticed",
     "what": "Government, university and news websites that link to its site, from Common Crawl's link graph"},
]
CMP = {c["id"]: c for c in COMPONENTS}


def log(m):
    print(m, file=sys.stderr, flush=True)


def years_through(today):
    return list(range(FIRST_YEAR, today.year + 1))


# ----------------------------------------------------------- vc press math
def vc_estimate(items):
    """Vital City's count from page-checked items: CONFIRMED ONLY, a floor.

    An earlier version counted unreadable pages at the confirmation rate seen
    on readable ones. The Times showed why that fails: its unreadable hits mix
    Rikers and subway-crime stories with war reports from Ukraine ("a vital
    city in the south"), so a rate borrowed from other outlets would have
    counted the war reports too. Unreadable hits are reported as possible
    additions and counted only once a person reads them (status set to
    confirmed or generic by hand). Returns (count, low, high, breakdown)."""
    c = Counter(i.get("status", "unchecked") for i in items)
    readable = c["confirmed"] + c["generic"] + c["absent"]
    rate = (c["confirmed"] / readable) if readable else 0
    unread = c["unreadable"] + c["unchecked"]
    return (c["confirmed"], c["confirmed"], c["confirmed"] + unread,
            {"confirmed": c["confirmed"], "generic": c["generic"], "absent": c["absent"],
             "unreadable": unread, "rate": round(rate, 3)})


# ------------------------------------------------------ component counts
def complete_domains(raw, section, years, domains):
    """Outlets pulled for every organization and year. An outlet still being
    collected would otherwise count for the organizations queried first and not
    the rest (Vital City is queried first), which would tilt every ratio."""
    pulled = raw.get(section, {}).get("pulled", {})
    from influence_pull import SELF_OUTLET
    ok = []
    for dom in domains:
        if all(f"{o['id']}|{dom}|{y}" in pulled for o in ORGS if o["press"]
               for y in years if SELF_OUTLET.get(o["id"]) != dom):
            ok.append(dom)
    return ok


def press_counts(raw, section, years, domains):
    """{org: {year: count}} plus Vital City's audit trail."""
    cells = raw.get(section, {}).get("items", {})
    domains = complete_domains(raw, section, years, domains)
    counts = {o["id"]: {} for o in ORGS if o["press"]}
    vc_detail = {}
    for oid in counts:
        for y in years:
            items = []
            for dom in domains:
                items += cells.get(f"{oid}|{dom}|{y}", [])
            # one story, one count: Google returns a story once per matching
            # outlet scope, so dedupe on outlet + title
            seen, uniq = set(), []
            for it in items:
                k = (it.get("domain"), it["title"].lower())
                if k not in seen:
                    seen.add(k)
                    uniq.append(it)
            if oid == "vc":
                est, lo, hi, br = vc_estimate(uniq)
                counts[oid][y] = est
                vc_detail[y] = {"estimate": round(est, 1), "low": lo, "high": hi, **br}
            else:
                counts[oid][y] = len(uniq)
    return counts, vc_detail


def vc_items(raw, section):
    out = []
    for k, v in raw.get(section, {}).get("items", {}).items():
        if not k.startswith("vc|"):
            continue
        for it in v:
            out.append({"date": it["date"], "domain": it.get("domain"), "title": it["title"],
                        "url": it.get("resolved_url") or it.get("url"), "status": it.get("status", "unchecked"),
                        "context": it.get("context", ""), "where": it.get("where", ""), "why": it.get("why", "")})
    seen, uniq = set(), []
    for it in sorted(out, key=lambda x: x["date"], reverse=True):
        k = (it["domain"], it["title"].lower())
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    return uniq


def docket_of(url):
    m = re.search(r"/docket/(\d+)/", url or "")
    return m.group(1) if m else url


def courts_counts(raw, years):
    """Cases, not documents: one count per case (docket) per year in which a
    filing carried the organization's address. CourtListener indexes every
    attachment separately, so a single administrative record in the
    congestion-pricing suit shows Vital City's address nine times; counting
    documents would let one filing outweigh four other cases."""
    orgs = raw.get("courts", {}).get("orgs", {})
    counts = {oid: {y: 0 for y in years} for oid in NAME}
    for oid, docs in orgs.items():
        seen = set()
        for d in docs:
            y = int(d["date"][:4]) if d.get("date") else None
            key = (docket_of(d.get("url")), y)
            if y in counts[oid] and key not in seen:
                seen.add(key)
                counts[oid][y] += 1
    return counts


def dated_counts(rows_by_org, years):
    """{org: {year: n}} from {org: [{"date": ...}, ...]}."""
    out = {oid: {y: 0 for y in years} for oid in NAME}
    for oid, rows in (rows_by_org or {}).items():
        for r in rows:
            y = int(r["date"][:4]) if r.get("date") else None
            if y in out[oid]:
                out[oid][y] += 1
    return out


def links_counts(raw, years):
    """Per year: distinct government, university and news domains linking to
    each organization's site, from the year's Common Crawl domain graph (the
    latest release ending in that year). Also the full breakdown."""
    wl = raw.get("weblinks", {})
    by_year = {}
    for rel in wl:
        y = release_end(rel)[0]
        if y in years and (y not in by_year or release_end(rel) > release_end(by_year[y])):
            by_year[y] = rel
    counts = {oid: {} for oid in NAME}
    detail = {}
    for y, rel in by_year.items():
        for oid in NAME:
            ds = wl[rel]["orgs"].get(oid, [])
            kinds = Counter(link_kind(d) for d in ds)
            counts[oid][y] = kinds["gov"] + kinds["edu"] + kinds["news"]
            detail.setdefault(y, {})[oid] = {"all": len(ds), **{k: kinds[k] for k in ("gov", "edu", "news")},
                                             "release": rel}
    return counts, detail


def cityhall_rows(raw):
    """{org: [items]} from the City Hall store (items keyed by link)."""
    out = {}
    for link, it in raw.get("cityhall", {}).get("items", {}).items():
        for oid in it["orgs"]:
            out.setdefault(oid, []).append({**it, "link": link})
    return out


def court_cases(raw, oid="vc"):
    """Vital City's court evidence grouped by case, for the page."""
    cases = {}
    for d in raw.get("courts", {}).get("orgs", {}).get(oid, []):
        m = re.search(r"/docket/(\d+)/[^/]+/(?:\d+/)?([a-z0-9-]+)/?$", d.get("url", ""))
        slug = m.group(2) if m else ""
        k = docket_of(d.get("url"))
        c = cases.setdefault(k, {"case": slug.replace("-", " ").title().replace(" V ", " v. "),
                                 "filings": [], "first": d["date"], "last": d["date"]})
        e = re.search(r"/docket/\d+/(\d+)/", d.get("url", ""))
        entry = e.group(1) if e else d.get("url")
        if any(f["entry"] == entry for f in c["filings"]):
            continue          # another attachment of a filing already listed
        c["filings"].append({"date": d["date"], "desc": d.get("desc", ""), "url": d.get("url", ""), "entry": entry})
        c["first"], c["last"] = min(c["first"], d["date"]), max(c["last"], d["date"])
    out = sorted(cases.values(), key=lambda c: c["last"], reverse=True)
    for c in out:
        c["filings"].sort(key=lambda f: f["date"])
    return out


def scholar_counts(raw, years):
    cells = raw.get("scholar", {}).get("cells", {})
    counts = {}
    for o in ORGS:
        counts[o["id"]] = {}
        for y in years:
            if o["id"] == "cji" and f"cji-or|{y}" in cells:
                # one query for both addresses, so a work citing both counts once
                counts["cji"][y] = cells[f"cji-or|{y}"]["n"]
                continue
            vals = [cells[f"{d}|{y}"]["n"] for d in o["domains"] if f"{d}|{y}" in cells]
            if vals:
                counts[o["id"]][y] = sum(vals)
    return counts


def wiki_counts(raw, years, today):
    w = raw.get("wiki", {})
    series, cps = w.get("series", {}), w.get("checkpoints", [])
    counts = {}
    for oid, s in series.items():
        counts[oid] = {}
        for y in years:
            cp = f"{y + 1}-01-01"
            if cp not in s:           # the current year: stock as of today
                cp = cps[-1]
            counts[oid][y] = s.get(cp, 0)
    return counts


def web_values(raw, years):
    """Standing in Common Crawl's domain graph.

    Common Crawl ranks every domain two ways, by PageRank and by harmonic
    centrality, and the two disagree often enough (the Citizens Budget
    Commission sits near the top on one and far down the other in the same
    release) that neither is used alone. Each organization's standing in a
    release is 1 / sqrt(PageRank position x harmonic position): the geometric
    mean of its two ranks, inverted so that higher is better. Dividing Vital
    City's standing by the peers' median then reads as "ranked at 0.6 times the
    typical peer's position". An organization with two addresses takes its
    better-ranked one. A year's value is the median over that year's releases,
    which keeps one odd crawl (mid-2024 put Vital City fivefold higher than the
    releases either side of it) from carrying the year."""
    wg = raw.get("webgraph", {})
    per_rel = {}
    for rel, d in wg.items():
        yr = release_end(rel)[0]
        best = {}
        for dom, row in d["rows"].items():
            s = 1 / math.sqrt(row["pr_pos"] * row["hc_pos"])
            if s > best.get(row["org"], {}).get("s", 0):
                best[row["org"]] = {"s": s, "pr_pos": row["pr_pos"], "hc_pos": row["hc_pos"]}
        per_rel[rel] = {"year": yr, "end": "%d-%02d" % release_end(rel),
                        "orgs": best}
    by_year = {}
    for oid in NAME:
        by_year[oid] = {}
        for y in years:
            xs = [r["orgs"][oid]["s"] for r in per_rel.values() if r["year"] == y and oid in r["orgs"]]
            if xs:
                by_year[oid][y] = statistics.median(xs)
    return by_year, per_rel


# ---------------------------------------------------------------- scoring
def ratio(vc, peers, smooth):
    """(vc + s) / (median(peers) + s). s = 1 for counts (so a year of zeros is
    1.0 rather than undefined), 0 for PageRank."""
    med = statistics.median(peers)
    return (vc + smooth) / (med + smooth), med


def rank_of(vc, vals):
    return 1 + sum(1 for v in vals if v > vc)


def score(comp_counts, years, weights, peer_ids=None):
    """Composite per year from {component: {org: {year: value}}}."""
    peer_ids = peer_ids or PEERS
    out = {}
    for y in years:
        num, den, parts = 0.0, 0.0, {}
        for cid, counts in comp_counts.items():
            if weights.get(cid, 0) == 0 or y not in counts.get("vc", {}):
                continue
            peers = [counts[p][y] for p in peer_ids if p in counts and y in counts[p]]
            if len(peers) < 5:
                continue
            r, _ = ratio(counts["vc"][y], peers, 0 if cid == "web" else 1)
            parts[cid] = r
            num += weights[cid] * math.log(r)
            den += weights[cid]
        out[y] = {"value": math.exp(num / den) if den else None, "parts": parts}
    return out


def poisson(lam, rng):
    if lam <= 0:
        return 0
    if lam > 60:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def intervals(comp_counts, years, weights, sims=3000):
    """90% band for the composite from counting noise alone: every count is
    redrawn as Poisson around what was observed, and the index recomputed.
    PageRank is taken as fixed. The band answers "could this year-to-year move
    be luck of the draw?", not "is the method right?"."""
    rng = random.Random(20260925)
    draws = {y: [] for y in years}
    for _ in range(sims):
        sim = {}
        for cid, counts in comp_counts.items():
            if cid == "web":
                sim[cid] = counts
                continue
            sim[cid] = {oid: {y: poisson(v, rng) for y, v in ys.items()} for oid, ys in counts.items()}
        for y, r in score(sim, years, weights).items():
            if r["value"]:
                draws[y].append(r["value"])
    band = {}
    for y, xs in draws.items():
        if xs:
            xs.sort()
            band[y] = [xs[int(0.05 * len(xs))], xs[int(0.95 * len(xs)) - 1]]
    return band


# ---------------------------------------------------------------- readers
def readers_series(raw, today):
    rows = raw.get("readers", {}).get("rows", [])
    months = []
    y, m = 2021, 9
    while (y, m) <= (today.year, today.month):
        months.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    out = []
    for (y, m) in months:
        end = date(y + (m == 12), m % 12 + 1, 1).isoformat()     # first day of next month
        def on(r):
            return r["since"] < end and not (r["unsub"] and r["unsub_date"] and r["unsub_date"] < end)
        out.append({"month": f"{y}-{m:02d}", "all": sum(1 for r in rows if on(r)),
                    "nyc": sum(1 for r in rows if on(r) and r["nyc"])})
    return out


# ------------------------------------------------------------------- main
def main():
    raw = json.loads(RAW.read_text())
    today = datetime.now(timezone.utc).date()
    years = years_through(today)

    major, major_vc = press_counts(raw, "press", years, [d for d, t in TIER.items() if t == "major"])
    nypress, nypress_vc = press_counts(raw, "press", years, [d for d, t in TIER.items() if t == "ny"])
    _, press_vc = press_counts(raw, "press", years, list(TIER))
    courts = courts_counts(raw, years)
    ch = dated_counts(cityhall_rows(raw), years)
    comp = dated_counts(raw.get("comptroller", {}).get("orgs", {}), years)
    have_record = bool(raw.get("cityhall", {}).get("done")) and "comptroller" in raw
    record = {oid: {y: courts[oid][y] + ch[oid][y] + comp[oid][y] for y in years} for oid in NAME}
    record_parts = {"courts": courts, "cityhall": ch, "comptroller": comp}
    scholar = scholar_counts(raw, years)
    wiki = wiki_counts(raw, years, today)
    web, web_rel = web_values(raw, years)
    links, links_detail = links_counts(raw, years)
    # Council hearings: shown beside the index, not in it, until the corpus
    # reaches back to 2022 (it starts with the 2024 session), because a measure
    # that joins mid-series would move the index for reasons that are not news
    council_cov = raw.get("council", {}).get("coverage", {})
    council = dated_counts(raw.get("council", {}).get("orgs", {}),
                           [int(y) for y, n in council_cov.items() if n >= 100 and int(y) >= FIRST_YEAR])

    comp_counts = {"major": major, "nypress": nypress, "record": record if have_record else {},
                   "scholar": scholar, "wiki": wiki, "links": links}
    missing = [cid for cid, c in comp_counts.items() if not any((c.get("vc") or {}).values())]
    if missing and "--allow-missing" not in sys.argv:
        raise SystemExit(f"build: no Vital City data for {missing}; run those collectors first "
                         f"(or pass --allow-missing for a preview)")
    for cid in missing:
        comp_counts.pop(cid)
        log(f"  PREVIEW: {cid} left out (no data yet)")
    weights = {c["id"]: c["weight"] for c in COMPONENTS}

    composite = score(comp_counts, years, weights)
    band = intervals(comp_counts, years, weights)

    # every organization's own composite, scored against the other eleven the
    # same way, so the page can rank all twelve on one scale
    league = {}
    for oid in NAME:
        others = [p for p in NAME if p != oid]
        relabeled = {cid: {("vc" if k == oid else ("_vc" if k == "vc" else k)): v for k, v in c.items()}
                     for cid, c in comp_counts.items()}
        peer_ids = ["_vc" if p == "vc" else p for p in others]
        s = score(relabeled, years, weights, peer_ids)
        # ranked only when the measures covering it carry at least 75 percent
        # of the weight: City Limits has no press counts (its name is ordinary
        # English), and without them it ranked second on the strength of
        # Wikipedia and web links
        tot = sum(weights[c] for c in comp_counts)
        league[oid] = {y: (round(r["value"], 3) if r["value"] and
                           sum(weights[c] for c in r["parts"]) >= 0.75 * tot else None)
                       for y, r in s.items()}

    # sensitivity: does the story survive other reasonable choices?
    variants = [("Equal weights", {k: 0.2 for k in weights}, None)]
    for c in COMPONENTS:
        if c["id"] not in comp_counts:
            continue
        variants.append((f"Without {c['label'].lower()}", {**weights, c["id"]: 0}, None))
    variants.append(("Peers without City Journal and Furman Center",
                     weights, [p for p in PEERS if p not in ("cj", "furman")]))
    variants.append(("Peers limited to the six research shops",
                     weights, ["cbc", "cuf", "css", "fpi", "furman", "rpa"]))
    sens = [{"label": lab, "values": {y: (round(r["value"], 3) if r["value"] else None)
                                      for y, r in score(comp_counts, years, w, pids).items()}}
            for lab, w, pids in variants]

    comps = []
    for c in COMPONENTS:
        if c["id"] not in comp_counts:
            continue
        counts = comp_counts[c["id"]]
        rows = {}
        for y in years:
            if y not in counts["vc"]:
                continue
            peers = {p: counts[p][y] for p in PEERS if p in counts and y in counts[p]}
            if len(peers) < 5:
                continue
            r, med = ratio(counts["vc"][y], list(peers.values()), 0 if c["id"] == "web" else 1)
            vals = [counts["vc"][y], *peers.values()]
            rows[y] = {"vc": counts["vc"][y], "median": med, "ratio": r,
                       "rank": rank_of(counts["vc"][y], list(peers.values())), "of": len(vals),
                       "orgs": {"vc": counts["vc"][y], **peers}}
        comps.append({**c, "years": rows})

    # the press detail the page draws: Vital City by quarter, and by outlet
    vc_press = vc_items(raw, "press")
    for it in vc_press:
        it["tier"] = TIER.get(it["domain"], "ny")
    # companion: Council hearings, scored the same way for the years covered
    council_rows = {}
    for y in sorted(next(iter(council.values()), {})):
        peers = {p: council[p][y] for p in PEERS}
        r, med = ratio(council["vc"][y], list(peers.values()), 1)
        council_rows[y] = {"vc": council["vc"][y], "median": med, "ratio": r,
                           "rank": rank_of(council["vc"][y], list(peers.values())), "of": len(peers) + 1,
                           "orgs": {"vc": council["vc"][y], **peers}}
    q = Counter()
    for it in vc_press:
        if it["status"] == "confirmed":
            d = it["date"]
            q[f"{d[:4]}-Q{(int(d[5:7]) - 1) // 3 + 1}"] += 1
    by_outlet = Counter(it["domain"] for it in vc_press if it["status"] == "confirmed")
    outlet_names = {d: n for d, n, _ in OUTLETS}

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "years": years,
        "partial_year": today.year,
        "missing": missing,
        "as_of": today.isoformat(),
        "orgs": [{"id": o["id"], "name": o["name"], "domains": o["domains"]} for o in ORGS],
        "components": comps,
        "weights": weights,
        "composite": {y: {"value": round(r["value"], 3) if r["value"] else None,
                          "parts": {k: round(v, 3) for k, v in r["parts"].items()},
                          "band": [round(b, 3) for b in band.get(y, [])]}
                      for y, r in composite.items()},
        "league": league,
        "sensitivity": sens,
        "press_vc": press_vc,
        "press_vc_tier": {"major": major_vc, "ny": nypress_vc},
        "press_outlets_counted": complete_domains(raw, "press", years, list(TIER)),
        "record_parts": {part: {oid: {y: c[oid][y] for y in years} for oid in NAME}
                         for part, c in record_parts.items()},
        "council": {"years": council_rows, "coverage": council_cov,
                    "what": "City Council hearings (transcripts and written testimony) that name the organization"},
        "press_quarters": dict(sorted(q.items())),
        "press_outlets": [{"domain": d, "name": outlet_names.get(d, d), "n": n}
                          for d, n in by_outlet.most_common()],
        "evidence": {
            "press": [i for i in vc_press if i["status"] == "confirmed"],
            "press_unreadable": [i for i in vc_press if i["status"] in ("unreadable", "unchecked")],
            "cityhall": sorted(cityhall_rows(raw).get("vc", []), key=lambda x: x["date"], reverse=True),
            "comptroller": raw.get("comptroller", {}).get("orgs", {}).get("vc", []),
            "council": raw.get("council", {}).get("orgs", {}).get("vc", []),
            "courts": court_cases(raw),
            "wiki": raw.get("wiki", {}).get("first_adds_vc", [])
                    or [{"title": t} for t in raw.get("wiki", {}).get("pages", {}).get("vc", [])],
            "scholar": raw.get("scholar", {}).get("list", []),
        },
        "links_detail": links_detail,
        "links_vc": {k: [d for d in raw.get("weblinks", {}).get(max(raw.get("weblinks", {}) or {"": 0},
                        key=lambda r: release_end(r) if r else (0, 0)), {}).get("orgs", {}).get("vc", [])
                         if link_kind(d) == k] for k in ("gov", "edu", "news")},
        "web_releases": [{"release": rel, **v} for rel, v in sorted(web_rel.items(), key=lambda kv: kv[1]["end"])],
        "readers": readers_series(raw, today),
        "sources_as_of": {
            "press": max(raw.get("press", {}).get("pulled", {}).values(), default=""),
            "city hall": raw.get("cityhall", {}).get("pulled", ""),
            "comptroller": raw.get("comptroller", {}).get("pulled", ""),
            "council": raw.get("council", {}).get("pulled", ""),
            "courts": raw.get("courts", {}).get("pulled", ""),
            "scholar": max(raw.get("scholar", {}).get("pulled", {}).values(), default=""),
            "wiki": raw.get("wiki", {}).get("pulled", ""),
            "links": max((v.get("pulled", "") for v in raw.get("weblinks", {}).values()), default=""),
            "readers": raw.get("readers", {}).get("pulled", ""),
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, default=lambda o: round(o, 6)))
    log(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    for y in years:
        c = payload["composite"][y]
        log(f"  {y}: {c['value']}  band {c['band']}  " +
            "  ".join(f"{k} {v:.2f}" for k, v in c["parts"].items()))


if __name__ == "__main__":
    main()
