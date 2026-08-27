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

    # ---- Historical reader mix, from GA4 --------------------------------
    # Ghost analytics start 2026-03-01, but GA4 tracked the previous site and
    # holds per-article rows per calendar year. Joining those to the same
    # subject tags is the only way to see whether the audience's interests
    # moved -- and they did, sharply. Coverage is GA4's per-year page list
    # (top rows by views above a 100-view floor), so these are shares among a
    # year's most-read pieces, not all traffic; the row count is reported so
    # the basis is visible rather than implied.
    import importlib.util
    spec = importlib.util.spec_from_file_location("gp", ROOT / "growth_pull.py")
    gp = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(gp)
        tmap = gp.catalogue_topic_map()
    except Exception as e:
        print(f"  note: could not load topic map for history ({e})")
        tmap = {}
    history = {}
    for yr, rows in sorted(((g.get("ga4") or {}).get("engagement_by_year") or {}).items()):
        counts = {}
        for r in rows:
            sl = (r.get("path") or "").rstrip("/").rsplit("/", 1)[-1].lower()
            if sl:
                counts[sl] = counts.get(sl, 0) + int(r.get("views") or 0)
        if not counts or not tmap:
            continue
        res = gp.by_topic(counts, tmap, f"GA4 {yr}")
        res["pages"] = len(rows)
        # Concentration, reported rather than buried. These year rows are far
        # more fragile than a percentage table looks: in 2024 a single evergreen
        # explainer ("20 Strategies for Reducing Crime in Cities") is 43% of all
        # measured views, so every subject tag on that one piece -- Safety,
        # Crime AND History -- reads as a ~50% audience share. Without this
        # figure the table invites a claim about what readers wanted, when the
        # honest claim is about which one or two pieces broke through.
        ordered = sorted(rows, key=lambda r: -int(r.get("views") or 0))
        tot = sum(int(r.get("views") or 0) for r in ordered) or 1
        res["top1_share"] = round(int(ordered[0].get("views") or 0) / tot * 100, 1)
        res["top1_title"] = ordered[0].get("title") or ""
        res["top3_share"] = round(sum(int(r.get("views") or 0) for r in ordered[:3]) / tot * 100, 1)
        # Same mix with the year's dominant piece removed, so a reader can see
        # how much of the shape survives it.
        rest = {}
        for r in ordered[1:]:
            sl = (r.get("path") or "").rstrip("/").rsplit("/", 1)[-1].lower()
            if sl:
                rest[sl] = rest.get(sl, 0) + int(r.get("views") or 0)
        res["ex_top1"] = gp.by_topic(rest, tmap, f"GA4 {yr} ex-top1") if rest else None
        history[yr] = res

    out = {
        "generated_from": "private/growth.json",
        "history": history,
        "history_note": ("Per-article reader mix by calendar year from Google Analytics, "
                         "which tracked the site before Ghost analytics began on "
                         "2026-03-01. Each year covers GA4's per-year page list above a "
                         "100-view floor, so these are shares among that year's most-read "
                         "pieces rather than all traffic."),
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
