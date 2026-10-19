#!/usr/bin/env python3
"""Weekly subscriber report: who joined, who left, and how to sync the two lists.

    Signups come in through Ghost (the website form).
    The newsletter goes out through Mailchimp, so unsubscribes land there.

Every Wednesday this answers three questions for the person who does the
Thursday sync by hand:
  1. Who subscribed in the past 7 days (Ghost, by Ghost signup time)?
  2. Who unsubscribed in the past 7 days (Mailchimp, by Mailchimp date; plus
     the few who unsubscribed on the website, from Ghost's own event log)?
  3. Exactly what to import where so both lists hold the same active
     subscribers under their current names.

READ-ONLY. It never writes to Ghost or Mailchimp. It writes a report and
ready-to-import CSV files to ~/Desktop/Vital City subscriber sync/<date>/ and a
short Slack-ready summary (summary.txt) beside them.

USAGE
    python3 weekly_subscriber_report.py              # window = the 7 days to now
    python3 weekly_subscriber_report.py --out DIR    # write somewhere else

KEYS: MAILCHIMP_KEY / GHOST_ADMIN_KEY from the environment, falling back to
private/.mailchimp_key and private/.ghost_admin_key.

The output lists subscriber names and emails. It goes to the Desktop and a
Slack self-DM only, never into this repo (which is public).
"""
import argparse, csv, datetime as dt, html, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for var, fname in (("MAILCHIMP_KEY", ".mailchimp_key"), ("GHOST_ADMIN_KEY", ".ghost_admin_key")):
    if not os.environ.get(var) and (ROOT / "private" / fname).exists():
        os.environ[var] = (ROOT / "private" / fname).read_text().strip()

import reconcile_subscribers as rs   # API helpers + the fail-loud guard rails

UTC = dt.timezone.utc
DEAD = {"unsubscribed", "cleaned"}


def parse_ts(s):
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def et(ts):
    """Show times in New York time, the way staff read them."""
    from zoneinfo import ZoneInfo
    return ts.astimezone(ZoneInfo("America/New_York"))


def split_name(full):
    full = " ".join((full or "").split())
    if not full:
        return "", ""
    first, _, last = full.partition(" ")
    return first, last


def norm(s):
    return " ".join((s or "").lower().split())


# ------------------------------------------------------------------ fetching
def mc_everyone(key, dc, list_id):
    out, offset = {}, 0
    fields = ("members.email_address,members.status,members.merge_fields.FNAME,"
              "members.merge_fields.LNAME,members.last_changed,members.unsubscribe_reason,total_items")
    while True:
        page = rs.mc_call(f"/lists/{list_id}/members?count=1000&offset={offset}&fields={fields}", key, dc)
        rows = page.get("members") or []
        for m in rows:
            e = (m.get("email_address") or "").strip().lower()
            if not e:
                continue
            mf = m.get("merge_fields") or {}
            out[e] = {"status": m.get("status"),
                      "first": (mf.get("FNAME") or "").strip(),
                      "last": (mf.get("LNAME") or "").strip(),
                      "changed": parse_ts(m.get("last_changed")),
                      "reason": (m.get("unsubscribe_reason") or "").strip()}
        offset += 1000
        if offset >= int(page.get("total_items") or 0) or not rows:
            break
    return out


def ghost_everyone():
    out, page = [], 1
    while True:
        d = rs.ghost_call(f"/members/?limit=500&page={page}"
                          "&fields=id,email,name,created_at,subscribed,geolocation&include=newsletters")
        rows = d.get("members") or []
        for m in rows:
            geo = m.get("geolocation") or ""
            try:
                import json
                g = json.loads(geo) if geo else {}
                where = ", ".join(x for x in (g.get("region"), g.get("country")) if x)
            except Exception:
                where = ""
            out.append({"id": m.get("id"),
                        "email": (m.get("email") or "").strip().lower(),
                        "name": " ".join((m.get("name") or "").split()),
                        "created": parse_ts(m.get("created_at")),
                        "active": bool(m.get("subscribed")) and bool(m.get("newsletters")),
                        "where": where})
        pg = (d.get("meta") or {}).get("pagination") or {}
        if page >= (pg.get("pages") or 1) or not rows:
            break
        page += 1
    return out


def ghost_newsletter_events(since):
    """Newsletter subscribe/unsubscribe events on the website side, newest first."""
    out, page = [], 1
    while page <= 40:
        d = rs.ghost_call(f"/members/events/?limit=100&page={page}&filter=type:newsletter_event")
        rows = d.get("events") or []
        older = False
        for ev in rows:
            data = ev.get("data") or {}
            ts = parse_ts(data.get("created_at"))
            if ts and ts < since:
                older = True
                break
            out.append({"member_id": data.get("member_id"), "at": ts,
                        "subscribed": bool(data.get("subscribed"))})
        if older or not rows:
            break
        page += 1
    return out


