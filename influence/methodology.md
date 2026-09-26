# Influence index: methodology

First version Sept. 25, 2026. The page (influence/index.html, "Method") carries the same text with
the current numbers filled in. Code: `influence_pull.py` (collection), `influence_build.py`
(scoring), `encrypt_influence.py` (publishing), `.github/workflows/influence-refresh.yml` (weekly).

## What the index measures

Influence on policy cannot be observed directly. Uptake can: the places where people who make,
argue about or study New York City policy use an organization's work in public. The index counts
uptake in six places and compares Vital City with eleven peer organizations counted identically.
It measures how much of the observable policy conversation runs through Vital City. It does not
measure whether any policy changed because of it.

Left out on purpose: private access (meetings, calls), which leaves no public trace; podcasts, radio
and television, which cannot be searched at scale for peers; and Vital City's own output (pieces,
events, newsletters), which is input rather than uptake. Cases of influence are recorded by hand in
the impact ledger on the Prospects page. The index uses only sources that can be queried the same way
every year, because a hand-kept count rises with the effort put into keeping it.

## Why a comparison

Every source changes on its own. Google News returns three times as many Politico items naming the
Citizens Budget Commission in 2025 as in 2023; Google Scholar's recent years fill in for months. A
count of Vital City alone mixes Vital City's growth with the sources' growth. Asking the identical
question about peers and dividing cancels what affects all of them alike.

## The peers

Chosen before any counts were pulled, on three tests: publishes policy analysis or argument about
New York City; the city is its main subject; independent nonprofit (government bodies such as the
Independent Budget Office are cited as authorities, not voices, and are excluded).

| Organization | Web address(es) | Press query |
|---|---|---|
| Citizens Budget Commission | cbcny.org | "Citizens Budget Commission" |
| Center for an Urban Future | nycfuture.org | "Center for an Urban Future" |
| Community Service Society | cssny.org | "Community Service Society" |
| Fiscal Policy Institute | fiscalpolicy.org | "Fiscal Policy Institute" |
| NYU Furman Center | furmancenter.org | "Furman Center" |
| Regional Plan Association | rpa.org | "Regional Plan Association" |
| City Journal | city-journal.org | "City Journal" |
| Gotham Gazette | gothamgazette.com | "Gotham Gazette" |
| City Limits | citylimits.org | none (name is ordinary English) |
| Center for Justice Innovation | innovatingjustice.org, courtinnovation.org | either name (renamed 2023) |
| Data Collaborative for Justice | datacollaborativeforjustice.org | "Data Collaborative for Justice" |

## The six measures (weights in parentheses)

**Major outlets (0.15) and New York press (0.15).** Google News RSS, query `"<name>" site:<outlet>
after:<Jan 1> before:<Jan 1 next year>`. Major outlets (14): nytimes.com, wsj.com,
washingtonpost.com, politico.com, newyorker.com, nymag.com, bloomberg.com, theatlantic.com, npr.org,
economist.com, theguardian.com, axios.com, gothamist.com, wnyc.org. New York press (20): thecity.nyc,
nydailynews.com, nypost.com, cityandstateny.com, ny1.com, amny.com, crainsnewyork.com,
streetsblog.org, citylimits.org, gothamgazette.com, therealdeal.com, hellgatenyc.com, nysfocus.com,
chalkbeat.org, silive.com, brooklynpaper.com, documentedny.com, newsday.com, timesunion.com, law.com.
Scored as two measures so a Times story is not diluted by a neighborhood weekly. A window that
returns Google's 100-item maximum is split by date and re-asked. Unit: one story per outlet
(duplicate titles removed). An outlet is never counted for the organization that publishes it.

Vital City hits are resolved to the article and read (`check_page`): *confirmed*, *generic*,
*absent* or *unreadable* (paywall, bot wall, failed fetch; pages from hard-paywalled outlets that do
not show the name are unreadable, not absent). Only confirmed hits count, so Vital City's press count is a floor. Unreadable hits (the Times,
Politico and the Staten Island Advance block scripts) are listed as possible additions and count
once a person reads them and sets their status by hand. Borrowing the readable-page confirmation
rate was tried first and dropped: the Times's unreadable hits include war reports from Ukraine that
call a city "vital."

**Official record (0.25).** Three sources, added:
- City Hall: every item in the mayor's office newsroom since 2022 (nyc.gov
  `bin/nyc/articlesearch.json` index, about 5,600 releases and transcripts; bodies from each item's
  `.model.json`), checked for each organization's exact, case-sensitive name (`TEXT_NAMES`, and
  `names_us()` for Vital City). Unit: one item.
- Comptroller: comptroller.nyc.gov WordPress search (posts and pages) for each exact name, confirmed
  in the post text. Unit: one post.
- Federal courts: CourtListener RECAP (API v4, `type=rd`), each organization's web address in
  quotation marks. Unit: one case (docket) per year.
Replaced on Sept. 25, 2026: the first version used Google News's index of government sites, which
dates pages by crawl and holds little besides press releases.

**Scholarship (0.25).** Google Scholar, `"<web address>"` limited to one publication year, run in a
browser (Scholar refuses scripts). Scholar's printed estimate is stored with its text. The Center for
Justice Innovation's two addresses are added. Name-only citations are missed, for everyone.

