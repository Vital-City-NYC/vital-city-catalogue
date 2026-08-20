#!/usr/bin/env python3
"""Search the open web for the exact email addresses of unnamed devoted readers.

WHY THIS EXISTS
Josh found dpearlstein@gmail.com on Google in one search: a Journal of Planning
History paper prints "Daniel Pearlstein ... dpearlstein@gmail.com" right under
the title. My own search tool's index does not contain that page, and Google,
Bing, DuckDuckGo and Brave all refuse scripted queries (consent walls, CAPTCHAs,
or they silently drop the exact-phrase constraint and answer a different
question).

Google Scholar does answer scripted exact-phrase queries, and it indexes the
full text of papers, working papers and reports — which is precisely where a
person's own email address ends up in print. So this sweep runs there.

BUT THE BETTER METHOD IS THE BROWSER. Josh pointed out that Claude can drive
his actual Chrome, where Google answers normally. From a google.com tab:

    fetch("/search?q=" + encodeURIComponent('"' + email + '"'), {credentials:"include"})

is same-origin, so a whole batch runs from one tool call. Two things matter:
read ONLY the results region (#rso) — the page header echoes the query, and
parsing the whole body makes every search look like a hit — and pace it, because
Google starts serving "unusual traffic" at roughly 28 queries. Pause there
rather than risk a block on his account; resume later.

That method found, in one sitting: Martin F. Horn (former NYC Correction and
Probation Commissioner), Daniel Pearlstein of Riders Alliance, Nathan Eagan,
Kellie Leeson, Walter S. Topp, plus proof for three names that had only been
inferred from an organisation's email convention.

WHAT COUNTS AS A HIT
The address appears in a document Scholar indexed. That is proof, not
inference: the person put the address in the paper. The author line gives the
name, and usually the affiliation.

For addresses Scholar does not know, this is not the end of the road — it just
means the person is not published under that address, and the fallback is the
name the address spells (see enrich_readers.py).

    python3 find_reader_names.py            # unnamed devoted readers
    python3 find_reader_names.py --all      # every unnamed engaged reader
"""
import argparse, html, json, random, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
OUT = PRIV / "reader_email_search.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def scholar(query, timeout=25):
    url = "https://scholar.google.com/scholar?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def strip(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def parse(page):
    """Scholar result blocks: title, the author/venue line, the snippet, the link."""
    out = []
    for blk in re.findall(r'<div class="gs_ri">(.*?)</div>\s*</div>', page, re.S) or \
               re.findall(r'<div class="gs_r gs_or gs_scl".*?</div>\s*</div>\s*</div>', page, re.S):
        title_m = re.search(r'<h3 class="gs_rt".*?</h3>', blk, re.S)
        auth_m = re.search(r'<div class="gs_a">(.*?)</div>', blk, re.S)
        snip_m = re.search(r'<div class="gs_rs">(.*?)</div>', blk, re.S)
        link_m = re.search(r'<h3 class="gs_rt".*?<a href="([^"]+)"', blk, re.S)
        if not title_m:
            continue
        out.append({"title": strip(title_m.group(0)),
                    "authors": strip(auth_m.group(1)) if auth_m else "",
                    "snippet": strip(snip_m.group(1)) if snip_m else "",
                    "url": html.unescape(link_m.group(1)) if link_m else ""})
    return out


def weak_name(r):
    n = (r.get("n") or "").strip()
    return (not n) or (r.get("ns") == "guess" and len(n.split()) < 2)


def devoted(r):
    return (not r.get("unsub")) and ((r.get("erate") or 0) >= 4
                                     or ((r.get("erate") or 0) >= 3 and (r.get("eclick") or 0) > 0))


def engaged(r):
    return (not r.get("unsub")) and ((r.get("eclick") or 0) > 0 or (r.get("eopen") or 0) >= 50)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every engaged reader, not just the devoted")
    ap.add_argument("--sleep", type=float, default=7.0)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    people = json.loads((PRIV / "people.json").read_text())
    pool = [r for r in people if weak_name(r) and (engaged(r) if a.all else devoted(r))]
    pool.sort(key=lambda r: -((r.get("eopen") or 0) + (r.get("eclick") or 0) * 3))
    if a.limit:
        pool = pool[:a.limit]

    done = {}
    if OUT.exists():
        done = {d["email"]: d for d in json.loads(OUT.read_text())}
    todo = [r for r in pool if (r.get("e") or "") not in done]
    print(f"pool {len(pool)} | already searched {len(pool)-len(todo)} | to search {len(todo)}",
          file=sys.stderr)

    results = list(done.values())
    for i, r in enumerate(todo, 1):
        email = r.get("e") or ""
        try:
            page = scholar(f'"{email}"')
        except Exception as e:
            code = getattr(e, "code", None)
            print(f"  [{i}/{len(todo)}] {email}: {type(e).__name__} {code or ''}", file=sys.stderr)
            if code == 429:
                print("  Scholar is rate-limiting. Stopping; rerun later to resume.", file=sys.stderr)
                break
            results.append({"email": email, "error": f"{type(e).__name__} {code or ''}"})
            continue
        if "not a robot" in page or "unusual traffic" in page:
            print("  Scholar wants a CAPTCHA. Stopping; rerun later to resume.", file=sys.stderr)
            break
        hits = parse(page)
        results.append({"email": email, "current_name": r.get("n") or "",
                        "open_rate_pct": r.get("eopen") or 0, "click_rate_pct": r.get("eclick") or 0,
                        "hits": hits})
        flag = f"** {len(hits)} HIT(S)" if hits else "   -"
        print(f"  [{i}/{len(todo)}] {email:<40} {flag}", file=sys.stderr)
        if hits:
            for h in hits[:2]:
                print(f"        {h['title'][:80]}", file=sys.stderr)
                print(f"        {h['authors'][:80]}", file=sys.stderr)
        OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False))
        time.sleep(a.sleep + random.uniform(0, 3))

    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    withhits = [r for r in results if r.get("hits")]
    print(f"\nsearched {len(results)} addresses | {len(withhits)} found in an indexed document",
          file=sys.stderr)
    print(f"wrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
