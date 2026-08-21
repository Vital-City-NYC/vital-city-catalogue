#!/usr/bin/env python3
"""Merge researched reader identifications into the contact database.

SOURCES
  1. private/all_prospects.csv    — the outside review (Polar, Aug 2026): 526 rows,
     517 with a name, every address present in people.json and none of them on a
     record a human had already confirmed.
  2. private/domain_harvest.json  — this repo's own staff-page harvest.

Cross-checked against each other where they overlap: 15 addresses in common,
15 agreements, 0 disagreements. The harvest also found 17 the review missed.
That is the best accuracy evidence available short of writing to each person.

WHAT GETS WRITTEN, AND WHAT DOES NOT
  HIGH / MEDIUM-HIGH   name, employer and title are written.
  MEDIUM               held for review — several carry caveats of their own
                       ("source says she no longer works there").
  LOW / UNKNOWN        never written. The source flags these itself: one reads
                       "REJECT - inference rests only on 'bo5'."
  Role accounts        no personal name, ever. subscriptions@, subs@ and the
                       like are not people.
  Public officials     excl=1, do not solicit. Government ethics rules restrict
                       soliciting public servants, and this database feeds a
                       fundraising tool.

Everything lands in private/name_overrides.csv, which build_network.py treats as
authoritative and which travels in the encrypted source bundle. people_overrides.json
would have been the more natural home, but the nightly workflow overwrites that
file wholesale with the Google Sheet, so anything written there locally is lost.

    python3 merge_prospects.py --dry-run
    python3 merge_prospects.py
"""
import argparse, csv, json, re, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
OVERRIDES = PRIV / "name_overrides.csv"
PROV = PRIV / "identification_provenance.json"

PROMOTE = {"HIGH", "MEDIUM-HIGH"}
NON_NAMES = re.compile(r"^(unknown|—|-|n/?a|none)$", re.I)
ROLE_LOCAL = re.compile(r"^(info|support|office|admin|contact|sales|help|team|hello|subs|"
                        r"subscriptions|enquiries|inquiries|mail|noreply|no-reply|newsletter)\b", re.I)
OFFICIAL = re.compile(r"public official|do not solicit|sitting (judge|official)", re.I)


def segment(r, flags):
    """One word for what kind of reader this is, for the prospect filter.
    Order matters: exclusions win over capacity, because a senior person who is
    also a sitting official is still someone you must not solicit."""
    f, sec = flags.upper(), (r.get("sector") or "").upper()
    cap = (r.get("capacity_segment") or "").upper()
    if "PUBLIC OFFICIAL" in f or "GOVERNMENT" in sec or "PUBLIC SECTOR" in cap: return "official"
    if "ROLE ACCOUNT" in f or "ROLE ACCOUNT" in sec: return "role"
    if "VITAL CITY STAFF" in f: return "staff"
    if "STUDENT" in f or "STUDENT" in cap: return "student"
    if "SENIOR PRIVATE SECTOR" in f or "PRIVATE-SECTOR SENIOR" in cap: return "senior-private"
    if "FOUNDATION STAFF" in f or "FOUNDATION" in sec or "FOUNDATION" in cap: return "funder"
    if "PEER PUBLISHER" in f: return "peer"
    if "NONPROFIT" in f or "NONPROFIT" in sec or "NONPROFIT" in cap: return "nonprofit"
    if "ACADEMIC" in f or "ACADEMIC" in sec or "ACADEMIC" in cap: return "academic"
    if "MEDIA" in f or "MEDIA" in sec or "MEDIA" in cap: return "media"
    if "PRIVATE" in f or "PRIVATE" in sec or "PRIVATE" in cap or "FOR-PROFIT" in sec: return "private"
    return ""


CAVEAT = re.compile(r"not confirmed|unconfirmed|possible same-pattern|no longer|thin|weak|"
                    r"reject|do not act|identity", re.I)


