#!/usr/bin/env python3
"""private/resharing.json — which archive piece to post, and when.

Feeds the gated /resharing/ tool and the monthly vc-resharing-calendar-monthly
routine. It replaces a hand-written page whose dates were month labels ("mid
January, State of the City season") with a join against the New York City
calendar, which already computes the real dates, their significance and their
strand. A moment now resolves to an actual dated event or it does not appear.

Three inputs:
  data/catalogue.json            every published piece
  GA4 piece index                per-piece lifetime views (via growth_pull)
  nyc-policy-calendar events     the dated event stream, fetched live
  seed/resharing_editorial.json  the hand-written picks and why-copy

Four constraints, each earned:

1. THE CATALOGUE READ IS FAIL-LOUD. A missing or implausibly small
   catalogue.json exits non-zero rather than emitting an empty page, because
   "nothing to post this month" and "we could not look" must not look alike.

2. TRAFFIC MAY BE STALE, AND SAYS SO. The GA4 service-account key lives in
   GitHub secrets and is not always on the laptop. When a live pull is
   impossible this falls back to the last good block in private/growth.json and
   stamps traffic.as_of + traffic.stale. A carried-forward figure is never
   presented as current.

3. HAND-PICKED AND MACHINE-SUGGESTED ARE NEVER MIXED. Every pick carried from
   the editorial seed is marked `reviewed: true`. Anything this script found by
   matching keywords is `reviewed: false` and the page labels it as unreviewed.
   The first build of this calendar showed keyword matching alone produces
   obvious false hits.

4. A GAP IS REPORTED, NOT FILLED. A high-significance event with no reviewed
   moment, no hook and no decent catalogue match is emitted as a gap. Filling
   it with the least-bad keyword match would hide exactly the thing the
   commissioning list exists to surface.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, urllib.parse, urllib.request, urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOGUE = ROOT / "data" / "catalogue.json"
GROWTH = ROOT / "private" / "growth.json"
SEED = ROOT / "seed" / "resharing_editorial.json"
STATE = ROOT / "private" / "resharing_state.json"
OUT = ROOT / "private" / "resharing.json"

CALENDAR_URL = "https://vitalcity-nyc.github.io/nyc-policy-calendar/data/events.json"
CALENDAR_LOCAL = ROOT.parent / "nyc-policy-calendar" / "data" / "events.json"

HORIZON_DAYS = 120          # how far ahead the page looks
MIN_SIGNIFICANCE = 45       # below this the calendar is routine committee business
GAP_TIERS = {"major", "marquee"}   # only a big unanswered moment counts as a gap
EVERGREEN_MONTHS = 9

UA = "VitalCityResharing/1.0 (+https://www.vitalcitynyc.org)"


def log(m): print(m, file=sys.stderr)


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


# ----------------------------------------------------------------- inputs
def load_catalogue():
    if not CATALOGUE.exists():
        sys.exit(f"FAIL: {CATALOGUE} missing — run the catalogue refresh first")
    items = json.loads(CATALOGUE.read_text())
    if not isinstance(items, list) or len(items) < 100:
        sys.exit(f"FAIL: {CATALOGUE} holds {len(items) if isinstance(items, list) else '?'} "
                 "records — that is not a full catalogue, refusing to build")
    return items


def load_calendar():
    """Live feed first. The local clone is a fallback, not a source: it is a
    working copy and goes stale between pulls, while the published feed is
    rebuilt twice a day."""
    try:
        req = urllib.request.Request(CALENDAR_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
        if d.get("events"):
            return d, CALENDAR_URL, False
    except Exception as e:
        log(f"calendar: live feed failed ({type(e).__name__}: {e}) — trying local clone")
    if CALENDAR_LOCAL.exists():
        d = json.loads(CALENDAR_LOCAL.read_text())
        if d.get("events"):
            return d, str(CALENDAR_LOCAL), True
    sys.exit("FAIL: no calendar events from the live feed or the local clone")


def live_ga4_pieces():
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
        prop = (json.loads(GROWTH.read_text()).get("ga4") or {}).get("property_id")
    if not prop:
        return None, "GA4_PROPERTY_ID not in env and not recorded in growth.json"
    try:
        sys.path.insert(0, str(ROOT))
        import base64 as _b64
        from growth_pull import _ga4_access_token, _ga4_piece_index  # noqa
        # _sa_access_token indexes creds["client_email"], so it wants the parsed
        # dict, not the raw value. The keychain copy is base64 and the CI secret
        # may be either, so try both the way growth_pull's own pull_ga4 does.
        # Passing the string through raised "string indices must be integers"
        # and sent every CI run down the fallback path.
        if isinstance(creds, str):
            try:
                creds = json.loads(_b64.b64decode(creds))
            except Exception:
                creds = json.loads(creds)
        idx = _ga4_piece_index(str(prop), _ga4_access_token(creds))
        if not idx or not idx.get("available") or not idx.get("pieces"):
            return None, "GA4 piece index came back empty"
        return idx["pieces"], idx.get("as_of") or date.today().isoformat()
    except Exception as e:
        return None, f"GA4 pull failed: {type(e).__name__}: {e}"


def stored_ga4_pieces():
    if not GROWTH.exists():
        return None, None, "private/growth.json missing"
    ga = json.loads(GROWTH.read_text()).get("ga4") or {}
    idx = ga.get("piece_index") or {}
    if not idx.get("pieces"):
        return None, None, "no piece_index in growth.json"
    return idx["pieces"], idx.get("as_of") or ga.get("as_of"), None


# ----------------------------------------------------------------- matching
def in_window(d: date, window) -> bool:
    """Windows are MM-DD pairs and may wrap the year end (12-26 to 01-02)."""
    lo, hi = window
    cur = d.strftime("%m-%d")
    return (lo <= cur <= hi) if lo <= hi else (cur >= lo or cur <= hi)


def event_haystack(ev) -> str:
    """Title only, and the note only when it is not a venue line.

    The first cut of this matcher searched the note and the `why` array too,
    and the results were junk: every Council hearing at City Hall matched the
    moment keyed to "City Hall", and the scoring rationale "high-salience
    committee" matched on words nobody meant editorially. A venue is not a
    subject."""
    hay = ev.get("title") or ""
    note = ev.get("note") or ""
    if note and not re.search(r"\d{2,}\s+\w+|Room|Floor|Broadway|Chambers|Hearing Room", note):
        hay += " " + note
    return hay.lower()


def has_word(hay: str, term: str) -> bool:
    """Word-boundary, not substring. "rat" was matching inside
    "administration" and "Corporation", which put the rodent piece against the
    Mayor's Management Report."""
    return re.search(r"\b" + re.escape(term.lower()) + r"\b", hay) is not None


