#!/usr/bin/env python3
"""Reconcile the newsletter list between Ghost and Mailchimp.

    Ghost  --(new subscribers)-->  Mailchimp
    Mailchimp --(unsubscribes)-->  Ghost

WHAT THIS REPLACES
Two jobs a person currently does by hand every week: pushing people who signed up
on the website (Ghost) into the Mailchimp audience, and reflecting Mailchimp
unsubscribes back into Ghost so we stop sending to them.

    ############################################################
    #  THIS IS OFF.  Dry run is the default and the ONLY mode  #
    #  unless BOTH --apply and RECONCILE_ALLOW_WRITES=yes are  #
    #  supplied.  Nothing is wired to a schedule.              #
    ############################################################

USAGE
    python3 reconcile_subscribers.py                 # dry run, prints a plan
    python3 reconcile_subscribers.py --json out.json # dry run + machine-readable plan
    python3 reconcile_subscribers.py --self-test     # logic tests, no network
    RECONCILE_ALLOW_WRITES=yes python3 reconcile_subscribers.py --apply   # writes

ENV
    MAILCHIMP_KEY, GHOST_ADMIN_KEY  (same secrets the refresh workflow uses)

SAFETY RULES BAKED IN — do not weaken without thinking hard
 1. NEVER DELETES A GHOST MEMBER. "Remove from the Ghost list" means clear their
    newsletter subscription. Deleting destroys signup date, source attribution and
    history, and cannot be undone.
 2. NO PING-PONG. Anyone Mailchimp lists as unsubscribed/cleaned is excluded from
    the Ghost->Mailchimp push. Without this the two tasks fight forever: task 2
    unsubscribes them, Ghost still says subscribed, task 1 re-adds them, repeat.
 3. FAILS LOUD. If either API returns an implausibly small population the run
    aborts. A truncated fetch must never be read as "everyone unsubscribed".
 4. CHANGE CAP. More than MAX_CHANGES proposed on either side and the run stops
    and asks for a human. A correct routine run is small.
 5. IDEMPOTENT. Running twice with no new activity proposes nothing the 2nd time.
 6. AUDIT TRAIL. Every run writes the full plan to private/reconcile_log/.
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
LOGDIR = PRIV / "reconcile_log"

# --- guard rails -----------------------------------------------------------
MAX_CHANGES      = 300    # per side, per run; above this we stop and ask a human
MIN_GHOST_MEMBERS = 5000  # sanity floor: the list is ~11k. Below this, abort.
MIN_MC_MEMBERS    = 5000
GHOST_API = "https://vital-city.ghost.io/ghost/api/admin"
UA = "vital-city-reconciler/1.0"


def log(m): print(m, file=sys.stderr, flush=True)


class Abort(Exception):
    """Refuse to proceed. Always means: change nothing, tell a human."""


# ---------------------------------------------------------------- Mailchimp
def mc_creds():
    k = os.environ.get("MAILCHIMP_KEY")
    if not k or "-" not in k:
        raise Abort("MAILCHIMP_KEY missing or malformed")
    return k, k.rsplit("-", 1)[1]


def mc_call(path, key, dc, method="GET", body=None):
    url = f"https://{dc}.api.mailchimp.com/3.0{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Basic " + __import__("base64").b64encode(f"anystring:{key}".encode()).decode(),
        "Content-Type": "application/json", "User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:400]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1)); continue
            raise Abort(f"Mailchimp {method} {path} -> {e.code}: {detail}")
        except Exception:
            if attempt == 2: raise
            time.sleep(2 * (attempt + 1))


def mc_list_id(key, dc):
    ls = mc_call("/lists?count=20&fields=lists.id,lists.name,lists.stats.member_count", key, dc).get("lists") or []
    if not ls:
        raise Abort("no Mailchimp audience found")
    return max(ls, key=lambda l: (l.get("stats") or {}).get("member_count") or 0)["id"]


def mc_members(key, dc, list_id):
    """email -> status, for every member regardless of status."""
    out, offset = {}, 0
    while True:
        page = mc_call(f"/lists/{list_id}/members?count=1000&offset={offset}"
                       f"&fields=members.email_address,members.status,total_items", key, dc)
        rows = page.get("members") or []
        for m in rows:
            e = (m.get("email_address") or "").strip().lower()
            if e: out[e] = m.get("status")
        total = int(page.get("total_items") or 0)
        offset += 1000
        if offset >= total or not rows: break
    return out


# -------------------------------------------------------------------- Ghost
def ghost_token():
    key = os.environ.get("GHOST_ADMIN_KEY") or ""
    if ":" not in key:
        raise Abort("GHOST_ADMIN_KEY missing or malformed (expect id:secret)")
    import hmac, hashlib, base64
    kid, secret = key.split(":", 1)
    now = int(time.time())
    hdr = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid}).encode()).rstrip(b"=")
    pay = base64.urlsafe_b64encode(json.dumps({"iat": now, "exp": now + 300, "aud": "/admin/"}).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(hmac.new(bytes.fromhex(secret), hdr + b"." + pay, hashlib.sha256).digest()).rstrip(b"=")
    return (hdr + b"." + pay + b"." + sig).decode()


def ghost_call(path, method="GET", body=None):
    req = urllib.request.Request(
        GHOST_API + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": "Ghost " + ghost_token(), "Accept-Version": "v5.0",
                 "Content-Type": "application/json", "User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:400]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1)); continue
            raise Abort(f"Ghost {method} {path} -> {e.code}: {detail}")
        except Exception:
            if attempt == 2: raise
            time.sleep(2 * (attempt + 1))


def ghost_members():
    """[{id, email, subscribed, newsletters[], created_at}] for every member."""
    out, page = [], 1
    while True:
        d = ghost_call(f"/members/?limit=500&page={page}&fields=id,email,created_at,subscribed&include=newsletters")
        rows = d.get("members") or []
        for m in rows:
            out.append({
                "id": m.get("id"),
                "email": (m.get("email") or "").strip().lower(),
                "subscribed": bool(m.get("subscribed")),
                "newsletters": [n.get("id") for n in (m.get("newsletters") or []) if n.get("id")],
                "created_at": m.get("created_at"),
            })
        pg = (d.get("meta") or {}).get("pagination") or {}
        if page >= (pg.get("pages") or 1) or not rows: break
        page += 1
    return out


# ------------------------------------------------------------------ planning
def build_plan(ghost, mc):
    """Pure function: given both populations, decide what should change.

    ghost: list of member dicts (see ghost_members)
    mc:    {email: status}   status in {subscribed, unsubscribed, cleaned, pending, ...}
    Returns {"to_mailchimp": [...], "to_ghost_unsub": [...], "skipped_pingpong": [...]}
    """
    DEAD = {"unsubscribed", "cleaned"}           # stop sending, either way
    to_mc, to_ghost, skipped = [], [], []

    for g in ghost:
        e = g["email"]
        if not e or "@" not in e:
            continue
        status = mc.get(e)

        # TASK 1 — new Ghost subscribers that Mailchimp has never seen.
        if g["subscribed"] and g["newsletters"]:
            if status is None:
                to_mc.append({"email": e, "ghost_id": g["id"], "created_at": g.get("created_at")})
            elif status in DEAD:
                # RULE 2: do NOT re-add. Mailchimp is the system of record for
                # unsubscribes; pushing them back starts the ping-pong loop.
                skipped.append({"email": e, "mc_status": status,
                                "why": "unsubscribed in Mailchimp — would loop"})

        # TASK 2 — Mailchimp unsubscribes that Ghost still sends to.
        if status in DEAD and g["subscribed"] and g["newsletters"]:
            to_ghost.append({"email": e, "ghost_id": g["id"], "mc_status": status})

    return {"to_mailchimp": to_mc, "to_ghost_unsub": to_ghost, "skipped_pingpong": skipped}


def check_guardrails(ghost, mc, plan):
    if len(ghost) < MIN_GHOST_MEMBERS:
        raise Abort(f"Ghost returned only {len(ghost)} members (floor {MIN_GHOST_MEMBERS}). "
                    "Refusing to act on what looks like a truncated fetch.")
    if len(mc) < MIN_MC_MEMBERS:
        raise Abort(f"Mailchimp returned only {len(mc)} members (floor {MIN_MC_MEMBERS}). "
                    "Refusing to act on what looks like a truncated fetch.")
    for side in ("to_mailchimp", "to_ghost_unsub"):
        if len(plan[side]) > MAX_CHANGES:
            raise Abort(f"{side} proposes {len(plan[side])} changes (cap {MAX_CHANGES}). "
                        "That is not a routine sync — a human should look before anything moves.")


# ------------------------------------------------------------------- applying
def apply_plan(plan, key, dc, list_id, ghost_newsletter_ids):
    """Only reachable with --apply AND RECONCILE_ALLOW_WRITES=yes."""
    done = {"added_to_mailchimp": 0, "unsubscribed_in_ghost": 0, "errors": []}
    for r in plan["to_mailchimp"]:
        try:
            # status_if_new=subscribed; never downgrades an existing record.
            mc_call(f"/lists/{list_id}/members/{__import__('hashlib').md5(r['email'].encode()).hexdigest()}",
                    key, dc, method="PUT",
                    body={"email_address": r["email"], "status_if_new": "subscribed"})
            done["added_to_mailchimp"] += 1
        except Exception as e:
            done["errors"].append(f"mailchimp add {r['email']}: {e}")
    for r in plan["to_ghost_unsub"]:
        try:
            # RULE 1: clear newsletters — do NOT DELETE the member.
            ghost_call(f"/members/{r['ghost_id']}/", method="PUT",
                       body={"members": [{"newsletters": []}]})
            done["unsubscribed_in_ghost"] += 1
        except Exception as e:
            done["errors"].append(f"ghost unsub {r['email']}: {e}")
    return done


# ----------------------------------------------------------------- self-test
def self_test():
    """Logic tests with fixtures — no network, no credentials needed."""
    G = lambda e, sub=True, nl=True, i=None: {
        "id": i or ("g_" + e.split("@")[0]), "email": e, "subscribed": sub,
        "newsletters": (["nl1"] if nl else []), "created_at": "2026-01-01"}
    cases, fails = [], []

    # 1 new Ghost signup, unknown to Mailchimp -> push
    p = build_plan([G("new@x.com")], {})
    cases.append(("new Ghost signup is pushed to Mailchimp",
                  [r["email"] for r in p["to_mailchimp"]] == ["new@x.com"]))

    # 2 THE PING-PONG GUARD: unsubscribed in Mailchimp, still 'subscribed' in Ghost
    p = build_plan([G("gone@x.com")], {"gone@x.com": "unsubscribed"})
    cases.append(("unsubscribed member is NOT re-added to Mailchimp",
                  p["to_mailchimp"] == []))
    cases.append(("...and IS unsubscribed in Ghost",
                  [r["email"] for r in p["to_ghost_unsub"]] == ["gone@x.com"]))
    cases.append(("...and is recorded as skipped, with a reason",
                  len(p["skipped_pingpong"]) == 1))

    # 3 hard-bounced (cleaned) behaves like unsubscribed
    p = build_plan([G("bounce@x.com")], {"bounce@x.com": "cleaned"})
    cases.append(("cleaned/bounced also stops Ghost sending",
                  [r["email"] for r in p["to_ghost_unsub"]] == ["bounce@x.com"]))
    cases.append(("cleaned/bounced is not re-added", p["to_mailchimp"] == []))

    # 4 already in sync -> nothing to do (idempotence)
    p = build_plan([G("ok@x.com")], {"ok@x.com": "subscribed"})
    cases.append(("in-sync member produces no changes",
                  not p["to_mailchimp"] and not p["to_ghost_unsub"]))

    # 5 idempotence after task 2: Ghost now unsubscribed -> still nothing
    p = build_plan([G("gone@x.com", sub=False, nl=False)], {"gone@x.com": "unsubscribed"})
    cases.append(("after unsubscribing in Ghost, a re-run proposes nothing",
                  not p["to_mailchimp"] and not p["to_ghost_unsub"]))

    # 6 a Ghost member who never opted into a newsletter is not pushed
    p = build_plan([G("noopt@x.com", sub=True, nl=False)], {})
    cases.append(("Ghost member with no newsletter is not pushed", p["to_mailchimp"] == []))

    # 7 junk email is ignored
    p = build_plan([G("notanemail")], {})
    cases.append(("malformed email is ignored", p["to_mailchimp"] == []))

    # 8 guard rails
    try:
        check_guardrails([G(f"a{i}@x.com") for i in range(10)], {"x@x.com": "subscribed"},
                         {"to_mailchimp": [], "to_ghost_unsub": []})
        cases.append(("tiny population aborts", False))
    except Abort:
        cases.append(("tiny population aborts", True))
    big = [G(f"b{i}@x.com") for i in range(MIN_GHOST_MEMBERS + 10)]
    bigmc = {f"c{i}@x.com": "subscribed" for i in range(MIN_MC_MEMBERS + 10)}
    try:
        check_guardrails(big, bigmc, {"to_mailchimp": [{}] * (MAX_CHANGES + 1), "to_ghost_unsub": []})
        cases.append(("over-cap change set aborts", False))
    except Abort:
        cases.append(("over-cap change set aborts", True))
    try:
        check_guardrails(big, bigmc, {"to_mailchimp": [{}] * 5, "to_ghost_unsub": [{}] * 5})
        cases.append(("normal-size change set passes", True))
    except Abort:
        cases.append(("normal-size change set passes", False))

    print("\nSELF-TEST")
    for name, ok in cases:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok: fails.append(name)
    print(f"\n{len(cases) - len(fails)}/{len(cases)} passed")
    return 1 if fails else 0


# ------------------------------------------------------------------- report
def build_summary(rec, err=None):
    """The weekly report, as plain text. This is what a person actually reads.

    Written for the person who does this sync by hand: it should answer "is
    there anything for me to do, and does the robot agree with me?" without
    needing to open GitHub. Emails are included because the reviewer needs to
    recognize the names — which is exactly why this goes to a DM and an
    access-controlled artifact, never to the public repo.
    """
    L = []
    if err:
        L.append("*Ghost / Mailchimp sync check - COULD NOT RUN*")
        L.append(f"```{err}```")
        L.append("Nothing was changed. This needs a look.")
        return "\n".join(L)

    p, mode = rec["plan"], rec["mode"]
    add, unsub, skip = p["to_mailchimp"], p["to_ghost_unsub"], p["skipped_pingpong"]
    live = mode == "apply"
    L.append(f"*Ghost / Mailchimp sync check - {rec['at'][:10]}*")
    L.append("_Preview only. Nothing was changed._" if not live else "_LIVE RUN - changes were made._")
    L.append("")
    L.append(f"Ghost members: {rec['ghost_members']:,}   |   Mailchimp records: {rec['mailchimp_records']:,}")
    L.append("")

    if not add and not unsub:
        L.append("*Nothing to do this week.* The two lists agree.")
    else:
        verb = ("Added" if live else "Would add")
        L.append(f"*{verb} to Mailchimp: {len(add)}*  (signed up on the website, not on the list yet)")
        for r in add[:25]:
            L.append(f"  - {r['email']}")
        if len(add) > 25: L.append(f"  ...and {len(add)-25} more (see the attached file)")
        L.append("")
        verb = ("Unsubscribed" if live else "Would unsubscribe")
        L.append(f"*{verb} in Ghost: {len(unsub)}*  (unsubscribed in Mailchimp, still on in Ghost)")
        for r in unsub[:25]:
            L.append(f"  - {r['email']}")
        if len(unsub) > 25: L.append(f"  ...and {len(unsub)-25} more (see the attached file)")

    if skip:
        L.append("")
        L.append(f"_Left alone: {len(skip)} already unsubscribed in Mailchimp. "
                 "Not re-added, on purpose - re-adding them would start a loop._")
    if live and rec.get("result", {}).get("errors"):
        L.append("")
        L.append(f"*{len(rec['result']['errors'])} errors - see the attached file.*")
    if not live:
        L.append("")
        L.append("_This is a preview so it can be checked against how the sync is done by "
                 "hand. It will keep previewing until someone deliberately turns writing on._")
    return "\n".join(L)


def post_slack(text):
    """Post to a Slack DM. Loud on failure: a report nobody receives is worse
    than no report, because it looks like everything is fine."""
    tok, to = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_DM_TO")
    if not tok or not to:
        raise Abort("SLACK_BOT_TOKEN / SLACK_DM_TO not set - report has nowhere to go")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": to, "text": text, "unfurl_links": False}).encode(),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read() or b"{}")
    if not resp.get("ok"):
        raise Abort(f"Slack refused the message: {resp.get('error')}")
    log("posted report to Slack")


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Reconcile Ghost and Mailchimp subscribers.")
    ap.add_argument("--apply", action="store_true",
                    help="actually write. Also requires RECONCILE_ALLOW_WRITES=yes.")
    ap.add_argument("--json", metavar="PATH", help="write the plan as JSON")
    ap.add_argument("--self-test", action="store_true", help="run logic tests, no network")
    ap.add_argument("--slack", action="store_true",
                    help="post the report to Slack (needs SLACK_BOT_TOKEN + SLACK_DM_TO)")
    ap.add_argument("--report", metavar="PATH", help="also write the report as a text file")
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    writes = a.apply and os.environ.get("RECONCILE_ALLOW_WRITES") == "yes"
    if a.apply and not writes:
        log("--apply given but RECONCILE_ALLOW_WRITES is not 'yes'. Staying in DRY RUN.")

    try:
        key, dc = mc_creds()
        list_id = mc_list_id(key, dc)
        log("fetching Mailchimp members…")
        mc = mc_members(key, dc, list_id)
        log(f"  {len(mc):,} Mailchimp records")
        log("fetching Ghost members…")
        ghost = ghost_members()
        log(f"  {len(ghost):,} Ghost members")

        plan = build_plan(ghost, mc)
        check_guardrails(ghost, mc, plan)
    except Abort as e:
        # An abort must still reach a human. Silence would read as "all clear".
        log(f"\nABORTED — nothing was changed.\n  {e}")
        if a.slack:
            try: post_slack(build_summary(None, err=str(e)))
            except Exception as e2: log(f"and the Slack alert also failed: {e2}")
        return 2

    mode = "APPLY (writing)" if writes else "DRY RUN (nothing will change)"
    print(f"\n=== Ghost <-> Mailchimp reconciliation — {mode} ===")
    print(f"  Ghost members ............... {len(ghost):,}")
    print(f"  Mailchimp records ........... {len(mc):,}")
    print(f"  ADD to Mailchimp ............ {len(plan['to_mailchimp']):,}")
    print(f"  UNSUBSCRIBE in Ghost ........ {len(plan['to_ghost_unsub']):,}")
    print(f"  skipped (would ping-pong) ... {len(plan['skipped_pingpong']):,}")
    for side, label in (("to_mailchimp", "would add to Mailchimp"),
                        ("to_ghost_unsub", "would unsubscribe in Ghost")):
        if plan[side]:
            print(f"\n  first 10 {label}:")
            for r in plan[side][:10]:
                print(f"    {r['email']}")

    LOGDIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rec = {"at": stamp, "mode": "apply" if writes else "dry-run",
           "ghost_members": len(ghost), "mailchimp_records": len(mc), "plan": plan}

    if writes:
        print("\napplying…")
        rec["result"] = apply_plan(plan, key, dc, list_id, None)
        print(f"  added to Mailchimp: {rec['result']['added_to_mailchimp']}")
        print(f"  unsubscribed in Ghost: {rec['result']['unsubscribed_in_ghost']}")
        for e in rec["result"]["errors"][:10]:
            print(f"  ERROR {e}")
    else:
        print("\nDry run — nothing was changed. To enable, see the runbook in this file.")

    (LOGDIR / f"reconcile_{stamp}.json").write_text(json.dumps(rec, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(rec, indent=1))
    print(f"audit log: {LOGDIR / f'reconcile_{stamp}.json'}")

    summary = build_summary(rec)
    if a.report:
        Path(a.report).write_text(summary)
    if a.slack:
        post_slack(summary)   # raises Abort -> nonzero exit, so a lost report is visible
    return 0


# =============================================================================
# RUNBOOK — how to turn this on, once the person who does it manually agrees
#
# 1. Have them run it themselves in dry run and read the plan:
#        MAILCHIMP_KEY=... GHOST_ADMIN_KEY=... python3 reconcile_subscribers.py
#    Compare the two lists against what they would have done by hand. Repeat over
#    a couple of weeks until the plan matches their judgement every time.
# 2. Spot-check a handful of the proposed changes directly in both dashboards.
# 3. First real run: keep MAX_CHANGES low, run with --apply and
#    RECONCILE_ALLOW_WRITES=yes by hand, watch it, then verify both systems.
# 4. Only then consider scheduling. If it is scheduled, add it to
#    .github/workflows/ as its OWN workflow (never inside network-refresh.yml —
#    a data-refresh failure must never leave a half-finished sync), with
#    RECONCILE_ALLOW_WRITES set as a repo secret so it can be revoked instantly
#    by deleting the secret.
# 5. Keep the audit logs. private/reconcile_log/ is gitignored with the rest of
#    private/ — it holds subscriber emails, so it must never be committed.
# =============================================================================

if __name__ == "__main__":
    sys.exit(main())
