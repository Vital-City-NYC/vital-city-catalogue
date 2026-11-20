#!/usr/bin/env python3
"""
What would the Vital City iPhone app show right now?

On Nov. 18, 2026 the app's Today screen went blank for every reader: the AI
and the City issue put 13 pieces up at once, all tagged #hidehome, the app
asked Ghost for the 13 newest pieces and then dropped the hidden ones, and
nothing was left. Nothing was down. Ghost answered, the site was fine, and
the monthly health check (vital-city-ios/tools/health-check.py, which asks
Ghost for three posts) would have passed.

This asks the app's own questions, the way each screen asks them, and reports
only when a screen would come up empty, wrong or stale. Silence means every
screen has something to show.

It lives in this repository, not the app's, because the Slack secrets that
let a GitHub run message Josh directly are here. It reads only public things:
the app's settings file, Ghost's Content API with the app's public key, the
website's homepage and the Oh snap! feed. Keep its queries in step with the
app's (the file and function each one mirrors is named beside it).

Run:   python3 app_screen_check.py            print findings, exit 1 if any
       python3 app_screen_check.py --slack    also DM Josh when there are findings
       python3 app_screen_check.py --selftest check the logic against saved cases
       python3 app_screen_check.py --say-ok   DM Josh once that all is well (setup test)
"""

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

CONFIG_URL = "https://vital-city-nyc.github.io/vital-city-app/data/app-config.json"
ARCHIVE_FEED = "https://vital-city-nyc.github.io/vital-city-app/data/archive-feed.json"
SITE = "https://www.vitalcitynyc.org"
# AppConfig.swift's compiled-in fallbacks, used when the settings file is unreadable.
GHOST_BASE = "https://vital-city.ghost.io/ghost/api/content"
GHOST_KEY = "dd8e178e9ddfc883537e71dd07"
UA = "VitalCityAppScreenCheck/1.0 (+https://github.com/vitalcity-nyc/vital-city-catalogue)"
NY = ZoneInfo("America/New_York")

HIDE_HOME = {"hash-hidehome", "hash-hideall"}   # Models.swift: isHiddenFromHome
HIDE_ALL = {"hash-hideall"}                     # Models.swift: isHiddenFromLists
FRONT_PAGE_SIZE = 13                            # TodayView.load


class Unreachable(Exception):
    pass


def fetch(url, headers=None, tries=3, timeout=30):
    """The body as text. Retries, so one dropped connection is not a finding."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
            if e.code in (401, 403, 404):
                break
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(5 * (i + 1))
    raise Unreachable("%s -> %s" % (url.split("?")[0], last))


class Ghost:
    def __init__(self, base, key):
        self.base, self.key = base.rstrip("/"), key

    def get(self, path, **params):
        """GhostAPI.fetch: the key first, then the parameters, v6.0 pinned."""
        q = urllib.parse.urlencode({"key": self.key, **params})
        return json.loads(fetch("%s/%s/?%s" % (self.base, path, q),
                                {"Accept-Version": "v6.0"}))

    def posts(self, **params):
        """GhostAPI.posts: authors and tags included, #hideall dropped."""
        params.setdefault("include", "authors,tags")
        params.setdefault("order", "published_at desc")
        got = self.get("posts", **params).get("posts") or []
        return [p for p in got if not (tags_of(p) & HIDE_ALL)]

    def pages(self, tag, order="published_at desc"):
        """GhostAPI.pages(tagged:): every page carrying a tag."""
        out, page = [], 1
        while True:
            d = self.get("pages", limit=100, page=page, filter="tag:%s" % tag,
                         include="tags", order=order)
            out += d.get("pages") or []
            nxt = ((d.get("meta") or {}).get("pagination") or {}).get("next")
            if not nxt:
                return out
            page = nxt

    def count(self, flt):
        d = self.get("posts", limit=1, fields="slug", filter=flt)
        return ((d.get("meta") or {}).get("pagination") or {}).get("total", 0)


def tags_of(post):
    return {t.get("slug") for t in post.get("tags") or []}


def article_filter(slug):
    """Models.swift, Issue.articleFilter."""
    return "tags:[hash-%s,%s]" % (slug, slug)


# ------------------------------------------------------------------ the checks
#
# Each takes what was fetched and returns plain sentences Josh can act on.
# Keeping the judgment apart from the fetching is what lets --selftest replay
# Nov. 18 without the network.

