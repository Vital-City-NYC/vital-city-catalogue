#!/usr/bin/env python3
"""Pull the full Vital City catalogue from the Ghost Content API.

Outputs (into ./data):
  - catalogue.json   full structured records, one per published post
  - catalogue.csv    flat spreadsheet view (one row per post)
  - authors.json     per-author rollup (post counts, bio, socials)
  - issues.json      per-issue rollup (date range, post count, sections)
  - tags.json        topic-tag rollup with post counts
  - meta.json        run metadata (timestamp, totals)

No third-party dependencies: standard library only.
"""

import csv
import json
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

API_BASE = "https://vital-city.ghost.io/ghost/api/content"
# Public, read-only key exposed on the site for its own search feature.
API_KEY = "dd8e178e9ddfc883537e71dd07"
SITE = "https://www.vitalcitynyc.org"

DATA_DIR = Path(__file__).resolve().parent / "data"

# Internal Ghost tags that are migration artifacts, not real classifications.
JUNK_TAG_SLUGS = {"hash-imagesuploaded", "hash-none"}
JUNK_TAG_PREFIXES = ("hash-import-",)


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "vital-city-catalogue/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_all_posts():
    """Page through every published post with authors + tags included."""
    posts = []
    page = 1
    while True:
        url = (
            f"{API_BASE}/posts/?key={API_KEY}"
            f"&include=authors,tags&limit=50&page={page}"
            # feature_image_caption carries the photo credit ("Mark Abramson /
            # The New York Times / Redux"); alt is the accessibility text.
            f"&fields=id,uuid,title,slug,url,excerpt,custom_excerpt,feature_image,"
            f"feature_image_alt,feature_image_caption,featured,visibility,"
            f"published_at,updated_at,created_at,reading_time"
            f"&formats=html"
            f"&order=published_at%20desc"
        )
        try:
            data = fetch_json(url)
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code} on page {page}: {e.reason}", file=sys.stderr)
            raise
        batch = data.get("posts", [])
        posts.extend(batch)
        pagination = data.get("meta", {}).get("pagination", {})
        total = pagination.get("total")
        next_page = pagination.get("next")
        print(f"  page {page}: {len(batch)} posts (running total {len(posts)}/{total})")
        if not next_page:
            break
        page = next_page
        time.sleep(0.3)  # be polite to the API
    return posts


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# What material is embedded in a piece.
#
# The article HTML is already fetched for word counts, so this costs no extra
# request. Two forms matter:
#   - Flourish ships as <div class="flourish-embed" data-src="visualisation/ID">,
#     NOT an iframe, so an iframe-only scan misses every chart.
#   - Everything else is an <iframe>, classified by host.
# Vital City embeds its own projects more than anything else, across four
# different GitHub Pages orgs, so those are recognised as one category.
# ---------------------------------------------------------------------------
FLOURISH_RE = re.compile(r'data-src=["\']((?:visualisation|story)/[^"\']+)', re.I)
IFRAME_RE   = re.compile(r'<iframe[^>]+src=["\']([^"\']+)', re.I)
_SELF_HOSTS = ("vitalcity-nyc.github.io", "vital-city.github.io",
               "vital-city-nyc.github.io", "joshgreenman1973.github.io",
               "vitalcitynyc.org")
_KINDS = (
    ("podcast",     ("simplecast.com", "soundcloud.com", "spotify.com", "megaphone.fm",
                     "libsyn.com", "buzzsprout.com", "art19.com")),
    ("video",       ("youtube.com", "youtu.be", "vimeo.com", "descript.com")),
    # Flourish ships two ways: a <div data-src> and an iframe on flo.uri.sh.
    # Counting only the div undercounts it badly -- 54 of 889 pieces use the
    # iframe form.
    ("flourish",    ("flo.uri.sh", "public.flourish.studio")),
    ("chart",       ("datawrapper", "dwcdn.net", "tableau", "infogram")),
    ("document",    ("docs.google.com", "drive.google.com", "documentcloud.org",
                     "scribd.com")),
    ("social",      ("twitter.com", "x.com", "instagram.com", "bsky.app", "tiktok.com")),
    ("map",         ("google.com/maps", "mapbox", "arcgis", "felt.com")),
    ("form",        ("typeform", "airtable", "surveymonkey", "jotform")),
)

