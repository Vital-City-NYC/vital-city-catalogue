#!/usr/bin/env python3
# Title: What Vital City's pieces have been about — subject-matter analysis
# Date: 2026-08-04
# Data source: data/catalogue.json (every published vitalcitynyc.org piece,
#   Ghost Content API pull; see methodology.md for provenance).
# Description: The Ghost `topics` field cannot answer "what have we written
#   about" on its own, because it mixes three different kinds of label:
#     - real subjects ("Housing", "Gun Violence")
#     - issue section rubrics ("Setting the Stage", "What Can Be Done?"), which
#       exist to structure one issue's table of contents and name no subject
#     - format/meta labels ("Podcast", "Data Stories", "interview"), which
#       duplicate what the `type` field already records
#   This script sorts all 206 normalized topics into those three buckets by hand
#   (below), maps the subjects onto 18 beats, and writes the aggregates to
#   data/subject_analysis.json. Every topic is accounted for — nothing is
#   silently dropped, and the rubric and meta lists are written to the output so
#   the sort can be audited.
# Dependencies: Python 3.9 stdlib only.
import json, collections, re, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAT = json.load(open(ROOT / "data/catalogue.json"))

# Ghost holds a few tags twice, once with a trailing period ("History." and
# "History"). Normalize those together; keep the three tags whose punctuation is
# part of the name.
KEEP_PUNCT = {"Etc.", "If I Had a Hammer...", "In Conversation With..."}
def norm(t):
    return t if t in KEEP_PUNCT else t.rstrip(".")

# --- Bucket 1: subjects, mapped to beats -----------------------------------
BEATS = {
  "Crime & violence": [
    "Crime", "Gun Violence", "Guns", "Subway Crime", "Subway Safety", "Safety",
    "Community Safety", "Broken Windows", "Disorder", "Quality of Life",
    "Crime Stories", "Subway Safety Stories", "Two Sides of the Gun: Stories of Possession and Victimization"],
  "Policing": ["Police Reform", "Police-Community Relations", "Street Lighting"],
  "Courts & prosecution": ["Justice", "Criminal Justice", "Prosecution", "Law", "Corruption"],
  "Jails & incarceration": [
    "Jails", "Incarceration", "Incarceration Stories", "Corrections",
    "Projecting the Size of the Jail Population — More than Math"],
  "Housing": ["Housing", "Rent regulation", "rent", "Public Housing"],
  "Land use & the built city": [
    "City Planning", "Urban Planning", "Urbanism", "Architecture", "Design",
    "Community Development", "Place", "Neighborhood Life", "Parks", "Streets",
    "Supermarkets", "Building Blocks", "Pouring the Foundation"],
  "Transportation": ["Transit", "Transportation", "Subways", "Traffic", "Infrastructure",
    "Why the Trains Matter"],
  "City government & governance": [
    "City Government", "Government Operations", "Governance", "Mayoralty",
    "Charter Revision", "COGE", "Policymakers", "Comings and Goings",
    "Leadership in Crisis", "Just Fix It", "The State of the City", "The State of Gotham"],
  "Money, budgets & the economy": [
    "Economics", "Budget", "Jobs", "Labor", "What We Can and Can't Afford",
    "The $2 Trillion Question", "The Shape of the Economic Engine",
    "More Money in More Pockets"],
  "Politics & elections": ["Politics", "Elections", "Mamdani"],
  "State, federal & beyond NYC": [
    "State Government", "Federal Government", "Immigration", "Foreign Policy",
    "Military", "Chicago", "The Role of the Feds", "Borrow and Steal"],
  "Health, mental health & drugs": [
    "Public Health", "Mental Health", "Health", "Drugs", "Substance Abuse",
    "Alcohol", "Legalization", "My Substance Story", "People in Crisis on Streets and Subways"],
  "Homelessness & social services": [
    "Homelessness", "Social Services", "Community Services", "Child Welfare", "Poverty"],
  "Education & youth": ["Education", "Youth"],
  "Climate, environment & sanitation": ["Climate Change", "Environment", "Sanitation", "Cleanup on Aisle 10"],
  "Technology": ["Technology", "Artifical Intelligence"],
  "Race, gender & inequality": ["Race", "Gender", "Inequality"],
  # "History" is kept out of Culture deliberately. It is applied as a *lens*
  # across the whole corpus — to housing, charter-reform and infrastructure
  # pieces as often as to cultural ones — so folding it into Culture would
  # overstate culture coverage by about half. 102 of its 142 pieces carry no
  # other cultural tag. Its overlap with every other beat is reported separately.
  "History & the long view": ["History", "Historical Lessons"],
  "Culture & city life": [
    "culture", "Sports", "Museums", "Film & TV", "Music & Entertainment",
    "Arts", "Theater", "Photography", "Food and Drink", "Religion", "Libraries",
    "Civic Life", "Sights and Sounds", "The Spirit of the City", "Hello To All That",
    "The Best Connection I Ever Made", "Modern Evolution: Marketing and Profits"],
  "Media & journalism": ["Journalism", "Media"],
  "Civil society & philanthropy": [
    "Nonprofits", "Nonprofit Management", "Nonprofit Sector", "Nonprofit Model",
    "Philanthropy", "Community Organizing", "Community", "Social Change",
    "Foundations: The Wild West and the Nation"],
}
SUBJECT_BEAT = {}
for beat, subs in BEATS.items():
    for s in subs:
        assert s not in SUBJECT_BEAT, f"{s} mapped to two beats"
        SUBJECT_BEAT[s] = beat

