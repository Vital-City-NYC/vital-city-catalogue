# Getting picked up by Apple News and other curators

Audited 2026-08-27 against the live site.

## The good news: the feed is already the right shape

Apple News, Flipboard, SmartNews and MSN all ingest an RSS feed, and they all
want the same things. Vital City's feed has them:

| What they need | Status |
|---|---|
| Full article text, not an excerpt | Yes — 12,664 characters on the first item |
| Author on every item | Yes |
| Categories | Yes |
| Images, inline and as a separate tag | Yes, both |
| Publication title, description and logo | Yes |

That is better than a lot of what gets accepted. Nothing about the content
needs to change.

## The problem: nobody can find the feed

The feed is at **`/commentary/rss/`**, because articles are routed under
`/commentary/`. The conventional locations all return a 404 page:

    /rss/       404
    /feed/      404
    /atom.xml   404

The site head does declare the real location correctly, so a careful crawler
finds it. But plenty of submission forms, directory listings and aggregators
guess `/rss/` first, and a 404 there reads as "this publication has no feed."

**Fixed** in `redirects.json` — four rules pointing the conventional paths at
the real feed. Upload it the same way as before.

## Applying to Apple News

Apple News is an application, not a crawl. Nobody gets picked up passively.

1. Go to **publish.apple.com** and sign in with an Apple ID that should belong
   to the organization, not a person who might leave.
2. Choose **RSS feed** as the source and give it
   `https://www.vitalcitynyc.org/commentary/rss/`.
3. It asks for a channel logo and a publication description. The logo has hard
   requirements that change; take them from the form rather than from here.
4. Review takes a few weeks. Approval puts articles in the Apple News app; it
   does not by itself put them in the curated **Top Stories**, which is chosen
   by Apple's editors.

What actually earns the curated placement, once a channel exists, is being a
reliable source on a story an editor is already assembling. Vital City's
strongest claim is the crime and city-government data during a contested
mayoralty — the same material that already draws the readership.

## Other curators worth the twenty minutes

Ordered by effort against likely return for a New York City policy journal.

- **Google News** — no application any more; it indexes automatically. What
  helps is the article markup, and there is one gap: the site emits
  `@type: Article` where Google prefers `@type: NewsArticle`. That is a theme
  change, not a settings toggle.
- **Flipboard** — self-serve. Create a publisher account, point it at the feed.
  Reaches a general-interest audience that email does not.
- **SmartNews** — publisher application, RSS-based, meaningful US traffic.
- **Techmeme and Memeorandum** — no application; they watch a fixed set of
  sources. Getting on their radar is a function of being cited by publications
  they already read, which the mentions tracking is the right instrument for.
- **RealClearPolitics / RealClearPolicy** — aggregate opinion and policy
  writing daily and do accept suggestions by email. A good fit for the
  argument-driven pieces.
- **Newsletter aggregators** — Substack's recommendation network reaches the
  audience most likely to subscribe rather than just read. The mentions audit
  already found fourteen newsletters citing Vital City; those relationships are
  the warm version of this.

## One structural note

Curators reward consistency more than volume. The engagement analysis found
that cutting the newsletter from 34 sends a quarter to 16 improved every
measure. The same logic applies here: a predictable publication rhythm is
easier for an aggregator to slot into than an irregular one.
