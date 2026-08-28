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

**All four items below are Ghost's stock RSS defaults**, not errors anyone
introduced. None can be changed from the Ghost admin, and none can be fixed by
editing an existing theme file, because Ghost generates RSS in core. They are
fixed together by adding one custom feed template — see "Who can fix these" for
the mechanism and the evidence, so this can be handed over without the
recipient re-deriving it.

**Not on this list, deliberately:** the site's article schema uses
`@type: Article` rather than `NewsArticle`. That was raised and withdrawn.
Google treats Article, NewsArticle and BlogPosting as interchangeable for
article rich results, Google News eligibility does not depend on structured
data at all, and Apple News does not read JSON-LD in any case — it ingests RSS
or Apple News Format. The existing markup is complete and correct; changing it
would gain nothing.

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

**Two separate facts, easily confused:** the artwork already exists — Ghost
holds a 1267 × 265 logo under Settings → General, so nobody needs to design
anything. But *which* image the feed uses is decided inside Ghost's RSS
generator, which always reaches for the site icon. The asset being present does
not make this fixable from settings.

**What to do:** in the custom template, point `<image><url>` at the site logo
rather than the icon, and declare the dimensions.

(Replacing the *icon* with the logo would make the stock feed serve it, and is
a bad trade: Ghost's icon must be square, so a wordmark would be cropped or
rejected, and it would change the browser tab icon everywhere.) See the
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

## Who can fix these, and how — read this before assigning the work

Corrected 27 August after a second review caught an error in an earlier version
of this note.

**The feed is stock Ghost output, not a customised template.** The wire format
carries `<generator>Ghost 6.61</generator>`, an atom self-link, `<ttl>`, and
GUIDs that are Ghost ObjectIds with `isPermaLink="false"`. Stock Ghost omits
`<language>` and `<copyright>`, uses the site *icon* as the channel image, and
caps the feed at 15 items. **All four open items are Ghost's defaults**, not
mistakes anyone made.

What *is* customised is the feed's path. `/commentary/rss/` comes from a
collection defined in `routes.yaml`, which is also why `/rss/` returned 404
until the redirects were added.

This matters because it changes the fix. **Ghost generates RSS in core. There
is no `rss.hbs` in a theme that can be edited to change it**, so an earlier
version of this note was wrong to say the file already exists and just needs
four small edits.

### The actual fix: one piece of work, not four

Ghost's own tutorial for a [custom RSS feed](https://ghost.org/tutorials/custom-rss-feed/)
is the supported route, and it has two parts:

1. **A route in `routes.yaml`** naming a template and an XML content type.
   Uploadable from **Settings → Labs → Routes** with no deploy.
2. **A new template file** in the theme that emits the XML.

The template is where `<language>`, `<copyright>`, the logo URL and the item
count all get set — so **items 1 through 4 are a single change, not four
separate requests**. Whoever does it writes one file.

**It does require theme access.** But it is a documented, self-contained
addition — a new template file, no redesign, nothing existing modified. It is
not a proxy, an edge worker, or a rebuild of the feed pipeline.

**The path is the risky part — test it before pointing the live URL at it.**

`/commentary/rss/` is currently produced *automatically* by the commentary
collection, not by a route. A custom route would want to own the same URL, so
the two collide. Ghost matches routes before collections, so the route should
win, but this is the part to prove rather than assume, because **both failure
modes are silent**:

- The stock feed keeps being served and the new template looks like it did
  nothing.
- Or the path 404s and **every existing subscriber breaks at once**.

Ghost collections are reported to take an `rss: false` flag that switches off
the built-in feed, which exists precisely for this collision. I could not
confirm that flag in the routing documentation I was able to read, so treat it
as a lead to check rather than a settled answer.

**Build it on a throwaway path first** — `/feed-test/rss/` — confirm the output,
and only then move it onto `/commentary/rss/`. The site's `<head>` link and the
`/rss/`, `/feed/` and `/atom.xml` redirects all point at that path, so it is the
one URL that must not break.

**Two notes for whoever writes the template:**

- **The 15-item cap is fixed in this same file.** It is a property of Ghost's
  default feed, not a site setting, so a custom template simply chooses the
  number — the route's limit, or `{{#get "posts" limit="50"}}` in the template.
  Item 4 is a number in the file you are already adding, not a separate problem.
- **Escaping is the likely regression.** A custom feed is hand-written markup,
  so wrap post content in CDATA and validate the output. Escaping bugs produce a
  feed that parses for some readers and not others, which is far harder to
  notice than a feed that fails outright.

### The logo needs no new artwork

Ghost already holds both images: a **1267 × 265 logo** and a **201 × 201 icon**.
Stock RSS uses the icon. The custom template should point at the logo.

### Tested and ruled out, 27 August — please do not retry

The `/commentary/` collection was given `limit: 30` in `routes.yaml` and the
change was uploaded and confirmed live. **The feed stayed at 15 items.** Ghost's
feed generator ignores the collection's limit; that setting governs page size
on the site only. The routes file was rolled back afterwards and the live
configuration is unchanged.

That was the last admin-side possibility for the item count. It is recorded here
so the theme team can see the settings options were exhausted rather than
skipped.

### Nothing here is fixable from the Ghost admin

Each was checked against live settings. Publication language is already set to
`en` and stock Ghost's RSS does not emit it; copyright is not a Ghost setting;
this Ghost version exposes no posts-per-page control; and the channel image is
chosen by Ghost's RSS generator. The site description was fixable that way, but
it was the exception.

## Priority, if only some of this gets done

1. **Item 4, the 15-item cap.** The one that genuinely limits what a new
   aggregator sees when it first reads the feed.
2. **Item 1, `<language>`.** One line, and feed validators flag its absence.
3. **Item 3, `<copyright>`.** One line.
4. **Item 2, the channel logo.** Lowest. Every *item* already carries a real
   Ghost-hosted image in `media:content` plus full text in `content:encoded`,
   which is what aggregators actually key off. The channel favicon is cosmetic
   next to that.

Since all four come from the same template, doing one means doing all four.

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