# ------------------------------------------------------------------ analysis
def name_upgrade(mc_name, ghost_name):
    """True when the Ghost name only adds to what Mailchimp has: Mailchimp is
    blank, or holds just a first name that the Ghost name starts with. Any
    other difference is a judgment call and goes to a person, because the
    Mailchimp version is sometimes the fuller one."""
    m, g = norm(mc_name), norm(ghost_name)
    if not m:
        return True
    return " " not in m and g.startswith(m + " ")


def analyse(ghost, mc, g_events, since):
    by_id = {g["id"]: g for g in ghost}
    by_email = {g["email"]: g for g in ghost if g["email"]}
    g_unsubs = [ev for ev in g_events if not ev["subscribed"]]
    last_join = {}            # member id -> latest website subscribe this week
    for ev in g_events:
        if ev["subscribed"] and ev["at"]:
            last_join[ev["member_id"]] = max(ev["at"], last_join.get(ev["member_id"], ev["at"]))

    # 1. New subscribers this week (Ghost signup time), still subscribed.
    new = []
    for g in ghost:
        if g["created"] and g["created"] >= since and g["email"]:
            m = mc.get(g["email"])
            new.append({**g, "mc": m["status"] if m else None})
    new.sort(key=lambda r: r["created"])

    # 2a. Unsubscribed (or bounced) in Mailchimp this week.
    left_mc = []
    for e, m in mc.items():
        if m["status"] in DEAD and m["changed"] and m["changed"] >= since:
            g = by_email.get(e)
            name = (g or {}).get("name") or " ".join(x for x in (m["first"], m["last"]) if x)
            left_mc.append({"email": e, "name": name, "at": m["changed"], "status": m["status"],
                            "reason": m["reason"], "ghost_active": bool(g and g["active"])})
    left_mc.sort(key=lambda r: r["at"])

    # 2b. Unsubscribed on the website this week, per Ghost's event log.
    left_ghost, seen = [], set()
    for ev in g_unsubs:
        g = by_id.get(ev["member_id"])
        if not g or g["email"] in seen or g["active"]:
            continue          # resubscribed since, or not findable
        seen.add(g["email"])
        m = mc.get(g["email"])
        left_ghost.append({"email": g["email"], "name": g["name"], "at": ev["at"],
                           "mc": m["status"] if m else None})
    left_ghost.sort(key=lambda r: r["at"])

    # 3. The to-do lists, computed from the whole of both lists (not just this
    #    week) so stragglers from earlier weeks are caught too.
    add_mc, fix_names, check_names, backlog, rejoined = [], [], [], [], []
    for g in ghost:
        e = g["email"]
        if not g["active"] or "@" not in e:
            continue
        m = mc.get(e)
        if m is None:
            add_mc.append(g)
        elif m["status"] in DEAD:
            row = {"email": e, "name": g["name"], "status": m["status"], "at": m["changed"]}
            joined = max(x for x in (g["created"], last_join.get(g["id"])) if x)
            if m["changed"] and joined > m["changed"]:
                # Signed up on the website AFTER leaving Mailchimp: they want
                # back in. Never unsubscribe these in Ghost.
                rejoined.append({**row, "joined": joined})
            else:
                backlog.append(row)
        elif m["status"] == "subscribed" and g["name"]:
            mc_name = " ".join(x for x in (m["first"], m["last"]) if x)
            if norm(mc_name) != norm(g["name"]):
                row = {"email": e, "ghost": g["name"], "mc": mc_name}
                (fix_names if name_upgrade(mc_name, g["name"]) else check_names).append(row)
    add_mc.sort(key=lambda r: r["created"] or since)

    week_emails = {r["email"] for r in left_mc}
    unsub_ghost_week = [r for r in backlog if r["email"] in week_emails]
    unsub_mc = [r for r in left_ghost if r["mc"] == "subscribed"]

    return {"new": new, "left_mc": left_mc, "left_ghost": left_ghost,
            "add_mc": add_mc, "fix_names": fix_names, "check_names": check_names,
            "backlog": backlog, "rejoined": rejoined,
            "unsub_ghost_week": unsub_ghost_week, "unsub_mc": unsub_mc,
            "ghost_active": sum(1 for g in ghost if g["active"]),
            "mc_active": sum(1 for m in mc.values() if m["status"] == "subscribed")}