def front_page_findings(filtered, newest):
    """TodayView.load.

    `filtered`: what 1.0.9 and later get (Ghost leaves hidden pieces out
    before counting). `newest`: the 13 newest whatever their tags, which is
    what 1.0.8 and earlier fetch before dropping hidden ones on the phone.
    """
    out = []
    shown = [p for p in filtered if not (tags_of(p) & HIDE_HOME)]
    if not shown:
        out.append("Today is blank in the current app: Ghost returned no pieces that are "
                   "allowed on the front page. Readers see \"Hmm, nothing loaded.\"")
    old = [p for p in newest if not (tags_of(p) & HIDE_HOME)]
    if newest and not old:
        out.append("Today is blank on phones still on version 1.0.8 or earlier: the %d newest "
                   "pieces on the site are all tagged #hidehome or #hideall. Taking #hidehome "
                   "off one of them brings the screen back for those readers." % len(newest))
    return out


def spotlight_slug(html):
    """GhostAPI.spotlightSlug, line for line: the first vitalcitynyc.org link
    inside the homepage's lead card."""
    i = html.find("main-home-post")
    if i < 0:
        return None
    near = html[i + len("main-home-post"):][:4000]
    window = near.split("</article>")[0]
    m = re.search(r'href="https://www\.vitalcitynyc\.org/([a-z0-9-]+)/"', window)
    return m.group(1) if m else None


def lead_findings(html, resolve):
    """TodayView.loadSpotlight. `resolve(slug)` -> ("post", None), ("page",
    number of pieces behind it) or (None, None)."""
    slug = spotlight_slug(html)
    if not slug:
        return ["The featured card at the top of Today: the app can no longer find the "
                "website's lead story, so it leads with the newest piece instead. The "
                "homepage's markup has probably changed (the app looks for \"main-home-post\")."]
    kind, pieces = resolve(slug)
    if kind is None:
        return ["The featured card at the top of Today: the website leads with /%s/, which "
                "is neither a published piece nor a page the app can open, so the app shows "
                "no featured card." % slug]
    if kind == "page" and slug != "issues" and not pieces:
        return ["The featured card at the top of Today opens an empty list: the website leads "
                "with the page /%s/, and no pieces carry its tag (#%s)." % (slug, slug)]
    return []


def journal_findings(issues, newest_count):
    """GhostAPI.issues and the current-issue shelf on Today."""
    issues = [i for i in issues if i.get("slug") != "issues"]
    if not issues:
        return ["The Journal: Ghost returned no issue pages (pages tagged #journal), so the "
                "issue list and Today's current-issue shelf are empty."]
    if not newest_count:
        return ["The current issue, \"%s\", opens an empty list in the app: no pieces carry "
                "its tag (#%s)." % (issues[0].get("title"), issues[0].get("slug"))]
    return []


def policy_findings(series, recent_count):
    """PolicyView.load."""
    if not series:
        return ["Policy: Ghost returned no franchise pages (pages tagged #what-to-do). The app "
                "falls back to the list it shipped with, which may be out of date."]
    if not recent_count:
        return ["Policy: \"Recently in policy\" is empty. No pieces carry any franchise's tag."]
    return []


def data_findings(nav, data_posts):
    """DataView.loadTools and loadCharts."""
    out, under, tools = [], False, 0
    for item in nav or []:
        label = item.get("label") or ""
        if not label.startswith("-"):
            under = label.strip().lower() == "data"
            continue
        tools += under
    if not tools:
        out.append("Data: the website's menu no longer has entries under \"Data\", so the app "
                   "keeps showing the tools it last saved and will not pick up changes.")
    if not any("flourish" in (p.get("html") or "") for p in data_posts):
        out.append("Data: the \"latest charts\" shelf is empty. None of the %d newest pieces "
                   "tagged Data contains a Flourish chart." % len(data_posts))
    return out


def podcast_findings(episodes):
    """TodayView.load and PodcastView."""
    return [] if episodes else ["Podcast: Ghost returned no pieces tagged podcast, so the "
                                "episode shelf is empty."]


# Wording that is true only in the week a photo was picked. A title should
# never say "today". A line under a photo may ("today the world's busiest
# bridge"), so there only the counting-from-this-week forms are flagged.
TITLE_WEEK_WORDS = re.compile(r"\b(?:today|tonight|yesterday)\b", re.I)
HOOK_WEEK_WORDS = re.compile(
    r"\byears ago (?:today|tonight)\b|"
    r"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day is \d+ years\b|"
    r"\bis (?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day, ", re.I)


