# Vital City content catalogue — methodology

This document explains exactly where the catalogue data comes from, how every
field is derived, what is included and excluded, and the known limitations.
Nothing here is a black box.

## Source

All data is pulled from the **Ghost Content API** that powers
vitalcitynyc.org. Vital City runs on Ghost, and Ghost exposes a read-only
Content API for its own on-site search feature.

- API base: `https://vital-city.ghost.io/ghost/api/content/`
- Endpoint used: `/posts/` with `include=authors,tags`
- Key: a public, read-only Content API key that the site itself embeds in its
  front-end search widget (`data-key` on the page). It grants read access to
  already-published content only. It cannot edit, delete or read drafts.

We page through every post (50 per request, ordered by publish date) until the
API reports no further pages. No scraping of rendered HTML pages is involved —
we read the same structured data Ghost uses internally.

## What counts as "published content"

- **Included:** every Ghost *post* (article) returned by the Content API. The
  Content API only returns published, public-visible posts — drafts, scheduled
  and members-only content are not exposed by this key.
- **Excluded:** Ghost *pages* (static pages like About, Masthead, Submissions).
  These are site furniture, not editorial articles. They can be added later if
  wanted by also querying the `/pages/` endpoint.

As of the latest run this is **881 articles** spanning **2021-09-15 to
2026-07-31**.

## Field definitions

Per article (`data/catalogue.json`):

| Field | Source / derivation |
|---|---|
| `title` | Ghost `title` |
| `slug` | Ghost `slug` |
| `url` | `https://www.vitalcitynyc.org/<slug>/` |
| `published_date` | Date portion of Ghost `published_at` (UTC) |
| `published_at` / `updated_at` | Ghost timestamps, verbatim |
| `primary_author` | Ghost `primary_author.name` (the lead byline) |
| `authors` | All bylined authors, in Ghost order |
| `topics` | Public-facing tags (see tag classification below) |
| `issues` | Internal series/issue tags (see below), with the `#` stripped |
| `issue_numbers` | Integer pulled from any `#issue-N` tag |
| `excerpt` | Ghost `custom_excerpt` if set, otherwise Ghost's auto-generated `excerpt` |
| `feature_image` | Ghost `feature_image` URL |
| `featured` | Ghost `featured` flag (editor-promoted) |
| `visibility` | Ghost `visibility` (public/members/paid) |
| `word_count` | Count of whitespace-separated tokens in the stripped article HTML |
| `reading_minutes` | `word_count / 230`, rounded, floor of 1 (230 wpm is a standard reading-speed assumption) |

## Tag classification — how topics and issues are separated

Ghost stores two kinds of tags. We split them by Ghost's own `visibility` flag:

- **Public tags → `topics`.** These are subject tags shown to readers (Crime,
  Housing, History, Gun Violence, etc.). ~200 distinct topics.
- **Internal tags (name begins with `#`) → `issues`.** Vital City uses internal
  tags to group articles into themed **issues and series**, e.g. `#issue-14`,
  `#congestion-pricing`, `#whither-new-york`, `#rubber-meets-road`,
  `#data-stories`. We strip the leading `#` for display. Numbered issues get a
  friendly `display_name` ("Issue 14"); named series are title-cased.

A single article can belong to more than one issue/series and to many topics.

### Tags deliberately dropped as junk

Two internal tags are migration/system artifacts, not real classifications, and
are excluded everywhere:

- `#ImagesUploaded` (slug `hash-imagesuploaded`) — auto-applied during a media import
- `#Import 2026-02-26 13:34` (slug prefix `hash-import-`) — a one-time content import marker
- `#none` (slug `hash-none`) — a stray empty tag on 4 posts

## Content type classification

Each article is assigned exactly one **type**, plus a `type_basis` field that
records *why* it got that type (so nothing is a black box and you can audit or
reclassify any call).

### The vocabulary mirrors the website

The types are the sections vitalcitynyc.org itself uses to organize content, so
the catalogue and the site agree about what a piece is:

| Type | Corresponds to |
|---|---|
| **opinion/commentary** | the site's **Commentary**, and the essays that fill each issue of **The Journal** — analysis and argument, overwhelmingly by outside contributors |
| **policy** | the site's **Policy** section — Vital City's own recommendations (the *Just Fix It*, *What To Do (and Not To Do)* and *Rubber Meets Road* series) |
| **data analysis** | the site's **Data** section — data stories and the recurring State of Crime / State of the Jails reports |
| **podcast** | the site's **Podcast** section |
| **q&a** | interviews, panels and forum transcripts |
| **book review** | surfaced in the site's **Culture** section |
| **map/tool** | a piece that *is* an interactive tool or map |
| **something else** | site furniture — press releases, editor's notes, event notices, obituaries |

