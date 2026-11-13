#!/usr/bin/env python3
"""Copy the "Vital City key indicators" Google Sheet's tabs into CSV files for
the Vital City analytics dashboard.

Run by .github/workflows/dashboard-data.yml after the dashboard build. The
dashboard used to read these tabs live through the Google Sheets connector,
which kept failing for readers; it now reads these files instead.

    weekly!A1:T300      -> out/kp_weekly.csv
    monthly!A1:T200     -> out/kp_monthly.csv
    benchmarks!A1:F30   -> out/kp_benchmarks.csv
    events!A1:D60       -> out/kp_events.csv
    about!A1:B20        -> out/kp_about.csv

Each file is the tab as the sheet shows it (the same formatted values the
connector returned): the sheet's own header row, then every data row, with
fully empty trailing rows dropped. Standard CSV quoting, UTF-8.

THE OUTPUT IS PRIVATE and goes only to the private repository
vitalcity-nyc/vc-dashboard-data, named by VC_DASH_DIR (the same rule as
vc_dashboard_build.py). The tabs hold aggregate counts only; a tab with an
email address in it is not written.

Login: the service account in GA4_CREDS_JSON, the same one kpi_weekly.py
writes the sheet with, asking only for read access. Nothing secret is printed.

If any tab can't be read or looks wrong, that file keeps its previous copy and
the script still exits 0, so the rest of the workflow carries on. The log names
files and row counts only, never a figure.
"""
import csv, io, json, os, re, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("VC_DASH_DIR") or HERE.parent / "vc-dashboard-data").resolve()
if DATA == HERE or HERE in DATA.parents:
    raise SystemExit("VC_DASH_DIR points inside this public repository; the output must go to the private one")
if not DATA.is_dir():
    raise SystemExit(f"no data folder at {DATA}: check out vitalcity-nyc/vc-dashboard-data there, or set VC_DASH_DIR")
OUT = DATA / "out"; OUT.mkdir(exist_ok=True)

SHEET_ID = os.environ.get("KPI_SHEET_ID") or "1OlElkNQYaZEl4kYU2EexoU52MBgqTjkmdfGEkHwLWzc"
TABS = [  # (file, range) - the ranges the dashboard read
    ("kp_weekly.csv",     "weekly!A1:T300"),
    ("kp_monthly.csv",    "monthly!A1:T200"),
    ("kp_benchmarks.csv", "benchmarks!A1:F30"),
    ("kp_events.csv",     "events!A1:D60"),
    ("kp_about.csv",      "about!A1:B20"),
]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")


def warn(msg):
    # GitHub shows ::warning lines on the run page without failing it.
    print(f"::warning title=Key indicators file kept from last time::{msg}", flush=True)


def read_ranges():
    sys.path.insert(0, str(HERE))
    import kpi_weekly, growth_pull as gp
    creds = kpi_weekly.ga4_creds()
    if not creds:
        raise RuntimeError("GA4_CREDS_JSON is not set, so the sheet can't be read")
    token = gp._sa_access_token(creds, "https://www.googleapis.com/auth/spreadsheets.readonly")
    q = [("ranges", r) for _, r in TABS] + [("majorDimension", "ROWS"),
                                            ("valueRenderOption", "FORMATTED_VALUE")]
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values:batchGet?"
           + urllib.parse.urlencode(q))
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try: why = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception: why = ""
        raise RuntimeError(f"Sheets API said {e.code} {why}".strip()) from None
    got = body.get("valueRanges") or []
    if len(got) != len(TABS):
        raise RuntimeError(f"asked for {len(TABS)} ranges, got {len(got)}")
    return [vr.get("values") for vr in got]


def to_csv(rows):
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    while rows and not any(c.strip() for c in rows[-1]):   # drop fully empty trailing rows
        rows.pop()
    width = max((len(r) for r in rows), default=0)        # the API leaves off empty cells at a row's end
    rows = [r + [""] * (width - len(r)) for r in rows]
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue(), rows


def main():
    try:
        tabs = read_ranges()
    except Exception as e:
        for name, _ in TABS: warn(f"{name}: the sheet could not be read ({type(e).__name__}: {e})")
        return
    for (name, rng), values in zip(TABS, tabs):
        path = OUT / name
        try:
            if values is None:
                raise ValueError("the tab came back empty")
            text, rows = to_csv(values)
            if len(rows) < 2 or not any(c.strip() for c in rows[0]):
                raise ValueError("no header row and data rows")
            if any(EMAIL.search(c) for r in rows for c in r):
                raise ValueError("a cell holds an email address; these files take aggregate counts only")
            if path.exists():
                old = len([l for l in csv.reader(io.StringIO(path.read_text(encoding="utf-8")))])
                if old > 1 and len(rows) < old * 0.5:
                    raise ValueError(f"down to {len(rows) - 1} rows from {old - 1}")
            tmp = path.with_suffix(".csv.tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
            print(f"ok: {name} from {rng.split('!')[0]}, {len(rows[0])} columns, {len(rows) - 1} data rows", flush=True)
        except Exception as e:
            warn(f"{name}: {e}")


if __name__ == "__main__":
    main()