def oh_snap_findings(feed, now):
    """OhSnapView. `now` is New York time."""
    items = (feed or {}).get("items") or []
    if not items:
        return ["Oh snap!: the photo feed is empty or unreadable, so the app shows the photos "
                "it shipped with."]
    out = []
    monday = (now - dt.timedelta(days=now.weekday())).date()
    newest = max(i.get("week") or "" for i in items)
    # The weekly job's last backup runs Tuesday morning; by Tuesday afternoon
    # a missing week is a missed week.
    due = now.weekday() > 1 or (now.weekday() == 1 and now.hour >= 14)
    if due and newest < monday.isoformat():
        out.append("Oh snap! is stale: the newest photos are from the week of %s, and this "
                   "week's set (%s) has not arrived." % (newest, monday.isoformat()))
    this_week = [i for i in items if i.get("week") == newest]
    if len(this_week) < 4:
        out.append("Oh snap!: the newest week has only %d photo(s)." % len(this_week))
    dated = [i for i in items
             if TITLE_WEEK_WORDS.search(i.get("title") or "")
             or HOOK_WEEK_WORDS.search(i.get("hook") or "")]
    if dated:
        out.append("Oh snap!: %d photo(s) carry wording that is only true on one day, for "
                   "example \"%s\"." % (len(dated), (
                       dated[0]["title"] if TITLE_WEEK_WORDS.search(dated[0].get("title") or "")
                       else dated[0].get("hook") or "")[:90]))
    return out


def dead_images(items, limit=8):
    """A photo the archive has moved is an empty box in the app. Only a plain
    'gone' counts; a busy archive is not a finding."""
    gone = []
    for it in items[:limit]:
        url = it.get("image") or ""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
            urllib.request.urlopen(req, timeout=30).close()
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                gone.append(it.get("title") or url)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    if gone:
        return ["Oh snap!: %d photo(s) no longer load and show as empty boxes: %s."
                % (len(gone), "; ".join(g[:60] for g in gone[:3]))]
    return []


# --------------------------------------------------------------------- the run

def run():
    findings = []

    def attempt(label, fn):
        try:
            findings.extend(fn() or [])
        except Unreachable as e:
            findings.append("%s could not be checked: %s." % (label, e))
        except Exception as e:  # noqa: BLE001 - a bug here must be heard, not hidden
            findings.append("%s: the check itself failed (%s: %s). Tell Claude."
                            % (label, type(e).__name__, e))

    base, key = GHOST_BASE, GHOST_KEY
    try:
        cfg = json.loads(fetch(CONFIG_URL))
        base, key = cfg.get("ghostBase") or base, cfg.get("ghostKey") or key
    except (Unreachable, ValueError) as e:
        findings.append("The app's settings file is unreadable (%s). Installed copies fall "
                        "back to their built-in settings, and a rotated Ghost key could not "
                        "reach them." % e)
    g = Ghost(base, key)

    try:
        g.get("posts", limit=1, fields="slug")
    except Unreachable as e:
        return findings + ["Ghost is not answering the app's key (%s). Every screen shows its "
                           "saved copy, or an error on a first launch." % e]

    attempt("Today", lambda: front_page_findings(
        g.posts(limit=FRONT_PAGE_SIZE, filter="tag:-hash-hidehome+tag:-hash-hideall"),
        g.posts(limit=FRONT_PAGE_SIZE)))

    def resolve(slug):
        try:
            if g.get("posts/slug/%s" % slug, fields="slug").get("posts"):
                return "post", None
        except Unreachable:
            pass
        try:
            if g.get("pages/slug/%s" % slug, fields="slug").get("pages"):
                return "page", g.count(article_filter(slug))
        except Unreachable:
            pass
        return None, None

    attempt("The featured card", lambda: lead_findings(
        fetch(SITE + "/", {"Accept": "text/html"}), resolve))

    def journal():
        issues = [i for i in g.pages("hash-journal") if i.get("slug") != "issues"]
        return journal_findings(issues, g.count(article_filter(issues[0]["slug"])) if issues else 0)
    attempt("The Journal", journal)

    def policy():
        series = g.pages("hash-what-to-do", order="title asc")
        tags = [t for s in series for t in ("hash-" + s["slug"], s["slug"])]
        return policy_findings(series, g.count("tags:[%s]" % ",".join(tags)) if tags else 0)
    attempt("Policy", policy)

    attempt("Data", lambda: data_findings(
        (g.get("settings").get("settings") or {}).get("navigation"),
        g.posts(limit=6, filter="tag:data")))

    attempt("Podcast", lambda: podcast_findings(g.posts(limit=2, filter="tag:podcast")))

    def oh_snap():
        try:
            feed = json.loads(fetch(ARCHIVE_FEED))
        except ValueError:
            feed = None
        got = oh_snap_findings(feed, dt.datetime.now(NY))
        return got + dead_images((feed or {}).get("items") or [])
    attempt("Oh snap!", oh_snap)

    return findings


def slack_dm(text):
    """Only ever a direct message to Josh. Never a channel, and no fallback."""
    tok = os.environ.get("SLACK_BOT_TOKEN", "")
    to = os.environ.get("SLACK_DM_TO") or "U0730459X4L"
    if not tok:
        print("no SLACK_BOT_TOKEN; the failed run is the only notice")
        return
    if not to.startswith(("U", "D", "W")):
        print("SLACK_DM_TO is not a person or a DM; not posting anywhere")
        return
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": to, "text": text, "unfurl_links": False}).encode(),
        headers={"Authorization": "Bearer %s" % tok,
                 "Content-Type": "application/json; charset=utf-8"})
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    print("DM sent" if r.get("ok") else "Slack refused: %s" % r.get("error"))


