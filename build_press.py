#!/usr/bin/env python3
"""Build the Press map: who covers New York City government, and what they cover.

Writes private/press.json (gitignored) for press/index.html to read after
encrypt_press.py turns it into press/data.enc.

The idea the tool rests on: a reporter's beat is not a label somebody typed on a
masthead, it is the set of stories they actually filed. So the build harvests
bylines first -- RSS for every outlet, the WordPress API wherever one is
readable -- matches each story against a vocabulary of New York City government
beats, and keeps the matching stories next to the count. Every card can show its
work, and the ranking on a topic search is a claim about published evidence.

Contact rules, inherited from the officials database:
  * an address is kept only if it was read verbatim off a page we fetched,
  * and only if it pairs with the person's name -- newsroom addresses are built
    from names, so an address that cannot be derived from the name is evidence
    the parser walked into the wrong person's block. Those are dropped to a
    review list rather than published.
Nothing is ever inferred from a pattern.

  python3 build_press.py            # full harvest (~12 min)
  python3 build_press.py --fast     # reuse cached harvest, rebuild the output

Dependencies beyond the standard library: feedparser, beautifulsoup4. Fetching
is done with curl, so no requests dependency.
"""
import argparse, collections, csv, html as H, json, os, re, subprocess, sys, unicodedata
import concurrent.futures as cf
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
PRESS = ROOT / "press"
CACHE = ROOT / "private" / "press_cache"   # inside private/, which is already gitignored
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")

# ---------------------------------------------------------------- fetching
def _cf_decode(h):
    try:
        k = int(h[:2], 16)
        return "".join(chr(int(h[i:i + 2], 16) ^ k) for i in range(2, len(h), 2))
    except Exception:
        return ""

def unhide_emails(src):
    """Cloudflare rewrites every address on a page it protects into a hex blob
    (data-cfemail="…", /cdn-cgi/l/email-protection#…) that a browser decodes and
    a scraper never sees. The Trace, The 74 and Jewish Insider publish their
    reporters' addresses this way, so to this build they had none. Decoding is
    reading what the page publishes, not inferring anything."""
    src = re.sub(r'data-cfemail="([0-9a-fA-F]{8,})"', lambda m: f'href="mailto:{_cf_decode(m.group(1))}"', src)
    src = re.sub(r'/cdn-cgi/l/email-protection#([0-9a-fA-F]{8,})', lambda m: f'mailto:{_cf_decode(m.group(1))}', src)
    return src

def curl(url, timeout=30):
    try:
        p = subprocess.run(["curl", "-sSL", "--max-time", str(timeout), "-A", UA, url],
                           capture_output=True, timeout=timeout + 20)
        return unhide_emails(p.stdout.decode("utf8", "ignore"))
    except Exception:
        return ""

def curl_json(url, timeout=45):
    try:
        return json.loads(curl(url, timeout))
    except Exception:
        return None

# ---------------------------------------------------------------- names
def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()

def person_key(name, outlet):
    slug = re.sub(r"\s+", "-", re.sub(r"[^a-z ]", "", norm(name)).strip())
    return outlet + ":" + slug

def merge_name(name):
    """Loose key for matching a reporter across sources (press list, VC authors)."""
    return re.sub(r"[^a-z]", "", norm(name))

def _key(passphrase, salt, iters):
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters).derive(passphrase.encode())

def encrypt_blob(data: bytes, passphrase: str) -> dict:
    """AES-256-GCM, PBKDF2-SHA256 600k: the scheme every toolkit payload uses."""
    import base64, secrets
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    ct = AESGCM(_key(passphrase, salt, 600_000)).encrypt(iv, data, None)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iters": 600_000, "salt": b(salt), "iv": b(iv), "ct": b(ct)}

def decrypt_blob(blob: dict, passphrase: str) -> bytes:
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    d = lambda x: base64.b64decode(x)
    return AESGCM(_key(passphrase, d(blob["salt"]), blob["iters"])).decrypt(d(blob["iv"]), d(blob["ct"]), None)

def person_case(name):
    """"JENIFEER PORTER GORE" -> "Jenifeer Porter Gore", keeping McX, O'X and
    hyphenated surnames intact."""
    def word(w):
        parts = re.split(r"([-'\u2019])", w.lower())
        out = "".join(x.capitalize() if x not in "-'\u2019" else x for x in parts)
        return re.sub(r"^Mc([a-z])", lambda m: "Mc" + m.group(1).upper(), out)
    return " ".join(word(w) for w in name.split())

def clean_person_name(name, has_byline):
    """A byline or a masthead line only becomes a person if it looks like one.

    Two words at least, no digits, no @: that drops CMS logins ("edavis",
    "mgross170") and the address somebody typed into a byline field. All-caps
    names are real on some bylines -- the Amsterdam News sets them that way --
    so they are re-cased, but an all-caps line lifted off a masthead with no
    byline behind it is a section heading ("SCHOOL CLOSINGS", "BETTER GET
    BAQUERO"), not a reporter."""
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" .,;:|")
    # Wire datelines: "Joseph Gedeon in Washington", "Xan Brooks in Venice".
    n = re.sub(r"\s+in\s+[A-Z][\w.\-]+(?:\s+[A-Z][\w.\-]+)?$", "", n)
    # Credit lines, desks and features that sit in a byline field.
    low = n.lower()
    if re.search(r"\b(photos?|courtesy|subscriber|faq|tracker|recovery|reporting|digital|updates?|"
                 r"live|video|podcast|newsletter|editorial|explainer|guide|q&a|news|team|network|connect|crime|pr|mundo|desk|wire)\b", low) or "\u2019re " in low or "'re " in low:
        return None
    raw_words = n.split()
    lower_words = [w for w in raw_words[1:] if w.islower() and w not in ("de", "da", "di", "del", "della", "der", "van", "von", "la", "le", "du", "dos", "y", "e", "and", "bin", "ibn", "al", "el")]
    if lower_words and not n.islower():
        return None          # "Word in Black": an ordinary lowercase word mid-name is prose, not a name
    if "@" in n or re.search(r"\d", n):
        return None
    words = [w for w in re.findall(r"[A-Za-z\u00c0-\u024f'\u2019\-]+", n) if len(w.strip("'-\u2019")) >= 2]
    if len(words) < 2:
        return None
    letters = re.sub(r"[^A-Za-z\u00c0-\u024f]", "", n)
    if letters.isupper():
        if not has_byline:
            return None
        n = person_case(n)
    elif letters.islower():
        n = person_case(n)
    from name_case import fix_name_case
    return fix_name_case(n)

def loose_name(name):
    """First and last name only. "John K. Roman" on his newsletter and "John
    Roman" on the press list are one person; so are "Charles Fain Lehman" and
    "Charles Lehman". Matching on the full string made two records for each, and
    only one of them carried the press-list flag."""
    parts = [w for w in re.sub(r"[^a-z\s\-]", " ", norm(name)).split() if len(w) > 1]
    if len(parts) < 2:
        return merge_name(name)
    return parts[0] + parts[-1]

def pairs_with_email(name, email):
    local = re.sub(r"[^a-z]", "", norm(email.split("@")[0]))
    parts = [re.sub(r"[^a-z\-]", "", norm(p)) for p in name.split()]
    parts = [p for p in parts if len(p) > 1]
    if not parts:
        return False
    first, last = parts[0], parts[-1]
    for L in {last, last.replace("-", "")}:
        if len(L) > 2 and L in local:
            return True
        if local in (first[0] + L, first + L, (first + L), L + first[0]):
            return True
    if len(parts) > 2:
        for mid in parts[1:-1]:
            if len(mid) > 2 and mid in local:
                return True
    return len(first) > 3 and local == re.sub(r"[^a-z]", "", first)

