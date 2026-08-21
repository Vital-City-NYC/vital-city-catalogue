#!/usr/bin/env python3
"""Repair malformed names in the contact database.

Josh spotted two in the tool — "Abbey, Esq." as a surname and "and Susanne von
Türk" as a surname — and an audit of all 11,788 named records found 63 with
structural problems, roughly half injected by the August research merges and
half pre-existing.

TWO DIFFERENT BUGS, TWO DIFFERENT FIXES
The first was the DISPLAY SPLITTER, not the data: "Roger G. Arrieux, Jr." is his
name, correctly stored; the tool was just putting "Arrieux, Jr." in the surname
column. Fixed in network/index.html — credentials and generational suffixes no
longer become surnames. That repaired ~29 records without touching any data.

What remains here is names that are genuinely wrong as stored:
  credentials      "Pam Mattel, LCSW" — a credential is not part of a name.
                   Generational suffixes (Jr., III) ARE and are kept.
  honorifics       "Prof. James E. Moore", and guesses like "Mrs Jennifertibbs"
                   built from mrs.jennifertibbs@gmail.com.
  reversed         "Ross, David E."
  not a name       "Joanna@Mikulskistrategies.Com", a bare "Ph.D."
  two people       "Philipp and Susanne von Türk" gets an explicit first/last
                   split rather than a guess; the household stays one record.

Everything is written to name_overrides.csv, so it survives the nightly rebuild
and is reversible in one file.

    python3 fix_names.py --dry-run
    python3 fix_names.py
"""
import argparse, csv, json, re, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
OVERRIDES = PRIV / "name_overrides.csv"

CRED = re.compile(r"[,\s]+(esq|m\.?d|ph\.?d|j\.?d|mba|cfa|cpa|rn|lcsw(-r)?|dds|edd|msw|mph|"
                  r"do|sjd|mpa|dsw|psyd|dvm)\.?\s*$", re.I)
HON = re.compile(r"^(dr|mr|mrs|ms|prof|professor|hon|rev|sir|dame)\.?\s+", re.I)
BARE_CRED = re.compile(r"^(ph\.?d|m\.?d|j\.?d|esq|jd|md|rn|ms|mr|mrs|dr)\.?$", re.I)

# Names no rule should touch — a person is two people, or the stored string is
# beyond repair. Handled explicitly, with the reasoning visible.
EXPLICIT = {
    "svonturk@gmail.com":        {"n": "Philipp and Susanne von Türk",
                                  "fn": "Philipp and Susanne", "ln": "von Türk",
                                  "why": "a couple sharing one subscription; split explicitly so the surname column is right"},
    "raja.aurangzeb345@gmail.com": {"n": "Aurangzeb Raja", "why": "trailing 'and' with nothing after it"},
    "deross56@gmail.com":        {"n": "David E. Ross", "why": "stored surname-first"},
    "hcyourow@msn.com":          {"n": "Howard Charles Yourow", "why": "credential run onto the surname without a space"},
    "joanna@mikulskistrategies.com": {"n": "Joanna", "why": "the whole email address was in the name field"},
    "sjsimon@arizona.edu":       {"n": "Samantha Simon Jones", "why": "email handle appended to the name"},
}


def rederive_from_address(email):
    """When the guesser built a name from an address that begins with an
    honorific — mr.caden.johnson.1234@gmail.com became "Mr Johnson" — the
    address still holds the real name. Drop the honorific and read the rest."""
    local = email.split("@")[0]
    parts = [x for x in re.split(r"[._\-]+", local) if x]
    if not parts or not re.fullmatch(r"(dr|mr|mrs|ms|prof|rev)", parts[0], re.I):
        return None
    rest = [x for x in parts[1:] if not x.isdigit() and len(x) > 1]
    # dr.u.m.mondp.art.y@ is scattered noise, not a name. Require every part to
    # read like a word — otherwise leave it as the marked guess it already is.
    if len(rest) < 2 or any(len(x) < 4 or not x.isalpha() for x in rest[:2]):
        return None
    return " ".join(x.capitalize() for x in rest[:3])


def repair(n):
    """Return a cleaned name, or None if nothing needed changing."""
    out = n.strip()
    if BARE_CRED.match(out):
        return ""                      # a credential alone is not a name
    prev = None
    while prev != out:                 # "Deborah Tucker, MPA, PhD"
        prev = out
        out = CRED.sub("", out).strip().rstrip(",").strip()
    out = HON.sub("", out).strip()
    out = re.sub(r"\s{2,}", " ", out)
    return out if out != n.strip() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    people = json.loads((PRIV / "people.json").read_text())

    rows = {}
    if OVERRIDES.exists():
        for r in csv.DictReader(OVERRIDES.open()):
            rows[(r.get("email") or "").strip().lower()] = r

    changes = []
    for p in people:
        em = (p.get("e") or "").strip().lower()
        n = (p.get("n") or "").strip()
        if not em:
            continue
        if em in EXPLICIT:
            e = EXPLICIT[em]
            row = rows.get(em, {"email": em})
            row["name"] = e["n"]
            if e.get("fn"): row["fn"] = e["fn"]
            if e.get("ln"): row["ln"] = e["ln"]
            rows[em] = row
            if n != e["n"] or e.get("fn"):
                changes.append((em, n, e["n"], e["why"]))
            continue
        if not n:
            continue
        fixed = repair(n)
        if fixed is None:
            continue
        better = rederive_from_address(em) if HON.match(n) else None
        if better:
            fixed = better
        row = rows.get(em, {"email": em})
        row["name"] = fixed
        rows[em] = row
        why = ("re-read from the address, which held the full name" if better
               else "credential or honorific stripped" if fixed else "not a name")
        changes.append((em, n, fixed, why))

    print(f"{len(changes)} names repaired\n")
    for em, before, after, why in sorted(changes, key=lambda x: x[3]):
        print(f"  {before[:34]:<36} -> {(after or '(blank)')[:28]:<30} {why[:46]}")
    if a.dry_run:
        print("\n(dry run — nothing written)")
        return
    cols = ["email", "name", "fn", "ln", "inst", "role", "excl", "seg", "nyc", "oom"]
    shutil.copy(OVERRIDES, OVERRIDES.with_suffix(".csv.bak"))
    with OVERRIDES.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for em in sorted(rows):
            w.writerow(rows[em])
    print(f"\nwrote {OVERRIDES} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