# --- Bucket 2: format / meta labels ----------------------------------------
# These describe how a piece was made, not what it is about. The `type` field
# already carries this, so they are excluded from subject counts.
META = {
  "Podcast", "interview", "Conversations", "In Conversation With...", "Book Review",
  "Data Stories", "data", "Reality Check", "Statistics", "Social Science", "Sociology",
  "Press Releases", "Events", "About This Project", "In Memoriam", "Report",
  "Overview", "terminology", "policy", "Context: Politics and Data",
  "The Research That Changed My Thinking", "Reflections", "The Long View",
}

# --- Bucket 3: issue section rubrics ---------------------------------------
# Table-of-contents headings inside a single issue. They name a slot in an
# issue's arc ("here is the problem", "here is what to do"), not a subject.
RUBRICS = {
  "Setting the Stage", "Where Do We Go From Here?", "The Way Forward", "What to Do Now",
  "The Great Debate", "Some Policy Solutions", "Looking Back", "What Can Be Done?",
  "Toward Solutions", "Currents", "Persistent Problems Inside", "Where We’re Headed",
  "Where We Go From Here", "What Doesn’t Work", "What Makes a Great City Work?",
  "Beyond False Simplicity", "The Policy Record", "Where We Are",
  "Solutions for Today and Tomorrow", "What Opportunities Await?", "Wrenches in the Gears",
  "Mugged by Reality", "Decisions, Decisions, Decisions", "Etc.", "If I Had a Hammer...",
  "What Does It All Mean?", "What Do We Know?", "The Joy of Incrementalism",
  "What’s Driving Trends and What to Do About It", "Solving Cases: The System",
  "Solving Cases: The People", "New Solutions", "The Causes", "The Upside — Yes, Really",
  "How Did It Get This Bad?", "What Are We Afraid Of?", "What Could Go Wrong?",
  "Defining the Challenge", "Public Perception and Statistical Realities",
  "Connecting Dots", "What It Looks Like Up Close", "Repercussions", "What's The Plan?",
  "What the Future Holds", "Where We’ve Been", "Dreams of the Future",
  "Sweating the Small Stuff", "What Else Can Be Done",
}