def _iframe_kind(url):
    u = (url or "").lower()
    if any(h in u for h in _SELF_HOSTS):
        return "vital city project"
    for kind, hosts in _KINDS:
        if any(h in u for h in hosts):
            return kind
    return "other"

def extract_embeds(html):
    """Return {flourish:[...], iframes:[...], counts:{...}} for one piece."""
    html = html or ""
    flourish = []
    for src in FLOURISH_RE.findall(html):
        vid = src.split("?")[0].split("/")[-1]
        flourish.append({"id": vid, "src": src,
                         "url": f"https://public.flourish.studio/{src.split('?')[0]}/"})
    iframes = []
    for src in IFRAME_RE.findall(html):
        try:
            host = src.split("//", 1)[-1].split("/")[0].lower()
        except Exception:
            host = ""
        iframes.append({"url": src, "host": host, "kind": _iframe_kind(src)})
    counts = {"flourish": len(flourish)}
    for e in iframes:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return {"flourish": flourish, "iframes": iframes,
            "counts": {k: v for k, v in counts.items() if v},
            "total": len(flourish) + len(iframes)}


def html_to_text(html):
    if not html:
        return ""
    text = TAG_RE.sub(" ", html)
    text = unescape(text)
    return WS_RE.sub(" ", text).strip()


def word_count(html):
    return len(html_to_text(html).split())


def classify_tags(tags):
    """Split a post's tags into topics, issues, and dropped junk.

    Issues are internal (#-prefixed) tags such as #issue-14 or named series
    like #rubber-meets-road. Topics are the public-facing subject tags.
    """
    topics, issues = [], []
    for t in tags:
        slug = t.get("slug", "")
        if slug in JUNK_TAG_SLUGS or slug.startswith(JUNK_TAG_PREFIXES):
            continue
        if t.get("visibility") == "internal":
            issues.append(t)
        else:
            topics.append(t)
    return topics, issues


ISSUE_NUM_RE = re.compile(r"^#issue-(\d+)$")


def issue_number(name):
    m = ISSUE_NUM_RE.match(name.strip())
    return int(m.group(1)) if m else None


SENT_END_RE = re.compile(r"(?<=[.!?])\s")


def one_line_summary(p):
    """A single-line statement of the article's main idea.

    Prefers the editorial custom excerpt (Ghost `custom_excerpt`). Where none
    exists, falls back to the first sentence of Ghost's auto excerpt, trimmed.
    Returns None when neither is available.
    """
    ce = (p.get("custom_excerpt") or "").strip()
    if ce:
        return ce
    ex = html_to_text(p.get("excerpt") or "")
    if not ex:
        return None
    first = SENT_END_RE.split(ex, 1)[0].strip()
    if len(first) > 160:
        first = first[:157].rsplit(" ", 1)[0] + "…"
    return first or None


PODCAST_TAGS = {"podcast"}
QA_TAGS = {"interview", "conversations", "in conversation with..."}
QA_TITLE = re.compile(r"q&a|q & a|in conversation|a conversation with|\binterview\b|talks? (?:to|with)|speaks with|sits down with|\bpanel\b|\bforum\b", re.I)
REVIEW_TITLE = re.compile(r"a review of|book review|\breviewed\b", re.I)
TOOL_TITLE = re.compile(r"interactive|explorer|\btracker\b|dashboard|calculator|simulator|mapping tool|interactive map|\bquiz\b|proof.of.concept", re.I)
# Match actual JS library references (script src / cdn URLs), not prose words
# like "Vegas" or "roadmap". These signal the piece is itself an interactive tool.
MAP_LIB = re.compile(
    r"leaflet\.(?:js|css)|unpkg\.com/leaflet|api\.mapbox\.com|mapbox-gl|maplibre-gl|"
    r"/d3@|d3\.min\.js|d3js\.org|cdn\.jsdelivr\.net/npm/d3|vega-lite|/vega@|vega\.min|"
    r"deck\.gl|cdn\.observableusercontent", re.I)
