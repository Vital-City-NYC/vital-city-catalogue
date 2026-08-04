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
import json, collections, statistics
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
print(f"\nPieces with no subject tag at all: {len(untagged)}")
for u in untagged[:12]:
    print(f"  {u['date']}  [{u['type']}]  {u['title'][:58]}  topics={u['topics']}")