GENERIC_LOCAL = re.compile(
    r"^(tips?|info|news|editor|editors|desk|contact|press|media|support|help|careers|jobs|hello|"
    r"admin|webmaster|advertis\w*|sales|subscriptions?|general|newsroom|feedback|letters|corrections|"
    r"noreply|no-reply|privacy|legal|events|donate|membership|viewer\.services|assignment\w*|story\w*)$", re.I)

# ---------------------------------------------------------------- beats
def compile_beats(beats):
    out = {}
    for bid, b in beats.items():
        pats = []
        for t in b["terms"]:
            if t.endswith("*"):
                pats.append((re.compile(r"\b" + re.escape(t[:-1]) + r"\w*", re.I), t))
            elif t.isupper() and len(t) <= 5:
                # case-sensitive so ICE does not match "police" and DOE not "does"
                pats.append((re.compile(r"\b" + re.escape(t) + r"\b"), t))
            else:
                pats.append((re.compile(r"\b" + re.escape(t) + r"s?\b", re.I), t))
        out[bid] = {"label": b["label"], "priority": b.get("priority", 3), "pats": pats}
    return out

STOP = set("""a an the and or but of in on at to for from with by as is are was were be been being this
that these those it its if then than so such not no nor can could will would should may might must do
does did done have has had new york city nyc more over after before amid says say said why how what when
who whom which about into out up down off again also just only very much many most some any each other
another one two three first second last next year years day days week weeks month months""".split())

def terms_of(text):
    ws = re.findall(r"[a-zA-Z][a-zA-Z'’\-]{2,}", (text or "").lower())
    return [w for w in ws if w not in STOP and len(w) > 2]

# ---------------------------------------------------------------- harvest: RSS
BAD_AUTHOR = re.compile(r"^(staff|editor|admin|newsroom|press|associated press|ap|reuters|none|unknown|"
                        r"[\w.\-]*(?:rest|api|service|bot|agent|wire|feed|cms|syndicat\w*)[\w.\-]*)$", re.I)
NAME_OK = re.compile(r"^[A-ZÀ-Ü][\w'’.\-]+(\s+[\w'’.\-À-Ü]+){1,3}$")

def clean_authors(raw):
    if not raw:
        return []
    a = re.sub(r"<[^>]+>", " ", H.unescape(raw))
    a = re.sub(r"^\s*(by|By|BY)\s+", "", re.sub(r"\s+", " ", a).strip())
    out = []
    for p in re.split(r",| and | & |/|\|", a):
        p = re.sub(r"\s*\(.*?\)\s*", "", p).strip(" .;")
        if not p or len(p) < 4 or len(p) > 48:
            continue
        if BAD_AUTHOR.match(p) or not NAME_OK.match(p):
            continue
        if p.lower().endswith((" news", " media", " desk", " report")):
            continue
        out.append(p)
    return list(dict.fromkeys(out))

def entry_authors(e):
    cands = []
    for a in (e.get("authors") or []):
        if isinstance(a, dict) and a.get("name"):
            cands.append(a["name"])
    for k in ("author", "dc_creator", "creator"):
        if e.get(k):
            cands.append(e[k])
    seen, out = set(), []
    for c in cands:
        for n in clean_authors(c):
            if n.lower() not in seen:
                seen.add(n.lower()); out.append(n)
    return out

def entry_date(e):
    for k in ("published_parsed", "updated_parsed"):
        if e.get(k):
            try:
                return datetime(*e[k][:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return None

def harvest_rss(outlets):
    def one(o):
        items, errors = [], []
        for url in o.get("rss") or []:
            raw = curl(url)
            if not raw:
                errors.append({"outlet": o["id"], "url": url, "error": "empty response"}); continue
            d = feedparser.parse(raw)
            if not d.entries:
                errors.append({"outlet": o["id"], "url": url, "error": "parsed 0 entries"}); continue
            ff = o.get("feed_filter")
            for e in d.entries:
                link = e.get("link") or ""
                if ff and ff not in link:
                    continue
                items.append({
                    "outlet": o["id"],
                    "title": H.unescape(re.sub(r"<[^>]+>", "", e.get("title") or "")).strip(),
                    "url": link, "date": entry_date(e), "authors": entry_authors(e),
                    "summary": H.unescape(re.sub(r"<[^>]+>", " ", e.get("summary") or ""))[:600].strip(),
                    "tags": [t.get("term") for t in (e.get("tags") or []) if t.get("term")][:8],
                })
        return items, errors

    all_items, all_errors = [], []
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        for items, errors in ex.map(one, outlets):
            all_items += items; all_errors += errors
    return all_items, all_errors

# ---------------------------------------------------------------- harvest: WordPress
def harvest_wp(outlets, pages=3, per_page=100):
    def strip(t):
        return H.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()

    def one(o):
        base = o["site"].rstrip("/")
        items = []
        for page in range(1, pages + 1):
            d = curl_json(f"{base}/wp-json/wp/v2/posts?per_page={per_page}&page={page}&_embed=author,wp:term")
            if not isinstance(d, list) or not d:
                break
            for p in d:
                emb = p.get("_embedded") or {}
                authors = [strip(a.get("name")) for a in (emb.get("author") or [])
                           if isinstance(a, dict) and a.get("name")]
                terms = [strip(t["name"]) for g in (emb.get("wp:term") or []) for t in (g or [])
                         if isinstance(t, dict) and t.get("name")]
                items.append({
                    "outlet": o["id"], "author_id": p.get("author"),
                    "coauthors": p.get("coauthors") or [],
                    "title": strip((p.get("title") or {}).get("rendered")),
                    "url": p.get("link"),
                    "date": (p.get("date_gmt") + "Z") if p.get("date_gmt") else None,
                    "authors": [a for a in authors if a and a.lower() not in ("admin", "staff", "editor")],
                    "summary": strip((p.get("excerpt") or {}).get("rendered"))[:400],
                    "tags": terms[:10],
                })
            if len(d) < per_page:
                break
        return o["id"], items

    all_items, by_id = [], {o["id"]: o for o in outlets}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for oid, items in ex.map(one, outlets):
            all_items += items

    # Tribune and MediaNews papers -- the Daily News among them -- keep bylines in
    # a Co-Authors Plus taxonomy and refuse the users endpoint outright. That
    # taxonomy is public, and its terms carry the author archive link, so the real
    # display name can be read off the reporter's own page rather than guessed
    # out of a slug.
    need_co = sorted({i["outlet"] for i in all_items if i.get("coauthors") and not i["authors"]})
    for oid in need_co:
        base = by_id[oid]["site"].rstrip("/")
        wanted = {c for i in all_items if i["outlet"] == oid for c in (i.get("coauthors") or [])}
        # Fetched one term at a time by id. Paging the whole taxonomy looked
        # tidier but the Daily News carries thousands of historical bylines, so
        # the reporters on this month's stories were never in the first pages
        # and every name came back empty.
        def term_by_id(tid):
            d = curl_json(f"{base}/wp-json/wp/v2/coauthors/{tid}")
            if isinstance(d, dict) and d.get("id"):
                return tid, {"slug": d.get("name") or "", "link": d.get("link")}
            return tid, None
        terms = {}
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            for tid, t in ex.map(term_by_id, sorted(wanted)):
                if t:
                    terms[tid] = t
        if not terms:
            continue

        def display(term):
            """The author archive page carries the reporter's name in its h1 and
            its og:title. Read it rather than title-casing a slug, which cannot
            tell a hyphenated surname from two words."""
            # The taxonomy link is a query-string URL that several sites render
            # as the homepage. The clean /author/<slug>/ path is the page that
            # actually carries the reporter's name, so try it first and fall back.
            clean = base + "/author/" + re.sub(r"^cap-", "", term["slug"] or "") + "/"
            src = curl(clean, 20)
            if len(src) < 2000 and term.get("link"):
                src = curl(term["link"], 20)
            else:
                term["link"] = clean
            for pat in (r"<h1[^>]*>(.*?)</h1>",
                        r'property="og:title"\s+content="([^"]{4,60})"'):
                for m in re.findall(pat, src, re.S | re.I):
                    t = strip_tags(H.unescape(m))
                    t = re.split(r"\s+[|\u2013\u2014]\s+", t)[0].strip()
                    if 4 < len(t) < 45 and re.match("^" + NAME_PAT + "$", t) and not JUNK.match(t):
                        return t, term["link"], "author archive page"
            return None, term.get("link"), None

        resolved = {}
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            for tid, (name, link, how) in zip(terms.keys(), ex.map(display, terms.values())):
                if name:
                    resolved[tid] = name
        for i in all_items:
            if i["outlet"] == oid and not i["authors"]:
                names = [resolved[c] for c in (i.get("coauthors") or []) if c in resolved]
                if names:
                    i["authors"] = names
        print(f"  co-authors resolved for {oid}: {len(resolved)} names")

    # Some sites serve posts but refuse the author embed; ask for the user list.
    need = sorted({i["outlet"] for i in all_items if i["author_id"] and not i["authors"]})
    users = {}
    for oid in need:
        d = curl_json(by_id[oid]["site"].rstrip("/") + "/wp-json/wp/v2/users?per_page=100")
        if isinstance(d, list) and d:
            users[oid] = {str(u.get("id")): strip(u.get("name")) for u in d if u.get("id")}
    for i in all_items:
        if not i["authors"] and i["author_id"] is not None:
            n = users.get(i["outlet"], {}).get(str(i["author_id"]))
            if n and n.lower() not in ("admin", "staff", "editor"):
                i["authors"] = [n]
    return all_items

# ---------------------------------------------------------------- harvest: mastheads
ROLE = re.compile(r"reporter|editor|correspond|columnist|producer|anchor|writer|chief|bureau|director|"
                  r"publisher|founder|host|photograph|data|investigat|deputy|managing|senior|contribut|"
                  r"critic|desk|politics|housing|education|health|transit|justice|climate|immigration|"
                  r"business|labor|courts|news|manager|president|officer|fellow|coordinator|engagement|"
                  r"audience|social|newsletter", re.I)
JUNK = re.compile(r"^(home|about|staff|contact|menu|search|subscribe|donate|newsletter|privacy|terms|follow|"
                  r"share|more|read|sign|log|our team|the team|masthead|support|advertise|careers|jobs|events|"
                  r"podcast|español|new york|york city|city hall|united states|read more|learn more|get in|sign up)\b", re.I)
NAME_PAT = (r"[A-Z][\w'’\-áéíóúñàüöä]+"
            r"(?:\s+(?:de|van|von|del|la|di|Mc|Mac)?[A-Z][\w'’\-áéíóúñàüöä.]+){1,3}")

def ok_name(s):
    if not s or len(s) < 5 or len(s) > 42:
        return False
    if JUNK.match(s) or ROLE.search(s):
        return False
    return bool(re.match("^" + NAME_PAT + "$", s))

def deescape(s):
    return (s.replace('\\"', '"').replace("\\n", "\n").replace("\\/", "/")
             .replace("\\u003C", "<").replace("\\u003E", ">").replace("\\u002F", "/"))

INLINE = re.compile(r"</?(?:b|i|em|strong|span|u|small|sup|sub|a|mark|abbr|wbr)\b[^>]*>", re.I)

def strip_tags(s):
    """Inline tags close up, block tags become a space. Replacing every tag with
    a space turned "Co<span>ntent</span> Producer" into "Co ntent Producer"."""
    s = INLINE.sub("", s)
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s))).strip()