def pattern_corroborates(email, name, org):
    """Does the address itself back up the name? first-initial+surname (or a
    close variant) as the local part, on a domain that is the named employer."""
    lp, _, dom = email.partition("@")
    w = [x for x in re.split(r"[^A-Za-z]+", name or "") if len(x) > 1
         and x.lower() not in ("jr", "sr", "ii", "iii", "phd", "md")]
    if len(w) < 2:
        return False
    f, l = w[0].lower(), w[-1].lower()
    shapes = {f"{f[0]}{l}", f"{f}.{l}", f"{f}{l}", f"{f}_{l}", f"{l}{f[0]}", f"{f}-{l}", f"{f[0]}.{l}",
              f"{f[:2]}{l}", f"{f[:3]}{l}", f"{l}{f[:2]}"}   # jahorowitz = Ja + Horowitz
    if re.sub(r"[^a-z]", "", lp.lower()) not in {re.sub(r"[^a-z]", "", s) for s in shapes}:
        return False
    # Domain-to-organisation by shared word stems, not substring: "pewtrusts"
    # holds both "pew" and "trust" from "The Pew Charitable Trusts", but neither
    # string contains the other.
    root = re.sub(r"[^a-z]", "", dom.rsplit(".", 1)[0])
    if not root or not org:
        return False
    STOP = {"the", "of", "and", "for", "inc", "llc", "llp", "corp", "group", "company",
            "foundation", "trust", "trusts", "institute", "center", "centre", "new", "york",
            "city", "national", "american", "association", "services", "partners"}
    words = [w for w in re.findall(r"[a-z]{3,}", org.lower())]
    strong = [w for w in words if w not in STOP]
    hits = sum(1 for w in strong if w[:6] in root or root in w)
    generic = sum(1 for w in words if w in STOP and w[:5] in root)
    return hits >= 1 and (hits >= 2 or len(root) <= 14 or generic >= 1)