### The rules, in order

Rule-based and most-specific-first; the first rule that matches wins.

| Order | Type | Matched when… | `type_basis` |
|---|---|---|---|
| 1 | **something else** | tagged "Press Releases" or "In Memoriam"; title like "About This Project", "Editor's Note", "Masthead", "A Note From…", "Call for Submissions"; **or** tagged "Events" and under 700 words and not a transcript (an event notice, not an article) | `tag:press-release` / `tag:in-memoriam` / `title:framing-page` / `tag:event-notice` |
| 2 | **book review** | tagged "Book Review", or title says "a review of" / "reviewed" | `tag:book-review` / `title:review` |
| 3 | **podcast** | tagged "Podcast" | `tag:podcast` |
| 4 | **q&a** | tagged interview, Conversations, or "In Conversation With…"; title reads like a conversation ("in conversation", "a conversation with", "talks to/with", "Q&A", "panel", "forum"); **or** the body *is* a multi-speaker transcript (see below) | `tag:<name>` / `title:conversation` / `html:multi-speaker-transcript` |
| 5 | **data analysis** | tagged "Data Stories" or in the `#data-stories` series | `tag:data-stories` |
| 6 | **map/tool** | title names an interactive artifact ("interactive", "explorer", "tracker", "dashboard", "calculator", "simulator", "quiz", "proof-of-concept"); **or** the body is essentially just the embed — under 300 words plus an embedded Vital City app or a JS map library | `title:tool-or-map` / `html:embed-is-the-piece` |
| 7 | **data analysis** | title like "by the numbers" / "in N charts" / "mapped"; **or** the piece embeds **3 or more** charts (Flourish / Datawrapper) | `title:data-framing` / `html:N-chart-embeds` |
| 8 | **policy** | in the `#just-fix-it`, `#what-to-do-and-not-to-do` or `#rubber-meets-road` series (the three series the site files under Policy); **or** the title is "Just Fix It: …" / "What To Do (and Not To Do) …" | `series:<name>` / `title:policy-recommendation` |
| 9 | **opinion/commentary** | everything else (the default — Vital City is fundamentally a commentary journal) | `default` |

Plus a short, hand-checked override table (`TYPE_OVERRIDES` in `scrape.py`),
keyed by slug, for the handful of calls no rule can see. Each override records
its own reason in `type_basis` as `curated:<reason>`. There are currently three.

As of the latest run: opinion/commentary 712, q&a 58, data analysis 47,
podcast 28, something else 14, policy 12, book review 6, map/tool 4.

### Transcript detection

A piece counts as a multi-speaker transcript when **12 or more** of its
paragraphs open with a speaker label ("Errol Louis:", "EL:", "Vital City:") and
**at least two** speakers take **four or more** turns each. That separates
pieces whose *form* is the conversation — interviews, the *Borrow and Steal*
interview series, panel and forum proceedings — from prose columns that merely
quote a short exchange. The thresholds were set by checking both sides: a
950-word column quoting a nine-line debate exchange fails; a 1,500-word
interview passes.

**Deliberate design choices and their limits:**
- **Embedding a chart or a map does not make a piece a tool.** An earlier
  version typed any article containing a Vital City app iframe as `map/tool`,
  which mislabeled ten commentary essays that embedded one of our maps to
  illustrate an argument. A piece is a tool only if its title says so or the
  embed is substantially the whole piece.
- "tool" and bare "map" are **not** matched in titles because they are usually
  metaphorical ("the unlikely *tool* that could transform hiring").
- Mapping/viz libraries are matched by their actual script/CDN references (e.g.
  `leaflet.js`, `api.mapbox.com`, `/d3@`, `vega-lite`), **not** loose words, so
  prose like "Las **Vega**s" or "road**map**" does not trigger a false positive.
- The 3-chart threshold for "data analysis" keeps opinion essays that merely
  include a chart or two in "opinion/commentary"; only genuinely chart-driven
  pieces flip to "data analysis".
- **Data beats policy, and data beats tool.** A chart-driven component of a
  policy series (e.g. "Subway Safety: What the Data Show", inside *What To Do
  (and Not To Do)*) is typed `data analysis`, because that is what the reader
  gets. The same precedence keeps "The New York City Economy: A Data Story" —
  an interactive app tagged Data Stories — with the other data stories.
