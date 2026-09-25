# Influence index: methodology

First version Sept. 25, 2026. The page (influence/index.html, "Method") carries the same text with
the current numbers filled in. Code: `influence_pull.py` (collection), `influence_build.py`
(scoring), `encrypt_influence.py` (publishing), `.github/workflows/influence-refresh.yml` (weekly).

## What the index measures

Influence on policy cannot be observed directly. Uptake can: the places where people who make,
argue about or study New York City policy use an organization's work in public. The index counts
uptake in five places and compares Vital City with eleven peer organizations counted identically.
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

## The five measures

**Press (weight 0.30).** Google News RSS, query `"<name>" site:<outlet> after:<Jan 1> before:<Jan 1
next year>`, for each of 27 outlets that cover New York City government (list in `OUTLETS`). Google
returns at most 100 items; a window that hits 100 is split in half by date and re-asked until none is
truncated. Unit: one story per outlet (duplicate titles removed). An outlet is never counted for the
organization that publishes it.

Vital City's name is also ordinary English, and Google's phrase match ignores case, so every Vital
City hit is resolved to its article and read (`check_page`): *confirmed* if the page has "Vital City"
capitalized and not directly after a determiner ("a," "our," "the," "this" ...) and not before a
generic noun ("services," "agencies" ...), or links to vitalcitynyc.org; *generic* if the phrase is
only English; *absent* if a readable page lacks it; *unreadable* if a paywall, bot wall or failed
fetch hides the text (pages from hard-paywalled outlets that do not show the name are unreadable,
not absent). Counted = confirmed + unreadable x (confirmed / readable), by year. Peers' names are
unambiguous and are not checked. City Limits has no press count.

**Official record (0.25).** (a) Government web pages: the same Google News method over nyc.gov,
council.nyc.gov, comptroller.nyc.gov, advocate.nyc.gov, ibo.nyc.gov, ny.gov, nysenate.gov,
nyassembly.gov and nycourts.gov, with Vital City hits checked the same way. (b) Federal court
filings: CourtListener's RECAP archive (API v4, `type=rd`), searched for each organization's web
address in quotation marks. Counted once per case (docket) per year: the archive indexes every
attachment, and one congestion-pricing filing carries Vital City's address in nine attachments.
State court filings are not publicly searchable and are missing for everyone.

**Scholarship (0.20).** Google Scholar, query `"<web address>"` limited to one publication year,
run in a browser because Scholar refuses scripts. The number is Scholar's printed estimate ("About 40
results"), stored with the printed text. For the Center for Justice Innovation the two addresses'
counts are added (a work citing both counts twice; rare). Works cited by name without an address
are missed, for everyone. Recent years fill in slowly, for everyone.

**Wikipedia (0.10).** MediaWiki `list=exturlusage` gives the articles citing each address today.
For each, a binary search over checkpoints (Jan. 1 and July 1 of each year since 2021) finds the
first checkpoint whose article text contains the address. Unit: articles citing the organization at
year's end (current year: today). Citations removed for good are missed, for everyone. Low weight
because anyone, including an organization's staff, can add a link.

**Web standing (0.15).** Common Crawl's domain-level web graph ranks
(`projects/hyperlinkgraph/<release>/domain/<release>-domain-ranks.txt.gz`), one release per quarter
since mid-2021, streamed and filtered. Standing in a release = 1 / sqrt(PageRank position x harmonic
centrality position), using an organization's better-ranked address. Year value = median over that
year's releases (one mid-2024 crawl ranked Vital City five times higher than its neighbors).

## From counts to the index

For each measure and year: `ratio = (Vital City + 1) / (median of the peers + 1)`; web standing uses
`Vital City / median` without the one. The one keeps zero years defined and damps tiny counts. The
median keeps City Journal and the Furman Center from setting the bar alone.

`index = exp( sum(weight x ln(ratio)) / sum(weight) )` over the measures with data that year.

The league table scores each organization against the other eleven the same way.

## Uncertainty and robustness

Band: every count redrawn 3,000 times as a Poisson variable around its observed value (seed
20260925), index recomputed, middle 90 percent kept. Web standing held fixed.

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

## Refresh

Weekly (Mondays): press and government pages for the current year, plus the previous year in each
month's first week; new Vital City hits checked; CourtListener, Wikipedia, new Common Crawl
releases and government readers re-read; index rebuilt. Scholar: by hand each quarter
(`python3 influence_pull.py scholar-import <file>`; the file format is in `import_scholar`).

## Changes

- 2026-09-25: first version.
