#!/usr/bin/env python3
"""Build the fundraising-prospects intelligence page's data.

Reads   private/people.json    (merged contact DB: Ghost + Mailchimp + Donorbox + CRM)
        private/growth.json    (growth pull: Donorbox windows, campaigns)
        data/catalogue.json    (public catalogue, for editorial-fit counts)
        private/employer_inferences.json  (optional; tier-B principals)
Writes  private/prospects.json (plaintext, gitignored)
        prospects/data.enc     (AES-256-GCM, same passphrase as the other tools)

Design rules, deliberately repeated from the rest of the repo:
- Facts and inferences are labelled differently. Curated CRM tags and Donorbox
  amounts are facts; employer inferences and the external funder list are leads
  that carry their basis with them.
- The external grant-source list is a set of LEADS TO VERIFY, not research: the
  page says so. Nothing here should be pasted into a grant application.
- No single opaque score. Every list shows the components (gave, opens, clicks,
  tag) that put a person on it.
"""
import json, os, base64, secrets, statistics as st
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict, Counter
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parent
PEOPLE = Path(os.environ.get("PROSPECTS_PEOPLE", ROOT / "private" / "people.json"))
GROWTH = Path(os.environ.get("PROSPECTS_GROWTH", ROOT / "private" / "growth.json"))
CAT    = ROOT / "data" / "catalogue.json"
INFER  = ROOT / "private" / "employer_inferences.json"
OUT    = ROOT / "private" / "prospects.json"
ENC    = ROOT / "prospects" / "data.enc"
ITERS  = 600_000
TODAY  = date.today()

