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

---

## 1. The publication description is broken — fix this one first

The feed currently says:

    <description>/ new ideas</description>

That is what Apple News, Flipboard and every feed reader display under the
publication name. It reads as a fragment because it is one — it looks like a
tagline that lost its first half.

**This is very likely a settings change, not a theme change.** A standard Ghost
theme emits `{{@site.description}}` here, which is the **Site description**
field in Ghost under Settings → General. If that field currently reads
"/ new ideas", editing it fixes the feed immediately and nothing needs to be
deployed. Check there first.

The agreed wording is:

    Pragmatic ideas to solve cities' hardest problems.

Note that the homepage's meta description is a different string ("New York City
News, Policy Analysis, Data & Urban Affairs"), so the two are being set in
different places. That is fine — the meta description is tuned for search
results, the feed description is what a reader sees under the publication name
in Apple News. They do not have to match, but neither should be a fragment.

If the Site description field is already correct and the feed still says
"/ new ideas", then the theme is building the string by hand and it is a theme
change after all.

## 2. The feed does not declare a language

There is no `<language>` element. Feed validators flag it, and aggregators use
it to route a publication to the right regional edition.

**What to do:** add `<language>en-US</language>` to the channel block.

## 3. The channel logo is a favicon

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

## 4. Missing publisher metadata

Absent from the channel block: `<copyright>`, `<managingEditor>`,
`<webMaster>`. None is fatal. `<copyright>` is the one worth adding, since
aggregators surface rights information and some submission reviews look for it.

## 5. The feed carries 15 items

Fifteen is enough to be accepted, but a new aggregator only ever sees what is
in the feed at the moment it first reads it, so a longer feed gives a better
first impression and back-fills more history on day one. Ghost controls this
with the posts-per-page setting the feed inherits. **25–50 would be better.**

---

## How to check the work

    curl -sL https://www.vitalcitynyc.org/rss/ | head -40

The channel block should show a full sentence in `<description>`, an
`<language>` element, and an `<image><url>` that is not `favicon.png`.

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