# --- Rubrics, sorted again by the JOB they name -----------------------------
# The rubrics are useless as subjects but they carry something no other field
# does: the *function* a piece serves inside its issue. An issue is built as an
# argument — here is the terrain, here is what is broken, here is what to do —
# and the rubric names which slot a piece fills. Sorting them by that job turns
# a discarded bucket into the only available read on the journal's rhetorical
# posture. Only pieces in curated issues carry one, so this describes the
# curated third of the catalogue, not all of it; that coverage is reported.
STANCES = {
  "Framing the terms": [
    "Setting the Stage", "Defining the Challenge", "What Makes a Great City Work?",
    "Currents", "Connecting Dots", "What Do We Know?",
    "Public Perception and Statistical Realities", "Beyond False Simplicity",
    "What It Looks Like Up Close", "What Does It All Mean?"],
  "Diagnosing what's broken": [
    "How Did It Get This Bad?", "Mugged by Reality", "Persistent Problems Inside",
    "The Causes", "What Doesn’t Work", "Wrenches in the Gears", "Repercussions",
    "What Are We Afraid Of?", "Solving Cases: The System", "Solving Cases: The People",
    "The Policy Record", "Where We Are"],
  "Prescribing a fix": [
    "Some Policy Solutions", "Solutions for Today and Tomorrow", "New Solutions",
    "Toward Solutions", "What Can Be Done?", "What Else Can Be Done", "What to Do Now",
    "The Way Forward", "Where Do We Go From Here?", "Where We Go From Here",
    "If I Had a Hammer...", "The Joy of Incrementalism", "Sweating the Small Stuff",
    "What's The Plan?", "Decisions, Decisions, Decisions",
    "What’s Driving Trends and What to Do About It"],
  "Looking ahead": [
    "Where We’re Headed", "What the Future Holds", "Dreams of the Future",
    "What Opportunities Await?", "What Could Go Wrong?", "The Upside — Yes, Really"],
  "Looking back": ["Looking Back", "Where We’ve Been"],
  "Staging a debate": ["The Great Debate"],
  "Unsorted": ["Etc."],
}
RUBRIC_STANCE = {}
for st, rs in STANCES.items():
    for r_ in rs:
        assert r_ not in RUBRIC_STANCE, f"{r_} mapped to two stances"
        RUBRIC_STANCE[r_] = st
assert set(RUBRIC_STANCE) == RUBRICS, (
    "stance map and rubric list disagree: "
    f"{sorted(RUBRICS - set(RUBRIC_STANCE))} / {sorted(set(RUBRIC_STANCE) - RUBRICS)}")

# --- Verify every topic is accounted for ------------------------------------
all_topics = collections.Counter()
for r in CAT:
    for t in (r.get("topics") or []):
        all_topics[norm(t)] += 1
unaccounted = sorted(t for t in all_topics if t not in SUBJECT_BEAT and t not in META and t not in RUBRICS)
if unaccounted:
    raise SystemExit("Topics not sorted into a bucket:\n  " + "\n  ".join(unaccounted))

def beats_of(rec):
    return {SUBJECT_BEAT[norm(t)] for t in (rec.get("topics") or []) if norm(t) in SUBJECT_BEAT}

def year(r): return (r.get("published_date") or "")[:4]

# --- Aggregations -----------------------------------------------------------
beat_n = collections.Counter()
beat_words, beat_types, beat_years = {}, {}, {}
cooc = collections.Counter()
hist_overlap = collections.Counter()
beat_bylines = {}
untagged = []
for r in CAT:
    bs = beats_of(r)
    if "History & the long view" in bs:
        for b in bs - {"History & the long view"}:
            hist_overlap[b] += 1
    if not bs:
        untagged.append({"title": r["title"], "date": r.get("published_date"),
                         "topics": r.get("topics") or [], "type": r.get("type")})
        continue
    for b in bs:
        beat_n[b] += 1
        beat_words.setdefault(b, []).append(r.get("word_count") or 0)
        beat_types.setdefault(b, collections.Counter())[r.get("type")] += 1
        beat_years.setdefault(b, collections.Counter())[year(r)] += 1
        beat_bylines.setdefault(b, collections.Counter())[r.get("primary_author")] += 1
    for a in sorted(bs):
        for b in sorted(bs):
            if a < b: cooc[(a, b)] += 1

# Criminal-justice cluster: the four beats that make up VC's founding subject.
CJ = ["Crime & violence", "Policing", "Courts & prosecution", "Jails & incarceration"]
cj_pieces = {i for i, r in enumerate(CAT) if beats_of(r) & set(CJ)}
by_year_total = collections.Counter(year(r) for r in CAT if year(r))
cj_by_year = collections.Counter(year(CAT[i]) for i in cj_pieces if year(CAT[i]))