# ------------------------------------------------------------------- writing
def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def fmt_day(ts):
    return et(ts).strftime("%a %b %-d, %-I:%M %p") if ts else ""


def build(out_dir, a, since, now):
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = et(now).strftime("%Y-%m-%d")
    tag = f"ghost-sync-{stamp}"

    # File 1: one Mailchimp import that adds new people AND corrects names.
    mc_rows = [(g["email"], *split_name(g["name"])) for g in a["add_mc"]]
    mc_rows += [(r["email"], *split_name(r["ghost"])) for r in a["fix_names"]]
    files = {}
    if mc_rows:
        files["mc"] = "1-import-to-mailchimp-as-subscribed.csv"
        write_csv(out_dir / files["mc"], ["Email Address", "First Name", "Last Name"], mc_rows)
    if a["unsub_ghost_week"]:
        files["ghost"] = "2-unsubscribe-in-ghost.csv"
        write_csv(out_dir / files["ghost"], ["email", "labels"],
                  [(r["email"], f"unsub-{stamp}") for r in a["unsub_ghost_week"]])
    if a["unsub_mc"]:
        files["mc_unsub"] = "3-import-to-mailchimp-as-unsubscribed.csv"
        write_csv(out_dir / files["mc_unsub"], ["Email Address", "First Name", "Last Name"],
                  [(r["email"], *split_name(r["name"])) for r in a["unsub_mc"]])
    if a["backlog"]:
        files["backlog"] = "optional-full-backlog-unsubscribe-in-ghost.csv"
        write_csv(out_dir / files["backlog"], ["email", "labels"],
                  [(r["email"], f"unsub-backlog-{stamp}") for r in a["backlog"]])

    # ---- the report page
    E = html.escape
    def table(head, rows):
        if not rows:
            return "<p class=none>None.</p>"
        h = "".join(f"<th>{E(x)}</th>" for x in head)
        b = "".join("<tr>" + "".join(f"<td>{E(str(c))}</td>" for c in r) + "</tr>" for r in rows)
        return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"

    def mc_label(s):
        return {"subscribed": "Yes", None: "Not yet", "unsubscribed": "Unsubscribed there",
                "cleaned": "Bounced there", "pending": "Pending"}.get(s, s)

    window = f"{fmt_day(since)} to {fmt_day(now)}"
    new_rows = [(g["name"] or "(no name given)", g["email"], fmt_day(g["created"]),
                 g["where"], "Yes" if g["active"] else "Already unsubscribed", mc_label(g["mc"]))
                for g in a["new"]]
    left_rows = [(r["name"] or "(no name)", r["email"], fmt_day(r["at"]),
                  "Bounced" if r["status"] == "cleaned" else "Unsubscribed",
                  r["reason"] if r["status"] == "unsubscribed" else "",
                  "Still subscribed" if r["ghost_active"] else "Off")
                 for r in a["left_mc"]]
    lg_rows = [(r["name"] or "(no name)", r["email"], fmt_day(r["at"]), mc_label(r["mc"]))
               for r in a["left_ghost"]]
    fix_rows = [(r["email"], r["mc"] or "(blank)", r["ghost"]) for r in a["fix_names"]]
    check_rows = [(r["email"], r["mc"], r["ghost"]) for r in a["check_names"]]
    rejoin_rows = [(r["name"] or "(no name)", r["email"], fmt_day(r["at"]), fmt_day(r["joined"]))
                   for r in a["rejoined"]]

    steps = []
    n_add, n_fix = len(a["add_mc"]), len(a["fix_names"])
    if "mc" in files:
        what = []
        if n_add: what.append(f"adds {n_add} new subscriber{'s' * (n_add != 1)}")
        if n_fix: what.append(f"corrects {n_fix} name{'s' * (n_fix != 1)}")
        steps.append(f"""<li><b>Mailchimp: add new subscribers and fix names.</b> File: <code>{files['mc']}</code> ({' and '.join(what)}).
<ol type=a>
<li>Audience &rarr; Add contacts &rarr; Import contacts &rarr; Upload a file. Choose the file.</li>
<li>Status: <b>Subscribed</b>. Tick <b>Update any existing contacts</b> (this is what fixes the names).</li>
<li>Add the tag <code>{tag}</code> so this batch can be found later.</li>
<li>Match the columns: Email Address, First Name, Last Name. Complete the import.</li>
</ol>
Mailchimp will not resubscribe anyone who unsubscribed there, so this file cannot undo an unsubscribe.</li>""")
    if "ghost" in files:
        n = len(a["unsub_ghost_week"])
        steps.append(f"""<li><b>Ghost: turn off the newsletter for this week's Mailchimp unsubscribes.</b> File: <code>{files['ghost']}</code> ({n} {'person' if n == 1 else 'people'}).
<ol type=a>
<li>Ghost admin &rarr; Members &rarr; the gear menu &rarr; Import members. Choose the file. It only adds the label <code>unsub-{stamp}</code> to people already there.</li>
<li>In Members, filter by that label. From the gear menu choose <b>Unsubscribe</b> (not Delete). Deleting erases signup history.</li>
</ol></li>""")
    if "mc_unsub" in files:
        n = len(a["unsub_mc"])
        steps.append(f"""<li><b>Mailchimp: unsubscribe people who unsubscribed on the website.</b> File: <code>{files['mc_unsub']}</code> ({n}).
Import as in step 1, but set Status to <b>Unsubscribed</b> and tick <b>Update any existing contacts</b>.</li>""")
    if a["rejoined"]:
        n = len(a["rejoined"])
        steps.append(f"""<li><b>Mailchimp: {n} {'person' if n == 1 else 'people'} signed up again after unsubscribing.</b> Listed below under "Signed up again." Mailchimp will not re-add someone who unsubscribed, by import or by hand; they have to opt back in themselves. Send each one the Mailchimp signup form link (Audience &rarr; Signup forms) and Mailchimp will email them a confirmation. Do not unsubscribe them in Ghost.</li>""")
    if not steps:
        steps.append("<li><b>Nothing to do.</b> The two lists agree on everyone who is active.</li>")
    steps.append("""<li><b>Check.</b> Next Wednesday's report should show none of these people again. Anyone who reappears did not take.</li>""")

    backlog_note = ""
    if a["backlog"]:
        backlog_note = f"""<h2>Older unsubscribes still on in Ghost: {len(a['backlog']):,}</h2>
<p>People who unsubscribed or bounced in Mailchimp in earlier weeks but are still marked subscribed in Ghost. On Sept. 23 the call was to leave these alone, since Ghost does not send the newsletter. Mailchimp already stops mailing them, and step 1 cannot re-add them. If Ghost is ever going to send, clear them with <code>{files['backlog']}</code>, using step 2's method.</p>"""

    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Subscriber sync {stamp}</title>
