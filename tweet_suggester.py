#!/usr/bin/env python3
"""
Scan vitalcitynyc.org for newly published pieces and draft 2-3 posts for each.

Reads the Ghost Content API, keeps a seen-list so nothing is suggested twice,
and drafts three posts per piece in one of two ways:

  rules   (default when no ANTHROPIC_API_KEY is set; free): built from what this
          account's own posts show works. The editor's dek as the claim, "Read
          [writer] on ..." with their known handle, and a sentence quoted
          verbatim from the piece. Every draft still goes through the style screen.
  claude  (when the key is set): sends the full text to Claude with the style
          guide below, as before. About $0.02 a piece.

Writes a rolling 30-day file, data/tweet_suggestions.json, that the Press
page's "Who should hear about this" module reads. Posts to Slack when a
destination is configured; without one it skips delivery instead of failing.

  python3 tweet_suggester.py                    # last 7 days, print
  python3 tweet_suggester.py --days 30          # wider window
  python3 tweet_suggester.py --slack            # post to Slack
  python3 tweet_suggester.py --dry-run          # list what it would draft, no API spend
  python3 tweet_suggester.py --piece <slug>     # redo one piece, ignoring the seen-list
  python3 tweet_suggester.py --self-test        # offline checks
  python3 tweet_suggester.py --rules            # force the free rule-based drafts
  python3 tweet_suggester.py --refill 30        # redraft every piece of the last N days
                                                # (rules mode; rebuilds the Press module)

Costs money: one Claude call per new piece (~$0.02 each at current Sonnet
prices). --dry-run first if a wide window might pick up dozens.

Secrets: ANTHROPIC_API_KEY from env or macOS keychain. Slack needs
SLACK_BOT_TOKEN and SLACK_DM_TO in the environment.
"""

import argparse, json, os, re, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE  = Path(__file__).resolve().parent
STATE = HERE / "data" / "tweet_suggester_seen.json"
OUT   = HERE / "data" / "tweet_suggestions.json"

GHOST_KEY = "dd8e178e9ddfc883537e71dd07"          # public content key
GHOST_API = "https://vital-city.ghost.io/ghost/api/content"
API_URL   = "https://api.anthropic.com/v1/messages"
MODEL     = "claude-sonnet-5"
MAX_CHARS = 260        # X allows 280; leave room for the link X appends


class Abort(Exception):
    """Something is wrong enough that a silent partial run would mislead."""


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# --------------------------------------------------------------- the prompt
# The ban list is Josh's anti-style guide. It is stated as concrete sentence
# shapes rather than "write naturally", because a model told to write
# naturally writes the same six shapes every time.