# Single-beat vs multi-beat pieces
nbeats = collections.Counter(len(beats_of(r)) for r in CAT)

# --- Rhetorical stance (curated-issue pieces only) --------------------------
def stances_of(rec):
    return {RUBRIC_STANCE[norm(t)] for t in (rec.get("topics") or []) if norm(t) in RUBRIC_STANCE}

stance_n = collections.Counter()
with_rubric = 0
for r in CAT:
    ss = stances_of(r)
    if ss:
        with_rubric += 1
    for s in ss:
        stance_n[s] += 1

# --- Curated issues vs standalone, and the recurring franchises -------------
# `issues` holds Vital City's internal (#-prefixed) tags: numbered issues plus
# named series. Membership is the cleanest available signal for how a piece was
# commissioned — as part of an assembled argument, or on its own.
in_issue = [r for r in CAT if r.get("issues")]
series_n = collections.Counter()
for r in CAT:
    for i in (r.get("issues") or []):
        series_n[i] += 1
named_series = [(k, v) for k, v in series_n.most_common() if not k.startswith("issue-")]

# --- Beat trajectory, collapsed to one early-vs-recent comparison ----------
# Two-year windows on each end rather than single years, so one heavy issue
# doesn't read as a trend. 2021 (one piece) and the partial current year are
# folded into their neighbours' windows.
EARLY, LATE = ["2021", "2022", "2023"], ["2025", "2026"]
early_tot = sum(by_year_total[y] for y in EARLY)
late_tot = sum(by_year_total[y] for y in LATE)
def window_share(beat, yrs):
    return sum(beat_years[beat].get(y, 0) for y in yrs)
beat_shift = sorted(
   [{"beat": b, "pieces": n,
     "early": round(window_share(b, EARLY) / early_tot * 100, 1),
     "late": round(window_share(b, LATE) / late_tot * 100, 1),
     "change": round(window_share(b, LATE) / late_tot * 100
                     - window_share(b, EARLY) / early_tot * 100, 1)}
    for b, n in beat_n.items() if n >= 30],
   key=lambda x: -x["change"])

# --- Who the journal argues with, by name in the headline -------------------
# A crude but literal measure of mayoral attention: how often a mayor is named
# in a headline. Checked by eye against the full hit lists — every "Adams" is
# Eric Adams and every "Mamdani" is Zohran Mamdani, so the bare surname is safe
# here. It would not be for a name like "Wilson".
def headline_hits(name):
    pat = re.compile(rf"\b{name}\b")
    hits = [r for r in CAT if pat.search(r.get("title") or "")]
    return {"name": name, "headlines": len(hits),
            "share": round(len(hits) / len(CAT) * 100, 1),
            "by_year": dict(sorted(collections.Counter(year(r) for r in hits).items())),
            "first": min((r.get("published_date") or "") for r in hits) if hits else None,
            "titles": [{"date": r.get("published_date"), "title": r["title"]} for r in hits]}

named_in_headline = [headline_hits(n) for n in ("Mamdani", "Adams", "Trump", "Hochul", "de Blasio", "Bloomberg")]

# --- What the headlines actually say ----------------------------------------
# Word frequency across all headlines. Two deliberate choices:
#   1. "New York", "city" and "New Yorkers" are stopped. They appear in a large
#      share of headlines and say nothing — every piece is about New York.
#   2. Possessives are merged into the base word ("Mamdani's" -> "Mamdani"), and
#      a short list of singular/plural pairs is merged, so the counts are of
#      words rather than of surface forms.
# Format artifacts survive on purpose and are labelled where they show up:
# "conversation" and "editor's note" count the Q&A and framing formats, not a
# subject. Anything drawn from this list should be read with that in mind.
STOP = set("""
a an the and or but for to of in on at by with from as is are was be been being it its this that these those
what how why when where who whom which will would can could should must may might do does did done not no nor
so than then there all any both each few other some such only own same too very now new york yorker yorkers
city cities citys about into over under after before again once you your we our us they their he his she her
i my me if part one two three vs still even more most less least make makes made get gets got take takes
""".split())
MERGE = {"jails": "jail", "mayors": "mayor", "mayoral": "mayor", "policing": "police",
         "crimes": "crime", "housings": "housing", "conversations": "conversation"}