def tidy_title(t):
    if not t:
        return None
    t = re.sub(r"\s+", " ", t).strip(" ,-–—|·•:")
    if t.isupper():
        small = {"for", "of", "and", "in", "the", "at", "on", "to", "a", "an", "with", "by", "de"}
        words = []
        for i, w in enumerate(t.lower().split()):
            words.append(w if (i and w in small) else "-".join(x.capitalize() for x in w.split("-")))
        t = " ".join(words)
    return t

def candidates_from_tail(tail):
    toks = tail.split()
    out = []
    for i in range(len(toks) - 1, -1, -1):
        for L in (2, 3, 4):
            if i + L > len(toks):
                break
            cand = " ".join(toks[i:i + L]).strip(" ,–—-|·•:")
            if cand.isupper() or not ok_name(cand):
                continue
            title = " ".join(toks[i + L:]).strip(" ,–—-|·•:")
            if title and (len(title) > 80 or not ROLE.search(title)):
                continue
            out.append((cand, title, i))
    return out

def parse_masthead(oid, src, url, review):
    people = {}
    # 1. published addresses, read backwards for the name and role in front of them
    s = deescape(src)
    for m in re.finditer(r"mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", s):
        email = m.group(1).strip().lower()
        if GENERIC_LOCAL.match(email.split("@")[0]):
            continue
        ctx = strip_tags(re.sub(r"<[^>]*$", " ", s[max(0, m.start() - 460):m.start()]))
        tail = re.split(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", ctx[-230:])[-1]
        tail = re.sub(r"<[^>]*$", " ", tail).strip()
        cands = candidates_from_tail(tail)
        if not cands:
            continue
        paired = next(((n, t) for n, t, _ in cands if pairs_with_email(n, email)), None)
        name, title = paired if paired else (cands[0][0], cands[0][1])
        rec = people.setdefault(name, {"name": name, "outlet": oid, "staff_page": url})
        if paired:
            rec["email"] = email
            rec["email_source_url"] = url
            rec["email_evidence"] = tail[-110:]
        else:
            review.append({"outlet": oid, "email": email, "nearest_name": name,
                           "reason": "no name in the surrounding text pairs with this address",
                           "context": tail[-150:], "source_url": url})
        if title and not rec.get("title"):
            rec["title"] = tidy_title(title)
            rec["title_source_url"] = url
    # 2. name / role pairs in card markup, for the many mastheads without addresses
    soup = BeautifulSoup(src, "html.parser")
    for bad in soup(["script", "style", "noscript"]):
        bad.decompose()
    text = lambda el: re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "b", "p", "span", "div", "li",
                            "figcaption", "td", "a"]):
        name = text(h)
        if not ok_name(name):
            continue
        title, sib, hops = "", h.next_sibling, 0
        while sib is not None and hops < 4:
            st = text(sib) if getattr(sib, "get_text", None) else re.sub(r"\s+", " ", str(sib)).strip()
            if st:
                if ROLE.search(st) and len(st) < 85:
                    title = st; break
                if len(st) > 85:
                    break
            sib = sib.next_sibling; hops += 1
        if not title and h.parent is not None:
            m = re.search(re.escape(name) + r"\s*[,|·•—–-]?\s*([^.|·•]{3,80})", text(h.parent))
            if m and ROLE.search(m.group(1)):
                title = m.group(1).strip(" ,-–—|")
        if not title:
            continue
        rec = people.setdefault(name, {"name": name, "outlet": oid, "staff_page": url})
        rec.setdefault("title", tidy_title(title))
        rec.setdefault("title_source_url", url)
    return list(people.values())

def harvest_mastheads(outlets):
    jobs = [(o["id"], o["staff_url"]) for o in outlets if o.get("staff_url")]
    people, review, fails = [], [], []

    def one(job):
        oid, url = job
        return oid, url, curl(url, 40)

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for oid, url, src in ex.map(one, jobs):
            if not src or len(src) < 500:
                fails.append({"outlet": oid, "url": url, "error": "masthead did not load"}); continue
            people += parse_masthead(oid, src, url, review)
    return people, review, fails

# ---------------------------------------------------------------- harvest: byline blocks
AUTHORPATH = re.compile(r'href="([^"]*/(?:author|authors|staff|people|profile|contributor|contributors|by|reporters?)/[^"?#]+)"', re.I)

def slugs(name):
    parts = re.sub(r"[^a-z\s\-]", "", norm(name)).split()
    if not parts:
        return []
    return list(dict.fromkeys(["-".join(parts), "".join(parts), ".".join(parts), "_".join(parts)]))