def match_moment(ev, ev_date, moments):
    """A moment binds to a NAMED event or it does not bind at all.

    There is deliberately no seasonal fallback here. An earlier version let any
    October event fall through to the October moment, which put the crime
    strategies piece against a birth-control-clinic anniversary and a book
    launch. Moments with an open window but no event of their own are carried
    separately, as the seasons they are."""
    hay = event_haystack(ev)
    for m in moments:
        if any(has_word(hay, k) for k in m["match"].get("keywords") or []):
            return m, "keyword"
    strand = ev.get("strand")
    for m in moments:
        mm = m["match"]
        if strand and strand in (mm.get("strands") or []) and in_window(ev_date, mm["window"]):
            return m, "strand"
    return None, None


def match_hook(ev, hooks):
    """Two independent signals, or none. A single common word is coincidence:
    one hit put the homelessness hook against a book launch."""
    hay = event_haystack(ev)
    best = None
    for h in hooks:
        hits = [s for s in h.get("signals") or [] if has_word(hay, s)]
        if len(hits) >= 2 and (best is None or len(hits) > len(best[1])):
            best = (h, hits)
    return best if best else (None, None)


STOP = {"committee", "hearing", "council", "meeting", "anniversary", "public", "street",
        "broadway", "floor", "room", "scheduled", "salience", "high", "vote", "stated",
        "annual", "report", "board", "commission", "office", "department", "bureau",
        "first", "second", "third", "york", "city", "cityw", "general", "special"}


