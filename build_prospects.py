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
FUNDERS = [
 {"name":"Arnold Ventures","domain":"arnoldventures.org",
  "focus":"Criminal justice policy, evidence-based government",
  "fit":["criminal justice","data journalism"],
  "note":"John Arnold has a Vital City byline and a 99% open rate. The single warmest institutional door in the file."},
 {"name":"Harry Frank Guggenheim Foundation","domain":"hfg.org",
  "focus":"Research on violence and its reduction",
  "fit":["criminal justice","gun violence"],
  "note":"Two staff are donors already — the only funder with staff who have personally given."},
 {"name":"Revson Foundation","domain":"revsonfoundation.org",
  "focus":"New York City civic life, journalism, urban affairs",
  "fit":["nyc civic","journalism"],
  "note":"Historic funder of NYC journalism. Julie Sandorf led its local-news grantmaking."},
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
 {"name":"Tiger Foundation","domain":"tigerfoundation.org",
  "focus":"Breaking the cycle of poverty in New York City",
  "fit":["nyc civic","education"],
  "note":"Charles Buice (president) is an engaged reader."},
 {"name":"Clark Foundation","domain":"clarkfoundation.org",
  "focus":"New York City nonprofits and opportunity",
  "fit":["nyc civic"],
  "note":"Doug Bauer (executive director) is a reader."},
 {"name":"Fund for the City of New York","domain":"fcny.org",
  "focus":"NYC government performance and civic innovation",
  "fit":["city government"],
  "note":"Already Vital City's fiscal sponsor — the relationship exists by construction."},
 {"name":"Tow Foundation","domain":"towfoundation.org",
  "focus":"Juvenile and criminal justice; investigative journalism",
  "fit":["criminal justice","journalism"],
  "note":"One subscriber on file, unengaged. Focus fit is strong; the door is cold."},
 # ---- leads (not currently in the reader network in any strength) ----
 {"name":"Press Forward","domain":"pressforward.news","lead":True,
  "focus":"National coalition funding local news (>$500M pooled)",
  "fit":["journalism","nyc civic"],
  "note":"The largest pool of local-journalism money in the country right now. Chapters + open calls; eligibility via fiscal sponsor needs checking."},
 {"name":"Knight Foundation","domain":"knightfoundation.org","lead":True,
  "focus":"Journalism, informed communities",
  "fit":["journalism","data journalism"],
  "note":"The reference funder for journalism innovation. No meaningful reader presence on file."},
 {"name":"American Journalism Project","domain":"theajp.org","lead":True,
  "focus":"Venture philanthropy for nonprofit local news",
  "fit":["journalism"],
  "note":"Funds operating capacity, not coverage — relevant to the growth side of the org."},
 {"name":"Democracy Fund","domain":"democracyfund.org","lead":True,
  "focus":"Local news ecosystems, civic engagement",
  "fit":["journalism","nyc civic"],
  "note":"Ecosystem grants often route through intermediaries; worth mapping which."},
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
            "lead": bool(f.get("lead")),
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

    lybunt = [person_row(r, "Gave last year, nothing this year")
              for r in donors if (r.get("dlast") or "") < f"{TODAY.year}-01"
              and not r.get("unsub")]
    lybunt.sort(key=lambda x: -x["damt"])

    out = {
        "generated_at": TODAY.isoformat(),
        "topline": topline,
        "funders": funders_out,
        "beats": beats,
        "readiness": {
            "sponsor": "Fund for the City of New York (FCNY)",
            "ein": "13-2612524", "status": "501(c)(3) via fiscal sponsorship",
            "note": "Grant applications and checks route through the fiscal sponsor. "
                    "Confirm current sponsorship terms with FCNY before quoting them to a funder."},
        "tiers": {
            "advisors": advisors, "upgrade": upgrade, "second": second,
            "notables": notables, "principals": principals,
            "foundation_staff": fstaff, "lybunt": lybunt},
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