# ---------------------------------------------------------------------------
# The curated funder list. Two kinds of rows:
#   - warm: the org already reads Vital City (matched to subscribers below)
#   - lead: well-known funders of policy journalism / civic research whose
#           public focus plausibly fits Vital City's beats. These are LEADS —
#           current programs, deadlines and eligibility must be verified on the
#           funder's own site before anyone acts.
# fit: which Vital City beats the funder's stated focus overlaps.
# ---------------------------------------------------------------------------
# "current": named as a funder on vitalcitynyc.org/about (read Aug 2026) —
# these are renewal-and-growth relationships, not prospects.
FUNDERS = [
 {"name":"Arnold Ventures","domain":"arnoldventures.org","current":True,
  "focus":"Criminal justice policy, evidence-based government",
  "fit":["criminal justice","data journalism"],
  "note":"CURRENT FUNDER. John Arnold has a byline and a 99% open rate; 12 staff read. The renewal case writes itself — the expansion case is their government-performance program."},
 {"name":"Harry Frank Guggenheim Foundation","domain":"hfg.org","current":True,
  "focus":"Research on violence and its reduction",
  "fit":["criminal justice","gun violence"],
  "note":"CURRENT FUNDER — and two staff donate personally on top of it. The strongest institutional relationship in the file."},
 {"name":"Charles H. Revson Foundation","domain":"revsonfoundation.org","current":True,
  "focus":"New York City civic life, journalism, urban affairs",
  "fit":["nyc civic","journalism"],
  "note":"CURRENT FUNDER. Julie Sandorf led its local-news grantmaking; four staff read."},
 {"name":"Achelis & Bodman Foundation","domain":"achelis-bodman-fnd.org","current":True,
  "focus":"New York City and area nonprofits",
  "fit":["nyc civic"],
  "note":"CURRENT FUNDER per the about page. No staff found among readers — the relationship exists outside the subscriber file."},
 {"name":"Public Welfare Foundation","domain":"publicwelfare.org","current":True,
  "focus":"Criminal and youth justice reform",
  "fit":["criminal justice"],
  "note":"CURRENT FUNDER per the about page. No staff found among readers."},
 {"name":"Teagle Foundation","domain":"teagle.org","current":True,
  "focus":"Liberal arts education and civic initiatives",
  "fit":["education","nyc civic"],
  "note":"CURRENT FUNDER per the about page. No staff found among readers."},
 {"name":"MacArthur Foundation","domain":"macfound.org",
  "focus":"Journalism and media; criminal justice reform",
  "fit":["journalism","criminal justice"],
  "note":"Laurie Garduque (criminal justice program) is a reader."},
 {"name":"Robin Hood","domain":"robinhood.org",
  "focus":"New York City poverty",
  "fit":["nyc civic","economy"],
  "note":"Richard Buery is a Vital City advisor."},
 {"name":"Bloomberg Philanthropies","domain":"bloomberg.org",
  "focus":"Cities, public health, government innovation",
  "fit":["city government","public health"],
  "note":"Seven readers including Bloomberg Associates staff; Linda Gibbs and Rose Gill read."},
 {"name":"Tiger Foundation","domain":"tigerfoundation.org","current":True,
  "focus":"Breaking the cycle of poverty in New York City",
  "fit":["nyc civic","education"],
  "note":"CURRENT FUNDER. Charles Buice (president) is an engaged reader."},
 {"name":"Clark Foundation","domain":"clarkfoundation.org",
  "focus":"New York City nonprofits and opportunity",
  "fit":["nyc civic"],
  "note":"Doug Bauer (executive director) is a reader."},
 {"name":"Fund for the City of New York","domain":"fcny.org",
  "focus":"NYC government performance and civic innovation",
  "fit":["city government"],
  "note":"Already Vital City's fiscal sponsor — the relationship exists by construction."},
 {"name":"Tow Foundation","domain":"towfoundation.org","current":True,
  "focus":"Juvenile and criminal justice; investigative journalism",
  "fit":["criminal justice","journalism"],
  "note":"CURRENT FUNDER — a reminder that funding and readership are different things: only one subscriber on file."},
 # ---- leads: abundance / state capacity — THE ACTIVE HUNT ----
 {"name":"Coefficient Giving","domain":"coefficientgiving.org","lead":True,"cat":"abundance","pursuit":True,
  "focus":"Abundance and growth: housing, land use, state capacity, evidence-based policy",
  "fit":["housing","city government","economy"],
  "note":"IN PURSUIT (per Josh, Aug 2026). Formerly Open Philanthropy; its Abundance and Growth fund is the closest large pool to Vital City's actual work. Pitch the policy-analysis output, not the journalism."},
 {"name":"Arnold Ventures — government performance","domain":"arnoldventures.org","lead":True,"cat":"abundance",
  "focus":"Evidence-based policy, government performance (beyond the criminal-justice program above)",
  "fit":["city government","data journalism"],
  "note":"Same warm door, second program: the abundance-adjacent pitch runs through their evidence-based-government side."},
 {"name":"Emergent Ventures (Mercatus)","domain":"mercatus.org","lead":True,"cat":"abundance",
  "focus":"Fast grants to people and projects advancing progress and state capacity",
  "fit":["city government","economy"],
  "note":"Small, fast, person-shaped grants — a fit for a specific Vital City project or fellow rather than general support."},
 {"name":"Hewlett Foundation — Economy and Society","domain":"hewlett.org","lead":True,"cat":"abundance",
  "focus":"Rethinking economic policy ideas and institutions",
  "fit":["economy","city government"],
  "note":"Ideas-infrastructure funder; commentary and policy analysis is squarely what it buys. Verify current strategy docs."},
 {"name":"Omidyar Network","domain":"omidyar.com","lead":True,"cat":"abundance",
  "focus":"Reimagining capitalism, technology and governance",
  "fit":["economy","technology"],
  "note":"Adjacent rather than central; strongest if the pitch leads with data analysis of how city systems perform."},
 {"name":"TransitCenter","domain":"transitcenter.org","lead":True,"cat":"abundance",
  "focus":"US transit improvement and advocacy (an operating foundation)",
  "fit":["transit","city government"],
  "note":"The subway-safety recommendations — NYT exclusive, partly adopted by the governor and MTA — are a ready-made door here. It runs its own programs as much as it grants; the fit is partnership as much as funding."},
 {"name":"Renaissance Philanthropy","domain":"renaissancephilanthropy.org","lead":True,"cat":"abundance",
  "focus":"Ambitious science, technology and state-capacity initiatives",
  "fit":["city government","technology"],
  "note":"Newer shop (Tom Kalil). Confidence on current programs is lower — verify before investing time."},
 # ---- leads: journalism — OFF-CENTER for a commentary/analysis shop ----
 {"name":"Press Forward","domain":"pressforward.news","lead":True,"cat":"journalism",
  "focus":"National coalition funding local news (>$500M pooled)",
  "fit":["journalism","nyc civic"],
  "note":"Huge pool, but aimed at news gathering. Vital City is commentary and analysis, not core local news — expect eligibility friction; the data-journalism output is the only natural wedge."},
 {"name":"Knight Foundation","domain":"knightfoundation.org","lead":True,"cat":"journalism",
  "focus":"Journalism, informed communities",
  "fit":["journalism","data journalism"],
  "note":"Reference journalism funder, same caveat: the informed-communities frame fits better than the newsroom frame."},
 {"name":"American Journalism Project","domain":"theajp.org","lead":True,"cat":"journalism",
  "focus":"Venture philanthropy for nonprofit local news",
  "fit":["journalism"],
  "note":"Funds local NEWS operations; a policy journal is off-profile. Low priority."},
 {"name":"Democracy Fund","domain":"democracyfund.org","lead":True,"cat":"journalism",
  "focus":"Local news ecosystems, civic engagement",
  "fit":["journalism","nyc civic"],
  "note":"The civic-engagement side is the fit, not the news side."},
 {"name":"JM Kaplan Fund","domain":"jmkfund.org","lead":True,
  "focus":"NYC civic innovation (Innovation Prize; historic city grantmaking)",
  "fit":["nyc civic","city government"],
  "note":"Small, NYC-specific, unsolicited-friendly historically."},
 {"name":"New York Community Trust","domain":"thenytrust.org","lead":True,
  "focus":"NYC community foundation; journalism and civic programs",
  "fit":["nyc civic","journalism"],
  "note":"Broad NYC funder with a standing grants process."},
 {"name":"Ford Foundation","domain":"fordfoundation.org","lead":True,
  "focus":"Cities and states; disruption of inequality; creativity and free expression",
  "fit":["nyc civic","criminal justice"],
  "note":"Large and slow; usually invitation-driven. A relationship play, not an application play."},
]