- **Policy tracks the series, not the byline.** Vital City commissions outside
  authors to write components of its policy packages (e.g. Aaron Chalfin's "50
  Years of Evidence" in *Rubber Meets Road*). Those are typed `policy` because
  the site files them under Policy.
- The classifier favors precision over recall on the smaller categories. A piece
  that is mis-typed can be inspected via `type_basis` and the rules adjusted in
  `scrape.py` (`classify_type`).

## Subject / beat classification

The `topics` field cannot answer "what have we written about" on its own,
because Ghost keeps three different kinds of label in it:

- **subjects** — real topics ("Housing", "Gun Violence"), 135 of the 206 tags
- **issue section rubrics** — table-of-contents headings that structure a single
  issue's arc ("Setting the Stage", "What Can Be Done?", "Where Do We Go From
  Here?"), 48 tags. They name no subject at all. Read raw, "Setting the Stage"
  (26 pieces) outranks homelessness.
- **format / meta labels** — "Podcast", "Data Stories", "interview", 23 tags,
  duplicating what `type` already records.

`analyze_subjects.py` sorts every tag into exactly one of the three buckets by
hand and maps the subjects onto 21 **beats**, writing
`data/subject_analysis.json`. It **exits non-zero if any tag is unsorted**, so a
newly added tag can never be silently dropped — the daily workflow logs a
warning and the beat charts go stale until the tag is placed.

Two deliberate calls, both documented in the script:

- **"History" is its own beat, not part of Culture.** It is the second
  most-applied tag in the catalogue (144 pieces) but functions as a *lens*,
  applied to housing, charter-reform and infrastructure pieces as readily as to
  cultural ones; 104 of its pieces carry no other cultural tag. Folding it into
  Culture would overstate cultural coverage by roughly half. Its overlap with
  every other beat is reported separately.
- **A piece counts toward every beat it touches**, so beat counts sum to more
  than 881. About 62% of pieces carry two beats.

Also normalized here: seven tags exist twice in Ghost, once with a trailing
period ("History." and "History"); those are counted together. `Etc.`,
`If I Had a Hammer...` and `In Conversation With...` keep their punctuation.

The results are charted at `/catalogue-analysis/`.

## Rollups

- `data/authors.json` — one entry per contributor: post count, the article
  slugs, plus bio/socials/profile URL pulled from Ghost's author records.
- `data/issues.json` — one entry per issue/series: post count, first/last
  publish date, top 5 co-occurring topics, issue number and display name.
- `data/tags.json` — every public topic with its post count.
- `data/types.json` — each content type with its post count.
- `data/meta.json` — run timestamp and totals.

## Contact CRM cross-analysis (local-only)

A separate, **private** layer lets us cross-analyze authors by contact type. It
is built by `build_contacts.py` from Vital City's contact agglomeration
spreadsheet and is **never published** — the source `.xlsx` and the entire
`private/` output folder are gitignored, so none of it reaches the public site.

- Source: `private/contacts_source.xlsx`, sheet `combined` (~1,250 contacts).
- Person-type categories used: VC contributor, VC advisor, journalist, academic,
  foundation leadership, nonprofit leadership, city gov, state gov, fed gov,
  judge, architect. (The sheet's criminal-justice / housing / transit columns are
  beat tags, kept as `topics`.)
- Authors are matched to contacts by **name** (exact normalized, then first+last),
  the same method used elsewhere — so it inherits the same name-matching caveats
  (namesakes, spelling variants). 245 of 443 authors (55%) matched.
- Outputs (all gitignored): `private/contacts.json`, `private/author_categories.json`
  (the file the catalogue UI reads), `private/cross_analysis.json` (summary counts).

In the catalogue UI, when this local layer is present the page shows an "author
type" filter and contact-category tags beside each author. On the public
GitHub Pages site the file is absent, so those features simply do not appear —
the public catalogue contains only published-content data, never the CRM.

## Known limitations

1. **Publish-date quirks.** A few issues span a wide date range (e.g. the
   current/rolling issue) because individual articles were published or
   re-dated over time. Dates are whatever Ghost records as `published_at`.
2. **Author name as identity.** Authors are keyed by display name. If the same
   person is entered under two spellings in Ghost, they would appear as two
   contributors. No de-duplication or identity matching is applied.
3. **Word counts are approximate.** They are computed from the article HTML
   with tags stripped; embedded charts, images, pull-quotes and captions are
   not counted as prose, and code/HTML cards are excluded from the text.
4. **Public content only.** Drafts, scheduled posts and any members-only
   content are not visible through this API key and are therefore not catalogued.
5. **Snapshot in time.** The catalogue reflects the moment `scrape.py` last ran.
   See README for the refresh schedule.