STYLE = """You are drafting posts for X (Twitter) for Vital City, a journal of
urban policy and civic life in New York City. The account's readers are
reporters, city officials, academics and engaged New Yorkers. They can tell
when something was written by a machine, and they discount it.

WHAT THIS ACCOUNT ACTUALLY POSTS
Measured across 179 posts with real reach, Aug 2025 to Aug 2026. Median post
is 183 characters and earns 4.4 link clicks per 1,000 impressions. Against
that baseline:
- Naming the writer and tagging their handle: 2.8x the click rate
- Saying "Read [name] on [subject]" outright: 3.3x
- Naming the writer in words - writes, argues, explains, traces, sat down
  with: 2.9x
- Opening with a sentence quoted from the piece: 2.2x
- Opening with a real question the piece answers: 1.9x
- Carrying a statistic: 0.63x, BELOW baseline
- Reaching for praise words - great, amazing, really interesting: 0.48x, the
  worst-performing habit in the sample

So: the writer is the draw, not the number. Say who wrote it and what they
say. A statistic belongs in a post only when the statistic IS the story.
Do not compliment the piece; describe it.

(Small samples, and some of this is mechanism rather than magic: tagging a
writer gets the post in front of that writer's followers when they repost it.
Which is a reason to do it, not a reason to discount it.)

WRITE LIKE THIS
- Plain declarative sentences. Short ones are good. Opening with "But" or
  "And" is good.
- Aim for 100 to 190 characters. Shorter than you think.
- Assume the reader is smart and busy. No throat-clearing.
- One idea per post.
- "Read Nicole Gelinas on why the rebuild felt slow" is a good post for this
  account. It is not engagement bait here; it is the house construction.

NEVER WRITE THESE (they are the tells that make copy read as AI-written)
- Negation-then-reveal in any form: "It's not X, it's Y." "This isn't about
  X. It's about Y." "X, not Y, is the real story." Split across two sentences
  counts too. Just state the positive claim and delete the thing it isn't.
- Significance inflation: "the single most", "the clearest example", "a
  watershed", "marks a turning point", "what everyone is missing", "the real
  story". Give the number and let it rank itself.
- Announcing that something matters: "Here's the thing." "Worth noting."
  "Read that again." "Let that sink in." "The tell is..." Say the thing.
- Purple abstraction: "the machinery of", "the architecture of", "the rhythm
  of", "lays bare", "grapples with", "sheds light on", "dives deep into",
  "unpacks", "explores the complex interplay".
- Aphorism formulas: "X is the language of Y", "the tail is where the
  variation lives", any slot-fill line that sounds quotable and says less
  than the plain version.
- Empty rhetorical questions with no answer behind them: "The question
  nobody is asking?" "Coincidence?" A question is fine when the piece
  genuinely answers it and the post is one of the three kinds below.
- Em dash used to stage a pause before a punchline. A two-sentence build
  where the second sentence exists only to deliver a reveal.
- Hollow intensifiers: genuinely, truly, simply, incredibly, remarkably,
  fascinating, powerful, essential, must-read, deeply.
- Engagement bait: "A thread.", "Link below", "Our latest", "New from us",
  "ICYMI", "Don't miss", "You won't believe". ("Read [name] on [subject]" is
  NOT in this category - it is what this account says and it works.)
- Hashtags. Emoji. Title Case. Exclamation marks.

MECHANICS
- "New York City" spelled out, never NYC. Spell out an acronym on first use
  (NYPD is New York City Police Department; MTA is Metropolitan
  Transportation Authority).
- No serial comma: "housing, transit and policing".
- Straight quotes and apostrophes only.
- Under 260 characters. The link is appended automatically, so do not
  include a URL, and do not write "link in bio" or similar.
- Name the author freely; this account does it constantly and it is the
  single strongest thing it does. Give their standing when it is the draw.
- Never write "in Vital City", "Vital City reports" or similar. The account
  posting this is Vital City; saying so is redundant.
- Do not guess anyone's pronouns. If the piece does not make a person's
  pronouns explicit, use their name again or write "they". Getting this
  wrong misgenders a real person; the neutral version never does. A
  first-person essay does NOT establish its author's pronouns - writing "I"
  for 2,000 words tells you nothing about how to refer to them.

THE THREE POSTS MUST DIFFER IN KIND, not be paraphrases of each other:
1. THE CLAIM. The piece's argument or its most counterintuitive point,
   credited to the writer. Model: "Why it takes four new housing units to
   get one person off the street, according to Jane Doe."
2. THE WRITER. Name the author and say what they say. Give their standing
   when it is the reason to read - former budget director, economist,
   architect. Use the handle from AUTHOR HANDLE below if one is given; if
   none is given, use their name in words and never invent a handle.
   Model: "Read Nicole Gelinas on why the MTA app went right."
3. THE QUOTE OR THE QUESTION. Either a sentence lifted verbatim from the
   piece that stands on its own, in straight double quotes, or a real
   question the piece answers. Not a teaser question with no answer - a
   question a reader would actually want settled.

WHOSE ARGUMENT IT IS
Vital City publishes and shares these pieces; the argument belongs to the
writer, not to the account. Every one of the three posts must make that
clear: name the writer (or tag the handle) and attribute the claim to them
- "Jane Doe argues", "says Jane Doe", "Jane Doe writes", "from Jane Doe".
Never state a writer's argument as the account's own opinion. The one
exception: when AUTHOR is "Vital City", the piece is the house's own (a
series such as Just Fix It), and the posts credit the series by name.

Every claim must come from the text given to you. Do not add numbers,
attributions or context that are not in the piece. If the piece is a
personal essay or a reminiscence rather than an argument, do not force it
into a policy frame; quote its concreteness instead."""