# Who each funder currently funds — the fit check Josh asked for. Researched
# Aug 2026 with sources; where a funder was NOT researched this pass, the field
# says so instead of guessing. Grant claims are examples, not exhaustive lists,
# and current-ness must be verified on the funder's own grants database.
GRANTEES = {
 "Coefficient Giving": {"who":"California YIMBY ($2M general support), YIMBY Action, YIMBY Law, Sightline Institute, Urban Institute, Greater Greater Washington — ~$27M into housing/land-use reform since 2015","src":"openphilanthropy.org grants pages; Inside Philanthropy (verified Aug 2026)"},
 "Hewlett Foundation — Economy and Society": {"who":"Roosevelt Institute, Niskanen Center, MIT Economics (Shaping the Future of Work) — $33.2M across 49 grants in 2024","src":"hewlett.org; Chronicle of Philanthropy (verified Aug 2026)"},
 "Arnold Ventures": {"who":"Council on Criminal Justice and CUNY Institute for State & Local Governance were both launched with Arnold support — and both have staff among Vital City readers","src":"widely reported; verify current grants at arnoldventures.org/grants"},
 "Arnold Ventures — government performance": {"who":"See Arnold Ventures above — same grants database covers the government-performance portfolio","src":"arnoldventures.org/grants"},
 "Harry Frank Guggenheim Foundation": {"who":"Grants to individual scholars researching violence (its core program), plus research prizes — it funds researchers more than organizations","src":"hfg.org (program structure; verify)"},
 "Revson Foundation": {"who":"Helped launch THE CITY; long record of NYC journalism and civic grants","src":"widely reported; verify at revsonfoundation.org/grants"},
 "Emergent Ventures (Mercatus)": {"who":"Small fast grants to individual researchers, writers and founders rather than organizations — the fit is a person or project, not general support","src":"mercatus.org/emergent-ventures (program structure)"},
}

EVENT_CSV = ROOT / "private" / "events" / "2025-11-fundraiser.csv"