DATA_TITLE = re.compile(r"by the numbers|in \d+ charts|, in charts|, charted|, mapped", re.I)
OTHER_TITLE = re.compile(r"about this project|: about\b|editor.?s? note|\bmasthead\b|welcome to vital city|a note (?:from|on|to)|call for submissions", re.I)
# The three series the site files under its own Policy section (vitalcitynyc.org/policy).
POLICY_SERIES = {"just-fix-it", "what-to-do-and-not-to-do", "rubber-meets-road"}
POLICY_TITLE = re.compile(r"^just fix it\b|what to do \(and not to do\)", re.I)
# Paragraphs that open with a speaker label ("Errol Louis:", "EL:", "Vital City:").
SPEAKER_PARA = re.compile(
    r"<p[^>]*>\s*(?:<[^>]+>\s*)*([A-Z][\w.'’-]+(?:\s+[A-Z][\w.'’-]+){0,3}):")

# Hand-checked calls the rules cannot see. Keyed by slug; each records its reason.
TYPE_OVERRIDES = {
    # Closing remarks at the "Are NYC's Jails Ungovernable?" forum — event
    # proceedings like its sibling panels, but a monologue, so no speaker labels.
    "are-nycs-jails-ungovernable-closing-remarks": ("q&a", "curated:event-proceedings"),
    "fixing-new-york-citys-jails-a-federal-receiver-closing-remarks":
        ("q&a", "curated:event-proceedings"),
    # Vital City's own intersection-design recommendation, published outside the
    # three Policy series.
    "a-safer-cheaper-quicker-way-of-daylighting-intersections":
        ("policy", "curated:vc-recommendation"),
}


def is_transcript(html):
    """True when the body is a multi-speaker conversation: many paragraphs
    opening with a speaker label, from at least two speakers who each take
    several turns. The thresholds are set high enough that a prose column
    quoting a short exchange does not qualify — only pieces whose form is the
    conversation itself."""
    labels = SPEAKER_PARA.findall(html or "")
    if len(labels) < 12:
        return False
    counts = {}
    for l in labels:
        counts[l] = counts.get(l, 0) + 1
    return sum(1 for n in counts.values() if n >= 4) >= 2


def classify_type(p, topics, issues):
    """Assign one content type, returning (type, basis). Rule-based and ordered
    most-specific-first; the basis string records why, for transparency.

    The type vocabulary mirrors how vitalcitynyc.org itself sections content:
    Commentary, Policy, Data, Podcast, plus Q&As, book reviews and tools.
    """
    slug = p.get("slug") or ""
    if slug in TYPE_OVERRIDES:
        return TYPE_OVERRIDES[slug]

    title = p.get("title") or ""
    tagnames = {t["name"].lower() for t in p.get("tags", [])}
    issue_slugs = {i.lower() for i in issues}
    html = p.get("html") or ""
    hl = html.lower()
    chart_embeds = hl.count("flourish-embed") + hl.count("datawrapper-vis") + hl.count("flo.uri.sh/visualisation")
    has_map_lib = bool(MAP_LIB.search(hl))
    # Iframe to Vital City's own hosted apps = a custom interactive tool/map
    has_vc_app = bool(re.search(r"<iframe[^>]+(?:vitalcity-nyc|vital-city-nyc)\.github\.io", hl))
    words = word_count(html)
    transcript = is_transcript(html)

    # 1. Site furniture and announcements, not editorial pieces.
    if "press releases" in tagnames:
        return "something else", "tag:press-release"
    if "in memoriam" in tagnames:
        return "something else", "tag:in-memoriam"
    if OTHER_TITLE.search(title):
        return "something else", "title:framing-page"
    if "events" in tagnames and words < 700 and not transcript:
        return "something else", "tag:event-notice"

    # 2. Culture: book reviews.
    if "book review" in tagnames or REVIEW_TITLE.search(title):
        return "book review", "tag:book-review" if "book review" in tagnames else "title:review"

    # 3. The podcast is its own section on the site.
    if tagnames & PODCAST_TAGS:
        return "podcast", "tag:podcast"

    # 4. Conversations: interviews, panels, forum transcripts.
    if tagnames & QA_TAGS:
        return "q&a", "tag:" + next(iter(tagnames & QA_TAGS))
    if QA_TITLE.search(title):
        return "q&a", "title:conversation"
    if transcript:
        return "q&a", "html:multi-speaker-transcript"

    # 5. Institutional data reports (the site's Data section).
    if "data stories" in tagnames or "data-stories" in issue_slugs:
        return "data analysis", "tag:data-stories"

    # 6. Genuine interactive tools: the title names one, or the body is
    #    essentially just the embed. An essay that merely embeds one of our
    #    charts or maps to illustrate its argument is still an essay.
    if TOOL_TITLE.search(title):
        return "map/tool", "title:tool-or-map"
    if words < 300 and (has_vc_app or has_map_lib):
        return "map/tool", "html:embed-is-the-piece"

    # 7. Chart-driven analysis.
    if DATA_TITLE.search(title):
        return "data analysis", "title:data-framing"
    if chart_embeds >= 3:
        return "data analysis", f"html:{chart_embeds}-chart-embeds"

    # 8. Vital City's own policy recommendations (the site's Policy section).
    if issue_slugs & POLICY_SERIES:
        return "policy", "series:" + next(iter(issue_slugs & POLICY_SERIES))
    if POLICY_TITLE.search(title):
        return "policy", "title:policy-recommendation"

    # 9. Everything else: analysis and opinion, mostly by outside contributors.
    return "opinion/commentary", "default"


