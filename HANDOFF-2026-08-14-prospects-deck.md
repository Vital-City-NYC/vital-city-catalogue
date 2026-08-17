# Handoff — updated 2026-08-17 · The prospects page, the funder deck (HTML + PowerPoint), social tracking, and everything around them

Continues HANDOFF-2026-08-04-session.md (reconciler design, growth-dashboard work).
Repo: vitalcity-nyc/vital-city-catalogue · push as **vitalcity-nyc** (`gh auth switch`).
Passphrase for all gated tools: in Keychain `vc-network-pass` (= `VitalCity2026!?`).

## 0. What exists now — the four-tool suite

| Tool | Path | Gate |
|---|---|---|
| Catalogue (public) | `/` | none — never link Prospects from here |
| Growth dashboard | `/growth/` | passphrase |
| Contacts | `/network/` | passphrase (has read-only detail view + edit view) |
| **Prospects** (new) | `/prospects/` | passphrase, shared localStorage key `vc_net_pass` |

All four carry the "Tools" pill nav (current tool filled). Prospects is `noindex`
and deliberately absent from the public catalogue's nav.

## 1. The prospects page (`prospects/index.html` + `build_prospects.py`)

Rebuilt nightly in network-refresh.yml AFTER growth_pull + people build.
`build_prospects.py` reads `private/people.json`, `private/growth.json`,
`data/catalogue.json`, optional `private/employer_inferences.json`; writes
`private/prospects.json` (plaintext, gitignored) + `prospects/data.enc`.

Modules: giving KPIs (ALL Donorbox-only — banner says so) · grant landscape in
four tiers (CURRENT funders per vitalcitynyc.org/about — Achelis & Bodman,
Arnold, Guggenheim, Public Welfare, Revson, Teagle, Tiger, Tow; warm doors =
readers-not-funders: Bloomberg, Robin Hood, Clark, MacArthur, FCNY; abundance
leads incl. Coefficient IN PURSUIT; journalism leads marked off-center) · **live
pipeline from the inbox** (Coefficient COGE project ~$300K+$125K, New America,
ABNY declined-but-partnership, Salam meeting, W.T. Grant cold inbound, Sahm
education-funder map unused, SocialSphere Index) · "The case for funders"
showcase (tiles/receipts/press/products, Copy/.md export) · 8 individual-prospect
tabs with CSV export (incl. Nov-'25 party: 49 RSVP'd, **36 attended never gave**)
· every card has a copy-link 🔗 and hash-URLs scroll after decrypt.

Every person row deep-links to their contact-tool profile (cyrb53 hash of email).

## 2. The deck (`prospects/deck.html`)

14 slides, Gascogne serif + black cover + real logo (`prospects/vc-logo-black.png`,
inverted white on cover — memory rule updated: logo OK for formal materials).
Live-site browser-frame on slide 2, dated not "live now". All numbers read from
`funder_facts` in data.enc — computed nightly, never typed.