**Wikipedia (0.10).** MediaWiki `list=exturlusage`, then a binary search over Jan. 1 and July 1
checkpoints for when each article first carried the address. Unit: articles citing the organization
at year's end (current year: today). First-add revisions and editors are stored for Vital City
(14 articles, 14 different editors as of Sept. 25, 2026).

**Links from policy sites (0.10).** Common Crawl's domain-level link graph
(`<release>-domain-vertices.txt.gz`, `<release>-domain-edges.txt.gz`), one release per year: three
streamed passes find each organization's vertex id, keep the edges pointing at it and name their
source domains (`collect_weblinks`). Unit: distinct government (`.gov`, `.mil`, state `.us`),
university (`.edu`, `.ac.xx`) and news domains (`NEWS_DOMAINS`: the press panel plus about 60
city and policy outlets) linking to the organization's site. Other linking domains are reported,
not counted. Domain level: nyc.gov counts once however many agencies link. Replaced, on Sept. 25,
2026, a measure of overall rank in the graph (PageRank and harmonic centrality), which tracked
Wikipedia closely and said little about policy audiences.

**Beside the index, not in it.** Council hearings: every transcript and written-testimony file in
the nyc-council-hearings corpus (Legistar, 2024 session on), exact names; unit one hearing; stated
meetings excluded. Kept out of the index until the corpus reaches back to 2022, since a measure that
joins partway would move the index for reasons unrelated to Vital City. Government readers:
newsletter subscribers on New York government domains (below).

## What counts as a mention of Vital City

Any form of the name ("Vital City," "Vital City's," "Vital City NYC," "the policy journal Vital
City"), references to its work ("a Vital City analysis," "the Vital City report") and to the
organization ("Vital City's founder"), and any link to vitalcitynyc.org. Both words must be
capitalized, and generic English ("remains a vital city," "our vital city," "vital city
services") is excluded (`names_us()`: accept when followed by 's or a noun such as report, analysis,
founder, editor, journal; otherwise reject after a determiner or before a generic noun).

Not captured: stories quoting a contributor without naming Vital City; press links to
vitalcitynyc.org without the name; scholarship citing the name without the address; podcasts,
radio and television. These apply to peers alike, except the first, which may undercount Vital City
somewhat more.

## Do the measures agree?

Across the twelve organizations, every pair of measures ranks them in the same direction (Spearman
rank correlations 0.26 to 0.93 in 2024 and 2025). Wikipedia and the web measures agree most closely;
web measures carry little weight.

## From counts to the index

For each measure and year: `ratio = (Vital City + 1) / (median of the peers + 1)`. The one keeps zero years defined and damps tiny counts. The
median keeps City Journal and the Furman Center from setting the bar alone.

`index = exp( sum(weight x ln(ratio)) / sum(weight) )`

Every measure is now a count, so every ratio uses the +1. over the measures with data that year.

The league table scores each organization against the other eleven the same way. An organization is
ranked only when the measures covering it carry at least 75 percent of the weight (City Limits has no
press counts and is listed unranked).

## Uncertainty and robustness

Band: every count redrawn 3,000 times as a Poisson variable around its observed value (seed
20260925), index recomputed, middle 90 percent kept.

Robustness: the index recomputed with equal weights; with each measure removed in turn; without City
Journal and the Furman Center; and with only the six research shops as peers.

## Government readers (companion, not in the index)

Subscribers (current or former, with a subscription date) whose address is on a New York government
domain: nyc.gov and subdomains, ny.gov, nysenate.gov, nyassembly.gov, state.ny.us, nycourts.gov,
nypd.org, the district attorneys' domains, mta.info, panynj.gov, nyccfb.info. Counted in a month if
subscribed by its end and not unsubscribed by then. Source: the contact tool's people file (Ghost
members, Mailchimp unsubscribe dates).

## Known limits

The current year is partial; ratios compare the same partial window, but move as the year fills in.
Google News reaches back unevenly. A newsletter roundup counts the same as a feature. Self-citation
counts for everyone alike (one of Vital City's court cases is an amicus brief its founder filed with
other former officials).

## Links to individual pieces (not yet used)

The link graph is domain level. Page-level links to specific vitalcitynyc.org pieces exist in
Google Search Console (Links > Export external links > Latest links: linking page and date), which
Vital City already has; the export is manual (the API does not serve links) and has no peer
equivalent, so it would feed the evidence list, not the index.

## Refresh

Weekly (Mondays): press for the current year, plus the previous year in each month's first week;
new Vital City hits checked; new City Hall items, the Comptroller, CourtListener, Wikipedia, new
Common Crawl releases and government readers re-read; index rebuilt. Council hearings: recounted on
the Mac (`influence_pull.py council`) when the hearings corpus is updated. Scholar: by hand each quarter
(`python3 influence_pull.py scholar-import <file>`; the file format is in `import_scholar`).

## Changes

- 2026-09-25: first version.
- 2026-09-25 (same day, after review): press split into major outlets (14) and New York press (20),
  seven national outlets added; official record rebuilt from City Hall, the Comptroller and federal
  courts; web rank replaced by links from government, university and news sites; weights now
  record .25, scholarship .25, major .15, New York press .15, Wikipedia .10, links .10 (were press .30, record .25, scholarship .20, web .15, Wikipedia .10); name test widened for
  "a/the Vital City <noun>"; Council hearings added beside the index; league requires 75 percent
  weight coverage.