def normalize_post(p):
    topics, issues = classify_tags(p.get("tags", []))
    authors = [a.get("name") for a in p.get("authors", []) if a.get("name")]
    primary = (p.get("primary_author") or {}).get("name")
    pub = p.get("published_at")
    pub_date = pub.split("T")[0] if pub else None

    issue_names = [i["name"].lstrip("#") for i in issues]
    numbered = [issue_number(i["name"]) for i in issues]
    numbered = [n for n in numbered if n is not None]
    ptype, type_basis = classify_type(p, [t["name"] for t in topics], issue_names)

    return {
        "title": p.get("title"),
        "slug": p.get("slug"),
        "url": f"{SITE}/{p.get('slug')}/",
        "type": ptype,
        "type_basis": type_basis,
        "published_date": pub_date,
        "published_at": pub,
        "updated_at": p.get("updated_at"),
        "primary_author": primary,
        "authors": authors,
        "topics": [t["name"] for t in topics],
        "issues": issue_names,
        "issue_numbers": numbered,
        "summary": one_line_summary(p),
        "excerpt": p.get("custom_excerpt") or (p.get("excerpt") or "").strip() or None,
        "feature_image": p.get("feature_image"),
        # Header-image provenance. The caption is where the credit lives
        # ("Mark Abramson / The New York Times / Redux"); stored as plain text
        # since Ghost wraps it in markup.
        "feature_image_alt": (p.get("feature_image_alt") or "").strip() or None,
        "feature_image_credit": html_to_text(p.get("feature_image_caption") or "").strip() or None,
        # What is embedded in the piece: Flourish charts by id, plus every
        # iframe classified by host. Costs no extra request -- the HTML is
        # already fetched for the word count.
        "embeds": extract_embeds(p.get("html")),
        "featured": p.get("featured", False),
        "visibility": p.get("visibility"),
        "word_count": word_count(p.get("html")),
        "reading_minutes": max(1, round(word_count(p.get("html")) / 230)) if p.get("html") else None,
        "id": p.get("id"),
    }


def build_rollups(records, raw_posts):
    # Authors
    authors = {}
    raw_by_id = {p["id"]: p for p in raw_posts}
    for r in records:
        for a in r["authors"]:
            authors.setdefault(a, {"name": a, "post_count": 0, "slugs": []})
            authors[a]["post_count"] += 1
            authors[a]["slugs"].append(r["slug"])
    # enrich author bios/socials from raw author objects
    bio_by_name = {}
    for p in raw_posts:
        for a in p.get("authors", []):
            if a.get("name") and a["name"] not in bio_by_name:
                bio_by_name[a["name"]] = {
                    "slug": a.get("slug"),
                    "bio": a.get("bio"),
                    "url": a.get("url"),
                    "twitter": a.get("twitter"),
                    "website": a.get("website"),
                }
    for name, info in authors.items():
        info.update(bio_by_name.get(name, {}))
        info["slugs"] = sorted(set(info["slugs"]))

    # Issues
    issues = {}
    for r in records:
        for name in r["issues"]:
            issues.setdefault(name, {"name": name, "post_count": 0, "dates": [], "topics": {}})
            issues[name]["post_count"] += 1
            if r["published_date"]:
                issues[name]["dates"].append(r["published_date"])
            for t in r["topics"]:
                issues[name]["topics"][t] = issues[name]["topics"].get(t, 0) + 1
    for name, info in issues.items():
        dates = sorted(d for d in info["dates"] if d)
        info["first_published"] = dates[0] if dates else None
        info["last_published"] = dates[-1] if dates else None
        info["number"] = issue_number("#" + name)
        if info["number"] is not None:
            info["display_name"] = f"Issue {info['number']}"
        else:
            info["display_name"] = name.replace("-", " ").title()
        info["top_topics"] = sorted(info["topics"].items(), key=lambda x: -x[1])[:5]
        del info["dates"], info["topics"]

    # Topics
    topics = {}
    for r in records:
        for t in r["topics"]:
            topics[t] = topics.get(t, 0) + 1
    topics = [{"name": k, "post_count": v} for k, v in sorted(topics.items(), key=lambda x: -x[1])]

    return authors, issues, topics


