#!/usr/bin/env python3
"""Infer employers for contacts where none is recorded — as a SEPARATE, labelled
guess file, never merged into the contact database.

WHY THIS IS A SIDECAR AND NOT AN UPDATE
An inference written into `inst` is indistinguishable from a fact a person told
us a week later. So everything here lands in private/employer_inferences.json
with its confidence and the evidence behind it, and people.json is never touched.
Promote a row into the real database only after a human confirms it.

CONFIDENCE TIERS — read these as what they are
  A  stated    Not an inference. The person's own contributor bio names the
               employer. Treat as fact.
  B  likely    Their surname is in their own email domain (alison@anthoinelaw.com),
               which usually means they own or lead the firm. Useful for
               fundraising: principals have capacity that salaried staff may not.
  C  possible  Corporate/institutional  domain -> organization name derived from the
               domain. Tells you WHERE, not WHAT they do. Never a capacity read.
  D  none      Personal email. No employer is recoverable. This is most people.

USAGE
    python3 infer_employers.py                # writes JSON + a review CSV
    python3 infer_employers.py --min-conf B   # only A and B
"""
import json, re, csv, argparse, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"

# Consumer mail, ISPs, privacy relays and feed-to-email bridges. Anything that
# matches is NOT an employer. Deliberately broad: a false "employer" of
# bigpond.com is worse than a blank, because a blank is honest.
CONSUMER = re.compile(r"""(gmail|yahoo|hotmail|outlook|live\.|msn|aol|icloud|me\.com|mac\.com|
 comcast|verizon|att\.net|sbcglobal|bellsouth|cox\.net|charter\.net|roadrunner|rr\.com|optonline|
 earthlink|mindspring|pacbell|rcn\.com|shaw\.ca|telus|rogers\.com|btinternet|t-online|web\.de|gmx|
 freenet|libero|wp\.pl|o2\.pl|yandex|mail\.ru|qq\.com|126\.com|163\.com|naver|daum|docomo|ezweb|
 softbank|nifty|ocn\.ne\.jp|protonmail|proton\.me|pm\.me|duck\.com|mozmail|simplelogin|anonaddy|
 fastmail|hey\.com|pobox|zoho|mail\.com|inbox\.|rocketmail|myyahoo|ymail|googlemail|juno\.com|
 netzero|frontier|windstream|centurylink|sympatico|videotron|blueyonder|virginmedia|sky\.com|
 orange\.fr|wanadoo|free\.fr|laposte|bluewin|bigpond|optimum\.net|knology|pipeline\.com|obox|
 mt-system|superluser|sent\.com|chorus\.net)""", re.I | re.X)
RELAY = re.compile(r"(kill-the-newsletter|readwise|feedb\.in|feedly|inoreader|ino\.to|mecoinbox|"
                   r"substack|beehiiv|omnivore|instapaper|dealerspike|webleads)", re.I)

# Domains whose organization name can't be read off the string.
ACRONYMISH = re.compile(r"^[a-z]{2,5}$")


def domain_of(email):
    return (email or "").split("@")[-1].lower().strip()


def org_from_domain(d):
    """Turn a domain into a readable organization name. Conservative: if the base
    is a short acronym we can't expand, we say so rather than inventing words."""
    base = d.split(".")[0]
    if ACRONYMISH.match(base):
        return base.upper()          # e.g. "HJRUSSELL" stays as-is, not "Hj Russell"
    # split camel/compound-ish domains on known joiners only
    words = re.sub(r"[-_]", " ", base)
    return words.title()


def name_tokens(n):
    return [t for t in re.findall(r"[a-z]+", (n or "").lower()) if len(t) > 3]


# Bios are written "is a <role> at <Organization>, where she..." — take the first
# organization that follows an at/of/for, stop at the first clause break. Anything
# we can't parse cleanly keeps employer=None and the raw bio as evidence, which is
# honest: a human reading the bio will do better than a fragile regex.
BIO_ORG = re.compile(
    r"\b(?:at|of|for|with)\s+(the\s+)?((?:[A-Z][\w&.'’-]*\s+){0,5}"
    r"(?:University|College|School|Institute|Foundation|Center|Centre|Museum|Library|"
    r"Department|Bureau|Office|Commission|Authority|Association|Society|Council|Fund|"
    r"Project|Initiative|Program|Partnership|Corporation|Company|Group|Firm|Partners|"
    r"Ventures|Capital|Institute|Lab|Laboratory|Press|Journal|Times|Post|Review|"
    r"Magazine|News|Network|Coalition|Alliance|Union|Trust|Hospital|Clinic|Academy|"
    r"LLP|LLC|Inc\.?)"
    # keep the trailing clause: "School of Professional Studies", "Center for an
    # Urban Future". Without this the name truncates at the keyword and reads as
    # a different institution than the one meant.
    r"(?:\s+(?:of|for|at)\s+(?:the\s+)?(?:[A-Z][\w&.'’-]*|an?\s+[A-Z][\w&.'’-]*)"
    r"(?:\s+[A-Z][\w&.'’-]*){0,3})?)")