def read_byline_block(job):
    pid, name, url = job
    out = {"id": pid}
    src = curl(url, 25)
    if not src:
        out["error"] = "story page did not load"
        return out
    s = src.replace('\\"', '"').replace("\\/", "/").replace("\\u003C", "<").replace("\\u003E", ">")
    sl = slugs(name)
    for m in AUTHORPATH.finditer(s):
        href = m.group(1)
        if any(x in norm(href) for x in sl):
            if href.startswith("/"):
                base = re.match(r"(https?://[^/]+)", url)
                href = (base.group(1) + href) if base else href
            if href.startswith("http"):
                out["author_page"] = href
                break
    for em in re.finditer(r"(?:mailto:)?([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", s):
        email = em.group(1).lower()
        if GENERIC_LOCAL.match(email.split("@")[0]) or email.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
            continue
        if pairs_with_email(name, email):
            out["email"] = email
            out["email_source_url"] = url
            out["email_evidence"] = strip_tags(s[max(0, em.start() - 160):em.end() + 40])[-150:]
            break
    for pat, fld in ((r'https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{2,15})', "x"),
                     (r'https?://bsky\.app/profile/([A-Za-z0-9._\-]+)', "bluesky")):
        for m in re.finditer(pat, s):
            h = m.group(1)
            if h.lower() in ("share", "intent", "home", "i", "search", "hashtag"):
                continue
            flat = [x.replace("-", "").replace(".", "").replace("_", "") for x in sl]
            if norm(h) in flat or norm(h) in norm(name).replace(" ", ""):
                out[fld] = h
                break
    return out

def read_author_page(job):
    pid, name, url = job
    out = {"id": pid}
    src = curl(url, 25)
    if not src:
        return out
    s = src.replace('\\"', '"').replace("\\/", "/")
    for em in re.finditer(r"(?:mailto:)?([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", s):
        email = em.group(1).lower()
        if GENERIC_LOCAL.match(email.split("@")[0]) or email.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
            continue
        if pairs_with_email(name, email):
            out["email"] = email
            out["email_source_url"] = url
            out["email_evidence"] = strip_tags(s[max(0, em.start() - 160):em.end() + 40])[-150:]
            break
    m = (re.search(r'<meta[^>]+name="description"[^>]+content="([^"]{40,400})"', s, re.I)
         or re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]{40,400})"', s, re.I))
    if m:
        bio = H.unescape(m.group(1)).strip()
        low = bio.lower()
        if name.split()[0].lower() in low or " covers " in low or " reports " in low:
            out["bio"] = bio[:400]
    return out

# ---------------------------------------------------------------- Vital City layer
def load_vc_layer():
    """Who already engages with Vital City, read from the catalogue's own files."""
    vc = {"press_list": {}, "authors": set(), "mentions": [], "ledger": {}, "errors": []}

    p = PRIV / "press_source.csv"
    if p.exists():
        for row in csv.DictReader(open(p, encoding="utf8")):
            n = (row.get("name") or "").strip()
            if n:
                vc["press_list"][loose_name(n)] = {
                    "name": n, "outlet": (row.get("outlet") or "").strip(),
                    "title": (row.get("title") or "").strip(),
                    "email": (row.get("email") or "").strip().lower() or None,
                    "twitter": (row.get("twitter") or "").strip() or None}
    else:
        vc["errors"].append("private/press_source.csv missing — the Vital City press list could not be read")

    a = ROOT / "data/authors.json"
    if a.exists():
        for rec in json.load(open(a)):
            n = (rec.get("name") or "").strip()
            if n and n.lower() != "vital city":
                vc["authors"].add(loose_name(n))
    else:
        vc["errors"].append("data/authors.json missing — Vital City contributors could not be flagged")

    g = PRIV / "growth.json"
    if g.exists():
        d = json.load(open(g))
        vc["mentions"] = d.get("news_mentions") or []
        vc["ledger"] = d.get("mentions_ledger") or {}
    else:
        vc["errors"].append("private/growth.json missing — Vital City mentions could not be read")
    return vc

def norm_title(t):
    """Google News titles arrive with the outlet appended and sometimes doubled.
    Strip that before comparing, or a real match looks like a miss."""
    t = re.sub(r"\s+[-\u2013\u2014|]\s+[^-\u2013\u2014|]{2,40}$", "", (t or "").strip())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", norm(t))).strip()