def selftest():
    hidden = [{"slug": "ai-%d" % n, "tags": [{"slug": "hash-ai-and-the-city"},
                                              {"slug": "hash-hidehome"}]} for n in range(13)]
    plain = [{"slug": "p-%d" % n, "tags": [{"slug": "policy"}]} for n in range(13)]
    home = '<div class="main-home-post"><a href="https://www.vitalcitynyc.org/ai-and-the-city/">'
    mon = dt.datetime(2026, 11, 23, 9, tzinfo=NY)
    wed = dt.datetime(2026, 11, 25, 9, tzinfo=NY)
    feed = {"items": [{"week": "2026-11-16", "title": "A", "hook": ""}] * 8}
    cases = [
        ("Nov. 18 as 1.0.8 saw it", front_page_findings(plain, hidden), 1),
        ("Nov. 18 before any fix", front_page_findings([], hidden), 2),
        ("an ordinary day", front_page_findings(plain, plain[:10] + hidden[:3]), 0),
        ("lead is an issue with pieces", lead_findings(home, lambda s: ("page", 26)), 0),
        ("lead is an issue with none", lead_findings(home, lambda s: ("page", 0)), 1),
        ("lead is a piece", lead_findings(home, lambda s: ("post", None)), 0),
        ("homepage markup changed", lead_findings("<html></html>", lambda s: ("post", None)), 1),
        ("lead resolves to nothing", lead_findings(home, lambda s: (None, None)), 1),
        ("lead slug", [spotlight_slug(home)] if spotlight_slug(home) != "ai-and-the-city" else [], 0),
        ("no issues", journal_findings([], 0), 1),
        ("issue with no pieces", journal_findings([{"slug": "x", "title": "X"}], 0), 1),
        ("issue fine", journal_findings([{"slug": "issues"}, {"slug": "x"}], 9), 0),
        ("policy fine", policy_findings([{"slug": "a"}], 5), 0),
        ("policy empty", policy_findings([], 0), 1),
        ("data fine", data_findings([{"label": "Data"}, {"label": "- Tool"}],
                                    [{"html": "<div class='flourish-embed'>"}]), 0),
        ("data menu gone", data_findings([{"label": "About"}, {"label": "- Team"}],
                                         [{"html": "flourish"}]), 1),
        ("no charts", data_findings([{"label": "Data"}, {"label": "- Tool"}], [{"html": ""}]), 1),
        ("podcast empty", podcast_findings([]), 1),
        ("photos on Monday morning", oh_snap_findings(feed, mon), 0),
        ("photos stale by Wednesday", oh_snap_findings(feed, wed), 1),
        ("photos say today", oh_snap_findings(
            {"items": [{"week": "2026-11-23", "title": "Parade took place today", "hook": ""}] * 8},
            mon), 1),
        ("photo line counts from the week", oh_snap_findings(
            {"items": [{"week": "2026-11-23", "title": "A",
                        "hook": "Saturday is 62 years since Nov. 21, 1964: opened."}] * 8}, mon), 1),
        ("dated line is fine", oh_snap_findings(
            {"items": [{"week": "2026-11-23", "title": "A",
                        "hook": "Nov. 21, 1964: opened. Today's bridge."}] * 8}, mon), 0),
        ("feed empty", oh_snap_findings({"items": []}, mon), 1),
    ]
    bad = 0
    for name, got, want in cases:
        ok = len(got) == want
        bad += not ok
        print("%s %s%s" % ("ok  " if ok else "FAIL", name,
                           "" if ok else "  got %d, want %d: %s" % (len(got), want, got)))
    print("\n%d/%d pass" % (len(cases) - bad, len(cases)))
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    found = run()
    if not found:
        print("Every screen has something to show.")
        # Used once by hand, to prove the message reaches Josh. The scheduled
        # runs never pass this: silence is the all-clear.
        if "--say-ok" in sys.argv:
            slack_dm("Vital City app check is set up. It asked the app's questions just now "
                     "and every screen has something to show. From here on it runs twice a "
                     "day and writes only when one would come up empty or stale.")
        raise SystemExit(0)
    text = "Vital City app check: %d thing%s to look at.\n" % (
        len(found), "" if len(found) == 1 else "s") + "\n".join("• " + f for f in found)
    run_url = os.environ.get("RUN_URL")
    if run_url:
        text += "\nRun: " + run_url
    print(text)
    if "--slack" in sys.argv:
        slack_dm(text)
    raise SystemExit(1)