TOKEN = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
words = collections.Counter()
for r in CAT:
    seen = set()
    for tok in TOKEN.findall(r.get("title") or ""):
        t = re.sub(r"['’]s$", "", tok.lower()).strip("-'’")
        t = MERGE.get(t, t)
        if len(t) > 2 and t not in STOP:
            seen.add(t)
    for t in seen:          # count each word once per headline, not per mention
        words[t] += 1
headline_words = [{"word": w, "headlines": n, "share": round(n / len(CAT) * 100, 1)}
                  for w, n in words.most_common(40)]

# --- Can a headline tell you opinion from analysis? -------------------------
# Asked directly, and answered by testing rather than asserting: label each
# headline by the signals it carries, then check the label against the content
# type the pipeline assigned independently of the title. Reported as lift over
# the base rate, which is the only honest way to read it — when 94% of argument
# pieces are opinion, a classifier that calls everything opinion is "94%
# accurate" and worthless.
#
# Q&As, podcasts, book reviews and interactive tools are excluded: they are a
# third kind of thing, neither opinion nor analysis, so forcing them onto this
# axis would be a category error.
NON_ARGUMENT = {"q&a", "podcast", "book review", "map/tool", "something else"}
OPINION_SIGNALS = {
  "modal prescription": r"\bshould\b|\bmust\b|\bneeds? to\b|\bought to\b|\blet'?s\b|\bit'?s time\b",
  "negative imperative": r"\bdon'?t\b|\bstop\b|\bno more\b|\bwon'?t\b|\bdoesn'?t work\b",
  "evaluative judgment": r"\bmistake\b|\bmyth\b|\bwrong\b|\bhubris\b|\bfolly\b|\babdication\b|\bfailure\b|\bmess\b|\bhole in\b",
  "declared stance": r"\bwe need\b|\bwhy i\b|\bin defense of\b|\bthe case (?:for|against)\b",
  "direct address": r"^[^,]{3,28},\s+here'?s\b|^(?:mayor|dear)\b.*,",
  "prescriptive frame": r"\bbetter\b|\bsmarter\b|\bhow to\b|\bblueprint\b|\bplaybook\b|\bfix\b",
}
ANALYSIS_SIGNALS = {
  "data framing": r"\bby the numbers\b|\bwhat the (?:data|numbers)\b|\breality check\b|\bin \d+ charts?\b|, charted|, mapped|\bthe data\b",
  "empirical question": r"\bhow (?:rare|safe|common|many|much|often|big)\b|\bhow did\b|\bwhat we know\b",
  "explanatory": r"\ba primer\b|\bexplained\b|\bunderstanding\b|\bwhat to know\b|\bin context\b|\ban? overview\b",
  "assessment": r"\bthe (?:big picture|state of)\b|\bmidyear\b|\byear-end\b|\btrends?\b|\bassessing\b|\bevaluating\b",
  "testing question": r"\b(?:did|does|is there|are)\b.*\?",
}
def headline_signal(title):
    o = any(re.search(p, title, re.I) for p in OPINION_SIGNALS.values())
    a = any(re.search(p, title, re.I) for p in ANALYSIS_SIGNALS.values())
    return ("both" if o and a else "opinion signal" if o
            else "analysis signal" if a else "no signal")

argument = [r for r in CAT if r.get("type") not in NON_ARGUMENT]
n_arg = len(argument)
base_data = sum(1 for r in argument if r.get("type") == "data analysis")
sig_rows = []
for lab in ("analysis signal", "opinion signal", "both", "no signal"):
    grp = [r for r in argument if headline_signal(r.get("title") or "") == lab]
    if not grp:
        continue
    d = sum(1 for r in grp if r.get("type") == "data analysis")
    sig_rows.append({
      "signal": lab, "headlines": len(grp),
      "share_of_argument": round(len(grp) / n_arg * 100, 1),
      "pct_data_analysis": round(d / len(grp) * 100, 1),
      "lift_vs_base": round((d / len(grp)) / (base_data / n_arg), 1)})