def suggest_from_catalogue(ev, evergreen):
    """Last resort, always labelled unreviewed, and deliberately strict: three
    distinctive shared words, not two. At two, "The Great Fire of 1776"
    returned a piece on municipal ingenuity."""
    words = {w for w in re.findall(r"[a-z]{5,}", event_haystack(ev)) if w not in STOP}
    if len(words) < 3:
        return []
    scored = []
    for r in evergreen:
        hay = (str(r["title"]) + " " + r["summary"] + " " + " ".join(r["topics"])).lower()
        hits = [w for w in words if has_word(hay, w)]
        if len(hits) >= 3:
            scored.append((len(hits), r["views"] or 0, r, hits))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [dict(r, matched_words=hits, reviewed=False) for _, _, r, hits in scored[:2]]


# ----------------------------------------------------------------- build
def main():
    today = date.today()
    horizon = today + timedelta(days=HORIZON_DAYS)

    items = load_catalogue()
    cal, cal_src, cal_local = load_calendar()
    seed = json.loads(SEED.read_text())
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    last_run = state.get("last_run")

    moments = [e for e in seed["entries"] if e["kind"] == "moment"]
    hooks = [e for e in seed["entries"] if e["kind"] == "hook"]

    # In CI the growth pull rebuilds private/growth.json minutes before this
    # runs, so its piece index is already current and querying GA4 again would
    # be a second identical round trip. Use it when it is from today; that block
    # is not stale just because we did not fetch it ourselves.
    pieces, as_of, err = stored_ga4_pieces()
    stale, reason = False, None
    if pieces and as_of == today.isoformat():
        log(f"using the piece index already built this run (as of {as_of})")
    else:
        fresh, fresh_as_of = live_ga4_pieces()
        if fresh is not None:
            pieces, as_of, stale = fresh, fresh_as_of, False
        elif pieces is not None:
            reason = fresh_as_of
            stale = True
            log(f"GA4 live pull unavailable ({reason}) — falling back to the stored "
                f"piece index from {as_of}")
        else:
            reason = fresh_as_of
            log(f"WARNING: no traffic data at all ({err or reason})")
            pieces, as_of, stale = [], None, True
    views = {p["slug"]: p.get("views") or 0 for p in pieces if p.get("slug")}

    by_slug, evergreen, new_since = {}, [], []
    for it in items:
        slug, pub = it.get("slug"), (it.get("published_date") or "")[:10]
        if not slug or not pub:
            continue
        try:
            pd = date.fromisoformat(pub)
        except ValueError:
            continue
        rec = {"slug": slug, "title": it.get("title"), "url": it.get("url"),
               "published": pub, "views": views.get(slug), "topics": it.get("topics") or [],
               "summary": it.get("summary") or "", "age_months": months_between(pd, today),
               # who wrote it, so draft posts can credit the writer
               "authors": [a for a in (it.get("authors") or []) if a and a != "Vital City"]}
        by_slug[slug] = rec
        if last_run and pub > last_run:
            new_since.append(rec)
        if rec["age_months"] >= EVERGREEN_MONTHS:
            evergreen.append(rec)
    evergreen.sort(key=lambda r: (r["views"] or -1), reverse=True)

    def from_site(slug):
        """A curated pick the catalogue lacks (the catalogue missed Howard
        Slatkin's rent piece): read it from the site's public content feed."""
        if slug in from_site.cache:
            return from_site.cache[slug]
        rec = None
        try:
            u = ("https://vital-city.ghost.io/ghost/api/content/posts/slug/" + urllib.parse.quote(slug) +
                 "/?key=dd8e178e9ddfc883537e71dd07&include=authors,tags&fields=title,url,published_at,custom_excerpt,slug")
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
                post = json.loads(r.read())["posts"][0]
            pub = (post.get("published_at") or "")[:10]
            rec = {"slug": slug, "title": post.get("title"), "url": post.get("url"), "published": pub,
                   "views": views.get(slug), "topics": [t["name"] for t in post.get("tags") or [] if t.get("visibility") == "public"],
                   "summary": post.get("custom_excerpt") or "",
                   "age_months": months_between(date.fromisoformat(pub), today) if pub else None,
                   "authors": [a["name"] for a in post.get("authors") or [] if a.get("name") and a["name"] != "Vital City"],
                   "from_site": True}
        except Exception as e:
            print(f"  resharing: {slug} is not in the catalogue and could not be read from the site ({e})")
        from_site.cache[slug] = rec
        return rec
    from_site.cache = {}

    def hydrate(refs, reviewed=True):
        out = []
        for ref in refs:
            r = by_slug.get(ref["slug"]) or from_site(ref["slug"])
            out.append(dict(r, reviewed=reviewed) if r else
                       {"slug": ref["slug"], "title": ref.get("title"), "url": None,
                        "views": None, "published": None, "missing": True, "reviewed": reviewed})
        return out

    upcoming, gaps, hook_schedule = [], [], {h["id"]: [] for h in hooks}
    for ev in cal["events"]:
        try:
            ed = date.fromisoformat(ev["date"])
        except Exception:
            continue
        if not (today <= ed <= horizon):
            continue
        if (ev.get("significance") or 0) < MIN_SIGNIFICANCE and ev.get("tier") not in GAP_TIERS:
            continue
        # Routine committee business is the bulk of the calendar and is never a
        # resharing occasion. Only a hearing the calendar itself scores as
        # major gets through.
        if ev.get("strand") == "hearings" and (ev.get("significance") or 0) < 70:
            continue

        row = {"date": ev["date"], "post_on": ev["date"],
               "event": {k: ev.get(k) for k in
                         ("title", "note", "strand", "source", "sourceUrl", "significance", "tier", "why")}}

        m, how = match_moment(ev, ed, moments)
        if m:
            row.update({"kind": "moment", "matched_by": how, "moment_id": m["id"],
                        "label": m["label"], "why": m["why"],
                        "picks": hydrate(m["picks"]), "also": hydrate(m["also"]),
                        "also_note": m.get("also_note") or ""})
            off = m["match"].get("post_offset_days")
            if off:
                row["post_on"] = (ed + timedelta(days=off)).isoformat()
                row["post_offset_reason"] = m["match"].get("offset_reason")
            upcoming.append(row)
            continue

        h, hits = match_hook(ev, hooks)
        if h:
            hook_schedule[h["id"]].append({"date": ev["date"], "title": ev.get("title"), "on": hits})
            row.update({"kind": "hook", "matched_by": "signal", "hook_id": h["id"],
                        "label": h["label"], "why": h["why"], "signals_hit": hits,
                        "picks": hydrate(h["picks"]), "also": hydrate(h["also"]),
                        "also_note": h.get("also_note") or ""})
            upcoming.append(row)
            continue

        sugg = suggest_from_catalogue(ev, evergreen)
        if sugg:
            row.update({"kind": "suggested", "matched_by": "catalogue keywords",
                        "label": ev.get("title"), "why": "", "picks": sugg, "also": [],
                        "also_note": ""})
            upcoming.append(row)
        elif ev.get("tier") in GAP_TIERS:
            gaps.append({"date": ev["date"], "title": ev.get("title"), "strand": ev.get("strand"),
                         "significance": ev.get("significance"), "tier": ev.get("tier"),
                         "why": ev.get("why") or []})

    upcoming.sort(key=lambda r: (r["post_on"], -(r["event"]["significance"] or 0)))

    # One moment, one post. Election week alone produced five entries -- early
    # voting opens, mail-ballot request deadline, early voting ends, the
    # election, the postmark deadline -- every one of them carrying the same
    # piece. Keep the most significant event in each cluster and hang the rest
    # off it as context, so the page reads as "post this, on this day".
    CLUSTER_DAYS = 14
    collapsed, seen = [], {}
    for r in upcoming:
        key = r.get("moment_id") or r.get("hook_id")
        d = date.fromisoformat(r["post_on"])
        prev = seen.get(key)
        if key and prev and (d - date.fromisoformat(prev["post_on"])).days <= CLUSTER_DAYS:
            if (r["event"]["significance"] or 0) > (prev["event"]["significance"] or 0):
                r["alongside"] = prev.get("alongside", []) + [
                    {"date": prev["date"], "title": prev["event"]["title"]}]
                collapsed[collapsed.index(prev)] = r
                seen[key] = r
            else:
                prev.setdefault("alongside", []).append(
                    {"date": r["date"], "title": r["event"]["title"]})
            continue
        collapsed.append(r)
        if key:
            seen[key] = r
    upcoming = collapsed

    # Moments the calendar has no event for. They are still real -- "December,
    # year-end giving" is a season, not a date -- so they are carried here
    # rather than bolted onto whatever event happened to fall in the window.
    bound = {r.get("moment_id") for r in upcoming}
    seasonal = []
    for m in moments:
        if m["id"] in bound:
            continue
        opens = any(in_window(today + timedelta(days=i), m["match"]["window"])
                    for i in range(0, HORIZON_DAYS + 1))
        if not opens:
            continue
        seasonal.append({"kind": "season", "moment_id": m["id"], "label": m["label"],
                         "why": m["why"], "window": m["match"]["window"],
                         "active_now": in_window(today, m["match"]["window"]),
                         "picks": hydrate(m["picks"]), "also": hydrate(m["also"]),
                         "also_note": m.get("also_note") or ""})

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of_date": today.isoformat(),
        "horizon_days": HORIZON_DAYS,
        "min_significance": MIN_SIGNIFICANCE,
        "last_run": last_run,
        "catalogue": {"total_pieces": len(items), "evergreen_pieces": len(evergreen),
                      "evergreen_definition": f"published more than {EVERGREEN_MONTHS} months ago",
                      "published_since_last_run": sorted(new_since, key=lambda r: r["published"], reverse=True)},
        "traffic": {"source": "GA4 piece index via growth_pull", "as_of": as_of,
                    "stale": stale, "stale_reason": reason,
                    "measured_of_evergreen": sum(1 for r in evergreen if r["views"])},
        "calendar": {"source": cal_src, "from_local_clone": cal_local,
                     "generated": cal.get("generated"), "window": cal.get("window"),
                     "events_total": len(cal["events"]),
                     "events_in_horizon": sum(1 for r in upcoming) + len(gaps)},
        "upcoming": upcoming,
        "seasonal": seasonal,
        "hooks": [dict(h, picks=hydrate(h["picks"]), also=hydrate(h["also"]),
                       scheduled=hook_schedule[h["id"]]) for h in hooks],
        "gaps": gaps,
        "always_on": [r for r in evergreen[:3]],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    kinds = {}
    for r in upcoming:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    log(f"wrote {OUT} — {len(items)} pieces, {len(evergreen)} evergreen; "
        f"{len(upcoming)} dated posts ({kinds}), {len(seasonal)} seasons, {len(gaps)} gaps; "
        f"traffic as of {as_of}{' (STALE)' if stale else ''}; calendar {cal.get('generated')}")


if __name__ == "__main__":
    main()
