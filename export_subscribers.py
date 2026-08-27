#!/usr/bin/env python3
"""Export every newsletter subscriber with their engagement level stated plainly.

The whole list, not just the engaged part, because the quiet majority is the
point of the file: knowing how many people never open is as useful as knowing
who reads every issue.

ENGAGEMENT LEVELS, and what they mean
  devoted    Mailchimp rating 4-5, or clicks 20%+ of sends
  engaged    clicks 10-19%
  reader     clicks at all, or opens 70%+
  skimmer    opens 50-69%
  light      opens 1-49%
  dormant    never recorded opening anything

READ THE RATES CORRECTLY
open_rate_pct and click_rate_pct are RATES and cap at 100. They are not counts.
Somebody at 62% clicks a link in nearly two of every three emails, which is
extraordinary; it does not mean 62 clicks.

TWO THINGS THAT WOULD OTHERWISE MISLEAD
  machine=1     a mail security gateway that opens and clicks everything to scan
                it, or a role mailbox. Their engagement is not a person's. Any
                ranking that ignores this column is partly measuring spam filters.
  rate_warning  open and click rates within a few points of each other. Usually
                a scanner, but sometimes a genuine reader with a tiny
                denominator — three sends, three opens, three clicks. Treat as
                unresolved rather than as fact.

Note on A/B sends: Mailchimp's parent campaign reports no per-member
opens for split tests, but the hidden child sends carry them; since
Aug 26 2026 the pipeline reads the children, so per-member activity is
complete again. Data refreshed before that date understates recent
activity for anyone whose only opens were on split-test sends.

    python3 export_subscribers.py
    python3 export_subscribers.py --include-unsubscribed
"""
import argparse, csv, json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"


def level(r):
    er, cl, op = r.get("erate") or 0, r.get("eclick") or 0, r.get("eopen") or 0
    if er >= 4 or cl >= 20: return "devoted"
    if cl >= 10: return "engaged"
    if cl > 0 or op >= 70: return "reader"
    if op >= 50: return "skimmer"
    if op > 0: return "light"
    return "dormant"


ORDER = ["devoted", "engaged", "reader", "skimmer", "light", "dormant"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-unsubscribed", action="store_true")
    ap.add_argument("--out", default=str(Path.home() / "Desktop" /
                                        "vital-city-newsletter-subscribers.csv"))
    a = ap.parse_args()
    people = json.loads((PRIV / "people.json").read_text())

    rows = []
    for r in people:
        if not r.get("mem"):                     # newsletter subscribers only
            continue
        if r.get("unsub") and not a.include_unsubscribed:
            continue
        email = (r.get("e") or "").strip()
        if not email:
            continue
        lv = level(r)
        rows.append({
            "engagement_level": lv,
            "email": email,
            "name": r.get("n") or "",
            "name_confirmed": "yes" if r.get("ns") == "given" else "no (guessed from the address)",
            "employer": r.get("inst") or "",
            "title": r.get("role") or "",
            "open_rate_pct": r.get("eopen") or 0,
            "click_rate_pct": r.get("eclick") or 0,
            "star_rating": r.get("erate") or 0,
            "subscribed_since": r.get("since") or "",
            "unsubscribed": 1 if r.get("unsub") else 0,
            "unsubscribed_date": r.get("udate") or "",
            "machine": 1 if r.get("gw") else 0,
            "machine_kind": {1: "security gateway", 2: "role mailbox"}.get(r.get("gw"), ""),
            "rate_warning": 1 if r.get("ratewarn") else 0,
            "segment": r.get("seg") or "",
            "nyc_link": 1 if r.get("nyc") else 0,
            "do_not_solicit": 1 if r.get("excl") else 0,
            "likely_prospect": 1 if (r.get("pros") or 0) >= 4 else 0,
            "prospect_reasons": r.get("prosw") or "",
            "donor": 1 if r.get("don") else 0,
            "donor_total": r.get("damt") or 0,
            "donor_gifts": r.get("dcnt") or 0,
            "last_gift": r.get("dlast") or "",
            "wrote_for_us": r.get("auth") or 0,
            "articles": r.get("arts") or 0,
            "notable_wikipedia": r.get("wiki") or 0,
            "domain": email.split("@")[-1].lower(),
        })

    rows.sort(key=lambda x: (ORDER.index(x["engagement_level"]),
                             -x["click_rate_pct"], -x["open_rate_pct"]))
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    c = Counter(r["engagement_level"] for r in rows)
    print(f"{len(rows):,} subscribers -> {a.out}\n")
    for k in ORDER:
        n = c.get(k, 0)
        print(f"  {k:<9} {n:>6,}  {n*100//max(1,len(rows)):>3}%")
    print(f"\n  named            {sum(1 for r in rows if r['name_confirmed']=='yes'):>6,}")
    print(f"  machines flagged {sum(1 for r in rows if r['machine']):>6,}")
    print(f"  rate warnings    {sum(1 for r in rows if r['rate_warning']):>6,}")
    print(f"  likely prospects {sum(1 for r in rows if r['likely_prospect']):>6,}")
    print(f"  do not solicit   {sum(1 for r in rows if r['do_not_solicit']):>6,}")


if __name__ == "__main__":
    main()
