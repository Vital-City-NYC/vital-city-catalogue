# Session handoff — 2026-08-04

Companion to `HANDOFF.md` (the standing maintainer's guide — read that first for repo
layout, secrets, accounts and the refresh workflow). This file covers **one unfinished
feature** and **the gotchas discovered in this session**, several of which cost multiple
20-minute CI cycles to find and would be expensive to rediscover.

---

## 1. UNFINISHED — the live request

**Josh's ask, verbatim:** *"can you build in the ability for any user of the growth dashboard
to get a detailed narrative analysis like the one you just produced, using all the data feeds
that are available? I don't want only my claude code to be the source of such insight."*

Context: I had just produced a long written audience-growth analysis (see §2 for the
artifacts). Josh wants that capability **inside the dashboard**, available to any user with
the passphrase — not dependent on a Claude Code session.

### Recommended approach: a deterministic narrative engine in the page

**Do NOT reach for an LLM API call.** Reasons, in order of weight:

1. The dashboard is a **static client-side page**. An API key in it would be exposed to
   anyone with the passphrase. A Cloudflare Worker proxy would be needed (the
   `nyc-foil-helper` project has that pattern) — real added infrastructure.
2. Josh's standing rule: flag every non-Claude-Code dollar. Per-view API cost is a recurring
   charge on an internal tool.
3. **The analysis is mostly deterministic anyway.** Reviewing what I actually did to write
   that report: compute pace, compare rolling windows, rank pieces, detect anomalies, attach
   caveats. That is encodable and gives the *same* answer from the same data — which matters
   for a data product (see `feedback_no_black_boxes`).

Honest limitation to state on the card: a rule engine surfaces only the patterns it is taught
to look for. It will not spot a genuinely novel pattern the way a human or an LLM might. Say
so plainly in the UI rather than implying open-ended intelligence.

### Design spec

Add `renderNarrative(data)` to `growth/index.html`, rendering into a new card placed
**immediately after the `#kpis` grid** (it is the executive summary of everything below).
Add it to the `#jumpNav` list too (see §3.7 for the ordering trap).

Compose from independent analyzer functions, each returning
`{title, paragraphs[], confidence, caveats[]}`. Sections to implement:

| Section | Computation | Source fields |
|---|---|---|
| Headline | Direction of reach + list + conversion, thresholded | all below |
| Reach | YTD users ÷ day-of-year × 365 vs prior full year | `ga4.by_year.years[]` |
| Step change | Rolling 6-week mean vs prior 6 weeks; report max ratio if > ~1.35 | `ga4.traffic_weekly[]` |
| → attribution | Pieces with `pub` within ~[-3, +9] days of the step week, top by views | `ga4.piece_index.pieces[]` |
| Topic concentration | Token frequency across top-10 titles; report any token in ≥3 | `ga4.top_pages_by_year[yr]` |
| Search | clicks/day, impressions/day, position, CTR across the 3 windows | `search_console.windows[28\|90\|365].totals` |
| Newsletter | list size, peak + current, organic signups, best month | `mailchimp.monthly_signups[]`, `signup_windows` |
| Anomaly detect | Month > ~2.5× trailing median → flag possible contamination; group runs | `monthly_signups[].new_signups` |
| Cleanup detect | implied removals = `new_signups − (cum[i] − cum[i-1])`; > ~3× median → cleanup | `monthly_signups[].cum_subs` |
| Engagement | totals (rate × recipients) **and** rates, YoY | `mailchimp.windows.ytd / .prior_ytd` |
| Conversion | visitors → `signup_windows.ytd_ghost` | `ga4`, `mailchimp` |
| Attribution mix | share by medium | `ghost_signup_attribution.by_medium` |
| Recommendations | Derived from which findings fired, ranked | — |
| Confidence + limits | **Auto-attach** based on what is actually present | see §3 |

**Critical:** make the logic *general*, not hardcoded to today's story. The anomaly and
cleanup detectors above are written as thresholds precisely so that when the bot surge ages
out of the window the narrative stops mentioning it, and if a new anomaly appears it gets
caught. Do not hardcode "bots" or "June 22" or "Mamdani" — derive them.

**Auto-caveats.** The engine should detect missing/degraded feeds and say so, e.g.
`mailchimp.mau.active_users === 0` → state that the 30-day active measure is unavailable and
why (§3.1), rather than silently reporting zero. Same for `date_suspect` pieces, the ~180-day
attribution window, and the 54%-unknown attribution share.

**Export.** Reuse the existing helpers already in the file: `lookupExportBar(id)` and
`bindLookupExport(barId, build)` — they give Print/PDF, .csv, .md and copy-as-text for free.
The Custom reports card uses them.

**Reference implementation of the prose itself:** `make_audience_report.py` in this repo
contains the full narrative I wrote by hand, with the exact framing, caveats and confidence
language Josh accepted. Use it as the copy model.

---

## 2. Artifacts from this session (context for the above)

