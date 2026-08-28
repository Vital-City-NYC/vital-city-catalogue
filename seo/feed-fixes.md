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
hardest problems." That one was a Ghost settings field.

**Everything below needs the theme.** Each item was checked against the site's
settings first; none of the four can be changed from the Ghost admin. The
evidence is in the section at the end, so this can be handed over without the
recipient re-checking.

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

## What can be fixed without the theme, and what cannot

Checked directly against the site's settings on 27 August. **None of the four
items above can be fixed from the Ghost admin.** The evidence, so nobody has to
re-litigate it:

| Item | Settings-fixable? | Why |
|---|---|---|
| 1. `<language>` | **No** | Ghost's publication language is already set to `en`. The feed still omits the element, which means the feed template is ignoring it. |
| 2. Favicon as logo | **No** | Ghost holds a correct 1267 × 265 logo *and* a 201 × 201 icon. The feed publishes the icon. Which one it uses is decided in the template. |
| 3. `<copyright>` | **No** | Not a Ghost setting at all. |
| 4. Item count | **No** | This Ghost version exposes no posts-per-page setting to change. |

The site description was fixable that way, which is why it is worth checking
first — but it was the exception, not the pattern.

### What this tells us about the feed

The publication language is set correctly and the feed still does not declare
it. Ghost's built-in feed emits `<language>` from that setting automatically.
So **this feed is already a custom template**, not Ghost's default — someone
has written it, and it omits language, copyright and the logo.

That is good news for the work: the file to change already exists in the theme.
Nobody has to add a new route or a new feed. The four fixes are edits to a file
that is already there.

### Ghost's own tutorials

The custom RSS and Google News sitemap guides are the right mechanism, and both
are two-part: a `routes.yaml` entry, which an administrator *can* upload under
**Settings → Labs → Routes**, and a template file that must sit in the theme.
`routes.yaml` alone changes none of the four items — the template is where all
of them are set. Given the feed is already custom, the route almost certainly
exists too, so only the template needs touching.

### One thing that is admin-editable, and worth knowing

**Settings → Code injection** takes arbitrary markup into every page's `<head>`
without any theme access. It currently holds 921 characters and no structured
data. That will not help this feed — code injection cannot reach RSS — but it
is the lever for a separate item raised elsewhere: articles identify themselves
to Google as generic `Article` where Google News prefers `NewsArticle`. That
one can be addressed from the admin, and it is worth doing while the theme
question is unresolved.

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