def write_csv(records, path):
    cols = [
        "published_date", "title", "type", "summary", "primary_author", "authors", "topics",
        "issues", "issue_numbers", "word_count", "reading_minutes",
        "featured", "visibility", "url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in records:
            w.writerow([
                r["published_date"], r["title"], r["type"], r["summary"] or "", r["primary_author"],
                "; ".join(r["authors"]), "; ".join(r["topics"]),
                "; ".join(r["issues"]), "; ".join(str(n) for n in r["issue_numbers"]),
                r["word_count"], r["reading_minutes"], r["featured"],
                r["visibility"], r["url"],
            ])


def load_previous_slugs():
    path = DATA_DIR / "catalogue.json"
    if not path.exists():
        return None  # first ever run
    try:
        return {r["slug"] for r in json.loads(path.read_text())}
    except Exception:
        return None


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    prev_slugs = load_previous_slugs()
    print("Fetching all posts from Ghost Content API...")
    raw = fetch_all_posts()
    print(f"Fetched {len(raw)} posts. Normalizing...")
    records = [normalize_post(p) for p in raw]
    records.sort(key=lambda r: r["published_at"] or "", reverse=True)

    # What changed since the last run (None on the very first run).
    new_articles = []
    if prev_slugs is not None:
        new_articles = [
            {"title": r["title"], "url": r["url"], "published_date": r["published_date"],
             "primary_author": r["primary_author"]}
            for r in records if r["slug"] not in prev_slugs
        ]

    authors, issues, topics = build_rollups(records, raw)

    (DATA_DIR / "catalogue.json").write_text(json.dumps(records, indent=2, ensure_ascii=False))
    write_csv(records, DATA_DIR / "catalogue.csv")
    (DATA_DIR / "authors.json").write_text(json.dumps(
        sorted(authors.values(), key=lambda a: -a["post_count"]), indent=2, ensure_ascii=False))
    (DATA_DIR / "issues.json").write_text(json.dumps(
        sorted(issues.values(), key=lambda i: (i["number"] is None, -(i["number"] or 0))),
        indent=2, ensure_ascii=False))
    (DATA_DIR / "tags.json").write_text(json.dumps(topics, indent=2, ensure_ascii=False))

    type_counts = {}
    for r in records:
        type_counts[r["type"]] = type_counts.get(r["type"], 0) + 1
    types = [{"type": k, "post_count": v} for k, v in sorted(type_counts.items(), key=lambda x: -x[1])]
    (DATA_DIR / "types.json").write_text(json.dumps(types, indent=2, ensure_ascii=False))

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "site": SITE,
        "total_posts": len(records),
        "total_authors": len(authors),
        "total_issues": len(issues),
        "total_topics": len(topics),
        "date_range": [
            min((r["published_date"] for r in records if r["published_date"]), default=None),
            max((r["published_date"] for r in records if r["published_date"]), default=None),
        ],
        "first_run": prev_slugs is None,
        "new_article_count": len(new_articles),
        "new_articles": new_articles,
    }
    (DATA_DIR / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    print("\nDone. Summary:")
    print(json.dumps({k: v for k, v in meta.items() if k != "new_articles"}, indent=2))
    if new_articles:
        print(f"\n{len(new_articles)} new article(s) since last run:")
        for a in new_articles:
            print(f"  - {a['published_date']}  {a['title']}  ({a['primary_author']})")


if __name__ == "__main__":
    main()