| File | What |
|---|---|
| `make_audience_report.py` | Generates the markdown audience report → Desktop. Reads `/tmp/rep.json`. |
| `report_charts.py` | Six matplotlib charts in the Vital City palette → `/tmp/vc_report_assets/` |
| `build_report_docx.js` | Word version (Josh's preferred format — pastes badly into Google Docs otherwise; upload the .docx to Drive instead) |
| `analyze_catalogue.py` + `catalogue-analysis/` | "The catalogue, analyzed" — charts of all 870 pieces |

To regenerate `/tmp/rep.json`: decrypt `growth/data.enc` with the passphrase (pattern is in
any of the scripts above).

---

## 3. Gotchas discovered this session — READ BEFORE DEBUGGING

### 3.1 Mailchimp does not report per-member opens for A/B sends ⚠️ biggest one

Symptom: "Active subscribers · 30d" reads **0**. Also empties the contact tool's
"active 30d" filter (so "notable + active 30d" showed nobody despite 226 notables).

**This is not fixable in code.** Proven by direct diagnostics against a variate campaign:

| Endpoint | Returns |
|---|---|
| `/reports/{id}/open-details` | `total_items=0` — genuinely empty, no error |
| `/reports/{id}/email-activity` | 8,510 rows, **activity arrays empty** |
| `/reports/{id}/sent-to` | 8,510 rows, `open_count` present but **every value 0** |

Aggregate `open_pct` (42–45%) *is* reported. So when every send in a window is an A/B test,
the deduped-union method returns nothing. **Shipped mitigation:** the tile shows a labeled
lower bound (largest single send's unique openers) instead of 0, and the contact tool renders
an explanation pointing at "Active · last year". If Vital City sends one non-A/B newsletter a
month, the exact figure returns.

I burned ~4 CI cycles guessing at this before instrumenting. **The opener pull had a bare
`except: break` swallowing every error** — that is why it looked healthy while returning zero.
Logging is now in place; keep it.

### 3.2 Bot signups contaminated May–September 2025

Confirmed by Josh. ~**4,981 net additions above** the ~184/month organic baseline, then a
collapse back to normal in October — *before* the November general election, which is why the
"it was the mayoral race" explanation does not fit. **May 2026 removed 575** in one month
(normal is 42–108) — the cleanup.

Consequence: **any 2025-vs-2026 signup comparison is invalid** (humans vs humans + bots).
The dashboard's `signup_windows.prior_ytd` still carries the contaminated figure. Treat the
list dropping from its April 2026 peak (11,114 → 10,853) as *hygiene, not decline*.

### 3.3 GA4 slugs: match on the LAST path segment

Old Prismic URLs (`/articles/<slug>`, `/vital_signs/<slug>`) still hold years of traffic.
Matching only the flat Ghost slug **silently dropped whole pieces** — the gun-violence data
page showed 252 lifetime views when the real number is **15,622**. Fixed; ~28,000 views
recovered across 11 pieces. Every catalogue slug is multi-word hyphenated, so last-segment
matching cannot collide with `/tag/...` or `/author/...`.

Still open: data-explorer **sub-tabs** (`/<slug>/data`, `/<slug>/map`) are not rolled up into
the parent piece, so interactive pieces still undercount somewhat.

### 3.4 Migration mis-assigned some publish dates

33 pieces show **zero views in their own first 30 days despite real lifetime traffic** —
the date is wrong, not the performance. One had 76,529 lifetime views and was being scored
"under-performing". These now carry `date_suspect: true`, are excluded from bands and show
"Not scoreable". Josh said the dates are being fixed in Ghost; when they are, these self-heal.

### 3.5 GA4 daily pull needs chunked pagination

`pagePath × date` over 3.5 years returns **259,828 rows** — past the 200k cap. Pulled in
yearly chunks with offset paging. Unpaginated it truncates *silently*.

### 3.6 Piece bands rank on total impact, not opening views

Josh's explicit call. Era-fair opening-view banding was confusing (an 815-view 2023 piece
outranked a 605-view 2025 piece). Bands now use **lifetime reader-hours** on one catalogue-wide
scale (`piece_index.impact_bands`), so a bigger number always ranks higher. Opening views
remain as a labeled "Launch reach" line. Per-year context: 2023 median opening 132 vs 2026 604.

### 3.7 Assorted traps

- **`gh workflow run` can dispatch against a pre-push SHA.** Always `--ref main`, and verify
  with `gh run list --json headSha`. I shipped a "fix" that ran on the previous commit and
  reported failure.
- **Jump-nav ordering:** link order ≠ DOM order. Sort targets by `compareDocumentPosition`
  or the wrong link highlights. Sticky-bar offset must be *measured* (`--navh`), not hardcoded.
- **Preview pane sometimes reports a 0×0 viewport**, producing nonsense geometry (negative
  scroll offsets, elements "17px tall"). Force `resize_window` 1280×900 before measuring.
- **No LibreOffice / pandoc / pdftoppm on this machine.** To eyeball a .docx use
  `qlmanage -t -s 1400 -o <dir> file.docx` (page 1 only), plus structural checks via python-docx.
- **The `docx` npm module is global:** `NODE_PATH="$(npm root -g)" node build_report_docx.js`.
- **Google Docs breaks percentage table widths** — use DXA on both table `columnWidths` and
  every cell, summing to 9360 for US Letter with 1" margins.
- **Search Console query→piece coverage is only ~24 of 870 pieces.** Full coverage needs a
  Search Console pull with the **page** dimension; currently queries are matched from the
  existing query lists. This is a real, unbuilt improvement.
- Local Python is **3.9** — skill scripts using `ignore_cleanup_errors` (3.10+) fail.

---

## 4. Other open items

- **Search Console page-dimension pull** (§3.7) — would give every piece its search data.
- **Data-explorer sub-tab rollup** (§3.3).
- **GA4 has 205 event names** including `newsletter_sign_up`, `form_submit`, `link_click`.
  Only `preferred_source_click` is wired up so far. `newsletter_sign_up` could give far better
  signup attribution than the ~180-day Ghost window (54% unknown).
- **Preferred-source tracking is live** but all 4 clicks so far came from one article — either
  the other placements are not firing the event or they have not been clicked. Worth checking
  once more data accrues.