EXAMPLES = """Posts the editor approved, as a calibration of tone and sentence
shape. They predate the rule that every post credits its writer, so most need
the writer's name added before they would pass today:

"Redlining ended in 1968. You can still find it on a map of New York City today."
"Twenty things that bring crime down in cities. None of them replace policing. All of them work alongside it."
"Rents are too high for tenants and too low to keep the buildings standing. Both are true, which is what makes the Rent Guidelines Board vote so hard."
"Five things that work on rats, according to the research. New York City keeps trying the other things."
"We asked a former Secretary of Homeland Security where immigration enforcement stops being enforcement. He answered."
"Government already spends billions putting food on New York City tables. Anyone calling municipal groceries radical might start with SNAP."
"A French aristocrat spent nine months here in 1831 working out why Americans join things. His answer still explains the nonprofit sector."
"Summer jobs get proposed every June as a violence strategy. The research says most violence is a crime of passion, which complicates the pitch."

Posts the editor would reject, and why:

"This piece unpacks the complex interplay between housing policy and homelessness." (purple abstraction, says nothing)
"It's not about the money. It's about who decides." (negation-then-reveal)
"The single most important thing you'll read about Rikers this year." (significance inflation)
"Ever wonder why your rent keeps going up? A must-read from our latest issue." (rhetorical question, engagement bait, hollow intensifier)
"New from us: a deep dive into NYPD staffing. A thread." (engagement bait, unspelled acronym)"""

TASK = """Here is a piece published by Vital City.

TITLE: {title}
DEK: {dek}
AUTHOR: {author}
AUTHOR HANDLE: {handle}
TAGS: {tags}
PUBLISHED: {date}

FULL TEXT:
{body}

Write three posts following the rules above. Return only JSON, no other
text, in this exact shape:

{{"posts": [
  {{"kind": "finding", "text": "..."}},
  {{"kind": "argument", "text": "..."}},
  {{"kind": "hook", "text": "..."}}
]}}"""


