# Press map

Who covers New York City government, what they have actually been writing about,
and how to reach them. A tool tab in the Vital City toolkit: `press/index.html`,
gated with the shared passphrase, reading `press/data.enc`.

## The idea

Every press database is a list of labels somebody typed: "housing reporter,"
"City Hall bureau." Labels go stale the week someone changes desks, and they
cannot answer the question you actually have, which is *who would want this
particular story*.

So this one does not store beats. It harvests bylines, matches each story
against a vocabulary of New York City government beats, and keeps the matching
stories next to the count. A beat is a claim with receipts: 23 stories on
policing, here are three of them, filed this month. When you paste a topic in,
the ranking is a statement about published evidence, and every card can show its
work.

## Running it

```
python3 build_press.py          # full harvest, 11-13 minutes
python3 build_press.py --fast   # reuse private/press_cache/, rebuild in seconds
python3 encrypt_press.py        # private/press.json -> press/data.enc
```

Dependencies: `feedparser`, `beautifulsoup4`. Fetching shells out to `curl`.

Config lives beside the page and is safe to commit:

- `press/outlets.json` — the outlet registry. 92 outlets: legacy dailies, wires,
  nonprofit and digital newsrooms, TV, radio, podcasts, ethnic and community
  press, hyperlocals, trade and policy titles, newsletters. Each carries its
  feeds, masthead URL, tips line and a `feed_note` when the outlet blocks
  automated clients.
- `press/beats.json` — 36 beats and their vocabularies, with a `priority`:
  1 for crime and criminal justice, 2 for city and state government, 3 for the
  rest. Priority orders things; it never filters. State-government coverage at
  city papers is carried under the Albany beat.

Output goes to `private/press.json` (gitignored), which is what
`encrypt_press.py` turns into `press/data.enc`.

## Where the data comes from

| Layer | Source | What it gives |
|---|---|---|
| Stories | each outlet's RSS feed | the last week or two, with bylines |
| Stories | WordPress REST API where readable | several hundred back, with the outlet's own category terms |
| Stories | Google News `site:` query | outlets that block crawlers — headlines, no bylines |
| People | 33 mastheads | names, titles, and addresses where published |
| People | the byline block on one recent story each | author archive link, address, social handles |
| People | the reporter's author archive page | bio, address |
| Vital City | `private/press_source.csv` | the curated press list |
| Vital City | `data/authors.json` | people who have written for Vital City |
| Vital City | `private/growth.json` | media mentions, for the rail and the citation flags |

## The rule about addresses

An address enters the file only if it was read verbatim off a page the build
fetched, **and** it pairs with the person's name. Newsroom addresses are built
out of names, so an address that cannot be derived from the name is evidence the
parser walked into the wrong person's block — which is the one failure mode that
would put a real reporter's address on somebody else's card. Those are dropped
into `unpaired_addresses` with the surrounding text, for a human to look at.

This is not theoretical. An early run paired Chalkbeat's data reporter with the
address of the person listed above her. The pairing rule caught it.

Nothing is ever inferred from a pattern. Same rule as the officials database.

## The Vital City flags

Josh asked that contacts Vital City already knows be bold. Three person-level
facts earn it:

- **Vital City press list** — on the curated list in `press_source.csv`.
- **Vital City contributor** — has published under a Vital City byline.
- **Has cited Vital City** — a story of theirs matches a logged media mention by
  title. The rarest and strongest, because the mentions feed records outlets, not
  bylines.

A fourth, **outlet cites us**, is shown but deliberately does not bold anything:
a newsroom's citation history says nothing about the reporter standing in it.

## Known limits

- Story counts are not comparable across outlets. An outlet with a readable API
  contributes hundreds; one behind Cloudflare contributes ten. Rank within an
  outlet, not across.
- Outlets reached only through Google News contribute headlines without bylines,
  so they show stories and few people. NY1, Crain's, Newsday and the Daily News
  are the significant ones.
- Titles come off mastheads, which go stale between reorganizations.
- A beat is what someone has been publishing, which is not always what they want
  next.
- Radio and TV people are under-covered relative to their real influence,
  because broadcast segments are not indexed the way text is.