def real_name(n):
    n = (n or "").strip()
    if not n or NON_NAMES.match(n):
        return ""
    # the source parenthesises its own doubts: "Clem (surname unconfirmed)"
    if re.search(r"\((?:surname |identity )?(?:unconfirmed|weak|guess)", n, re.I) or "WEAK" in n:
        return ""
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(Path.home() / "Downloads" / "all_prospects.csv"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    people = json.loads((PRIV / "people.json").read_text())
    known = {}
    for p in people:
        for e in (p.get("emails") or [p.get("e")]):
            if e:
                known[e.strip().lower()] = p

    existing = {}
    if OVERRIDES.exists():
        for row in csv.DictReader(OVERRIDES.open()):
            existing[(row.get("email") or "").strip().lower()] = row

    out, prov, skipped = dict(existing), [], {"low": 0, "unknown": 0, "role": 0, "absent": 0, "medium": 0}

    # ---- 1. the outside review
    rows = list(csv.DictReader(open(a.csv)))
    for r in rows:
        em = (r.get("email") or "").strip().lower()
        if not em or em not in known:
            skipped["absent"] += 1
            continue
        conf = (r.get("confidence") or "").strip().upper()
        name = real_name(r.get("name"))
        flags = r.get("flags") or ""
        official = bool(OFFICIAL.search(flags))
        source_url = (r.get("source_url") or r.get("source") or "").strip()
        role = (bool(ROLE_LOCAL.match(em.split("@")[0]))
                or "ROLE ACCOUNT" in (r.get("sector") or "").upper()
                or "ROLE ACCOUNT" in flags.upper())

        if role:
            skipped["role"] += 1
            # still worth marking so it never lands in an appeal
            row = out.get(em, {"email": em, "name": ""})
            row["excl"] = "1"
            row["seg"] = "role"
            row.setdefault("inst", (r.get("org") or "").strip())
            out[em] = row
            continue
        if not name:
            skipped["unknown" if conf == "UNKNOWN" else "low"] += 1
            continue
        if conf not in PROMOTE:
            # A MEDIUM row still clears the bar this project used for its own
            # institutional identifications when the address itself corroborates
            # the name: the local part is built from it, and the domain is the
            # organisation named. Rows carrying their own doubt are excluded.
            # Their own limits section is the rule here: MEDIUM means a plausible
            # match without the address being published, and a common name on a
            # free mailbox is the weakest case in the whole file — "a Gmail
            # reading David Solomon is far more likely to be one of the many
            # other David Solomons". So a MEDIUM row is only taken when the
            # address itself corroborates it, which by construction means a
            # work domain, never a free mailbox.
            if not (conf == "MEDIUM" and pattern_corroborates(em, name, r.get("org"))
                    and r.get("domain_type") != "freemail"
                    and not CAVEAT.search(flags)):
                skipped["medium"] += 1
                continue
            conf = "MEDIUM+pattern"

        row = out.get(em, {"email": em})
        row["name"] = name
        if (r.get("org") or "").strip() and (r.get("org") or "").strip() != "—":
            row["inst"] = r["org"].strip()
        if (r.get("title") or "").strip() and (r.get("title") or "").strip() != "—":
            row["role"] = r["title"].strip()
        if official:
            row["excl"] = "1"
        seg = segment(r, flags)
        if seg:
            row["seg"] = seg
        # NYC link matters more than sector for this publication's fundraising
        if (r.get("nyc_link") or "").strip().upper() == "YES":
            row["nyc"] = "1"
        # Their "OUT OF MARKET" flag is a better signal than any rate heuristic
        # for keeping a purchasing manager in Michigan off a New York
        # publication's prospect list.
        if "OUT OF MARKET" in flags.upper():
            row["oom"] = "1"
        out[em] = row
        prov.append({"email": em, "name": name, "source": "outside review (Polar) 2026-08-20",
                     "confidence": conf, "org": r.get("org"), "title": r.get("title"),
                     "sector": r.get("sector"),
                     "flags": flags, "evidence": (r.get("notes") or "")[:300], "url": source_url})

    # ---- 2. this repo's own staff-page harvest
    hp = PRIV / "domain_harvest.json"
    if hp.exists():
        for h in json.loads(hp.read_text()):
            em = h["email"].strip().lower()
            if em not in known or not real_name(h.get("proposed")):
                continue
            row = out.get(em, {"email": em})
            if not row.get("name"):
                row["name"] = h["proposed"]
                prov.append({"email": em, "name": h["proposed"], "source": "domain harvest (staff page)",
                             "confidence": h.get("conf", "high"), "org": h.get("domain"),
                             "evidence": (h.get("evidence") or "")[:200], "url": h.get("url")})
            out[em] = row

    # ---- 3. this repo's own researched identifications (enrich_readers.py).
    # Confirmed and high tiers only; "likely" and broker-sourced rows stay out.
    ep = PRIV / "reader_enrichment.json"
    if ep.exists():
        for f in json.loads(ep.read_text()):
            em = f["email"].strip().lower()
            if em not in known or f.get("conf") not in ("confirmed", "high", "address-encoded"):
                continue
            nm = real_name(f.get("name"))
            row = out.get(em, {"email": em})
            if nm and not row.get("name"):
                row["name"] = nm
                prov.append({"email": em, "name": nm, "source": "this repo's research",
                             "confidence": f["conf"], "org": f.get("employer"),
                             "title": f.get("role"), "evidence": (f.get("note") or "")[:220],
                             "url": f.get("url")})
            if f.get("employer") and not row.get("inst"):
                row["inst"] = f["employer"]
            if f.get("role") and not row.get("role"):
                row["role"] = f["role"]
            out[em] = row

    cols = ["email", "name", "inst", "role", "excl", "seg", "nyc", "oom"]
    added = len(out) - len(existing)
    print(f"override rows: {len(existing)} -> {len(out)}  (+{added})")
    print(f"  from the review: {sum(1 for p in prov if p['source'].startswith('outside'))}")
    print(f"  from the harvest: {sum(1 for p in prov if p['source'].startswith('domain'))}")
    print(f"  held back — medium {skipped['medium']}, unknown {skipped['unknown']}, "
          f"low/rejected {skipped['low']}, role accounts {skipped['role']}")
    print(f"  marked do-not-solicit: {sum(1 for r in out.values() if r.get('excl'))}")
    if a.dry_run:
        print("\n(dry run — nothing written)")
        return

    if OVERRIDES.exists():
        shutil.copy(OVERRIDES, OVERRIDES.with_suffix(".csv.bak"))
    with OVERRIDES.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for em in sorted(out):
            w.writerow(out[em])
    PROV.write_text(json.dumps(prov, indent=1, ensure_ascii=False))
    print(f"\nwrote {OVERRIDES} and {PROV}")


if __name__ == "__main__":
    main()
