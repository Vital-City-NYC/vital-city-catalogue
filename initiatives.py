"""The one log of what Vital City tried, and when.

Staff keep it in the "events" tab of the key-indicators Google Sheet (the same
sheet the weekly Claude dashboard reads). Every chart that marks initiatives
reads it from there: the growth dashboard's key indicators, its weekly table,
the weekly dashboard and the toolkit home page. Add a row to the sheet and the
next refresh marks it everywhere.

Columns: from, to, label, kind, notes. "from" and "to" are a month (2026-05)
or a day (2026-06-04); "to" is blank for a one-day or one-month event. The
sheet is private, so labels there may carry internal numbers. This file is
public, so the fallback list below must not.

load() never fails: if the sheet can't be read (no credentials on a local run,
a network error) it falls back to FALLBACK and says so in the result.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

SHEET_ID = os.environ.get("KPI_SHEET_ID", "").strip() or "1OlElkNQYaZEl4kYU2EexoU52MBgqTjkmdfGEkHwLWzc"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
TAB = "events"
KINDS = {"data", "fundraising", "site", "outreach", "event", "newsletter", "social", "other"}

# Used only when the sheet can't be read. Public, so no internal counts.
FALLBACK = [
    {"from": "2025-05", "to": "2025-09", "label": "Bot signup surge (about half of new signups)", "kind": "data"},
    {"from": "2025-11", "to": "2025-12", "label": "End-of-year fundraising drive; online giving opens Nov. 12", "kind": "fundraising"},
    {"from": "2026-03", "label": "Site moves from Prismic to Ghost; one-time catch-up import of signups into Mailchimp", "kind": "site"},
    {"from": "2026-04", "label": "Pages found missing from Google's index after the move; re-indexing requested", "kind": "site"},
    {"from": "2026-04", "to": "2026-05", "label": "University and law-school faculty outreach emails", "kind": "outreach"},
    {"from": "2026-04", "label": "Gopnik and Sampson event (Apr. 27)", "kind": "event"},
    {"from": "2026-05", "label": "Subject-line A/B tests begin (May 7); inactive addresses removed from the list", "kind": "newsletter"},
    {"from": "2026-05", "to": "2026-06", "label": "Spring fundraising drive (May 12 to June 13)", "kind": "fundraising"},
    {"from": "2026-06", "label": "Rent-freeze webinar; registrants added to the list", "kind": "event"},
    {"from": "2026-06-04", "label": "Newsletter goes to the engaged part of the list only; open rates jump that week", "kind": "newsletter"},
    {"from": "2026-10-08", "label": "Some new pieces go members-only", "kind": "site"},
    {"from": "2026-10-28", "label": "Signup boxes added inside and at the end of articles", "kind": "site"},
]

_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _log(m):
    print(m, file=sys.stderr, flush=True)


def _norm_date(v):
    """Accept 2026-06, 2026-06-04, or what Sheets shows for a typed date
    (6/4/2026). Returns '' when the cell can't be read as a date."""
    s = str(v or "").strip()
    if _DATE.match(s):
        return s
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.match(r"^(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    return ""


def clean(rows):
    """Sheet rows (header first) -> sorted items. Rows without a readable
    date or a label are skipped and reported, never guessed."""
    if not rows:
        return [], []
    head = [str(h).strip().lower() for h in rows[0]]
    col = {h: i for i, h in enumerate(head)}
    if "from" not in col or "label" not in col:
        raise ValueError("the events tab needs 'from' and 'label' columns")
    get = lambda r, k: (r[col[k]] if k in col and col[k] < len(r) else "")
    items, skipped = [], []
    for n, r in enumerate(rows[1:], start=2):
        if not any(str(c).strip() for c in r):
            continue
        frm, to = _norm_date(get(r, "from")), _norm_date(get(r, "to"))
        label = str(get(r, "label")).strip()
        if not frm or not label:
            skipped.append(f"row {n}: needs a date in 'from' (2026-05 or 2026-05-07) and a label")
            continue
        kind = str(get(r, "kind")).strip().lower() or "other"
        it = {"from": frm, "label": label, "kind": kind if kind in KINDS else "other"}
        if to and to != frm:
            it["to"] = to
        note = str(get(r, "notes")).strip()
        if note:
            it["notes"] = note
        items.append(it)
    items.sort(key=lambda e: e["from"])
    return items, skipped


def read_sheet(creds):
    """Read the events tab with the service account the weekly pull already
    uses (it has edit access to the sheet)."""
    import growth_pull as gp
    tok = gp._sa_access_token(creds, "https://www.googleapis.com/auth/spreadsheets.readonly")
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/"
           f"{urllib.parse.quote(TAB + '!A1:F400')}")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get("values") or []


def load():
    """{'available', 'source', 'sheet_url', 'items', 'skipped'}. Each item's
    'from'/'to' is kept as typed; 'month' is the month it falls in, which is
    what the monthly charts place it by."""
    raw = os.environ.get("GA4_CREDS_JSON", "").strip()
    items, skipped, source = None, [], "built-in list (the sheet could not be read)"
    if raw:
        try:
            items, skipped = clean(read_sheet(json.loads(raw)))
            source = "sheet"
            if not items:
                items, source = None, "built-in list (the sheet's events tab was empty)"
        except Exception as e:
            _log(f"  initiatives: sheet not read ({type(e).__name__}: {e}); using the built-in list")
    if items is None:
        items = sorted(FALLBACK, key=lambda e: e["from"])
    for it in items:
        it["month"] = it["from"][:7]
        if it.get("to"):
            it["to_month"] = it["to"][:7]
    for s in skipped:
        _log(f"  initiatives: skipped {s}")
    _log(f"  initiatives: {len(items)} from the {source}")
    return {"available": True, "source": source, "sheet_url": SHEET_URL, "items": items, "skipped": skipped}


if __name__ == "__main__":
    print(json.dumps(load(), indent=2))