def load_event(people):
    """The November 2025 house party — the one recorded ASK in the file.
    Matches invitees to the contact DB by email, then by normalized name."""
    import csv as _csv
    if not EVENT_CSV.exists():
        return None
    rows = list(_csv.DictReader(open(EVENT_CSV)))
    by_email = {}
    for p in people:
        for e in ([p.get("e")] + (p.get("emails") or [])):
            if e: by_email[e.lower()] = p
    by_name = {(p.get("n") or "").strip().lower(): p for p in people if p.get("n")}
    out = {"invited": len(rows), "attended": [], "regrets": 0, "no_response": 0}
    for r in rows:
        st = (r.get("Status") or "").strip()
        email = (r.get("Email/Phone Number") or "").strip().lower()
        name = (r.get("Full Name") or "").strip()
        p = by_email.get(email) or by_name.get(name.lower())
        if st == "Attending":
            gave_after = bool(p and (p.get("dlast") or "") >= "2025-11")
            rec = person_row(p, "RSVP'd yes to the Nov '25 party") if p else                   {"n": name, "e": email, "inst": "", "damt": 0, "dcnt": 0, "dlast": "",
                   "eopen": 0, "eclick": 0, "wiki": 0, "types": [],
                   "why": "RSVP'd yes; NOT in the contact database"}
            rec["gave_after"] = 1 if gave_after else 0
            if not gave_after and rec["why"].startswith("RSVP"):
                rec["why"] += " — no gift since"
            out["attended"].append(rec)
        elif st == "Regrets":
            out["regrets"] += 1
        else:
            out["no_response"] += 1
    out["attended"].sort(key=lambda x: (x["gave_after"], -x["damt"], -x["eopen"]))
    out["gave_after"] = sum(1 for x in out["attended"] if x["gave_after"])
    out["gave_after_amt"] = round(sum(x["damt"] for x in out["attended"] if x["gave_after"]))
    out["unconverted"] = sum(1 for x in out["attended"] if not x["gave_after"])
    return out

# Most-influential contributors for the deck. Curated Aug 2026 from the
# Wikipedia-notability ranking of bylined authors (article length as the rough
# prominence proxy), hand-filtered: deceased/archival authors excluded, chosen
# for breadth across discipline and political lean. The DESCRIPTIONS are
# point-in-time (Wikipedia, Aug 2026); the PIECES are matched live from the
# catalogue at every build, so links and counts stay current.
INFLUENTIALS = [
  ("Edward Glaeser", "Harvard economist — the leading urban economist of his generation"),
  ("Richard Florida", "Urban theorist, author of The Rise of the Creative Class"),
  ("Megan McArdle", "Washington Post columnist"),
  ("Jonathan Rauch", "Brookings senior fellow and The Atlantic contributing writer"),
  ("Carlina Rivera", "New York City Council member"),
  ("Erwin Chemerinsky", "Dean of Berkeley Law, leading constitutional scholar"),
  ("Brandon del Pozo", "Former police chief, Brown professor of policy and policing"),
  ("Majora Carter", "Urban revitalization strategist, Peabody-winning broadcaster"),
  ("Carlo Ratti", "MIT Senseable City Lab director and architect"),
  ("Bradley Tusk", "Venture capitalist and political strategist"),
]

def load(path, default=None):
    try:
        return json.load(open(path))
    except Exception:
        return default


def years_since(s):
    try:
        d = datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        return (TODAY - d).days / 365
    except Exception:
        return None


def person_row(r, why):
    """The displayed record for one prospect — components, never a single score."""
    return {"n": r.get("n") or "", "e": r.get("e") or "",
            "inst": (r.get("inst") or "").strip(),
            "damt": round(r.get("damt") or 0), "dcnt": r.get("dcnt") or 0,
            "dlast": (r.get("dlast") or "")[:10],
            "eopen": r.get("eopen") or 0, "eclick": r.get("eclick") or 0,
            "wiki": 1 if r.get("wiki") else 0,
            "types": r.get("types") or [], "why": why}


