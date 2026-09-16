#!/usr/bin/env python3
"""private/resharing_candidates.json — what the resharing calendar should be told about this month.

Feeds the monthly `vc-resharing-calendar-monthly` task, which does the editorial
work. This script does only the parts a machine can be trusted with: read the
catalogue, join it to per-article traffic, and say what changed since last time.

Three deliberate constraints:

1. TRAFFIC MAY BE STALE, AND SAYS SO. Per-article views come from GA4 via
   growth_pull's piece index. The GA4 service-account key lives in GitHub
   secrets and is not always on the laptop (see the local-runs-clobber-secrets
   note in HANDOFF). When a live pull is not possible this falls back to the
   last good block in private/growth.json and stamps `traffic.as_of` +
   `traffic.stale`. A stale figure is labelled, never passed off as current.

2. THE CATALOGUE READ IS FAIL-LOUD. A missing or empty catalogue.json exits
   non-zero rather than emitting an empty candidate list, because "nothing new
   this month" and "we could not look" must not look alike.

3. NOTHING HERE IS A DECISION. Keyword matching against the calendar's gap
   topics produced obvious false hits when the page was first built, so this
   emits ranked candidates for a human (or the task's editorial pass) to accept
   or reject. It never writes the page.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, urllib.request, urllib.error
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOGUE = ROOT / "data" / "catalogue.json"
GROWTH = ROOT / "private" / "growth.json"
STATE = ROOT / "private" / "resharing_state.json"
OUT = ROOT / "private" / "resharing_candidates.json"

EVERGREEN_MONTHS = 9

# The four moments the published page names as having no strong piece behind
# them. Matching is generous on purpose -- the task throws out the false hits.
GAPS = {
    "heat": ["heat wave", "heatwave", "extreme heat", "cooling center", "air conditioning",
             "hot weather", "heat emergency", "heat island"],
    "flooding": ["flood", "flooding", "stormwater", "sewer backup", "heavy rain",
                 "cloudburst", "basement apartment", "hurricane", "resilien"],
    "back to school": ["back to school", "school year", "first day of school", "chancellor",
                       "classroom", "school enrollment", "attendance", "students"],
    "immigration": ["migrant", "immigration", "asylum", "ice raid", "deportation",
                    "sanctuary city", "immigrant"],
}


def log(m): print(m, file=sys.stderr)


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


def load_catalogue():
    if not CATALOGUE.exists():
        sys.exit(f"FAIL: {CATALOGUE} missing — run the catalogue refresh first")
    items = json.loads(CATALOGUE.read_text())
    if not isinstance(items, list) or len(items) < 100:
        sys.exit(f"FAIL: {CATALOGUE} holds {len(items) if isinstance(items, list) else '?'} "
                 "records — that is not a full catalogue, refusing to emit candidates")
    return items


def live_ga4_pieces():
    """Try a fresh GA4 piece index. Returns (pieces, as_of) or (None, reason)."""
    creds = os.environ.get("GA4_CREDS_JSON")
    if not creds:
        try:
            creds = subprocess.run(
                ["security", "find-generic-password", "-s", "GA4_CREDS_JSON", "-w"],
                capture_output=True, text=True, timeout=15).stdout.strip() or None
        except Exception:
            creds = None
    if not creds:
        return None, "GA4_CREDS_JSON not in env or login keychain"
    prop = os.environ.get("GA4_PROPERTY_ID")
    if not prop and GROWTH.exists():
        prop = ((json.loads(GROWTH.read_text()).get("ga4") or {}).get("property_id"))
    if not prop:
        return None, "GA4_PROPERTY_ID not in env and not recorded in growth.json"
    try:
        sys.path.insert(0, str(ROOT))
        from growth_pull import _ga4_access_token, _ga4_piece_index  # noqa
        token = _ga4_access_token(creds)
        idx = _ga4_piece_index(str(prop), token)
        if not idx or not idx.get("available") or not idx.get("pieces"):
            return None, "GA4 piece index came back empty"
        return idx["pieces"], idx.get("as_of") or date.today().isoformat()
    except Exception as e:
        return None, f"GA4 pull failed: {type(e).__name__}: {e}"


def stored_ga4_pieces():
    if not GROWTH.exists():
        return None, None, "private/growth.json missing"
    ga = (json.loads(GROWTH.read_text()).get("ga4") or {})
    idx = ga.get("piece_index") or {}
    if not idx.get("pieces"):
        return None, None, "no piece_index in growth.json"
    return idx["pieces"], idx.get("as_of") or ga.get("as_of"), None


def check_links(urls):
    """HEAD every URL currently on the page. The first build of this calendar
    shipped 25 dead links out of 57 because URLs were reconstructed from
    titles; that must never recur silently."""
    dead = []
    for u in sorted(set(urls)):
        req = urllib.request.Request(u, method="HEAD", headers={
            "User-Agent": "VitalCityResharingCalendar/1.0 (+https://www.vitalcitynyc.org)"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                if r.status >= 400:
                    dead.append({"url": u, "status": r.status})
        except urllib.error.HTTPError as e:
            dead.append({"url": u, "status": e.code})
        except Exception as e:
            dead.append({"url": u, "status": f"{type(e).__name__}: {e}"})
    return dead


def main():
    today = date.today()
    items = load_catalogue()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    last_run = state.get("last_run")
    on_calendar = set(state.get("on_calendar_slugs") or [])

    pieces, as_of = live_ga4_pieces()
    stale, reason = False, None
    if pieces is None:
        reason = as_of
        log(f"GA4 live pull unavailable ({reason}) — falling back to stored piece index")
        pieces, as_of, err = stored_ga4_pieces()
        stale = True
        if pieces is None:
            log(f"WARNING: no traffic data at all ({err}) — candidates will be "
                "ranked on editorial fit alone")
            pieces, as_of, stale = [], None, True

    views = {p["slug"]: p.get("views") or 0 for p in pieces if p.get("slug")}

    evergreen, new_since, newly_evergreen, gap_hits = [], [], [], {k: [] for k in GAPS}
    for it in items:
        slug, pub = it.get("slug"), (it.get("published_date") or "")[:10]
        if not slug or not pub:
            continue
        try:
            pd = date.fromisoformat(pub)
        except ValueError:
            continue
        age = months_between(pd, today)
        rec = {"slug": slug, "title": it.get("title"), "url": it.get("url"),
               "published": pub, "age_months": age, "views": views.get(slug),
               "topics": it.get("topics") or [], "summary": it.get("summary") or "",
               "on_calendar": slug in on_calendar}
        if last_run and pub > last_run:
            new_since.append(rec)
        if age >= EVERGREEN_MONTHS:
            evergreen.append(rec)
            # crossed the line during the month just gone
            if months_between(pd, today) == EVERGREEN_MONTHS:
                newly_evergreen.append(rec)
        hay = " ".join([rec["title"] or "", rec["summary"], " ".join(rec["topics"])]).lower()
        for gap, words in GAPS.items():
            if any(w in hay for w in words):
                gap_hits[gap].append(rec)

    evergreen.sort(key=lambda r: (r["views"] or -1), reverse=True)
    for g in gap_hits:
        gap_hits[g].sort(key=lambda r: (r["views"] or -1), reverse=True)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of_date": today.isoformat(),
        "last_run": last_run,
        "catalogue": {"total_pieces": len(items),
                      "evergreen_pieces": len(evergreen),
                      "evergreen_definition": f"published more than {EVERGREEN_MONTHS} months ago"},
        "traffic": {"source": "GA4 piece index via growth_pull",
                    "as_of": as_of, "stale": stale, "stale_reason": reason,
                    "pieces_with_measured_traffic": sum(1 for r in evergreen if r["views"])},
        "published_since_last_run": sorted(new_since, key=lambda r: r["published"], reverse=True),
        "newly_evergreen_this_month": sorted(newly_evergreen, key=lambda r: (r["views"] or -1), reverse=True),
        "top_evergreen_not_on_calendar": [r for r in evergreen if not r["on_calendar"]][:40],
        "gap_candidates": {g: v[:12] for g, v in gap_hits.items()},
        "current_calendar_slugs": sorted(on_calendar),
    }

    if "--check-links" in sys.argv:
        urls = state.get("on_calendar_urls") or []
        out["dead_links"] = check_links(urls)
        out["links_checked"] = len(set(urls))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    log(f"wrote {OUT} — {len(items)} pieces, {len(evergreen)} evergreen, "
        f"{len(new_since)} published since {last_run or 'never'}, traffic as of {as_of}"
        f"{' (STALE)' if stale else ''}")


if __name__ == "__main__":
    main()
