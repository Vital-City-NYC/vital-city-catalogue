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

**What to do:** point `<image><url>` at the logo Ghost already holds — a
1267 × 265 PNG, set under Settings → General as the site Logo — rather than the
201 × 201 icon, and declare the dimensions. No new artwork is needed. See the
section below on custom feeds for the mechanism.

Apple News' own logo requirements are set in its publisher tool during the
application, not in the feed, and they change — take the exact sizes from
Apple's form. The feed's job is simply to stop advertising a favicon.

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

## Can Ghost's own tutorials do this without touching the theme?

Ghost publishes two relevant guides — a custom RSS feed, and a Google News
sitemap. Both are the right mechanism for everything above. **Neither is purely
a settings change**, so the short answer is: they fix all four items, but they
still need one file added to the theme.

Both work the same way, in two parts:

1. **A route**, added to `routes.yaml`. This part is self-serve — Ghost accepts
   a `routes.yaml` upload under **Settings → Labs → Routes**, no deploy needed.
2. **A template file** (`custom-rss.hbs` or similar) that produces the XML.
   This part has to live inside the theme.

So `routes.yaml` alone will not do it. The template is where `<language>`,
`<copyright>`, the logo URL and the item count are actually set.

**You do not necessarily need the original theme developers.** Ghost lets an
administrator download the active theme as a zip, and upload a modified one,
entirely through the admin interface: **Settings → Design → Theme → Download**,
then re-upload the edited zip. If you download it, the template can be written
for you and dropped in — no development environment required.

### What a custom feed would fix

| Item above | Fixed by a custom feed? |
|---|---|
| 1. Missing `<language>` | Yes — one line in the template |
| 2. Favicon as logo | Yes — and see below, the right image already exists |
| 3. Missing `<copyright>` | Yes — one line |
| 4. Only 15 items | Yes — the template sets its own limit |

### The logo is already in Ghost

Worth knowing before anyone commissions artwork. Ghost holds two images:

- **Logo — 1267 × 265 PNG.** A proper wordmark. This is the one the feed should use.
- **Icon — 201 × 201 PNG.** The browser tab favicon.

The feed currently publishes the icon. That is Ghost's default behaviour for
RSS, not an error in the theme — Ghost's built-in feed uses the site icon. A
custom feed template can point at the logo instead, which is why item 2 needs
no new asset.

### One caution about the route

The feed is currently at `/commentary/rss/`, and that URL is what the site
declares in its `<head>` and what the `/rss/` redirect points to. If a custom
feed is published at a *new* path, three things must move together: the route,
the `<link rel="alternate">` tag in the theme, and the redirects. Simplest is
to have the custom template serve the existing path rather than introduce a
second feed — two live feeds is how aggregators end up subscribed to the wrong
one.

### The Google News sitemap

Separate from all of the above and worth doing only if you are pursuing Google
News specifically. Ghost already publishes a complete standard sitemap (898
article URLs, correct and current), which is what ordinary Google indexing
uses. A Google News sitemap is a different, narrower file covering only the
last 48 hours of articles. It is not a prerequisite for being indexed, and it
is the lowest-priority item on this page.

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
