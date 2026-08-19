# Handoff — 2026-08-19 · Vital City Live (the real-time-ish growth PWA)

**URL:** https://vitalcity-nyc.github.io/vital-city-catalogue/growth/live/ — same passphrase as the suite. Linked from the growth dashboard masthead ("● Live"). Installable (Add to Home Screen on iPhone; install prompt in Chrome).

## What it is
A companion to the growth dashboard organized by time horizon, not by topic:
- **Now** — people on the site this minute (GA4 realtime) with a 30-minute sparkline; pages being read right now; today so far vs the same weekday last week **through the last hour GA4 has processed** (see gotcha 1); signups today (Ghost), list size (Mailchimp), gifts today (Donorbox), press mentions 48h; latest post, latest newsletter send, latest press.
- **Week** — visitors/views last 7 **complete** days vs the 7 before (today is partial, so it is excluded from the tiles and shown in orange on the chart); signups by day (Ghost) with Mailchimp unsubs as ghost bars; everything published this week with its views; most read this week; gifts, members, Bluesky/LinkedIn deltas.
- **28 days** — daily visitors with 7-day average; signups/unsubs/net; Ghost members by day; gifts by day; most read 28d; then **the long view** from the deep dashboard data (weekly visitors for a year, list size for two years, signups by month, visitors by year).
- **Deeper** — cards into every section of growth/index.html (each with a one-line figure from the deep data) and the rest of the suite.

## How it works
- `live_pull.py` → `private/live.json` (~25 cheap API calls: GA4 realtime + today + 28d + per-slug 7d views; Ghost members/posts; Mailchimp list/unsubs/last campaign; Donorbox 28d; Bluesky/LinkedIn + `data/social_history.json`; Google News RSS). Every source wrapped → `{available:false, reason}`; fails loud only if ALL six fail.
- `encrypt_live.py [out]` → AES-GCM with the suite passphrase.
- `.github/workflows/live-refresh.yml` — every 20 min 6am–midnight ET, hourly overnight, plus `workflow_dispatch`. Force-pushes ONE commit to the orphan **`live` branch** (live.enc + README). main and Pages never see it. `concurrency: cancel-in-progress: true`.
- App reads `https://raw.githubusercontent.com/vitalcity-nyc/vital-city-catalogue/live/live.enc` (CORS `*`, `max-age=300`) and `../data.enc` (deep, same origin). Re-fetches every 5 min and on tab focus. `?live=<url>` overrides the feed for local testing (`python3 live_pull.py && python3 encrypt_live.py growth/live/live.enc`, then serve the repo root; `growth/live/live.enc` is gitignored).
- Service worker `growth/live/sw.js`: shell cache-first, data network-first with cache fallback → opens offline on the last snapshot, masthead dot goes gold >35 min, red >90 min. Bump `VERSION` in sw.js when the shell changes materially.
- GA4 creds exist ONLY as repo secrets (`GA4_PROPERTY_ID`, `GA4_CREDS_JSON`); locally the site block is a stub. Test GA4 changes by dispatching the workflow and decrypting the published blob.

## Gotchas learned building it
1. **GA4 standard reports trail the clock by hours** (at 11:47am, today's hourly data ran through ~7am) while the realtime report is current. The puller records `today.processed_through_hour`; the app compares today vs last week through THAT hour and labels it "(GA4 lag)". Never compare a lagging today to a full last-week day.
2. **Mailchimp daily opt-ins bunch on Thursdays** because the Ghost→Mailchimp sync runs Thursdays. Ghost `members created_at` is the true daily signup flow; the app uses Ghost for signups and Mailchimp only for the list total and unsubscribes.
3. **Two visitor instruments**: the app is GA4; the dashboard's 30-day tile is Ghost analytics (Tinybird), which runs ~25% higher. Both are labelled; the Deeper tab says so explicitly.
4. Mailchimp's "last campaign" must skip `[TEST]` sends and tiny-segment sends (the district crime emails go to 1–4 people); A/B tests keep subjects in `variate_settings.subject_lines`.
5. Google News indexes vitalcitynyc.org itself — self-mentions are filtered out of "press".
6. Realtime `unifiedScreenName` reports the homepage as "Vital City"; the app relabels it "Homepage" and strips the "Vital City | " title prefix.
7. Hub pages with single-segment paths (e.g. /charts-data-stories/) can slip through the article filter in "most read"; harmless, tighten `ARTICLE_SKIP` in live_pull.py if it bothers anyone.

## Not done / ideas
- No push notifications (would need a push service; the app is pull-only by design).
- X/Instagram/Facebook follower counts are still manual (`update_social.py`); the app shows the latest manual reading with its date.
- Could add Search Console "today" (it lags 2–3 days, so it would not be live).