<style>
:root{{--ink:#111;--mute:#666;--line:#e3e3e3;--bg:#fff;--hi:#dde44c}}
body{{font:15px/1.5 -apple-system,system-ui,sans-serif;color:var(--ink);background:var(--bg);max-width:960px;margin:32px auto;padding:0 16px}}
h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:18px;margin:32px 0 8px}}
.dek{{color:var(--mute);margin:0 0 20px}}
.nums{{display:flex;gap:28px;flex-wrap:wrap;margin:16px 0 8px}}
.nums div b{{display:block;font-size:28px}} .nums div{{color:var(--mute);font-size:13px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font-weight:600}} code{{background:#f3f3f3;padding:1px 4px;border-radius:3px}}
ol>li{{margin-bottom:12px}} .todo{{background:#fafae8;padding:12px 18px 4px 36px;border-left:4px solid var(--hi)}}
.none{{color:var(--mute)}} .wrap{{overflow-x:auto}}
</style></head><body>
<h1>Subscriber sync, week ending {et(now).strftime('%b %-d, %Y')}</h1>
<p class=dek>{E(window)}. Signups from Ghost, unsubscribes from Mailchimp. Read-only: nothing was changed in either system.</p>
<div class=nums>
<div><b>{len(a['new'])}</b>new subscribers</div>
<div><b>{len(a['left_mc']) + len(a['left_ghost'])}</b>unsubscribed or bounced</div>
<div><b>{a['ghost_active']:,}</b>active in Ghost</div>
<div><b>{a['mc_active']:,}</b>active in Mailchimp</div>
</div>
<h2>To do before Thursday's send</h2>
<ol class=todo>{''.join(steps)}</ol>
<h2>New subscribers ({len(a['new'])})</h2><div class=wrap>
{table(['Name', 'Email', 'Signed up', 'Location', 'Still subscribed', 'In Mailchimp'], new_rows)}</div>
<h2>Unsubscribed in Mailchimp ({len(a['left_mc'])})</h2><div class=wrap>
{table(['Name', 'Email', 'When', 'What', 'Reason given', 'In Ghost'], left_rows)}</div>
<h2>Unsubscribed on the website ({len(a['left_ghost'])})</h2><div class=wrap>
{table(['Name', 'Email', 'When', 'In Mailchimp'], lg_rows)}</div>
<h2>Name corrections for Mailchimp ({len(fix_rows)})</h2>
<p class=dek>Mailchimp has no name, or only a first name, and Ghost has the fuller name the person typed at signup. Already included in step 1's file.</p><div class=wrap>
{table(['Email', 'Mailchimp now', 'Change to'], fix_rows)}</div>
<h2>Names that differ: check by hand ({len(check_rows)})</h2>
<p class=dek>Active in both, but the names disagree in a way a machine should not settle (a middle name, a nickname, a fuller name in Mailchimp). Not in any file. If the Ghost version is right, change the contact in Mailchimp.</p><div class=wrap>
{table(['Email', 'Mailchimp', 'Ghost'], check_rows)}</div>
<h2>Signed up again after unsubscribing ({len(rejoin_rows)})</h2><div class=wrap>
{table(['Name', 'Email', 'Left Mailchimp', 'Rejoined on website'], rejoin_rows)}</div>
{backlog_note}
<p class=dek style="margin-top:32px">Active means subscribed to the newsletter. The two active totals differ mostly because of the older unsubscribes above and contacts added to Mailchimp directly (imports, old forms, Donorbox).</p>
</body></html>"""
    (out_dir / "report.html").write_text(page)

    # ---- Slack-ready summary (names included: it goes to a self-DM only)
    S = [f"*Vital City subscriber sync, week ending {et(now).strftime('%b %-d')}*",
         f"{len(a['new'])} new subscribers, {len(a['left_mc']) + len(a['left_ghost'])} unsubscribed or bounced.",
         ""]
    if a["new"]:
        S.append("*New (Ghost):*")
        S += [f"• {g['name'] or '(no name)'} ({g['email']})" for g in a["new"][:40]]
        if len(a["new"]) > 40: S.append(f"…and {len(a['new']) - 40} more in the report")
        S.append("")
    left = [(r["name"], r["email"], "bounced" if r["status"] == "cleaned" else "Mailchimp") for r in a["left_mc"]]
    left += [(r["name"], r["email"], "website") for r in a["left_ghost"]]
    if left:
        S.append("*Unsubscribed:*")
        S += [f"• {n or '(no name)'} ({e}), {how}" for n, e, how in left[:40]]
        if len(left) > 40: S.append(f"…and {len(left) - 40} more in the report")
        S.append("")
    S.append("*To do before Thursday:*")
    k = 1
    if "mc" in files:
        S.append(f"{k}. Mailchimp: import `{files['mc']}` as Subscribed, with Update existing contacts ticked ({n_add} new, {n_fix} name fixes)."); k += 1
    if "ghost" in files:
        S.append(f"{k}. Ghost: import `{files['ghost']}`, filter by its label, Unsubscribe ({len(a['unsub_ghost_week'])})."); k += 1
    if "mc_unsub" in files:
        S.append(f"{k}. Mailchimp: import `{files['mc_unsub']}` as Unsubscribed ({len(a['unsub_mc'])})."); k += 1
    if a["rejoined"]:
        S.append(f"{k}. Mailchimp: {len(a['rejoined'])} rejoined on the website after unsubscribing; send them the Mailchimp signup link (names in the report)."); k += 1
    if k == 1:
        S.append("Nothing. The lists agree.")
    if a["check_names"]:
        S.append(f"Also: {len(a['check_names'])} names differ between the lists in ways to check by hand (in the report).")
    S.append("")
    S.append(f"Step-by-step instructions and the files: ~/Desktop/Vital City subscriber sync/{out_dir.name}/report.html")
    (out_dir / "summary.txt").write_text("\n".join(S))
    return out_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="output folder (default: ~/Desktop/Vital City subscriber sync/<date>)")
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()

    now = dt.datetime.now(UTC)
    since = now - dt.timedelta(days=a.days)
    try:
        key, dc = rs.mc_creds()
        list_id = rs.mc_list_id(key, dc)
        rs.log("fetching Mailchimp…")
        mc = mc_everyone(key, dc, list_id)
        rs.log("fetching Ghost…")
        ghost = ghost_everyone()
        g_events = ghost_newsletter_events(since)
        if len(ghost) < rs.MIN_GHOST_MEMBERS or len(mc) < rs.MIN_MC_MEMBERS:
            raise rs.Abort(f"implausibly small fetch (Ghost {len(ghost)}, Mailchimp {len(mc)}); "
                           "refusing to report on a truncated list")
    except rs.Abort as e:
        print(f"REPORT FAILED: {e}", file=sys.stderr)
        return 2

    res = analyse(ghost, mc, g_events, since)
    out = Path(a.out) if a.out else Path.home() / "Desktop" / "Vital City subscriber sync" / et(now).strftime("%Y-%m-%d")
    build(out, res, since, now)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
