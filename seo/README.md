# Search indexing: what was wrong, and the fix

Audited 2026-08-27 against the live site.

## The problem

Vital City used to publish articles at `/articles/<slug>/`. It now publishes at
`/<slug>/`. **The old URLs were never redirected — they return 404.**

160 distinct old URLs are affected, carrying **352,512 views** in the Google
Analytics record. Every link to them from another site, every Google result
still pointing at the old shape, and every saved bookmark lands on an error
page. The ranking authority those pages accumulated is not passed to the new
URLs, because nothing tells Google the two are the same piece.

157 of the 160 kept the same slug, so one rule handles them. Three also changed
slug — two were typos that got fixed (`zohhran`, `madani`) and one was a real
rename — so they are listed individually.

## The fix

`redirects.json` in this folder. In Ghost: **Settings → Labs → Redirects →
Upload redirects JSON**. It takes effect immediately, no rebuild.

Order matters. Ghost applies rules top to bottom, so the three specific
renames come first; otherwise the wildcard would forward them to a slug that
does not exist and they would still 404.

All rules are `"permanent": true` (a 301), which is what passes the old page's
standing to the new URL. A temporary redirect would not.

### Verifying after upload

    curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}\n' \
      https://www.vitalcitynyc.org/articles/twenty-strategies-for-reducing-crime-in-cities/

Expect `301` and the same slug without the `/articles/` prefix. Then re-run
`python3 seo/check_redirects.py` to test all 160 at once.

## What was already fine

Checked and needing no action:

- **Sitemap** — present, listed in robots.txt, and complete: 898 article URLs
  against 897 catalogue pieces, plus pages, authors and tags. Ghost regenerates
  it on publish.
- **robots.txt** — sensible. Blocks only admin, email and internal endpoints.
- **Hostnames** — `vitalcitynyc.org` redirects to `www.`, so there is no
  duplicate-content split.
- **Tag and author pages** — resolve correctly. Author slugs are surname-first
  (`/author/glazer-elizabeth/`), which is why guessing `elizabeth-glazer`
  returns 404; that is not a fault.

## Worth considering later

- **498 author pages for 897 articles.** Most contributors have one or two
  pieces, so most author pages are thin. Not harmful, but they are a large
  share of what Google crawls.
- **A/B test the biggest evergreen page.** "20 Strategies for Reducing Crime in
  Cities" is the single most-read piece in the entire record — 74,928 views on
  its old URL alone. It is worth making sure the new URL is the one being
  linked and shared.