# ---------------------------------------------------------------- build
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="reuse the cached harvest")
    ap.add_argument("--cache-only", action="store_true",
                    help="on the Mac: harvest only the outlets a GitHub runner is refused by, "
                         "and write press/harvest_cache.json (public data, no addresses)")
    args = ap.parse_args()
    global CACHE
    if args.cache_only:
        CACHE = PRIV / "press_cache_mac"      # never mixed with the full build's cache
        args.fast = False

    CACHE.mkdir(parents=True, exist_ok=True)
    PRIV.mkdir(exist_ok=True)
    outlets = json.load(open(PRESS / "outlets.json"))
    all_outlets = outlets
    if args.cache_only:
        outlets = [o for o in outlets if o.get("ci_blocked")]
        print(f"cache-only harvest: {len(outlets)} outlets a GitHub runner cannot reach")
    # Reporters almost never publish a direct line; newsrooms publish a tip line.
    # Harvested separately by press/phones.py and kept as an outlet-level fact.
    phones_path = PRESS / "phones.json"
    phones = json.load(open(phones_path)) if phones_path.exists() else {}
    beats_raw = json.load(open(PRESS / "beats.json"))
    beats = compile_beats(beats_raw["beats"])
    started = datetime.now(timezone.utc)
    report = {"errors": [], "notes": []}

    def cached(name, fn):
        f = CACHE / f"{name}.json"
        if args.fast and f.exists():
            print(f"  [cache] {name}")
            return json.load(open(f))
        val = fn()
        json.dump(val, open(f, "w"))
        return val

    print("harvesting feeds…")
    rss_items, rss_errors = cached("rss", lambda: harvest_rss(outlets))
    report["errors"] += [dict(e, stage="rss") for e in rss_errors]
    print(f"  {len(rss_items)} items, {len(rss_errors)} feed errors")

    print("harvesting WordPress APIs…")
    wp_items = cached("wp", lambda: harvest_wp(outlets))
    print(f"  {len(wp_items)} posts")

    print("reading mastheads…")
    mast, review, mast_fails = cached("mast", lambda: harvest_mastheads(outlets))
    report["errors"] += [dict(e, stage="masthead") for e in mast_fails]
    print(f"  {len(mast)} masthead records, {len(review)} addresses dropped for not pairing")

    # ---- the Mac's harvest, for what the runner is refused -------------------
    # Substack and one nonprofit news host refuse GitHub's datacenter IPs, so on
    # CI those outlets come back empty. press/harvest_cache.json is written on
    # the Mac by --cache-only and holds only public material -- headlines,
    # bylines, links, bios. No address is ever in it. An outlet falls back to it
    # only when the live fetch returned nothing, and only while it is fresh.
    HCACHE = PRESS / "harvest_cache.json"
    hcache, from_cache = {}, {}
    if not args.cache_only and HCACHE.exists():
        hcache = json.load(open(HCACHE))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(hcache["as_of"])).days
        if age > 14:
            report["notes"].append(f"harvest_cache.json is {age} days old; not used")
            hcache = {}
        else:
            live = collections.Counter(i["outlet"] for i in (rss_items + wp_items))
            for oid, items in (hcache.get("items") or {}).items():
                if live.get(oid):
                    continue
                wp_items += items
                from_cache[oid] = hcache["as_of"][:10]
            if from_cache:
                print(f"  {len(from_cache)} outlets filled from the Mac harvest of {hcache['as_of'][:10]}")

    # ---- a rolling six months of stories ----------------------------------
    # The outlets with the biggest audiences have the shallowest feeds: the Times
    # hands over its last 21 metro stories and blocks its article pages, Gothamist
    # its last 40. A single build sees a week of them, so almost no one there
    # reaches two clips on a beat. Every build now keeps what it saw, public
    # fields only, and adds it to the next; coverage accumulates instead of
    # resetting. On CI the file rides in the Actions cache, not the repository.
    HIST = PRIV / "press_story_history.json"
    if not args.cache_only:
        try:
            hist = json.load(open(HIST)) if HIST.exists() else {}
        except Exception:
            hist = {}
        today = datetime.now(timezone.utc).date().isoformat()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=183)).isoformat()
        live_urls = set()
        for it in (rss_items + wp_items):
            u = it.get("url")
            if not u or not it.get("authors"):
                continue
            live_urls.add(u)
            hist[u] = {k: it.get(k) for k in ("outlet", "title", "url", "date", "authors", "tags")}
            hist[u]["summary"] = (it.get("summary") or "")[:300]
            hist[u]["seen"] = hist.get(u, {}).get("seen") or today
        hist = {u: v for u, v in hist.items() if (v.get("date") or v.get("seen") or "") >= cutoff[:10]}
        json.dump(hist, open(HIST, "w"))
        older = [v for u, v in hist.items() if u not in live_urls]
        print(f"  story history: {len(hist)} stories kept, {len(older)} of them from earlier builds")
        wp_items = wp_items + older

    stories = [s for s in (rss_items + wp_items) if s.get("authors")]
    if not stories:
        sys.exit("FATAL: harvest produced no bylined stories — refusing to write an empty press.json")

    # ---- fold stories into people
    # Keyed on the person, not on person-and-masthead. Schneps runs one byline
    # across amNewYork, the Brooklyn Paper, QNS, the Bronx Times, Gay City News
    # and the Queens papers, so keying by outlet turned one reporter into six
    # half-records and then, when they were added back together, credited him
    # with six copies of the same story. Stories are deduped by normalized title
    # inside the person, and the beat counts are computed after that.
    def title_key(t):
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", norm(t or ""))).strip()[:70]

    # Wire credits and CMS service accounts arrive looking exactly like bylines.
    # "Associated Press" was the Daily News's most prolific reporter, and
    # "PubSubHub User" its fourth.
    NOT_A_PERSON = re.compile(
        # "Vital City" is ours and is never a reporter. It is named here rather than
        # left to the outlet-name check, because Vital City is not an outlet in
        # the map -- and The City Reporter bylines the pieces it republishes from us
        # as "Vital City", which walked in as a bold, cited-us reporter.
        r"^(the )?(vital city( nyc)?|associated press|ap|reuters|bloomberg|tribune( news service| content agency)?|"
        r"wire( services?)?|newsroom|[\w .\-]*editorial board|the editors?|"
        r"[\w .\-]*\b(user|bot|admin|api|rest|feed|cms|syndicat\w*|services?|agent|contributor|"
        r"staff|reports?|newsroom|editors)\b[\w .\-]*)$",
        re.I)

    people = {}
    all_outlet_names = set()
    for o in outlets:
        all_outlet_names.add(merge_name(o["name"]))
        all_outlet_names.add(merge_name(re.sub(r"\s*\(.*?\)", "", o["name"])))
        all_outlet_names.add(merge_name(o["id"].replace("-", " ")))
    all_outlet_names.discard("")
    registry = {o["id"] for o in outlets}
    for s_ in stories:
        oid = s_["outlet"]
        if oid not in registry:
            continue
        for a in s_["authors"]:
            # A feed bylined with the publication's own name is not a person.
            # Podcast feeds do this constantly: every episode of Max Politics is
            # "by Max Politics", which otherwise walks in as the most prolific
            # City Hall reporter in New York.
            # Checked against every outlet in the registry, not just this feed's:
            # The City Reporter co-publishes the FAQ NYC podcast, so "FAQ NYC"
            # arrives as a byline on somebody else's feed.
            a = clean_person_name(a, has_byline=True)
            if not a:
                continue
            ma = merge_name(a)
            if (ma in all_outlet_names or NOT_A_PERSON.match(a.strip())
                    or (len(ma) >= 5 and any(n.startswith(ma) for n in all_outlet_names))):
                continue
            k = merge_name(a)
            if len(k) < 5:
                continue
            p = people.setdefault(k, {"key": k, "name": a, "outlet_counts": collections.Counter(),
                                      "stories": {}, "titles": set()})
            if len(p["name"]) < len(a):
                p["name"] = a
            p["outlet_counts"][oid] += 1
            # the last date seen at each masthead, counted before syndicated
            # copies are merged away, so amNewYork still counts as current for
            # a reporter whose stories also run in the Astoria Post
            if s_.get("date"):
                lb = p.setdefault("last_by_outlet", {})
                lb[oid] = max(lb.get(oid, ""), s_["date"][:10])
            tk = title_key(s_.get("title"))
            if tk and tk in p["titles"]:
                continue                      # same story, another masthead
            p["titles"].add(tk)
            p["stories"][s_.get("url") or tk] = {"title": s_.get("title"), "url": s_.get("url"),
                                                 "date": s_.get("date"), "outlet": oid,
                                                 "blob": " ".join([s_.get("title") or "", s_.get("summary") or "",
                                                                   " ".join(s_.get("tags") or [])])}

    # beats and vocabulary, computed once per person over their deduped file
    # Beats in the same group share reporters: a crime-statistics pitch belongs
    # with the Post's crime reporters even when few of their stories are about
    # data. Each person also gets a count of distinct stories across the crime
    # group (priority 1) and the city-and-state government group (priority 2).
    GROUPS = {"crime": {b for b, v in beats.items() if v["priority"] == 1},
              "government": {b for b, v in beats.items() if v["priority"] == 2}}
    for p in people.values():
        p["beat_hits"] = collections.Counter()
        p["beat_examples"] = collections.defaultdict(list)
        p["terms"] = collections.Counter()
        p["group_hits"] = collections.Counter()
        for st in p["stories"].values():
            blob = st.pop("blob", "")
            hit_groups = set()
            for bid, b in beats.items():
                matched = [lbl for pat, lbl in b["pats"] if pat.search(blob)]
                if matched:
                    for g, members in GROUPS.items():
                        if bid in members:
                            hit_groups.add(g)
                    p["beat_hits"][bid] += 1
                    if len(p["beat_examples"][bid]) < 3 and st.get("url"):
                        p["beat_examples"][bid].append({"title": st.get("title"), "url": st.get("url"),
                                                        "date": st.get("date"), "matched": matched[:4]})
            for g in hit_groups:
                p["group_hits"][g] += 1
            for t in terms_of(blob):
                p["terms"][t] += 1

    # A podcast has no byline, but it has a host, and a host is who you pitch.
    # Hosts are only carried where the show title or the podcast directory named
    # a person -- never inferred from the show's name.
    hosts = {o["id"]: o for o in outlets if o.get("host")}
    for oid, o in hosts.items():
        k = merge_name(o["host"])
        p = people.setdefault(k, {"key": k, "name": o["host"], "outlet_counts": collections.Counter(),
                                  "stories": {}, "titles": set(), "beat_hits": collections.Counter(),
                                  "beat_examples": collections.defaultdict(list), "terms": collections.Counter()})
        p.setdefault("title", "Host, " + o["name"])
        p.setdefault("title_source_url", o.get("host_source"))
        for s_ in stories:
            if s_["outlet"] != oid:
                continue
            tk = title_key(s_.get("title"))
            if tk in p["titles"]:
                continue
            p["titles"].add(tk)
            p["outlet_counts"][oid] += 1
            blob = " ".join([s_.get("title") or "", s_.get("summary") or ""])
            p["stories"][s_.get("url") or tk] = {"title": s_.get("title"), "url": s_.get("url"),
                                                 "date": s_.get("date"), "outlet": oid}
            for bid, b in beats.items():
                matched = [lbl for pat, lbl in b["pats"] if pat.search(blob)]
                if matched:
                    p["beat_hits"][bid] += 1
                    if len(p["beat_examples"][bid]) < 3 and s_.get("url"):
                        p["beat_examples"][bid].append({"title": s_.get("title"), "url": s_.get("url"),
                                                        "date": s_.get("date"), "matched": matched[:4]})
            for t in terms_of(blob):
                p["terms"][t] += 1

    # mastheads: titles and addresses, onto the same person
    for r in mast:
        if r.get("outlet") not in registry:
            continue                          # a masthead from an outlet no longer in the map
        cleaned = clean_person_name(r["name"], has_byline=merge_name(r["name"]) in people)
        if not cleaned:
            continue
        r = dict(r, name=cleaned)
        mn = merge_name(cleaned)
        if mn in all_outlet_names or (len(mn) >= 5 and any(n.startswith(mn) for n in all_outlet_names)):
            continue
        k = merge_name(r["name"])
        # mastheads list desks as if they were people: Customer Service, Our Staff
        if len(k) < 5 or NOT_A_PERSON.match(r["name"].strip()):
            continue
        p = people.setdefault(k, {"key": k, "name": r["name"], "outlet_counts": collections.Counter(),
                                  "stories": {}, "titles": set(), "beat_hits": collections.Counter(),
                                  "beat_examples": collections.defaultdict(list), "terms": collections.Counter()})
        p["outlet_counts"].setdefault(r["outlet"], 0)
        for fld in ("title", "email", "email_source_url", "email_evidence", "title_source_url", "staff_page"):
            if r.get(fld) and not p.get(fld):
                p[fld] = r[fld]

    dom_by_outlet = {o["id"]: re.sub(r"^www\.", "", re.sub(r"^https?://", "", o["site"]).split("/")[0])
                     for o in outlets}
    for k, p in people.items():
        p["id"] = k
        p["outlet"] = (p["outlet_counts"].most_common(1)[0][0] if p["outlet_counts"] else None)
        # Where someone works now is where they last filed. Six months of
        # history means a reporter who moved -- Ethan Corey, from The Appeal to
        # New York Focus -- has both mastheads on file; only the ones they have
        # filed for within four months of their latest story count as current.
        dated = sorted((s_ for s_ in p["stories"].values() if s_.get("date")),
                       key=lambda s_: s_["date"], reverse=True)
        if dated:
            latest = dated[0]["date"][:10]
            window = (datetime.fromisoformat(latest) - timedelta(days=120)).date().isoformat()
            lb = p.get("last_by_outlet") or {}
            p["recent_outlets"] = [o for o, d_ in sorted(lb.items(), key=lambda kv: kv[1], reverse=True) if d_ >= window] \
                or list(dict.fromkeys(s_["outlet"] for s_ in dated if s_["date"][:10] >= window))
            p["outlet"] = dated[0]["outlet"]
        else:
            p["recent_outlets"] = list(p["outlet_counts"])
        # A City & State address beats one stray Hell Gate freelance piece when
        # deciding which masthead to put under someone's name.
        em = (p.get("email") or "")
        if "@" in em and not dated:
            edom = em.split("@")[1]
            for oid in p["outlet_counts"]:
                od = dom_by_outlet.get(oid, "")
                if od and (edom.endswith(od) or od.endswith(edom)):
                    p["outlet"] = oid
                    break
        p["also_at"] = [o for o, _ in p["outlet_counts"].most_common() if o != p["outlet"]]
        p["stories"] = sorted(p["stories"].values(), key=lambda s: s.get("date") or "", reverse=True)

    # ---- byline blocks and author pages, one fetch each
    jobs = []
    for p in people.values():
        st = [s for s in p["stories"] if (s.get("url") or "").startswith("http")]
        if st:
            jobs.append((p["id"], p["name"], sorted(st, key=lambda s: s.get("date") or "", reverse=True)[0]["url"]))
    print(f"reading {len(jobs)} byline blocks…")
    blocks = cached("blocks", lambda: [r for r in cf.ThreadPoolExecutor(max_workers=12).map(read_byline_block, jobs)])
    by_id = {r["id"]: r for r in blocks}

    apjobs = [(r["id"], people[r["id"]]["name"], r["author_page"])
              for r in blocks if r.get("author_page") and r["id"] in people]
    print(f"reading {len(apjobs)} author pages…")
    apages = cached("apages", lambda: [r for r in cf.ThreadPoolExecutor(max_workers=12).map(read_author_page, apjobs)])
    ap_id = {r["id"]: r for r in apages}

    # One story is often the wrong story: The Real Deal signs off "Let me know at
    # ben.miller@therealdeal.com" on some pieces and not others. Anyone still
    # without an address gets up to two more of their own stories read.
    have = {r["id"] for r in (blocks + apages) if r.get("email")}
    more_jobs = []
    for p in people.values():
        if p["id"] in have or p.get("email"):
            continue
        st = [s_ for s_ in p["stories"] if (s_.get("url") or "").startswith("http")]
        for s_ in st[1:3]:
            more_jobs.append((p["id"], p["name"], s_["url"]))
    print(f"reading {len(more_jobs)} more stories for people still without an address…")
    more = cached("more", lambda: [r for r in cf.ThreadPoolExecutor(max_workers=12).map(read_byline_block, more_jobs)])
    more_id = {}
    for r in more:
        if r.get("email") and r["id"] not in more_id:
            more_id[r["id"]] = r

    for pid, p in people.items():
        for src in (by_id.get(pid) or {}, ap_id.get(pid) or {}, more_id.get(pid) or {}):
            for fld in ("author_page", "x", "bluesky", "bio"):
                if src.get(fld) and not p.get(fld):
                    p[fld] = src[fld]
            if src.get("email") and not p.get("email"):
                p["email"] = src["email"]
                p["email_source_url"] = src.get("email_source_url")
                p["email_evidence"] = src.get("email_evidence")

    if args.cache_only:
        blocked = {o["id"] for o in outlets}
        items = collections.defaultdict(list)
        for i in (rss_items + wp_items):
            if i["outlet"] in blocked:
                rec = {k: i.get(k) for k in ("outlet", "title", "url", "date", "authors", "summary", "tags")}
                if rec.get("summary"):
                    rec["summary"] = re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
                                            "[address removed]", rec["summary"])
                items[i["outlet"]].append(rec)
        EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
        profiles = {}
        for p in people.values():
            prof = {f: p.get(f) for f in ("author_page", "bio", "x", "bluesky") if p.get(f)}
            if prof.get("bio"):
                prof["bio"] = EMAIL.sub("[address removed]", prof["bio"])
            if prof:
                profiles[loose_name(p["name"])] = prof
        # A bare "@" is an Instagram handle, not an address; check for the real shape.
        leak = [k for k, v in profiles.items() if EMAIL.search(json.dumps(v))]
        if leak:
            sys.exit(f"FATAL: an address found its way into the public cache for {leak[:3]}")
        if not items:
            sys.exit("FATAL: cache-only harvest reached nothing — refusing to overwrite the cache")
        out = {"as_of": datetime.now(timezone.utc).isoformat(),
               "_note": "Written on the Mac by build_press.py --cache-only. Public material only: "
                        "headlines, bylines, links and bios for outlets that refuse GitHub's runners. "
                        "No addresses.",
               "items": items, "profiles": profiles}
        json.dump(out, open(HCACHE, "w"), indent=1, ensure_ascii=False)
        print(f"wrote {HCACHE} · {sum(len(v) for v in items.values())} stories from {len(items)} outlets · "
              f"{len(profiles)} profiles")

        # The addresses at these outlets cannot go in that public file, so they
        # are locked with the toolkit passphrase and CI unlocks them at build
        # time. The passphrase is taken only from VC_NETWORK_PASS -- never from
        # private/.netpass, which is how a stale key got published before -- and
        # it must first open press/data.enc, a payload CI itself encrypted. If
        # it cannot, this passphrase is not the live one and nothing is written.
        contacts = {}
        for p in people.values():
            if p.get("email"):
                contacts[loose_name(p["name"])] = {
                    "name": p["name"], "email": p["email"],
                    "email_source_url": p.get("email_source_url"),
                    "email_evidence": p.get("email_evidence")}
        passphrase = (os.environ.get("VC_NETWORK_PASS") or "").strip()
        live = PRESS / "data.enc"
        if not passphrase:
            print("  addresses NOT locked: VC_NETWORK_PASS is not set")
            return
        if not live.exists():
            print("  addresses NOT locked: press/data.enc is missing, so the passphrase cannot be checked")
            return
        try:
            decrypt_blob(json.load(open(live)), passphrase)
        except Exception:
            print("  addresses NOT locked: this passphrase does not open the live press/data.enc, "
                  "so it is not the one CI uses. Nothing written.")
            return
        blob = encrypt_blob(json.dumps({"as_of": out["as_of"], "contacts": contacts}).encode(), passphrase)
        json.dump(blob, open(PRESS / "blocked_contacts.enc", "w"))
        print(f"  locked {len(contacts)} addresses into press/blocked_contacts.enc "
              f"(passphrase checked against the live payload first)")
        return

    # profiles for people at outlets the runner could not read
    for p in people.values():
        prof = (hcache.get("profiles") or {}).get(loose_name(p["name"]))
        if prof:
            for f in ("author_page", "bio", "x", "bluesky"):
                if prof.get(f) and not p.get(f):
                    p[f] = prof[f]

    # addresses at outlets the runner could not read, locked on the Mac
    bce = PRESS / "blocked_contacts.enc"
    if bce.exists():
        passphrase = (os.environ.get("VC_NETWORK_PASS") or "").strip()
        try:
            bc = json.loads(decrypt_blob(json.load(open(bce)), passphrase))
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(bc["as_of"])).days
            if age > 30:
                raise ValueError(f"{age} days old")
            added = 0
            for p in people.values():
                c = bc["contacts"].get(loose_name(p["name"]))
                if c and not p.get("email") and pairs_with_email(p["name"], c["email"]):
                    p["email"] = c["email"]
                    p["email_source_url"] = c.get("email_source_url")
                    p["email_evidence"] = c.get("email_evidence")
                    added += 1
            print(f"  {added} addresses added from the Mac's locked file of {bc['as_of'][:10]}")
        except Exception as e:
            msg = f"blocked_contacts.enc not used ({type(e).__name__}: {e}); addresses at outlets that refuse CI will be missing"
            print("  WARNING: " + msg)
            report["notes"].append(msg)

    # ---- Vital City relationship layer
    vc = load_vc_layer()
    report["errors"] += [{"stage": "vital-city", "error": e} for e in vc["errors"]]

    cited_domains = collections.Counter()
    cited_dates = collections.defaultdict(list)
    mention_titles = {}
    for m in vc["mentions"]:
        if m.get("own_post") or m.get("kind") not in ("media", "republication"):
            continue
        dom = m.get("domain") or ""
        if dom:
            cited_domains[dom] += 1
            if m.get("published_iso"):
                cited_dates[dom].append(m["published_iso"])
        nt = norm_title(m.get("title"))
        if len(nt) > 25:
            mention_titles[nt] = m
            mention_titles.setdefault(nt[:45], m)

    dom_of = {}
    for o in outlets:
        d = re.sub(r"^www\.", "", re.sub(r"^https?://", "", o["site"]).split("/")[0])
        dom_of[o["id"]] = d

    # a story we harvested whose title matches a logged Vital City mention means
    # this reporter has cited Vital City by name -- the strongest person-level flag
    cited_people = {}
    for p in people.values():
        for s in p["stories"]:
            nt = norm_title(s.get("title"))
            hit = mention_titles.get(nt) or (mention_titles.get(nt[:45]) if len(nt) > 30 else None)
            if hit:
                cited_people[p["id"]] = {"title": s.get("title"), "url": s.get("url"),
                                         "date": s.get("date") or hit.get("published_iso")}
                break

    # ---- shape the output
    now = datetime.now(timezone.utc)
    recent_cut = (now - timedelta(days=60)).isoformat()
    out_people = []
    for p in people.values():
        st = [s for s in p["stories"] if s.get("url")]
        st.sort(key=lambda s: s.get("date") or "", reverse=True)
        seen, uniq = set(), []
        for s in st:
            if s["url"] in seen:
                continue
            seen.add(s["url"]); uniq.append(s)
        dates = [s["date"] for s in uniq if s.get("date")]
        total = len(uniq)
        ranked = sorted(p["beat_hits"].items(), key=lambda kv: (-kv[1], beats[kv[0]]["priority"]))[:6]

        mk = merge_name(p["name"])
        pl = vc["press_list"].get(loose_name(p["name"]))
        flags = {}
        if pl:
            flags["press_list"] = {"outlet": pl["outlet"], "title": pl["title"], "twitter": pl["twitter"]}
        if p["id"] in cited_people:
            flags["cited_vc"] = cited_people[p["id"]]
        dom = dom_of.get(p["outlet"])
        if dom and cited_domains.get(dom):
            flags["outlet_cites_vc"] = cited_domains[dom]
        # Only a fact about this person earns the bold treatment. An outlet that
        # has cited Vital City says nothing about the reporter standing in it.
        if flags:
            flags["person"] = bool(flags.get("press_list") or flags.get("cited_vc"))

        rec = {
            "id": p["id"], "name": p["name"], "outlet": p["outlet"],
            "also_at": p.get("also_at") or None,
            "scope": (next((o.get("scope") for o in outlets if o["id"] == p["outlet"]), None)),
            "title": tidy_title(p.get("title")), "bio": p.get("bio"),
            "email": p.get("email"), "email_source_url": p.get("email_source_url"),
            "email_evidence": (p.get("email_evidence") or "")[:130] or None,
            "recent_outlets": p.get("recent_outlets") or None,
            "x": p.get("x"), "bluesky": p.get("bluesky"),
            "author_page": p.get("author_page"), "staff_page": p.get("staff_page"),
            "story_count": total, "latest": max(dates) if dates else None,
            "active": bool(dates and max(dates) >= recent_cut),
            "beats": [{"id": b, "label": beats[b]["label"], "priority": beats[b]["priority"],
                       "count": c, "share": round(c / total, 3) if total else 0,
                       "examples": p["beat_examples"][b]}
                      for b, c in ranked if c >= 2],   # one story on a subject is not a beat
            "stories": uniq[:12],
            "terms": dict(sorted(p["terms"].items(), key=lambda kv: -kv[1])[:35]),
            "groups": {g: n for g, n in (p.get("group_hits") or {}).items() if n},
            "vc": flags or None,
        }
        # press-list people who never appeared in a harvest still belong in the map
        if pl and not rec["email"] and pl["email"]:
            rec["email"] = pl["email"]
            rec["email_source_url"] = "private/press_source.csv (Vital City press list)"
            rec["email_evidence"] = "From the curated Vital City press list, not harvested from a page."
        out_people.append(rec)

    # press-list contacts with no harvested presence at all
    have = {loose_name(p["name"]) for p in out_people}
    for mk, pl in vc["press_list"].items():
        if mk in have:
            continue
        out_people.append({
            "id": "presslist:" + re.sub(r"[^a-z]+", "-", mk), "name": pl["name"],
            "outlet": None, "outlet_text": pl["outlet"], "title": pl["title"],
            "email": pl["email"],
            "email_source_url": "private/press_source.csv (Vital City press list)",
            "email_evidence": "From the curated Vital City press list, not harvested from a page.",
            "x": (pl["twitter"] or "").lstrip("@") or None,
            "story_count": 0, "beats": [], "stories": [], "terms": {}, "active": False,
            # "person" is what bolds a name. It was missing here, so the sixteen
            # press-list contacts with no harvested byline were never bold.
            "vc": {"press_list": {"outlet": pl["outlet"], "title": pl["title"], "twitter": pl["twitter"]},
                   "person": True},
        })

    # ---- who is press ------------------------------------------------------
    # Having written for Vital City is not a credential. Our contributors are
    # criminologists, former cabinet secretaries and novelists, and a single
    # op-ed of theirs in the Daily News does not make them Daily News media. A
    # contributor stays only on independent evidence of being press. The rule is
    # scoped to contributors deliberately: a blanket "one byline and no address"
    # cut would also delete Times reporters, whose feed is shallow enough that
    # most of them show a single story.
    OPINION = re.compile(r"/(opinion|opinions|op-ed|oped|commentary|editorials?)/", re.I)
    tier_of = {o["id"]: o.get("tier", 2) for o in outlets}

    def outlet_domains(p):
        return {dom_of.get(o) for o in [p.get("outlet"), *(p.get("also_at") or [])] if dom_of.get(o)}

    def press_evidence(p):
        v = p.get("vc") or {}
        if v.get("press_list") or v.get("cited_vc"):
            return "on the press list or has cited Vital City"
        em = (p.get("email") or "").lower()
        if "@" in em and "press_source" not in (p.get("email_source_url") or ""):
            edom = em.split("@", 1)[1]
            if any(edom.endswith(d) or d.endswith(edom) for d in outlet_domains(p)):
                return "address on the outlet's own domain"
        t = (p.get("title") or "")
        if t and not re.search(r"contribut|fellow|guest|visiting", t, re.I):
            return "staff title on a masthead"
        if p.get("story_count", 0) >= 3:
            return "three or more bylines"
        return None

    kept, dropped = [], []
    for p in out_people:
        mk = merge_name(p["name"])
        why = None
        if loose_name(p["name"]) in vc["authors"] and not press_evidence(p):
            why = "Vital City contributor with no evidence of being press"
        elif (p.get("stories") and p.get("story_count", 0) <= 2
              and all(OPINION.search(s_.get("url") or "") for s_ in p["stories"])
              and not press_evidence(p)):
            why = "opinion bylines only"
        if why:
            dropped.append({"name": p["name"], "outlet": p.get("outlet"), "reason": why,
                            "stories": p.get("story_count", 0)})
            continue
        # best tier across every masthead they file for: a Schneps reporter
        # whose primary paper is the Astoria Post but who also files for amNY
        # counts as major media
        current = p.get("recent_outlets") or [p.get("outlet"), *(p.get("also_at") or [])]
        tiers = [tier_of.get(o, 2) for o in [p.get("outlet"), *current] if o]
        if not tiers and p.get("outlet_text"):
            ot = norm(p["outlet_text"])
            tiers = [o.get("tier", 2) for o in outlets
                     if norm(re.sub(r"\s*\(.*?\)", "", o["name"])) in ot]
        p["tier"] = min(tiers) if tiers else 2
        # Bill Parry files for the Astoria Post and for amNewYork. Listing him
        # under the Astoria Post, inside the major-outlets group, reads as a
        # mistake; lead with the masthead that earned the tier.
        if p.get("outlet") and tier_of.get(p["outlet"], 2) != p["tier"]:
            best = next(o for o in current if tier_of.get(o, 2) == p["tier"])
            p["also_at"] = [p["outlet"]] + [o for o in (p.get("also_at") or []) if o != best]
            p["outlet"] = best
            p["scope"] = next((o.get("scope") for o in outlets if o["id"] == best), p.get("scope"))
        # An address from a masthead they no longer file for may be dead.
        em = (p.get("email") or "").lower()
        if "@" in em and "press_source" not in (p.get("email_source_url") or ""):
            edom = em.split("@", 1)[1]
            owner = next((o for o in [p.get("outlet"), *(p.get("also_at") or [])]
                          if o and dom_of.get(o) and (edom.endswith(dom_of[o]) or dom_of[o].endswith(edom))), None)
            if owner and owner not in (p.get("recent_outlets") or [owner]):
                p["email_note"] = f"address from {next((x['name'] for x in outlets if x['id'] == owner), owner)}, where they no longer seem to file"
        kept.append(p)
    out_people = kept
    report["dropped_non_press"] = dropped
    print(f"  dropped {len(dropped)} people who are not press "
          f"({sum(1 for d in dropped if d['reason'].startswith('Vital City'))} contributors, "
          f"{sum(1 for d in dropped if d['reason'].startswith('opinion'))} opinion-only)")

    out_people.sort(key=lambda p: (p["tier"], -p["story_count"], p["name"]))

    # ---- outlet rollups
    per_outlet = collections.Counter()
    for p in out_people:
        for oid in {p["outlet"], *(p.get("also_at") or [])}:
            if oid:
                per_outlet[oid] += 1
    story_counts = collections.Counter(s["outlet"] for s in stories)
    # everything harvested, bylined or not -- an outlet reached only through a
    # Google News query contributes headlines with no byline, and showing it as
    # zero made a working feed look broken
    item_counts = collections.Counter(i["outlet"] for i in (rss_items + wp_items))
    out_outlets = []
    for o in outlets:
        d = dom_of[o["id"]]
        dates = sorted(cited_dates.get(d, []))
        out_outlets.append({**{k: v for k, v in o.items() if k != "feed_filter"},
                            "domain": d, "phones": phones.get(o["id"], []),
                            "via_mac_harvest": from_cache.get(o["id"]),
                            "people": per_outlet.get(o["id"], 0),
                            "stories": story_counts.get(o["id"], 0),
                            "items": item_counts.get(o["id"], 0),
                            "vc_citations": cited_domains.get(d, 0),
                            "vc_cited_first": dates[0][:10] if dates else None,
                            "vc_cited_last": dates[-1][:10] if dates else None})
    out_outlets.sort(key=lambda o: (-o["people"], o["name"]))

    mentions = {
        "media": [m for m in vc["mentions"] if m.get("kind") == "media" and not m.get("own_post")][:120],
        "gov": [m for m in vc["mentions"] if m.get("kind") in ("gov", "republication")][:60],
        "ledger": (vc["ledger"] or {}).get("items", []) if isinstance(vc["ledger"], dict) else [],
    }

    payload = {
        "as_of": now.isoformat(),
        "built_in_seconds": round((now - started).total_seconds()),
        "outlets": out_outlets,
        "people": out_people,
        "beats": {k: {"label": v["label"], "priority": v["priority"],
                      "terms": beats_raw["beats"][k]["terms"]} for k, v in beats.items()},
        "mentions": mentions,
        "unpaired_addresses": review,
        "report": report,
        "counts": {
            "outlets": len(out_outlets), "people": len(out_people),
            "with_email": sum(1 for p in out_people if p.get("email")),
            "with_beats": sum(1 for p in out_people if p["beats"]),
            "active_60d": sum(1 for p in out_people if p.get("active")),
            "stories": len(stories),
            "vc_flagged": sum(1 for p in out_people if (p.get("vc") or {}).get("person")),
            "major_outlet_people": sum(1 for p in out_people if p.get("tier") == 1),
            "dropped_non_press": len(report.get("dropped_non_press", [])),
            "feed_errors": len(report["errors"]),
        },
    }
    PRIV.mkdir(exist_ok=True)
    out = PRIV / "press.json"
    json.dump(payload, open(out, "w"), indent=1)
    c = payload["counts"]
    print(f"\nwrote {out} ({out.stat().st_size/1e6:.1f} MB)")
    print(f"  {c['outlets']} outlets · {c['people']} people · {c['with_beats']} with an evidenced beat")
    print(f"  {c['with_email']} with a published address · {c['active_60d']} active in 60 days")
    print(f"  {c['stories']} bylined stories · {c['vc_flagged']} flagged as Vital City contacts")
    if report["errors"]:
        print(f"  {len(report['errors'])} harvest errors (kept in report.errors):")
        for e in report["errors"][:12]:
            print("   ", e.get("stage"), e.get("outlet"), (e.get("error") or "")[:60])

main()