- **Variants**: `?v=abundance | justice | civic` — reorder receipts, swap the ten
  byline cards, flip lead product, add a "Selected work" slide. Buttons on the
  prospects CTA. Abundance spots incl. Stephen Smith (grocery), Martha Stark
  (pied-à-terre), Gordon/Paley (civil service), housing issue (Issue 14).
  Justice incl. Renita Francois ("now NYC Deputy Mayor for Community Safety" —
  **title is Josh's word; her Ghost bio is stale**), both Rikers issues, guns.
- **Print**: `?print=1` auto-opens the dialog (the CTA's big button). Prints
  LANDSCAPE (@page letter landscape), one slide per 7.3in fixed sheet.
- **Editable PowerPoint** (`?pptx=1` / ✎ PowerPoint button / "editable
  PowerPoint" link on the prospects CTA): `exportPptx()` in deck.html builds a
  real .pptx from the DATA (not the DOM) with pptxgenjs 4.0.1, vendored at
  `prospects/vendor/pptxgen.bundle.js` (460KB, self-hosted, no CDN). Design
  system mirrors the HTML: black cover + `vc-logo-white.png` (PowerPoint can't
  apply CSS invert — the black logo was invisible on black), Georgia display,
  orange eyebrow rule, black-bordered tile strip w/ hero tile, hairline rows
  with real hyperlinks (64), gold caveats, NATIVE bar charts (series reversed —
  PPT draws first category at the bottom), byline cards. Body y is measured
  from headline height (`s._bodyY`), never fixed. Variants carry through.
  Josh's standard for this: "look as good as the HTML" and "pay attention to
  all little design details" — audit EVERY slide in PowerPoint after any
  change (open the file, page through, zoom). Known-good v5 = 13 slides, 4
  charts, 64 links, zero blanks. Local audit trick that works: capture the
  blob in-page (monkeypatch writeFile → write({outputType:"blob"})), POST it
  to a throwaway 127.0.0.1 receiver, open in PowerPoint. PowerPoint's
  AppleScript PNG-export and the PowerPoint MCP's get_slide_content both fail
  on this machine — screenshot instead. Browser blocks a second download of
  the same filename, which is why the receiver exists.
- **Bio descriptor parser** (build_prospects `bio_descriptor`): splits only on
  a real sentence end `(?<=[a-z\)])\.\s+(?=[A-Z])` — the old ". " split
  turned Jens Ludwig into "Edwin A" (named chair). Watch for this class of bug.
- **Email**: `?email=1` / ✉ button → downloads a self-contained ungated copy
  (funder_facts + topline ONLY — verified no contact data) + opens mailto draft.
- **Long view**: visitors (GA4 `by_year`, starts 2023 — "unmeasured, not zero"),
  list at year end, pieces/year. 2021 dropped everywhere (launch stub).
- **Mentions per year**: from Josh's hand-kept archive docx (parsed Aug 14:
  2022:6 / 2023:14 / 2024:57 / 2025:133 / 2026:82-through-Jun-22), constants
  `MENTIONS_ARCHIVE` in build_prospects.py. NEVER merged with the tracker
  series; shown side by side. Re-parse when Josh updates the doc (or move to
  bundled CSV).
- **Charts**: fixed-track bars only — flex/inline layouts distorted lengths
  twice; verify with the pixel-vs-value measurement, target 0.0%.
- **Voice**: AI-tell purge done against Wikipedia's "Signs of AI writing" —
  the fingerprint was stacked "X, not Y" antithesis (7 in one deck), eight
  phrase-level cuts only. Kept "matched, not estimated" / "unmeasured, not
  zero" — load-bearing methodology, not decoration. Josh's rule: don't rewrite
  every sentence; just nothing that reads embarrassingly AI (think Pangram).
  Headlines since: media slide = "intelligent, honest analysis" (not "the
  numbers"); moment slide = "guide it toward what the evidence supports";
  impact = "Where the work has moved policy" (killed "Ideas go in. Policy comes
  out." as too swaggery); bylines = "The people who shape the debate". Echo
  scan across all 14 headlines: only "year over year over year" repeats, by
  design. Cover h1 has &nbsp; glue + 18ch measure so "on." never orphans.
- **Eyebrow rules** size to their own word (fit-content + 100% ::after); the
  pull quote has no bar. Josh dislikes extra rule lines — don't add any back.

## 3. Hard-won integrity rules (violations already happened once each)

1. **Fail loud**: build_prospects refuses <1000 people / missing mailchimp
   totals / <100 catalogue pieces. This exists because a build against deleted
   /tmp files silently published an all-zeros page. Never pipe builder output
   through `tail -1` — the counts line IS the alarm. Verify data.enc by
   decrypting it before pushing.
2. **Press counts**: tracker rows before 2021-09 are social-profile junk
   (Instagram/LinkedIn PROFILE pages leaking account-creation dates as
   publication dates; it made the tile read "since 2015-11") — filtered at
   source in build_prospects. 407 -> 395, "since 2022-01". Tracker backfill
   2022+ is real (7/9/59 vs Josh's manual archive 6/14/57). Counts are
   whitelist floors (~25 outlets).
3. **Donorbox-only** on every giving figure. 2025 signups bot-inflated → 2024
   is the volume baseline. Apple MPP inflates opens → click-to-open leads.
4. Current funders are RENEWALS, never prospects (about-page is the source).
5. NYT subway pieces: nytimes.com/2025/03/14 + /2025/09/10 (nyregion) — sourced.
   Mamdani "quite taken": NY Editorial Board substack transcript. Met VC **as a
   candidate**.

## 3b. Social follower tracking (built Aug 14)

The problem was never fetching a number — nothing KEPT A SERIES (LinkedIn's
baseline had to be recovered from git). Now:

- `data/social_history.json` — one observation per platform per day, committed
  forever. Seeded with all recoverable points; today's fresh reads: X 4,484 ·
  LinkedIn 3,362 · Bluesky 1,726 · Instagram 765 · Facebook 208 (first time
  tracked). Schema: `{d, p, n, src: live|manual}`.
- `growth_pull.py` appends nightly (idempotent per platform+day, non-fatal):
  **LinkedIn + Bluesky are truly automatic** (public page meta / official API).
  **X, Instagram, Facebook are login-walled to scrapers** — verified
  empirically: X syndication endpoint dead, IG no-login profile API blocked
  even from a residential IP, FB og-meta empty. Their rows come from
  MANUAL_FOLLOWERS in growth_pull.py.
- `update_social.py <platform> <count> [--asof]` — the 10-second manual
  refresh; appends history AND rewrites MANUAL_FOLLOWERS. Or: any Claude
  session can read the counts in the in-app browser (x.com/VitalCityNYC,
  instagram.com/vitalcitynyc, facebook.com/vitalcitynyc — all readable when
  navigated, not curled) and run it.
- Growth page social card gained "The running record": count, delta over the
  full span, compounded %/mo (needs 21+ days of history), freshness flag —
  manual rows show age and turn RED past 35 days. That red is the prompt.
- First rates: LinkedIn ~4.5%/mo, IG ~7.8%/mo (tiny base), X ~2.3%/mo, Bluesky
  ~0.7%/mo.
- Only true-automation path for X: Basic API tier (~$200/mo) — flagged to Josh
  as a cost decision, not recommended either way.

## 3c. Aug 17 fixes worth knowing

- "John ARNOLD" reappeared on the prospects page: the shared-edit override IS
  applied by the nightly people build (live network/data.enc reads correctly);
  the stale name was only in prospects/data.enc from an ad-hoc LOCAL build
  against an old people.json copy. Rule: any local build_prospects run MUST
  refetch live people/growth first, then decrypt-verify data.enc before push.
  Second time a local blob carried bad data to prod (first: all-zeros). A
  staleness guard (refuse if people source older than live blob) was proposed
  to Josh, not yet built.
- Print/email/pptx flows all read the same variant param; email export is a
  self-contained HTML (verified no contact data); pptx is the editable one.

## 4. Coordination

A parallel session ("Live healthy map URLs", uds:/tmp/cc-socks/94786.sock) built
deck.html originally; I rewrote it (v2 data contract) with notice sent. If it
resurfaces: funder_facts is v2 {tiles,receipts,press,products,engagement,
audience,longview,seniors,variants}; its deck work must rebase on main.

## 5. Open threads

- **Reconciler** (Ghost↔Mailchimp): built, tested, OFF. Wednesday-noon preview
  workflow exists; needs SLACK_BOT_TOKEN + SLACK_DM_TO secrets, and human
  approval before RECONCILE_ALLOW_WRITES ever gets set.
- **Senior contributors program**: 34 confirmed yes (docx formatting = answers:
  yellow+underline). UNANNOUNCED — deck says "deeper bench", never the label.
- **W.T. Grant**: inbound Mar 2025, gone cold — flagged for revival.
- **Sahm education-funder map**: sitting in email, no pitch attached.
- **Social manual snapshots**: X/IG/FB rows go red on the growth page after
  35 days — refresh via browser read + update_social.py (see 3b).
- **Weekly report**: Thursdays noon (launchd com.vitalcity.weekly-report),
  writes to Desktop; past reports live in Trash — Josh discards after reading.
- **Search Console upgrades** shipped (query+page attribution, trend column,
  Discover/News channels card); Keyword Planner discussed, not built (bucketed
  ranges without ad spend — flagged as a cost decision).
- Catalogue now records embeds + photo credits (532 Flourish charts, 463
  photographers filterable); chart pills open link popovers.

## 6. Memory files current as of today

`project_vc_fundraising.md` (positioning, funders, party, pipeline),
`feedback_vc_wordmark_not_logo.md` (logo exception). Trust these.