def main():
    people = load(PEOPLE) or []
    growth = load(GROWTH) or {}
    cat = load(CAT) or []
    infer = (load(INFER) or {}).get("rows", [])

    sub = [r for r in people if r.get("mem") and not r.get("unsub") and r.get("e")]
    donors = [r for r in people if r.get("don")]
    db = growth.get("donorbox", {}) or {}

    # ---------------- topline ----------------
    amts = sorted((r.get("damt") or 0) for r in donors)
    total = sum(amts)
    top5 = sum(amts[-5:]) if amts else 0
    repeat = sum(1 for r in donors if (r.get("dcnt") or 0) > 1)
    monthly = db.get("monthly_series") or []
    topline = {
        "raised": round(total), "donors": len(donors),
        "repeat": repeat, "repeat_pct": round(100 * repeat / len(donors)) if donors else 0,
        "top5_pct": round(100 * top5 / total) if total else 0,
        "median_gift": round(st.median(amts)) if amts else 0,
        "recurring_donors": db.get("active_recurring_donors"),
        "mrr": db.get("mrr_estimate"),
        "last_gift_month": max((r.get("dlast") or "" for r in donors), default="")[:7],
        "best_month": max(monthly, key=lambda m: m.get("amt", 0))["m"] if monthly else None,
        "best_month_amt": round(max((m.get("amt", 0) for m in monthly), default=0)),
    }

    # ---------------- warm doors: funders already reading ----------------
    by_funder = defaultdict(list)
    for r in sub:
        dom = (r.get("e") or "").split("@")[-1].lower()
        inst = (r.get("inst") or "").lower()
        for f in FUNDERS:
            if dom == f["domain"] or (len(f["name"]) > 6 and f["name"].lower() in inst):
                by_funder[f["name"]].append(r)
                break
    funders_out = []
    for f in FUNDERS:
        ppl = by_funder.get(f["name"], [])
        engaged = [r for r in ppl if (r.get("eopen") or 0) >= 50]
        funders_out.append({
            "name": f["name"], "focus": f["focus"], "fit": f["fit"], "note": f["note"],
            "lead": bool(f.get("lead")), "cat": f.get("cat"), "pursuit": bool(f.get("pursuit")),
            "current": bool(f.get("current")),
            "grantees": GRANTEES.get(f["name"]),
            "readers": len(ppl), "engaged": len(engaged),
            "donors": sum(1 for r in ppl if r.get("don")),
            "names": [r.get("n") for r in sorted(ppl, key=lambda r: -(r.get("eopen") or 0))
                      if r.get("n")][:4],
        })
    funders_out.sort(key=lambda f: (f["lead"], -f["engaged"], -f["readers"]))

    # ---------------- editorial fit: what VC can show funders ----------------
    y2 = [p for p in cat if (p.get("published_date") or "") >= f"{TODAY.year-1}-01-01"]
    tc = Counter()
    for p in y2:
        for t in (p.get("topics") or []):
            tc[t] += 1
    beats = tc.most_common(12)

    # ---------------- individual prospect tiers ----------------
    def eng(r): return (r.get("eopen") or 0)

    advisors = [person_row(r, "Formal advisor; no recorded gift")
                for r in sub if "VC advisor" in (r.get("types") or []) and not r.get("don")]
    advisors.sort(key=lambda x: -x["eopen"])

    upgrade = [person_row(r, "Already gives at level; reads consistently")
               for r in sub if (r.get("damt") or 0) >= 500 and eng(r) >= 40]
    upgrade.sort(key=lambda x: -x["damt"])

    second = [person_row(r, "One gift, still highly engaged — the second ask")
              for r in sub if r.get("don") and (r.get("dcnt") or 0) == 1
              and 100 <= (r.get("damt") or 0) < 500 and eng(r) >= 50]
    second.sort(key=lambda x: (-x["eopen"], -x["damt"]))

    notables = [person_row(r, "Public profile; never asked")
                for r in sub if r.get("wiki") and not r.get("don") and eng(r) >= 50]
    notables.sort(key=lambda x: -x["eopen"])

    fstaff = [person_row(r, "Foundation leadership — institutional door, do NOT ask for a personal check")
              for r in sub if "foundation leadership" in (r.get("types") or [])]
    fstaff.sort(key=lambda x: -x["eopen"])

    # principals: their own firm in their email domain (employer inference tier B)
    by_email = {r.get("e"): r for r in sub}
    principals = []
    for row in infer:
        if row.get("conf") != "B":
            continue
        r = by_email.get(row.get("email"))
        if r and eng(r) >= 50 and not r.get("don"):
            pr = person_row(r, "Own-name firm or practice — likely a principal")
            pr["inst"] = pr["inst"] or (row.get("employer") or "")
            principals.append(pr)
    principals.sort(key=lambda x: -x["eopen"])

    event = load_event(people)

    lybunt = [person_row(r, "Gave last year, nothing this year")
              for r in donors if (r.get("dlast") or "") < f"{TODAY.year}-01"
              and not r.get("unsub")]
    lybunt.sort(key=lambda x: -x["damt"])


    # ---------------- what we can show funders: computed, not typed ----------
    mc = growth.get("mailchimp", {}) or {}
    gt = growth.get("ghost_traffic", {}) or {}
    m26 = [r for r in (mc.get("monthly_campaigns") or []) if r.get("month", "") >= f"{TODAY.year}-01" and r.get("open_pct")]
    def _avg(rows, k):
        v = [r[k] for r in rows if r.get(k) is not None]
        return round(st.mean(v), 1) if v else None
    ts = [t for t in (gt.get("traffic_series") or []) if not t.get("partial")]
    half = len(ts) // 2
    tgrow = None
    if half >= 4:
        a = st.mean([t["visitors"] for t in ts[:half]]); b = st.mean([t["visitors"] for t in ts[half:]])
        tgrow = round((b - a) / a * 100)
    dom = lambda r: (r.get("e") or "").split("@")[-1].lower()
    gov = [r for r in sub if dom(r).endswith(".gov")]
    edu = [r for r in sub if dom(r).endswith(".edu")]
    org = [r for r in sub if dom(r).endswith(".org")]
    core = sum(1 for r in sub if (r.get("eopen") or 0) >= 50)
    mentions = growth.get("news_mentions") or []
    m_outlets = len({(x.get("domain") or x.get("source") or "") for x in mentions if not x.get("own_post")})
    authors = {a for p in cat for a in (p.get("authors") or [])}
    # v2: a showcase, not a stat dump. Tiles for the big numbers, receipts with
    # verified links, real press citations, and the named policy products.
    yoy_now = None; yoy_prev = None
    _cum = {r["month"]: r.get("cum_subs") for r in (mc.get("monthly_signups") or [])}
    if _cum:
        _mo = max(_cum); _prev = f"{int(_mo[:4])-1}{_mo[4:]}"
        yoy_now, yoy_prev = _cum.get(_mo), _cum.get(_prev)
    yoy_pct = round(100*(yoy_now-yoy_prev)/yoy_prev) if (yoy_now and yoy_prev) else None
    press = [x for x in mentions if not x.get("own_post")]
    p_out = Counter(x.get("domain") or "" for x in press)
    p_first = min((x.get("published_iso") or "9999" for x in press), default="")[:7]
    TOP_OUT = {"nytimes.com":"The New York Times","gothamist.com":"Gothamist","politico.com":"Politico",
               "thecity.nyc":"THE CITY","nydailynews.com":"Daily News","ny1.com":"NY1","wnyc.org":"WNYC",
               "nymag.com":"New York Magazine","cityandstateny.com":"City & State","nypost.com":"New York Post",
               "therealdeal.com":"The Real Deal","citylimits.org":"City Limits","crainsnewyork.com":"Crain's"}
    samples, seen_out = [], set()
    for x in sorted(press, key=lambda x: x.get("published_iso") or "", reverse=True):
        d0 = x.get("domain")
        _t = (x.get("title") or "").strip()
        # the tracker sometimes yields junk titles like "- The New York Times"
        if len(_t) < 16 or _t.startswith("-"):
            continue
        if d0 in TOP_OUT and d0 not in seen_out:
            samples.append({"outlet": TOP_OUT[d0], "date": (x.get("published_iso") or "")[:10],
                            "title": x.get("title") or "", "url": x.get("url") or ""})
            seen_out.add(d0)
        if len(samples) >= 5: break
    funder_facts = {
      "asof": TODAY.isoformat(),
      "tiles": [
        {"n": f"{mc.get('total_subscribers', len(sub)):,}", "l": "Newsletter subscribers",
         "s": (f"up {yoy_pct}% year over year" if yoy_pct else "Mailchimp, current")},
        {"n": f"{len(press):,}", "l": "Press citations",
         "s": f"across {sum(1 for v in p_out.values() if v)} outlets since {p_first} (whitelist-tracked)"},
        {"n": f"{p_out.get('nytimes.com', 0)}", "l": "New York Times citations",
         "s": "the most-cited outlet in the tracker"},
        {"n": f"{gt.get('visitors_30d') or 0:,}", "l": "Site visitors, last 30 days",
         "s": (f"weekly visitors up {tgrow}% across {TODAY.year}" if tgrow else "Ghost analytics")},
        {"n": f"{len(gov)+len(edu):,}", "l": "Government + university subscribers",
         "s": f"{sum(1 for r in gov if 'nyc.gov' in dom(r)):,} on nyc.gov — City Hall, the courts, both DAs"},
        {"n": f"{len(cat):,}", "l": "Pieces published",
         "s": f"by {len(authors):,} contributors since 2021"},
      ],
      "receipts": [
        {"head": "Zohran Mamdani", "claim": "As a candidate, sat with Vital City for an hour on public safety",
         "note": "after calling himself 'quite taken' by the annual crime analysis — he is now the mayor",
         "links": [{"t":"the interview","u":"https://www.vitalcitynyc.org/zohran-mamdani-talks-public-safety/"},
                   {"t":"'quite taken' (NY Editorial Board)","u":"https://nyeditorialboard.substack.com/p/zohran-mamdani-interview-transcript"},
                   {"t":"the crime analysis","u":"https://www.vitalcitynyc.org/crime-in-new-york-city-trends-statistics/"}]},
        {"head": "Rikers Island", "claim": "Made the case for a federal receiver; a judge has since appointed one", "note": "",
         "links": [{"t":"the case","u":"https://www.vitalcitynyc.org/the-rikers-receivership-risk-and-opportunity/"},
                   {"t":"the order (THE CITY)","u":"https://www.thecity.nyc/2025/05/13/federal-judge-rikers-oversight-remediation-manager/"},
                   {"t":"the receiver's powers (Queens Eagle)","u":"https://queenseagle.com/all/2025/12/22/judge-details-sweeping-powers-of-receiver-set-to-run-rikers"}]},
        {"head": "Subway safety", "claim": "Recommendations drove New York Times coverage",
         "note": "and were adopted in part by the governor and the MTA",
         "links": [{"t":"the recommendations","u":"https://www.vitalcitynyc.org/what-to-do-about-subway-safety-nyc-policy-recommendations/"},
                   {"t":"NYT, March 2025","u":"https://www.nytimes.com/2025/03/14/nyregion/subway-crime-nyc.html"},
                   {"t":"NYT, September 2025","u":"https://www.nytimes.com/2025/09/10/nyregion/nyc-subway-hochul-white-house.html"},
                   {"t":"the governor's program","u":"https://www.governor.ny.gov/news/safer-subways-one-year-after-deploying-additional-law-enforcement-and-safety-measures-governor"}]},
        {"head": "Permitting", "claim": "Days after publishing fixes for the permitting mess, City Hall released a report echoing them", "note": "",
         "links": [{"t":"the 8 fixes","u":"https://www.vitalcitynyc.org/nyc-housing-permits-fast-track-construction-mamdani/"}]},
        {"head": "Crime data", "claim": "When reporters dig into the city's numbers, it is often Vital City's analyses they build on",
         "note": f"{p_out.get('gothamist.com',0)} Gothamist and {p_out.get('politico.com',0)} Politico citations tracked",
         "links": [{"t":"the annual analysis","u":"https://www.vitalcitynyc.org/crime-in-new-york-city-trends-statistics/"},
                   {"t":"why the numbers change","u":"https://www.vitalcitynyc.org/real-crime-numbers-nyc-nypd/"}]},
      ],
      "press": {"total": len(press), "outlets": sum(1 for v in p_out.values() if v), "since": p_first,
                "y2026": sum(1 for x in press if (x.get("published_iso") or "").startswith(str(TODAY.year))),
                "permonth": round(sum(1 for x in press if (x.get("published_iso") or "").startswith(str(TODAY.year))) / max(1, TODAY.month - 0.5), 1),
                "top": [{"outlet": TOP_OUT[k], "n": v} for k, v in p_out.most_common(30) if k in TOP_OUT][:8],
                "samples": samples},
      "products": [
        {"name": "Just Fix It", "desc": "A standing series pressing specific, doable fixes on City Hall — permitting, government efficiency, a 100-day scorecard.",
         "count": 5, "links": [{"t":"8 permitting fixes","u":"https://www.vitalcitynyc.org/nyc-housing-permits-fast-track-construction-mamdani/"},
                               {"t":"Mamdani's first 100 days","u":"https://www.vitalcitynyc.org/mamdani-first-100-days-scorecard-nyc/"}]},
        {"name": "What To Do (and Not To Do)", "desc": "Policy playbooks that separate what works from what merely sounds tough — subway safety, people in crisis.",
         "count": 2, "links": [{"t":"subway safety","u":"https://www.vitalcitynyc.org/what-to-do-about-subway-safety-nyc-policy-recommendations/"},
                               {"t":"people in crisis","u":"https://www.vitalcitynyc.org/what-to-do-about-people-in-crisis-on-streets-and-subways/"}]},
        {"name": "Rubber Meets Road", "desc": "An eight-piece issue on execution — how the city actually gets things done, with an interactive map of where darkness and crime overlap.",
         "count": 8, "links": [{"t":"how to get it done","u":"https://www.vitalcitynyc.org/rubber-meets-road-lighting-policy-details/"},
                               {"t":"the darkness-and-crime map","u":"https://www.vitalcitynyc.org/rubber-meets-road-lighting-satellite-crime-map/"}]},
      ],
      "engagement": [
        {"label": "Click-to-open rate", "value": f"{_avg(m26,'ctor_pct')}%", "note": "cross-industry benchmark 5.3-8.6% — the metric Apple's auto-opens cannot inflate"},
        {"label": "Click rate", "value": f"{_avg(m26,'click_pct')}%", "note": "all-industry average 2.27%; media band 3-6%"},
        {"label": "Open rate", "value": f"{_avg(m26,'open_pct')}%", "note": "30-40% is 'solid' for media; inflated industry-wide by Apple Mail"},
      ],
      "audience": [
        {"label": "Email list, full size", "value": f"{mc.get('total_subscribers', len(sub)):,}",
         "note": (f"up {yoy_pct}% year over year" if yoy_pct else "Mailchimp, current")},
        {"label": "Nonprofit addresses", "value": f"{len(org):,}", "note": "Vera, Osborne, Arnold Ventures, CBC, Court Innovation among the densest"},
        {"label": "Staff at grantmaking foundations", "value": "Arnold Ventures, Bloomberg Philanthropies, Robin Hood, Guggenheim, Revson, Tiger, Clark, MacArthur", "note": "counts and names in the warm-doors table"},
        {"label": "Wikipedia-notable subscribers", "value": f"{sum(1 for r in sub if r.get('wiki')):,}", "note": "conservative floor — matched, not estimated"},
      ],
      "influentials": [
        {"n": name, "who": who,
         "npieces": len([p for p in cat if name in (p.get("authors") or []) or p.get("primary_author") == name]),
         "pieces": [{"t": p["title"], "u": p["url"]} for p in sorted(
             [p for p in cat if name in (p.get("authors") or []) or p.get("primary_author") == name],
             key=lambda p: p.get("published_date") or "", reverse=True)[:2]]}
        for name, who in INFLUENTIALS
        if any(name in (p.get("authors") or []) or p.get("primary_author") == name for p in cat)
      ],
      "longview": {
        # list size at each year end (current year = latest month available)
        "list": [{"y": y, "n": v} for y, v in sorted({
            m[:4]: c for m, c in sorted(_cum.items()) if c
        }.items())],
        "pieces": [{"y": y, "n": n} for y, n in sorted(Counter(
            (p.get("published_date") or "")[:4] for p in cat
            if (p.get("published_date") or "")[:4].isdigit()).items())],
      },
      "benchmark_note": ("Impact items are Vital City's own accounting, from the draft positioning language (Aug 2026) — "
                         "reuse the wording, but keep the causal framing as stated. "
                         "Press counts come from the growth dashboard's whitelist of ~25 outlets, so they undercount. "
                         "Benchmarks: Letterhead/ClickMinded/Brevo 2026 email compilations; publisher traffic decline "
                         "from Chartbeat data via Press Gazette. Third-party aggregates — bands, not lines. "
                         "Giving figures are deliberately absent here: audience evidence only, and internal gift data is Donorbox-only."),
    }

    out = {
        "generated_at": TODAY.isoformat(),
        "topline": topline,
        "funders": funders_out,
        "beats": beats,
        "funder_facts": funder_facts,
        "readiness": {
            "sponsor": "Fund for the City of New York (FCNY)",
            "ein": "13-2612524", "status": "501(c)(3) via fiscal sponsorship",
            "note": "Grant applications and checks route through the fiscal sponsor. "
                    "Confirm current sponsorship terms with FCNY before quoting them to a funder."},
        "tiers": {
            "advisors": advisors, "upgrade": upgrade, "second": second,
            "notables": notables, "principals": principals,
            "foundation_staff": fstaff, "lybunt": lybunt,
            "party": (event or {}).get("attended", [])},
        "event": event,
        "counts": {"subscribers": len(sub), "donors": len(donors)},
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))

    # ---------------- encrypt, same blob format as the other tools ----------
    passphrase = os.environ.get("VC_NETWORK_PASS") or \
        (ROOT / "private" / ".netpass").read_text().strip()
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=ITERS).derive(passphrase.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(out).encode(), None)
    ENC.parent.mkdir(exist_ok=True)
    ENC.write_text(json.dumps({
        "v": 1, "kdf": "PBKDF2-SHA256", "iters": ITERS,
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "ct": base64.b64encode(ct).decode()}))

    print(f"prospects: {len(sub):,} subscribers, {len(donors)} donors -> "
          f"advisors {len(advisors)}, upgrade {len(upgrade)}, second-gift {len(second)}, "
          f"notables {len(notables)}, principals {len(principals)}, "
          f"foundation staff {len(fstaff)}, lapsed {len(lybunt)}")
    print(f"wrote {OUT.name} and {ENC}")


if __name__ == "__main__":
    main()