headline_signal_test = {
  "argument_pieces": n_arg,
  "excluded_non_argument": len(CAT) - n_arg,
  "base_rate_data_analysis": round(base_data / n_arg * 100, 1),
  "base_rate_opinion": round((n_arg - base_data) / n_arg * 100, 1),
  "rows": sig_rows,
  "opinion_signal_patterns": OPINION_SIGNALS,
  "analysis_signal_patterns": ANALYSIS_SIGNALS,
}

# --- How much of the bench is one-and-done ---------------------------------
prim = collections.Counter(r.get("primary_author") for r in CAT)
once_only = sum(1 for a, c in prim.items() if c == 1)

out = {
  "generated_from": json.load(open(ROOT / "data/meta.json"))["generated_at"],
  "total_pieces": len(CAT),
  "n_topics_normalized": len(all_topics),
  "topic_bucket_sizes": {"subjects": len(SUBJECT_BEAT), "meta": len(META), "rubrics": len(RUBRICS)},
  "topic_bucket_piece_volume": {
     "subject_tag_applications": sum(v for t, v in all_topics.items() if t in SUBJECT_BEAT),
     "meta_tag_applications": sum(v for t, v in all_topics.items() if t in META),
     "rubric_tag_applications": sum(v for t, v in all_topics.items() if t in RUBRICS)},
  "rubrics_listed": sorted(RUBRICS),
  "meta_listed": sorted(META),
  "beats": [{"beat": b, "pieces": n, "share": round(n / len(CAT) * 100, 1),
             "median_words": int(statistics.median(beat_words[b])),
             "types": beat_types[b].most_common(),
             "by_year": dict(sorted(beat_years[b].items()))}
            for b, n in beat_n.most_common()],
  "cooccurrence_top20": [{"a": a, "b": b, "pieces": n} for (a, b), n in cooc.most_common(20)],
  # How wide each beat's contributor bench is. A beat where five bylines write
  # most of it is a specialist circle; a beat spread across a hundred bylines is
  # an open call. Both are editorial choices worth seeing side by side.
  "byline_concentration": sorted(
     [{"beat": b, "pieces": n, "distinct_bylines": len(beat_bylines[b]),
       "top5_share": round(sum(c for _, c in beat_bylines[b].most_common(5)) / n * 100, 1),
       "vital_city_share": round(beat_bylines[b].get("Vital City", 0) / n * 100, 1),
       "top3": [{"name": k, "pieces": v} for k, v in beat_bylines[b].most_common(3)]}
      for b, n in beat_n.items()],
     key=lambda x: -x["top5_share"]),
  # How far the historical lens reaches: share of each beat's pieces also tagged History.
  "history_lens_reach": sorted(
     [{"beat": b, "pieces": n,
       "with_history": hist_overlap[b],
       "share": round(hist_overlap[b] / n * 100, 1)}
      for b, n in beat_n.items() if b != "History & the long view"],
     key=lambda x: -x["share"]),
  "criminal_justice_cluster": {
     "beats": CJ, "pieces": len(cj_pieces),
     "share": round(len(cj_pieces) / len(CAT) * 100, 1),
     "by_year": {y: {"cj": cj_by_year[y], "total": by_year_total[y],
                     "share": round(cj_by_year[y] / by_year_total[y] * 100, 1)}
                 for y in sorted(by_year_total)}},
  "beats_per_piece": dict(sorted(nbeats.items())),
  # The job each piece does inside its issue, from the rubric it carries.
  "stance": {
     "pieces_with_rubric": with_rubric,
     "coverage_share": round(with_rubric / len(CAT) * 100, 1),
     "buckets": [{"stance": s, "pieces": n,
                  "share_of_rubriced": round(n / with_rubric * 100, 1)}
                 for s, n in stance_n.most_common()],
     "rubrics_by_stance": {s: sorted(rs) for s, rs in STANCES.items()}},
  # Commissioned as part of an assembled issue, or standalone.
  "curation": {
     "in_curated_issue": len(in_issue),
     "share": round(len(in_issue) / len(CAT) * 100, 1),
     "standalone": len(CAT) - len(in_issue),
     "n_issues_and_series": len(series_n),
     "named_series_top": [{"series": k, "pieces": v} for k, v in named_series[:12]]},
  # One early-vs-recent comparison per beat, replacing per-year small multiples.
  "beat_shift": {"early_years": EARLY, "late_years": LATE,
                 "early_pieces": early_tot, "late_pieces": late_tot,
                 "beats": beat_shift},
  "named_in_headline": named_in_headline,
  "headline_words": headline_words,
  "headline_signal_test": headline_signal_test,
  "bench": {"primary_bylines": len(prim), "wrote_once": once_only,
            "wrote_once_share": round(once_only / len(prim) * 100, 1)},
  # Pieces tagged History carrying no other cultural tag — the evidence that
  # History is a cross-cutting lens rather than a culture subject.
  "history_only_pieces": sum(
     1 for r in CAT
     if "History & the long view" in beats_of(r) and "Culture & city life" not in beats_of(r)),
  "pieces_with_no_subject_tag": {"count": len(untagged), "examples": untagged[:25]},
}
(ROOT / "data/subject_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))

# --- Validation output ------------------------------------------------------
print(f"wrote data/subject_analysis.json  ({len(CAT)} pieces, {len(all_topics)} normalized topics)")
print(f"\nTopic labels sorted: {len(SUBJECT_BEAT)} subjects / {len(META)} meta / {len(RUBRICS)} rubrics")
tv = out["topic_bucket_piece_volume"]
print(f"Tag applications:    {tv['subject_tag_applications']} subject / "
      f"{tv['meta_tag_applications']} meta / {tv['rubric_tag_applications']} rubric")
print("\nBEATS (a piece counts toward each beat it touches):")
for b in out["beats"]:
    print(f"  {b['pieces']:4} ({b['share']:4.1f}%)  med {b['median_words']:>5}w  {b['beat']}")
print(f"\nCriminal-justice cluster: {out['criminal_justice_cluster']['pieces']} pieces "
      f"({out['criminal_justice_cluster']['share']}%)")
for y, v in out["criminal_justice_cluster"]["by_year"].items():
    print(f"  {y}  {v['cj']:3}/{v['total']:3}  {v['share']:5.1f}%")
print("\nBeats per piece:", out["beats_per_piece"])
print(f"\nSTANCE (rubric-carrying pieces: {with_rubric} = {out['stance']['coverage_share']}% of catalogue):")
for b in out["stance"]["buckets"]:
    print(f"  {b['pieces']:4} ({b['share_of_rubriced']:5.1f}%)  {b['stance']}")
print(f"\nCURATION: {out['curation']['in_curated_issue']} in an issue/series "
      f"({out['curation']['share']}%) / {out['curation']['standalone']} standalone")
for s in out["curation"]["named_series_top"][:8]:
    print(f"  {s['pieces']:3}  {s['series']}")
print(f"\nBEAT SHIFT ({'+'.join(EARLY)} = {early_tot} pieces  ->  {'+'.join(LATE)} = {late_tot} pieces):")
for b in beat_shift:
    print(f"  {b['early']:5.1f}% -> {b['late']:5.1f}%  ({b['change']:+5.1f})  {b['beat']}")
print("\nTOP HEADLINE WORDS:")
for w in headline_words[:24]:
    print(f"  {w['headlines']:4} ({w['share']:4.1f}%)  {w['word']}")
print(f"\nHEADLINE SIGNAL TEST ({n_arg} argument pieces; base rate data-analysis "
      f"{headline_signal_test['base_rate_data_analysis']}%):")
for r_ in sig_rows:
    print(f"  {r_['headlines']:4} ({r_['share_of_argument']:4.1f}%)  {r_['signal']:16} "
          f"-> {r_['pct_data_analysis']:5.1f}% data analysis  ({r_['lift_vs_base']}x base)")
print("\nNAMED IN HEADLINE:")
for n in named_in_headline:
    print(f"  {n['headlines']:3} ({n['share']:4.1f}%)  {n['name']:10} {n['by_year']}")
print(f"\nBENCH: {len(prim)} primary bylines, {once_only} wrote once "
      f"({out['bench']['wrote_once_share']}%)")
print(f"\nPieces with no subject tag at all: {len(untagged)}")
for u in untagged[:12]:
    print(f"  {u['date']}  [{u['type']}]  {u['title'][:58]}  topics={u['topics']}")
