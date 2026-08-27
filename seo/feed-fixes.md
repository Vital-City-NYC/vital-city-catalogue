# Fixes for the RSS feed, for whoever maintains the Ghost theme

Checked against the live feed on 27 August 2026.

**Context:** Vital City is applying to Apple News, and may also submit to
Flipboard, SmartNews and MSN. All of them ingest the same RSS feed and read the
channel block before anything else. The article content in the feed is in good
shape — full text, images, authors, categories, absolute URLs, no missing
GUIDs. The problems are all in the channel header, and all of them are visible
to readers in those apps.

The feed is at `https://www.vitalcitynyc.org/commentary/rss/`. Redirects from
`/rss/`, `/feed/` and `/atom.xml` now point at it and are working.

**Already fixed, 27 August:** the channel description previously read
"/ new ideas", a fragment. It now reads "Pragmatic ideas to solve cities'
hardest problems." That turned out to be the **Site description** field under
Settings → General, not a theme change — worth checking settings first for
anything below that looks similar.

---

## 1. The feed does not declare a language

There is no `<language>` element. Feed validators flag it, and aggregators use
it to route a publication to the right regional edition.

**What to do:** add `<language>en-US</language>` to the channel block.

## 2. The channel logo is a favicon

    <image><url>https://www.vitalcitynyc.org/favicon.png</url></image>

That file is **201 × 201 pixels**. It is a browser tab icon being used as the
publication logo, and no `<width>`/`<height>` are declared alongside it.

Apple News wants a proper channel logo and will render this one poorly. Even
within the RSS spec, the `<image>` element is meant to be a publication logo.

**What to do:** point `<image><url>` at a real logo asset and declare its
dimensions. Note that Apple News' own logo requirements are set in the
publisher tool during the application, not in the feed, and they change — take
the exact sizes from Apple's form. The feed's job is simply to stop advertising
a favicon.

## 3. Missing publisher metadata

Absent from the channel block: `<copyright>`, `<managingEditor>`,
`<webMaster>`. None is fatal. `<copyright>` is the one worth adding, since
aggregators surface rights information and some submission reviews look for it.

## 4. The feed carries 15 items

Fifteen is enough to be accepted, but a new aggregator only ever sees what is
in the feed at the moment it first reads it, so a longer feed gives a better
first impression and back-fills more history on day one. Ghost controls this
with the posts-per-page setting the feed inherits. **25–50 would be better.**

---

## How to check the work

    curl -sL https://www.vitalcitynyc.org/rss/ | head -40

The channel block should show a `<language>` element and an `<image><url>`
that is not `favicon.png`.

W3C's validator is the other useful check, and it is what most aggregator
support teams will point at if a submission is rejected:
https://validator.w3.org/feed/check.cgi?url=https%3A%2F%2Fwww.vitalcitynyc.org%2Frss%2F

## What is already correct — please do not change it

Worth stating so none of this gets "fixed" by accident:

- Full article text in `<content:encoded>`, not a truncated excerpt. This is
  what Apple News needs and what most feeds get wrong.
- `<dc:creator>` on every item, so bylines survive into the aggregator.
- Categories on every item.
- Images both inline in the body and as `<media:content>`.
- Absolute URLs throughout. Relative links break in every aggregator.
- Unique GUIDs on every item.
- The channel `<description>`, as of 27 August.