# ----------------------------------------------------------------- plumbing
def http_json(url, headers=None, data=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def anthropic_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", "ANTHROPIC_API_KEY", "-w"],
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        raise Abort("No ANTHROPIC_API_KEY in the environment or the keychain.")


def fetch_posts(days, limit=100):
    """Recent posts with full text. An empty result is an error, not a quiet
    'nothing new' - a broken key or a changed endpoint looks identical to a
    quiet week otherwise."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    flt = urllib.parse.quote(f"published_at:>'{since}'")
    url = (f"{GHOST_API}/posts/?key={GHOST_KEY}&limit={limit}"
           f"&order={urllib.parse.quote('published_at desc')}&filter={flt}"
           "&include=authors,tags&formats=plaintext")
    d = http_json(url, timeout=45)
    if "posts" not in d:
        raise Abort(f"Ghost returned no posts array: {str(d)[:200]}")
    # A zero-length window is plausible; a zero-length 90-day window is not.
    if not d["posts"] and days >= 30:
        raise Abort(f"Ghost returned 0 posts for the last {days} days. "
                    "That is almost certainly a broken query, not a quiet quarter.")
    return d["posts"]


def load_seen():
    if STATE.exists():
        try:
            return set(json.loads(STATE.read_text()).get("slugs", []))
        except Exception:
            log("! seen-list unreadable, treating every piece as new")
    return set()


def save_seen(slugs):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(
        {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "slugs": sorted(slugs)}, indent=1))


# ------------------------------------------------------------------- drafting
BANNED = [
    r"\bit'?s not\b.{0,60}\bit'?s\b", r"\bisn'?t (?:about|just)\b.{0,60}\bit'?s\b",
    r"\bnot (?:just|only)\b.{0,40}\bbut\b",
    r"\bthe single (?:most|biggest|loudest)\b", r"\bwatershed\b", r"\bturning point\b",
    r"\bmust[- ]read\b", r"\bdeep dive\b", r"\bdives? deep\b", r"\bunpacks?\b",
    r"\bsheds? light\b", r"\blays? bare\b", r"\bgrapples? with\b",
    r"\bthe (?:machinery|architecture|rhythm) of\b",
    r"\bhere'?s the thing\b", r"\bworth noting\b", r"\blet that sink in\b",
    r"\bread that again\b", r"\bICYMI\b", r"\ba thread\b", r"\bdon'?t miss\b",
    r"\bour latest\b", r"\bnew from us\b", r"\blink in bio\b",
    r"\bgenuinely\b", r"\btruly\b", r"\bincredibly\b", r"\bremarkably\b",
    r"\bfascinating\b", r"\bever wonder\b", r"\bwhat if\b",
    r"#\w", r"[\U0001F300-\U0001FAFF☀-➿]", r"[’‘“”]", r"\bNYC\b",
]


def screen(text):
    """Return the reasons a draft should not go out as written."""
    bad = []
    for pat in BANNED:
        m = re.search(pat, text, re.I if not pat.startswith("#") else 0)
        if m:
            bad.append(repr(m.group(0)))
    if len(text) > MAX_CHARS:
        bad.append(f"{len(text)} chars")
    if re.search(r"https?://", text):
        bad.append("contains a URL")
    return bad


HANDLES = {}
if (HERE / "data" / "author_handles.json").exists():
    HANDLES = json.loads((HERE / "data" / "author_handles.json").read_text())["handles"]


def author_handle(post):
    """A handle only if this account has demonstrably used it. Never guessed:
    tagging the wrong person is worse than not tagging anyone."""
    for a in post.get("authors") or []:
        if a["name"] in HANDLES:
            return "@" + HANDLES[a["name"]]
    return None


def draft(key, post, retries=2):
    body = (post.get("plaintext") or "").strip()
    if len(body) < 200:
        raise Abort(f"'{post['title']}' came back with {len(body)} characters of text.")
    prompt = "\n\n".join([STYLE, EXAMPLES, TASK.format(
        title=post["title"],
        dek=post.get("custom_excerpt") or post.get("excerpt") or "(none)",
        author=", ".join(a["name"] for a in post.get("authors") or []) or "(unattributed)",
        handle=author_handle(post) or "(none known - use the name in words, do not invent one)",
        tags=", ".join(t["name"] for t in post.get("tags") or [] if not t["name"].startswith("#")) or "(none)",
        date=post["published_at"][:10],
        body=body[:24000])])

    last = None
    for attempt in range(retries + 1):
        msg = prompt if attempt == 0 else (
            prompt + "\n\nYour previous attempt broke these rules: " + last +
            "\nRewrite all three. Same JSON shape.")
        r = http_json(API_URL, timeout=120,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=json.dumps({"model": MODEL, "max_tokens": 4000,
                             "messages": [{"role": "user", "content": msg}]}).encode())
        text = "".join(b.get("text", "") for b in r.get("content", [])
                       if b.get("type") == "text").strip()
        if not text:
            kinds = [b.get("type") for b in r.get("content", [])]
            raise Abort(f"No text in the model reply (blocks: {kinds}, "
                        f"stop_reason: {r.get('stop_reason')})")
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        try:
            posts = json.loads(text[text.find("{"):text.rfind("}") + 1])["posts"]
        except Exception as e:
            last = f"the response was not valid JSON ({e})"
            continue
        problems = {p["text"]: screen(p["text"]) for p in posts}
        flagged = {t: v for t, v in problems.items() if v}
        if not flagged:
            return posts, attempt
        last = "; ".join(f"{t[:40]}... -> {', '.join(v)}" for t, v in flagged.items())
        log(f"  retry {attempt+1}: {last[:160]}")
    # Hand back the last attempt with its problems attached rather than
    # dropping the piece; a flagged draft a human can fix beats silence.
    for p in posts:
        p["flags"] = screen(p["text"])
    return posts, retries + 1


# ------------------------------------------------------------- rule-based drafts
# No model, no cost. Each shape is one this account's own posts show working
# (see STYLE): the claim, the writer by name and handle, a quoted sentence.
# They are starting points a human edits, and they go through screen() like
# any model draft.
LEAD_OFF = re.compile(r"^(this|that|these|those|it|its|they|their|he|she|his|her|we|our|us|"
                      r"but|and|so|or|yet|here|there|such|then|also|still|instead|meanwhile|"
                      r"however|moreover|indeed|similarly|likewise|in short|in other words)\b", re.I)


def plain(t):
    t = (t or "").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    t = re.sub(r"\bNYC\b", "New York City", t)
    return re.sub(r"\s+", " ", t).strip()


def names_line(post):
    names = [a["name"] for a in post.get("authors") or [] if a.get("name") and a["name"] != "Vital City"]
    if not names:
        return None
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


SERIES = ["Just Fix It", "Rubber Meets Road", "What To Do", "Reality Check"]


def house_series(post):
    names = {t.get("name") for t in post.get("tags") or []}
    return next((x for x in SERIES if x in names), None)


def quote_sentence(body):
    """A sentence from the piece that stands on its own: early in the piece,
    70 to 220 characters, not leaning on the sentence before it."""
    paras = [p for p in re.split(r"\n{2,}", body) if len(p) > 80]
    cands = []
    for pi, para in enumerate(paras[:12]):
        for sent in re.split(r"(?<=[.?!])\s+(?=[A-Z\"])", plain(para)):
            s = sent.strip()
            if not (70 <= len(s) <= 200) or LEAD_OFF.match(s) or '"' in s or "http" in s:
                continue
            if re.search(r"\bVital City\b|\bthis (?:piece|essay|article|series|issue)\b", s, re.I):
                continue                              # series boilerplate and self-reference
            if s.endswith(":") or s.count("(") != s.count(")"):
                continue
            score = pi + abs(len(s) - 120) / 50      # early, and about tweet length
            cands.append((score, s))
    return min(cands)[1] if cands else None


def rules_draft(post):
    title = plain(post.get("title"))
    dek = plain(post.get("custom_excerpt") or "")
    who = names_line(post)
    handle = author_handle(post)
    body = post.get("plaintext") or ""
    # The account shares the piece; the argument belongs to the writer, so
    # every draft names them up front. A piece bylined Vital City itself (a
    # house series such as Just Fix It) is the house's own argument, and is
    # credited to the series instead.
    by = (f"{who} ({handle})" if handle else who) if who else None
    series = house_series(post) if not who else None
    lead = f"From {by}: " if by else (f"From {series}: " if series else "")
    drafts = []
    if dek and len(lead + dek) <= MAX_CHARS:
        drafts.append({"kind": "claim", "text": lead + dek})
    if by:
        drafts.append({"kind": "writer", "text": f'Read {by}: "{title}"'})
    q = quote_sentence(body)
    if q:
        text = f'{who} writes: "{q}"' if who else f'{lead}"{q}"'
        if len(text) > MAX_CHARS:
            text = f'"{q}"'
        drafts.append({"kind": "quote", "text": text})
    if not drafts:
        drafts.append({"kind": "title", "text": title})
    for d in drafts:
        f = screen(d["text"])
        if f:
            d["flags"] = f
    return drafts


# ------------------------------------------------------------------ delivery
def format_slack(results):
    L = [f"*Vital City - {len(results)} new "
         f"{'piece' if len(results)==1 else 'pieces'}, suggested posts*", ""]
    for r in results:
        L.append(f"*<{r['url']}|{r['title']}>*")
        by = r.get("author")
        L.append(f"_{by} · {r['date']}_" if by else f"_{r['date']}_")
        for p in r["posts"]:
            flag = "  :warning: " + ", ".join(p["flags"]) if p.get("flags") else ""
            L.append(f"> {p['text']}{flag}")
        L.append("")
    L.append("_Drafts, not decisions. Each one is meant to be postable as written "
             "or cut for parts. The link is appended when you post, so none of "
             "them include a URL._")
    return "\n".join(L)


def post_slack(text):
    """Two ways in, because a webhook URL is far quicker to create than a bot
    token and either one gets the digest delivered. Webhook wins if both are set."""
    hook = os.environ.get("SLACK_WEBHOOK_URL")
    if hook:
        req = urllib.request.Request(hook, data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                raise Abort(f"Slack webhook returned {r.status}")
        log("posted to Slack via webhook")
        return

    tok, to = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_DM_TO")
    if not tok or not to:
        # The Press page is the main destination now; Slack is a bonus.
        log("no Slack destination configured (SLACK_WEBHOOK_URL, or SLACK_BOT_TOKEN "
            "and SLACK_DM_TO); drafts are on the Press page only")
        return
    r = http_json("https://slack.com/api/chat.postMessage", timeout=30,
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json; charset=utf-8"},
        data=json.dumps({"channel": to, "text": text, "unfurl_links": False}).encode())
    if not r.get("ok"):
        raise Abort(f"Slack refused the message: {r.get('error')}")
    log("posted to Slack")


# ----------------------------------------------------------------- self-test
def self_test():
    ok = True
    cases = [
        ("It's not the budget. It's the politics.", True),
        ("The single most important number in the report is 4.2%.", True),
        ("A must-read deep dive on Rikers. A thread.", True),
        ("Ever wonder why NYC rents keep climbing? 🏠 #housing", True),
        ("Redlining ended in 1968. You can still find it on a map of New York City today.", False),
        ("Twenty things that bring crime down in cities. None of them replace policing.", False),
        ("x" * 300, True),
    ]
    for text, should_flag in cases:
        flagged = bool(screen(text))
        if flagged != should_flag:
            ok = False
            print(f"FAIL: {text[:50]!r} flagged={flagged} expected={should_flag}")
    fake = {"title": "Why Affordable Apartments Sit Empty", "custom_excerpt": "A city in need of housing must unlock its empty rent-stabilized apartments.",
            "authors": [{"name": "Howard Yaruss"}],
            "plaintext": ("A short intro.\n\n"
                          "More than 57,000 rent-stabilized apartments are sitting empty across New York City, enough to house a small city. "
                          "This sentence leans on the one before it and should never be chosen as a quote.")}
    d = rules_draft(fake)
    kinds = [x["kind"] for x in d]
    if (kinds != ["claim", "writer", "quote"]
            or d[0]["text"] != "From Howard Yaruss: A city in need of housing must unlock its empty rent-stabilized apartments."
            or not d[2]["text"].startswith('Howard Yaruss writes: "More than 57,000')
            or d[1]["text"] != 'Read Howard Yaruss: "Why Affordable Apartments Sit Empty"' or any(x.get("flags") for x in d)):
        ok = False
        print("FAIL: rules_draft", json.dumps(d))
    print("self-test passed" if ok else "self-test FAILED")
    return 0 if ok else 1


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7, help="lookback window (default 7)")
    ap.add_argument("--slack", action="store_true", help="post the digest to Slack")
    ap.add_argument("--dry-run", action="store_true", help="list new pieces, spend nothing")
    ap.add_argument("--piece", metavar="SLUG", help="redraft one piece, ignoring the seen-list")
    ap.add_argument("--max", type=int, default=12, help="cap pieces per run (default 12)")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--rules", action="store_true", help="free rule-based drafts even if a key exists")
    ap.add_argument("--refill", type=int, metavar="DAYS",
                    help="redraft every piece from the last DAYS days (rules mode), ignoring the seen-list")
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    if a.refill:
        a.days, a.rules, a.max = a.refill, True, 200
    posts = fetch_posts(max(a.days, 60) if a.piece else a.days)
    seen = load_seen()

    if a.refill:
        new = list(posts)
    elif a.piece:
        new = [p for p in posts if p["slug"] == a.piece]
        if not new:
            raise Abort(f"No piece with slug '{a.piece}' in the last 60 days.")
    else:
        new = [p for p in posts if p["slug"] not in seen]
    # Pages that are not pieces: the issue landing pages and similar carry no
    # author and little text, and have nothing to pitch.
    new = [p for p in new if len((p.get("plaintext") or "").strip()) >= 400]

    log(f"{len(posts)} published in window, {len(new)} not yet suggested")
    if not new:
        log("nothing new")
        return 0
    if len(new) > a.max:
        log(f"! capping at {a.max}; run again to pick up the rest")
        new = new[:a.max]

    if a.dry_run:
        for p in new:
            print(f"  {p['published_at'][:10]}  {p['title']}")
        print(f"\n{len(new)} pieces would cost roughly ${0.02*len(new):.2f}.")
        return 0

    key = None
    if not a.rules:
        try:
            key = anthropic_key()
        except Abort:
            log("no ANTHROPIC_API_KEY: using the free rule-based drafts")
    mode = "claude" if key else "rules"
    results = []
    for i, p in enumerate(new, 1):
        log(f"[{i}/{len(new)}] {p['title'][:64]}")
        if key:
            drafts, tries = draft(key, p)
        else:
            drafts, tries = rules_draft(p), 0
        results.append({
            "slug": p["slug"], "title": p["title"], "url": p["url"],
            "date": p["published_at"][:10],
            "author": ", ".join(a_["name"] for a_ in p.get("authors") or []),
            "handle": author_handle(p),
            "dek": plain(p.get("custom_excerpt") or ""),
            "tags": [t["name"] for t in p.get("tags") or [] if not t["name"].startswith("#")],
            "mode": mode, "posts": drafts, "attempts": tries + 1})
        if key and i < len(new):
            time.sleep(1)

    # Rolling window: keep the last 30 days, newest first, one entry per piece.
    keep = {}
    if OUT.exists():
        try:
            for r in json.loads(OUT.read_text()).get("pieces", []):
                keep[r["slug"]] = r
        except Exception:
            log("! suggestions file unreadable, starting it fresh")
    for r in results:
        keep[r["slug"]] = r
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    window = sorted((r for r in keep.values() if r["date"] >= cutoff), key=lambda r: r["date"], reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "window_days": 30, "pieces": window}, indent=1, ensure_ascii=False))

    digest = format_slack(results)
    if a.slack:
        post_slack(digest)
    else:
        print("\n" + digest)

    if not a.piece and not a.refill:
        save_seen(seen | {p["slug"] for p in new})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Abort as e:
        log(f"ABORT: {e}")
        sys.exit(2)
