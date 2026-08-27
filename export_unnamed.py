#!/usr/bin/env python3
"""Export the engaged readers whose identity is still unestablished, for research.

Built to hand to a research pass (Polar or otherwise), so it carries everything
useful and — importantly — everything already TRIED, so a second pass does not
burn effort re-finding nothing.

WHO IS IN
Subscribed, not a security gateway or role mailbox, and `ns != given` — meaning
nobody has ever confirmed the name; whatever is in the name field was guessed
off the email address. Ranked into tiers by engagement so a limited research
budget can start at the top.

  A  star rating 4-5, or clicks 20%+ of sends
  B  clicks 10-19%
  C  clicks at all, or opens 70%+
  D  opens 50-69%

WHAT THE COLUMNS ARE FOR
  local_part / domain     the research handles. local_part is what a name has
                          to be read out of when the address is a free mailbox.
  name_hint               this repo's best split of the local part, where the
                          first token is a first name the database already
                          knows. A hint, not a claim.
  domain_type             freemail | org | edu | gov | isp
  open_rate_pct           RATES, not counts — they cap at 100. A person opening
  click_rate_pct          62% of sends is extraordinary; it is not "62 opens".
  prior_attempt           what has already been tried on this address and what
  prior_note              came back. "polar:UNKNOWN" means an outside pass
                          searched it and found nothing defensible.

CAVEAT ON THE ENGAGEMENT FIGURES
Note on A/B sends: Mailchimp's parent campaign reports no per-member
opens for split tests, but the hidden child sends carry them; since
Aug 26 2026 the pipeline reads the children, so per-member activity is
complete again. Data refreshed before that date understates recent
activity for anyone whose only opens were on split-test sends.

    python3 export_unnamed.py                    # tiers A-C
    python3 export_unnamed.py --tiers ABCD       # everything
    python3 export_unnamed.py --freemail-only
"""
import argparse, csv, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"

FREEMAIL = re.compile(r"^(gmail|googlemail|yahoo|ymail|rocketmail|hotmail|outlook|live|msn|aol|"
                      r"icloud|me|mac|proton|protonmail|pm|gmx|mail|zoho|fastmail|hey|duck|"
                      r"juno|inbox|yandex)\.", re.I)
ISP = re.compile(r"(comcast|verizon|att\.net|sbcglobal|optonline|earthlink|rcn\.com|rr\.com|"
                 r"cox\.net|charter\.net|bellsouth|windstream|frontier|centurylink|idt\.net|"
                 r"pacbell|roadrunner|nyc\.rr)", re.I)


def tier(r):
    er, cl, op = r.get("erate") or 0, r.get("eclick") or 0, r.get("eopen") or 0
    if er >= 4 or cl >= 20: return "A"
    if cl >= 10: return "B"
    if cl > 0 or op >= 70: return "C"
    if op >= 50: return "D"
    return ""


def domain_type(dom):
    if FREEMAIL.match(dom): return "freemail"
    if ISP.search(dom): return "isp"
    if dom.endswith(".edu"): return "edu"
    if dom.endswith(".gov") or dom.endswith(".mil"): return "gov"
    return "org"


