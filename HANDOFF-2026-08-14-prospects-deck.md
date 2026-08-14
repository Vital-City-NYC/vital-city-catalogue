# Handoff — 2026-08-14 · The prospects page, the funder deck, and everything around them

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
- **Print**: `?print=1` auto-opens the dialog (the CTA's big button).
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
- **Voice**: AI-tell purge done (stacked "X, not Y" antithesis was the
  fingerprint). Kept "matched, not estimated" / "unmeasured, not zero" — load-
  bearing. Headlines de-echoed; don't reintroduce swagger ("Ideas go in...").

## 3. Hard-won integrity rules (violations already happened once each)

1. **Fail loud**: build_prospects refuses <1000 people / missing mailchimp
   totals / <100 catalogue pieces. This exists because a build against deleted
   /tmp files silently published an all-zeros page. Never pipe builder output
   through `tail -1` — the counts line IS the alarm. Verify data.enc by
   decrypting it before pushing.
2. **Press counts**: tracker rows before 2021-09 are social-profile junk
   (account-creation dates) — filtered at source. Tracker backfill 2022+ is
   real. Counts are whitelist floors (~25 outlets).
3. **Donorbox-only** on every giving figure. 2025 signups bot-inflated → 2024
   is the volume baseline. Apple MPP inflates opens → click-to-open leads.
4. Current funders are RENEWALS, never prospects (about-page is the source).
5. NYT subway pieces: nytimes.com/2025/03/14 + /2025/09/10 (nyregion) — sourced.
   Mamdani "quite taken": NY Editorial Board substack transcript. Met VC **as a
   candidate**.

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
