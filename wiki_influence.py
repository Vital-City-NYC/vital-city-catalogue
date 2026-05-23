#!/usr/bin/env python3
"""Flag 'influential' people by checking whether they have an English Wikipedia
page — with context clues so we don't tag an unrelated same-named person.

Scope: only 'known + named' people (confirmed name + author/donor/typed/institution)
— never the anonymous webmail subscribers. Results cache to private/wiki_cache.json
so we only hit Wikipedia for names we haven't checked. build_network reads the
cache and sets p["wiki"]=1.

Disambiguation: a hit counts only if the Wikipedia summary (a) isn't a
disambiguation page and (b) mentions a context clue for THIS person — a word from
their institution, a keyword for their type/specialty, or "New York".
"""
import json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"
CACHE = PRIV / "wiki_cache.json"
UA = "VitalCity-ContactSync/1.0 (contact: info@vitalcitynyc.org)"

TYPE_KW = {
    "journalist": ["journalist", "reporter", "columnist", "editor", "correspondent", "writer"],
    "academic": ["professor", "scholar", "academic", "researcher", "sociologist", "economist", "historian", "political scientist"],
    "judge": ["judge", "justice", "jurist", "magistrate"],
    "foundation leadership": ["foundation", "philanthrop", "grantmaker"],
    "nonprofit leadership": ["nonprofit", "executive director", "advocate", "activist"],
    "city gov": ["commissioner", "deputy mayor", "city council", "mayor", "official"],
    "current nyc.gov": ["commissioner", "deputy mayor", "city council", "mayor", "official"],
    "state gov": ["governor", "state senator", "assembly", "attorney general", "comptroller"],
    "fed gov": ["senator", "congress", "representative", "secretary", "federal"],
    "VC contributor": ["author", "writer", "journalist", "professor", "economist", "policy"],
}
TOPIC_KW = {
    "criminal justice": ["criminal justice", "prosecutor", "police", "prison", "crime"],
    "housing": ["housing", "urban", "real estate"], "transit": ["transit", "transportation"],
    "urban planning": ["urban", "planner", "architecture", "city planning"],
    "education": ["education", "schools", "university"], "public health": ["health", "medicine", "physician"],
    "economy": ["economist", "economics", "business"], "architecture": ["architect", "architecture"],
    "politics & government": ["politic", "government", "mayor", "council"],
}
GENERIC = ["new york", "manhattan", "brooklyn"]


def get_summary(name):
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(name.replace(" ", "_"))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def clues_for(p):
    kws = set(GENERIC)
    for t in p.get("types", []):
        kws.update(TYPE_KW.get(t, []))
    for t in p.get("topics", []):
        kws.update(TOPIC_KW.get(t, []))
    for w in re.findall(r"[a-z]{4,}", (p.get("inst") or "").lower()):
        if w not in ("university", "school", "center", "institute", "foundation", "company", "group"):
            kws.add(w)
    return kws


def main():
    people = json.loads((PRIV / "people.json").read_text())
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    def known(p):
        return p.get("auth") or p.get("don") or p.get("types") or p.get("inst")

    cand = [p for p in people if p.get("ns") == "given" and not p.get("unsub")
            and known(p) and len(p["n"].split()) >= 2]
    checked = hits = newq = 0
    for p in cand:
        key = p["n"].strip().lower()
        if key in cache:
            continue
        newq += 1
        name = p["n"].strip()
        last = name.split()[-1].lower()
        try:
            s = get_summary(name)
        except Exception as e:
            print(f"  err {name}: {e}", file=sys.stderr); time.sleep(1); continue
        ok = False
        title = None
        if s and s.get("type") != "disambiguation" and s.get("extract"):
            extract = s["extract"].lower()
            title = s.get("title")
            if last in extract and any(k in extract for k in clues_for(p)):
                ok = True
        cache[key] = {"wiki": ok, "title": title if ok else None}
        checked += 1
        if ok:
            hits += 1
        time.sleep(0.15)   # be polite to Wikipedia
        if newq % 100 == 0:
            CACHE.write_text(json.dumps(cache))
            print(f"  …{newq} new checked, {hits} hits so far", file=sys.stderr)

    CACHE.write_text(json.dumps(cache))
    total_hits = sum(1 for v in cache.values() if v.get("wiki"))
    print(f"checked {checked} new names this run; cache has {len(cache)} names, "
          f"{total_hits} flagged influential -> {CACHE.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