def name_hint(local, first_names):
    """Best split of the local part, only where the leading token is a first
    name the database already knows. Deliberately conservative: a wrong hint is
    worse than none, because a researcher will anchor on it."""
    s = re.sub(r"\d+$", "", re.sub(r"[._\-]+", " ", local.lower())).strip()
    if " " in s:
        w = s.split()
        if w[0] in first_names and len(w[-1]) > 2:
            return " ".join(x.capitalize() for x in w)
        return ""
    for i in range(2, len(s) - 1):
        a, b = s[:i], s[i:]
        if a in first_names and len(b) >= 3:
            return f"{a.capitalize()} {b.capitalize()}"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="ABC")
    ap.add_argument("--freemail-only", action="store_true")
    ap.add_argument("--out", default=str(Path.home() / "Desktop" /
                                        "vital-city-unnamed-engaged-readers.csv"))
    a = ap.parse_args()

    people = json.loads((PRIV / "people.json").read_text())
    first_names = {(r.get("n") or "").split()[0].lower() for r in people
                   if r.get("ns") == "given" and len((r.get("n") or "").split()) >= 2}

    # what has already been tried, so nobody repeats it
    prior = {}
    pf = PRIV / "all_prospects.csv"
    if pf.exists():
        for r in csv.DictReader(pf.open()):
            em = (r.get("email") or "").strip().lower()
            if em:
                prior[em] = ("polar:" + (r.get("confidence") or "?").strip().upper(),
                             " / ".join(x for x in [(r.get("name") or "").strip(),
                                                    (r.get("org") or "").strip(),
                                                    (r.get("flags") or "").strip()] if x and x != "—")[:300])
    ef = PRIV / "reader_enrichment.json"
    if ef.exists():
        for f in json.loads(ef.read_text()):
            em = f["email"].lower()
            if f.get("conf") in ("searched", "unresolved", "likely", "broker-only"):
                prior[em] = ("in-house:" + f["conf"], (f.get("note") or "")[:300])
    sf = PRIV / "reader_email_search.json"
    if sf.exists():
        for f in json.loads(sf.read_text()):
            em = (f.get("email") or "").lower()
            if em and not f.get("hits") and em not in prior:
                prior[em] = ("in-house:scholar-nil", "exact-address search of Google Scholar found nothing")

    rows = []
    for r in people:
        if r.get("unsub") or r.get("gw") or r.get("ns") == "given":
            continue
        t = tier(r)
        if t not in set(a.tiers):
            continue
        email = (r.get("e") or "").strip()
        if not email:
            continue
        local, _, dom = email.partition("@")
        dt = domain_type(dom.lower())
        if a.freemail_only and dt not in ("freemail", "isp"):
            continue
        pa, pn = prior.get(email.lower(), ("", ""))
        # A person's click rate sits well below their open rate. When the two are
        # nearly equal and high, it is almost always a security gateway clicking
        # every link it opens. The `gw` flag in the pipeline only catches the
        # blatant 95/85+ cases; this catches the rest so nobody researches a
        # spam filter.
        op_, cl_ = r.get("eopen") or 0, r.get("eclick") or 0
        scanner = 1 if (cl_ >= 40 and (op_ - cl_) <= 6) else 0
        rows.append({
            "tier": t, "email": email, "local_part": local, "domain": dom.lower(),
            "domain_type": dt,
            "current_name_guess": r.get("n") or "",
            "name_hint": name_hint(local, first_names),
            "employer_on_file": r.get("inst") or "",
            "open_rate_pct": r.get("eopen") or 0,
            "click_rate_pct": r.get("eclick") or 0,
            "star_rating": r.get("erate") or 0,
            "subscribed_since": r.get("since") or "",
            "ghost_member": 1 if r.get("mem") else 0,
            "donor": 1 if r.get("don") else 0,
            "donor_total": r.get("damt") or 0,
            "donor_gifts": r.get("dcnt") or 0,
            "last_gift": r.get("dlast") or "",
            "wrote_for_us": r.get("auth") or 0,
            "articles": r.get("arts") or 0,
            "wikipedia_notable": r.get("wiki") or 0,
            "press_mentions": r.get("press") or 0,
            "press_outlet": r.get("poutlet") or "",
            "topics": "; ".join(r.get("topics") or []),
            "types": "; ".join(r.get("types") or []),
            "other_addresses": "; ".join(e for e in (r.get("emails") or []) if e != email),
            "record_source": "; ".join(r.get("src") or []),
            "suspect_scanner": scanner,
            "prior_attempt": pa, "prior_note": pn,
        })

    order = {"A": 0, "B": 1, "C": 2, "D": 3}
    rows.sort(key=lambda x: (order[x["tier"]], -x["click_rate_pct"], -x["open_rate_pct"]))
    cols = list(rows[0].keys()) if rows else []
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print(f"{len(rows)} readers exported -> {a.out}")
    print("  by tier:  " + "  ".join(f"{k} {v}" for k, v in sorted(Counter(r['tier'] for r in rows).items())))
    print("  by domain:" + "  ".join(f"{k} {v}" for k, v in Counter(r['domain_type'] for r in rows).most_common()))
    print(f"  with a name hint from the address: {sum(1 for r in rows if r['name_hint'])}")
    print(f"  already searched and not found:    {sum(1 for r in rows if r['prior_attempt'])}")
    print(f"  donors among them:                 {sum(1 for r in rows if r['donor'])}")
    print(f"  suspected security gateways:       {sum(1 for r in rows if r['suspect_scanner'])} "
          f"(flagged, not removed — skip these in research)")


if __name__ == "__main__":
    main()
