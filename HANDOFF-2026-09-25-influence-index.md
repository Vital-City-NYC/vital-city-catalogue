# Influence index: handoff (Sept. 25, 2026)

Josh asked for a metric of Vital City's prominence and influence in New York City policy, tracked
over time, with full methodology, then asked for animated charts that "look really good." He wants
to SEE it before deciding whether it moves into the growth dashboard. Do not merge it into growth/
until he says so.

## The design (settled)
Five measures, each counted identically for Vital City and 11 peers (CBC, Center for an Urban
Future, Community Service Society, Fiscal Policy Institute, Furman Center, RPA, City Journal, Gotham
Gazette, City Limits, Center for Justice Innovation, Data Collaborative for Justice), by calendar year
2022 to date. Ratio = (VC+1)/(peer median+1); index = weighted geometric mean.
Weights: press .30, official record .25, scholarship .20, web standing .15, Wikipedia .10.
Government newsletter readers = companion measure, not in the index.
Full method is in the page (methodBuild() in influence/index.html). influence/methodology.md is
NOT written yet: copy that text into it.

## Files (all in this repo, none committed yet)
- influence_pull.py: collectors. Raw store = private/influence_raw.json (per-section saves, locked).
- influence_build.py: scoring -> private/influence.json.
- encrypt_influence.py: -> influence/data.enc + influence/raw.enc; `unpack` reverses (for CI).
- influence/index.html: the gated page (hero, race, five measures, evidence lanes, readers, robustness, method).
- private/influence_backfill/: Scholar counts (scholar_2026-09-25.json), 18 Common Crawl TSVs, press_when_ready.sh.

## Data state
- DONE in raw store: readers, scholar (78 cells, taken in browser before Google flagged the network),
  webgraph (18 releases), courts (CourtListener; counted per case per year).
- Wikipedia: was running into a SIDE FILE private/influence_raw_wiki.json (to avoid a clobber).
  When done, merge: load both JSONs, copy side["wiki"] into main, save. If it died, rerun
  `INFLUENCE_RAW=private/influence_raw_wiki.json python3 influence_pull.py wiki` (resumes from rev_cache).
- Press + record: NOT collected. Google News returned 503 to this Mac after the first run (which
  reached 95% and lost its results; collector is now incremental and resumable). Run:
  `python3 influence_pull.py press --years 2022-2026` then `record`, then `verify-press`, `verify-record`.
  If the Mac is still blocked, run them in GitHub Actions (different IP) via a workflow.
- Google Scholar is blocked from this network for now (sorry page). Scholar counts are already saved.

## Remaining steps
1. Finish press/record + verification; merge wiki; `python3 influence_build.py`.
2. Spot-check by hand: 5 confirmed press items, the court cases, 3 Wikipedia adds.
3. Optionally `python3 influence_pull.py wiki-first-adds vc` (who added each VC link, for the evidence list).
4. Add to toolkit.js TOOLS: {id:"influence", label:"Influence", path:"influence/", gated:true,
   data:"influence/data.enc", blurb:"..."}.
5. Write influence/methodology.md; add .github/workflows/influence-refresh.yml (weekly: unpack,
   press/record current year, verify, courts, wiki, webgraph-new, readers, build, encrypt, commit
   influence/data.enc + influence/raw.enc). Scholar = quarterly by hand in a browser.
6. `python3 encrypt_influence.py`; test the page in the browser pane (inject data; see catalogue
   memory for the test recipe); check 375px width and dark mode; node --check the inline script.
7. Push as vitalcity-nyc (confirm account first; repo is under vitalcity-nyc user, Pages at
   vitalcity-nyc.github.io/vital-city-catalogue/influence/). Poll the live URL.
8. Show Josh the live page; ask whether to fold it into growth/.

## Status at end of first session (Sept. 25, 2026, ~6:15 p.m.)
- Page renders and animates (hero, race, measure cards checked in the browser pane). Preview with
  plaintext data: influence/preview.html (git-ignored; NEVER commit). Serve with the `vc-toolkit`
  entry in ~/Experiments/.claude/launch.json (port 8847) -> http://localhost:8847/influence/preview.html
  Rebuild the preview after any build: run influence_build.py (add --allow-missing while press is
  absent), then re-inject private/influence.json (see the python one-liner pattern: replace the first
  '<script>\n"use strict";' with a script setting window.__INFLUENCE_DATA__).
