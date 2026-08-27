#!/usr/bin/env python3
"""data/catalogue_reach.json — which subjects earn readers and signups.

Joins the growth pull's per-article rollups to the catalogue's subject tags, so
the catalogue analysis can answer "what share of readers and newsletter signups
does each subject account for?" rather than only "how much do we publish about
it?" Reads private/growth.json (produced by growth_pull.py) and writes a small
public-shaped aggregate that encrypt_catalogue_analysis.py bundles.

Two honesty constraints are baked into the output and surfaced on the page:

1. WINDOW. Ghost's own page analytics begin 2026-03-01 and its per-signup
   attribution begins 2026-02-28. Google Analytics holds the earlier traffic but
   is not joined per-article here, so these shares describe 2026 and cannot be
   extended backwards. The window is written into the file, not assumed.

2. MULTI-TAGGING. A piece carries several subjects and its readers are credited
   to each, so shares sum above 100%. The alternative -- splitting a reader
   into fractions across a piece's tags -- would invent precision the tagging
   cannot support. `share_basis` records which denominator was used.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GROWTH = ROOT / "private" / "growth.json"
# private/, never data/: data/ is served publicly, and these are audience
# and conversion figures. They reach the page only inside the encrypted
# bundle built by encrypt_catalogue_analysis.py.
OUT = ROOT / "private" / "catalogue_reach.json"


def main():
    if not GROWTH.exists():
        sys.exit("private/growth.json missing — run growth_pull.py first")
    g = json.loads(GROWTH.read_text())
    gt = g.get("ghost_traffic") or {}
    sa = g.get("ghost_signup_attribution") or {}

    traffic = gt.get("traffic_by_topic_since") or gt.get("traffic_by_topic_30d")
    signups = sa.get("by_topic")
    if not traffic and not signups:
        sys.exit("no topic rollups in growth.json — rerun growth_pull.py "
                 "(it computes traffic_by_topic_* and signup by_topic)")

    # Volume side, straight from the catalogue: how much we PUBLISH per subject,
    # which is what makes the reach numbers interpretable. A subject can be 3%
    # of the catalogue and 30% of the readers, and that gap is the finding.
    cat = json.loads((ROOT / "data" / "catalogue.json").read_text())
    items = cat if isinstance(cat, list) else (cat.get("items") or cat.get("posts") or [])
    skip = set()
    try:
        subj = json.loads((ROOT / "data" / "subject_analysis.json").read_text())
        for key in ("rubrics_listed", "meta_listed"):
            skip |= {str(x).lower().strip() for x in (subj.get(key) or [])}
    except Exception:
        pass
    pieces = {}
    for c in items:
        for t in (c.get("topics") or []):
            if isinstance(t, str) and t.lower().strip() not in skip:
                pieces[t] = pieces.get(t, 0) + 1
    n_pieces = len(items)

    out = {
        "generated_from": "private/growth.json",
        "window": {
            "traffic_start": gt.get("history_start"),
            "signups_start": sa.get("coverage_start"),
            "note": ("Ghost analytics begin 2026-03-01 and signup attribution "
                     "2026-02-28. Earlier traffic lives in Google Analytics and is "
                     "not joined per article, so these shares are 2026 only."),
        },
        "share_basis": ("Percentages are of the visits/signups that could be matched "
                        "to a tagged piece. A piece carries several subjects and is "
                        "credited to each, so shares sum above 100%."),
        "catalogue_pieces": n_pieces,
        "traffic": traffic,
        "signups": signups,
        "pieces_by_topic": [{"topic": t, "pieces": n,
                             "pct_of_catalogue": round(n / n_pieces * 100, 1)}
                            for t, n in sorted(pieces.items(), key=lambda kv: -kv[1])],
    }
    OUT.write_text(json.dumps(out, indent=1))
    tr = (traffic or {}).get("rows") or []
    sg = (signups or {}).get("rows") or []
    print(f"wrote {OUT.name}: {len(tr)} topics with traffic, {len(sg)} with signups, "
          f"{n_pieces} catalogue pieces")


if __name__ == "__main__":
    main()