# A bare keyword with no proper noun in front ("Trust", "the Center") names
# nothing. Reject rather than record a fragment that looks like an employer.
BARE = re.compile(r"^(the\s+)?(University|College|School|Institute|Foundation|Center|Centre|"
                  r"Department|Office|Fund|Trust|Group|Firm|Partners|Company|Program|Project|"
                  r"Council|Association|Society|Network|Lab|Press|News|Academy)$", re.I)


def org_from_bio(bio):
    m = BIO_ORG.search(bio or "")
    if not m:
        return None
    org = re.sub(r"\s+", " ", ((m.group(1) or "") + m.group(2))).strip(" ,.;")
    if BARE.match(org):
        return None
    return org if 3 < len(org) < 90 else None


def org_from_personal_domain(d, toks):
    """Split a vanity domain on the person's own name so anthoinelaw.com reads as
    'Anthoine Law', not 'Anthoinelaw'."""
    base = re.sub(r"[-_]", " ", d.split(".")[0])
    for t in sorted(toks, key=len, reverse=True):
        if t in base and base != t:
            i = base.index(t)
            base = (base[:i] + t.title() + " " + base[i + len(t):]).strip()
    return re.sub(r"\s+", " ", base).title().strip()


def infer(people, authors):
    out = []
    for r in people:
        if r.get("unsub") or not r.get("e"):
            continue
        if (r.get("inst") or "").strip():
            continue                                     # already known; leave alone
        e, n = r.get("e"), r.get("n") or ""
        d = domain_of(e)
        toks = name_tokens(n)

        # --- A. stated in their own contributor bio -----------------------
        bio = ((authors.get(r.get("aname") or n) or {}).get("bio") or "").strip()
        if bio:
            org = org_from_bio(bio)
            out.append({"email": e, "name": n, "conf": "A",
                        "basis": "named in their own contributor bio",
                        "employer": org, "evidence": bio[:240]})
            continue

        if not d or RELAY.search(d):
            continue
        if CONSUMER.search(d):
            continue                                     # tier D: nothing to say

        base = d.split(".")[0]
        # Guard against the circular case: many records had their NAME generated
        # from the email itself ("Aswoboda Gbateam"), so the domain trivially
        # "matches" the name and proves nothing. Reject when a whole name token
        # IS the domain base.
        circular = any(t == base for t in toks)

        # --- B. surname inside their own domain -> likely principal --------
        surname = toks[-1] if toks else ""
        if surname and not circular and surname in base and len(surname) > 3:
            # Could be their firm (anthoinelaw.com) or a personal site
            # (alessandrastanley.com). Both signal independence/seniority, but
            # they are not the same thing, so the label says both.
            out.append({"email": e, "name": n, "conf": "B",
                        "basis": "own-name domain — their own firm, or a personal site",
                        "employer": org_from_personal_domain(d, toks), "evidence": d})
            continue

        # --- C. institutional domain -> organization -----------------------
        kind = ("university" if d.endswith(".edu") or ".edu." in d else
                "government" if d.endswith(".gov") or ".gov." in d or d.endswith(".mil") else
                "nonprofit" if d.endswith(".org") else "company")
        out.append({"email": e, "name": n, "conf": "C",
                    "basis": f"{kind} email domain — indicates where, not what",
                    "employer": org_from_domain(d), "evidence": d})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-conf", default="C", choices=["A", "B", "C"])
    a = ap.parse_args()

    people = json.load(open(PRIV / "people.json"))
    authors = {x["name"]: x for x in json.load(open(ROOT / "data/authors.json"))}
    rows = infer(people, authors)
    keep = [r for r in rows if r["conf"] <= a.min_conf]

    live = [r for r in people if not r.get("unsub") and r.get("e")]
    blanks = [r for r in live if not (r.get("inst") or "").strip()]
    by = collections.Counter(r["conf"] for r in keep)

    print(f"live contacts ................. {len(live):,}")
    print(f"  employer already recorded ... {len(live)-len(blanks):,}")
    print(f"  blank ....................... {len(blanks):,}")
    print(f"\ninferred something for ........ {len(keep):,} "
          f"({100*len(keep)/max(1,len(blanks)):.0f}% of blanks)")
    for c, label in (("A", "stated in their own bio (fact, not a guess)"),
                     ("B", "likely principal of their own firm"),
                     ("C", "organization only, from domain")):
        if by[c]: print(f"    {c}  {by[c]:>5}   {label}")
    print(f"    D  {len(blanks)-len(keep):>5}   personal email — nothing recoverable")

    PRIV.mkdir(exist_ok=True)
    (PRIV / "employer_inferences.json").write_text(json.dumps(
        {"note": "GUESSES with confidence tiers. Not merged into people.json. "
                 "Confirm before treating any C-tier row as fact.",
         "counts": dict(by), "rows": keep}, indent=1))
    with open(PRIV / "employer_inferences.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["conf", "name", "email", "employer", "basis", "evidence"])
        w.writeheader()
        for r in sorted(keep, key=lambda r: (r["conf"], r["name"] or "")):
            w.writerow({k: r.get(k) or "" for k in w.fieldnames})
    print(f"\nwrote private/employer_inferences.json and .csv "
          f"(review the CSV; nothing was written to the contact database)")


if __name__ == "__main__":
    main()