- Preview numbers so far (press and Wikipedia missing, record = courts only): index 0.17 (2022)
  -> 0.89 (2026 to date); rank 12th -> 7th of 12.
- Two detached jobs were left running: the Wikipedia pull (side file) and
  private/influence_backfill/press_when_ready.sh (probes Google News every 2 min for 90 min, then
  runs press and record). Check private/influence_raw.json for "press"/"record" sections before rerunning.
- Known page nits: City Limits ranks 2nd on three measures only (caveat is on the page; consider
  requiring 4 of 5 measures for the league); gov-readers chart and evidence lanes not yet eyeballed.

## Update, Sept. 25, 2026, ~6:35 p.m.
- Josh: "make it a new tab, and update it when you're able to." Done: Influence tab is LIVE at
  https://vitalcity-nyc.github.io/vital-city-catalogue/influence/ (commit 67492d8), in toolkit.js
  TOOLS with staleHours 192 (home page allows a weekly tool eight days).
- Wikipedia merged (VC 0 -> 14 articles; 14 different editors, no single account) and
  first-adds stored. Published with press left out ("Not yet included" note on the page).
- Press + government pages are being collected in the cloud: workflow influence-refresh.yml,
  run 36196864424 (years 2022-2026). When it lands it commits influence/data.enc + raw.enc.
  NEXT: `git pull`, unpack raw (`python3 encrypt_influence.py unpack`), spot-check 5 confirmed
  press items and the verification audit, eyeball the page, tell Josh the new numbers.
- Weekly schedule: Mondays 13:30 UTC. Scholar is by hand, quarterly (browser; Google flagged this
  Mac on Sept. 25, so wait a while before the next Scholar pass).

## Update, ~7:50 p.m.: Josh asked to rethink the measures ("ensure these metrics make sense"),
## about NYT/major outlets, whether all references are caught, and links to our pieces.
Changes made locally (NOT yet pushed; push after the cloud press run lands and is merged):
- Six measures: major outlets .15 (14 outlets incl. 7 new national ones), New York press .15,
  official record .25 (City Hall newsroom 2022+ read in full + Comptroller WP search + CourtListener
  cases; Google-News gov pages dropped), scholarship .25, Wikipedia .10, links from policy sites .10
  (Common Crawl domain link graph: distinct gov/edu/news domains linking; replaces PageRank rank).
- Council hearings (local corpus, 2024+) shown beside the index, not in it, until backfilled to 2022.
- names_us() fixed: accepts "a/the Vital City <report|analysis|founder...>" and 's; generic-noun
  check is case-insensitive ("Protect Vital City Services" headline). Recheck press hits marked
  generic: `python3 influence_pull.py verify-press generic` (uses stored resolved_url; no Google).
- League ranks only orgs covered by >=75% of weight (City Limits unranked).
- New collectors: cityhall, comptroller, council, weblinks <release>, weblinks-new.
- Link backfill running locally: 2022-may-jun-aug, 2023-may-sep-nov, 2024-aug-sep-oct,
  2025-aug-sep-oct (+2026-jul-aug-sep done). ~16 min each.
- After the cloud run: git pull; decrypt its raw.enc to a temp file and copy ONLY its "press"
  section into the local private/influence_raw.json (local has cityhall/comptroller/council/weblinks);
  verify-press generic; spot-check NYT hits in the browser pane; build; encrypt; push; then dispatch
  the workflow again (years 2022-2026) to pull the 7 new national outlets (existing cells are skipped
  as fresh).
- Candidate measures not built, for Josh: Council backfill 2022-23 (Legistar calendar via browser),
  Bluesky shares (api.bsky.app searchPosts q=domain:<site> works without auth, 2023+ only),
  Search Console "Latest links" export for page-level links to VC pieces (manual export).
