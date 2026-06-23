# Vital City — Growth Dashboard & Contact Tool · Maintainer's Guide

Two internal tools, published as **static, client-side-encrypted** pages on GitHub Pages.
The data is encrypted in the browser with a shared passphrase, so the files can live in a
**public** repo and still be safe.

- **Growth dashboard** — `/growth/` — newsletter, donor, traffic, search, engagement and "who's reading" metrics.
- **Contact master search** — `/network/` — searchable database of everyone in Vital City's orbit.
- **Public content catalogue** — `/` (repo root) — the only *un*-encrypted page: every published article, searchable.

> ⚠️ The repo is **public**. Never commit the passphrase, a service-account key, a PAT or any
> API secret. All secrets live in **GitHub Actions secrets** (shared out-of-band). The *only*
> plaintext data committed is `data/` (the public catalogue + a counts-only policy-reach history).

---

## 0. Ownership & handover

These tools were first built through Claude Code on a personal account, but **nothing depends on
that person or account.** Everything required to run, fix and extend both tools lives in this repo
and in **GitHub Actions** (code, the scheduled refresh, the secrets). Anyone at Vital City with
access to the `vitalcity-nyc` GitHub account (which owns the repo) and the shared secrets can fully
manage them — there is no local machine, cron job or personal credential in the critical path.

To take over: get added to the `vitalcity-nyc` GitHub account, confirm the Actions secrets are in
place (§5), and either (a) keep driving changes through Claude Code on the repo — the lowest-friction
path — or (b) work the repo directly using this guide. Both tools' in-app "How it works" pages also
carry a maintainer summary that points back here.

---

## 1. The five golden rules

1. **Always `gh auth switch --user vitalcity-nyc` before any push or `gh` call.** The `vitalcity-nyc`
   account owns the repo and admins the org. The active account silently flips to `joshgreenman1973`
   sometimes — that account gets 403s here. Re-check with `gh api user --jq .login`.
2. **Never re-encrypt `*.enc` locally.** Only the GitHub Action encrypts, so the passphrase stays
   stable. Encrypting locally with a different/typo'd pass = a lockout. To publish a data change:
   push the *code*, then run the workflow.
3. **Front-end change → just push** (HTML/CSS/JS in `growth/index.html`, `network/index.html`, `index.html`
   deploy on push, no rebuild). **Data change → push, then run the workflow.**
4. **Both tools are PWAs / cached.** After any change, hard-refresh (**Cmd-Shift-R**) or you'll see the old version.
5. **Keep the numbers honest.** Every soft metric has a visible flag/caveat next to it (see §9). Match
   that when you add anything — and follow the Vital City voice (sentence case, no Oxford commas, straight quotes).

---

## 2. Where things live

| | |
|---|---|
| Repo (primary) | `vitalcity-nyc/vital-city-catalogue` — push as **`vitalcity-nyc`** |
| Institutional mirror | `Vital-City-NYC/vital-city-catalogue` (org) — a downstream copy, see §11 |
| Deploy | GitHub Pages, built from `main` on every push |
| Live — dashboard | https://vitalcity-nyc.github.io/vital-city-catalogue/growth/ |
| Live — contacts | https://vitalcity-nyc.github.io/vital-city-catalogue/network/ |
| Live — catalogue | https://vitalcity-nyc.github.io/vital-city-catalogue/ |
| "How it works" pages | `growth/about.html`, `network/about.html` (keep these in sync when you change a tool) |
| Passphrase | shared out-of-band; also the `VC_NETWORK_PASS` secret. One passphrase covers both tools; a device stays unlocked ~90 days. |

---

## 3. How it refreshes

One workflow rebuilds everything: **`.github/workflows/network-refresh.yml`**.

- Runs **twice daily, 11:00 and 23:00 UTC (≈ 7am and 7pm ET)**, plus manual `workflow_dispatch`.
  The second run is resilience — GitHub's scheduler often delays or skips cron jobs.
- Steps: unpack the encrypted source bundle → pull live data (Ghost, Mailchimp, Donorbox, GA4, Search
  Console, social, press) → rebuild `private/people.json` + `private/growth.json` → `sanity_check.py`
  gate (aborts if the dataset looks gutted) → **encrypt** to `network/data.enc` + `growth/data.enc` →
  commit & push (auto-deploys Pages) → mirror to the org (§11).
- Trigger by hand: `gh workflow run network-refresh.yml`. Watch: `gh run watch <id> --exit-status`.
- A second workflow, **`.github/workflows/mirror-all.yml`**, mirrors all public repos to the org (§11).

---

## 4. Pipeline scripts

| Script | Produces | Notes |
|---|---|---|
| `build_network.py` | `private/people.json` | Fuses Ghost members + CRM xlsx + Donorbox + author roster + Wikipedia flags + saved edits. Email-domain → affiliation inference (`INST_DOMAINS`, registrable-suffix match, `WEBMAIL` blanklist, `refresh_stale_inst`). Also sets each author's latest-piece date (`alast`) from the catalogue. |
| `growth_pull.py` | `private/growth.json` | Mailchimp, Ghost analytics, Donorbox, **GA4** (traffic, engagement, returning-vs-new, per-year + all-time leaderboards), **Search Console**, social, press/mentions. Slowest step (scrapes ~25 news outlets + social). `MANUAL_FOLLOWERS` holds the hand-entered X/IG counts. |
| `scrape.py` | `data/catalogue.json` | Re-scrapes the article catalogue from the Ghost Content API. |
| `encrypt_people.py` / `encrypt_growth.py` | `network/data.enc` / `growth/data.enc` | AES-256-GCM, PBKDF2-SHA256 (600k iters). Passphrase from `VC_NETWORK_PASS`. **Workflow-only.** |
| `sanity_check.py` | (gate) | Non-zero exit stops the publish before encrypt/commit. |
| `bundle_sources.py` | packs/unpacks `private_sources.enc` | The encrypted source bundle (CRM xlsx, etc.) the workflow unpacks at the start. |
| `weekly_report.py` | `~/Desktop/Vital-City-Weekly-*.md` | Local Friday report (§12). Not part of the workflow. |

**Inspect a published file** (passphrase via env, never hard-coded):
```python
import json, base64, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
b = json.load(open("growth/data.enc"))   # or network/data.enc
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                 salt=base64.b64decode(b["salt"]), iterations=b["iters"]).derive(os.environ["VC_NETWORK_PASS"].encode())
data = json.loads(AESGCM(key).decrypt(base64.b64decode(b["iv"]), base64.b64decode(b["ct"]), None))
```

---

## 5. Secrets (GitHub → repo Settings → Secrets → Actions)

| Secret | Powers |
|---|---|
| `VC_NETWORK_PASS` | Encryption/decryption passphrase |
| `GHOST_ADMIN_KEY` | Ghost members, posts, signup attribution |
| `GHOST_STAFF_KEY` | Ghost site analytics (visitors, top pages, sources, weekly trend) via Tinybird |
| `MAILCHIMP_KEY` | Signups, unsubscribes, campaigns, open/click, lifecycle, power readers |
| `DONORBOX_KEY` | Donors, gifts, YTD |
| `OVERRIDES_URL` | Google-Sheet shared-edit store for the contact tool (Apps Script GET) |
| `GA4_PROPERTY_ID` | GA4 property `360033941` |
| `GA4_CREDS_JSON` | GA4 service account `vital-city-dashboard-reader@vital-city-dashboard.iam.gserviceaccount.com` (read-only). **Search Console reuses this same key** — no separate GSC credential. |
| `MIRROR_TOKEN` *(optional)* | Enables auto-mirroring to the org (§11). Absent → mirror steps skip cleanly. |

---

## 6. Data sources & status

| Source | Powers | Status |
|---|---|---|
| Ghost (admin key) | subscribers, posts, per-piece signup attribution | live |
| Ghost (staff key) | website visitors, top pages, sources, weekly traffic trend | live |
| Mailchimp | signups/unsubs, campaigns, engagement, lifecycle, power readers | live |
| Donorbox | donors, gifts, YTD | live — **online gifts only** |
| GA4 (`360033941`) | 30-day + 1-year visitors, engaged time per piece, returning-vs-new, most-read by year + all-time, long view | live |
| Google Search Console | queries, impressions, clicks, CTR, position (28/90/365-day windows) | live — reuses the GA4 service account on `sc-domain:vitalcitynyc.org` |
| Contacts DB + catalogue | flags notable / government readers ("who's reading"); links pieces to bylines | live |
| Social — LinkedIn, Bluesky | follower counts + recent posts | live |
| Social — X, Instagram | follower counts | hand-entered (`MANUAL_FOLLOWERS`) |
| Google Trends | search-interest embed | client-side |

---

## 7. The growth dashboard — what's on it

Single file: `growth/index.html` (inline CSS + JS). Top to bottom:

- **"How to read this"** — four audience-strategy framing points (week-to-week is noise; engagement > traffic; think funnel; who reads > how many).
- **At a glance** — 9 KPI tiles (3×3): Subscribers, New signups·30d, Active subscribers·30d/·1y, Raised·YTD, Social followers, Website visitors·30d/·1y, Avg engaged time/view.
- **Last 7 days** — rolling pulse; the signups/unsubscribes/gifts counts are click-to-see-who. (The unsubscribe list comes from `recent_unsubs`, sourced from Mailchimp list members with `status=unsubscribed` so it stays current to today.)
- **Custom report — any two dates** — pick a date range (or quick chips) and get a date-sliceable summary of every indicator we hold day-by-day (newsletter signups/unsubs/opens/clicks, sends + rates, website traffic, online giving, plus who-lists), each compared to the previous equal-length period. Exports to PDF (clean print window), `.md`, `.csv` and clipboard. Pure client-side reader of the already-loaded data — no new pull. Indicators only available for fixed windows (search queries, per-piece engagement, social) are deliberately excluded and noted in-tool.
- **The long view** — whole-history (GA4 back to 2023): a growth-multiple strip, unique visitors by year, newsletter list by year-end, newsletter performance by year.
- **The funnel & who's reading** — visitor→subscriber conversion by year, returning-vs-new readers, and the policy circle (notable + government readers active in 30 days; the counts open a named-list popup).
- **Sections** (collapsible — click a header; state saved per device; "List health" starts collapsed): **Growing the list** (weekly growth chart, signup sources), **Donors & influence** (fundraising, engagement & influence), **The content engine** (per-piece performance, campaigns), **List health** (subscriber quality, lifecycle), **Reach & traffic** (website traffic, Search Console with 28/90/365 toggle, social, Reader attention by piece, Most-read pieces with a 2024/2025/2026/All-time toggle).
- **Flags** — small amber pills next to soft numbers ("noisy window", "Apple Mail–inflated", "comparative, not literal reading", "online gifts only", etc.). KPI flags use the `k.flag` field (the delta is escaped, so flag HTML must go through `k.flag`, **not** inline in the delta string).

To **add a KPI tile**: push an object to the `kpis` array (`{lbl, num, delta, flag, cls, tip}`). To **add a section card**: add `<div class="card">` markup + a `render*()` function called in the main render. Charts are inline SVG; dark-mode chart colors are remapped via `html.dark .chart [fill=...]` attribute-selector CSS.

---

## 8. The contact tool — what's on it & how edits persist

Single file: `network/index.html`.

- **Filters:** category tri-state chips (Subscribers/Donors/Authors/Other), refine chips (starred, notable, repeat donors, 2+ emails, no email, **no confirmed name**, include unsubscribed), name-quality + engagement dropdowns, search.
- **Built-in views:** **⚡ Most engaged** (subscribers ranked by engagement) and **⭐ Fundraising prospects**. Plus user-saved views (localStorage) and a "copy link to this view".
- **Sorting:** name/since/articles/engagement/donation; clicking the Authors filter defaults to **most-recent contribution** (`alast`).
- **Editing:** the edit modal (⌘-Enter saves) and the "delete entry" button write to a **Google-Sheet override store** via an Apps Script. The endpoint URL (`BACKEND_URL`) is embedded in `network/index.html` (it's not secret); a write is `POST {pass, key:<email>, override:{n:"Full Name", ...}}`. Edits show immediately for the editor and merge into everyone's view on the next refresh (the workflow GETs the store via the `OVERRIDES_URL` secret). The same store is editable as a Google Sheet, and the Sheet's "Add people" tab folds new rows in on the next refresh.
- **Confirming names at scale:** to bulk-assign confirmed names (e.g. from `firstinitial+lastname` work emails), POST overrides to the Apps Script with `{n}` set — `firstname.lastname` addresses are self-evident; ambiguous handles need a web lookup. Only write high-confidence names; keep an evidence trail.

---

## 9. Honesty rules baked in (don't break these)

- **Ghost vs GA4 count visitors differently** — never compare head-to-head; watch direction, not level.
- **Donor data = online Donorbox gifts only** — no checks, wires, FCNY gifts, events or pre-2026 giving.
- **Open rate is Apple-Mail-inflated** (auto-opens) — click rate is the honest signal.
- **All-time GA4 visitors ≈ yearly uniques summed**, not distinct humans (cookie-based).
- **Search Console "impressions" ≠ total search volume** — only times a VC page appeared.
- **Engaged time is active-tab time**, a comparative index, not literal reading.
- **7-day numbers are noisy** — the dashboard leads with longer trends for a reason.

---

## 10. Common how-tos

- **Update X / Instagram followers:** edit `MANUAL_FOLLOWERS` in `growth_pull.py`, bump `as_of`.
- **Publish a data change now:** push the code, then `gh workflow run network-refresh.yml`.
- **Edit the media-mentions whitelist:** `MENTION_OUTLETS` near the top of `growth_pull.py`.
- **Add a new contact source (CSV):** fold it into `build_network.py`'s source list.
- **See who's reading by name:** the funnel card's notable/government counts are clickable.

---

## 11. The institutional mirror (Vital-City-NYC org)

For continuity, every public `vitalcity-nyc` repo is mirrored into the **`Vital-City-NYC`** org (a
*different* account — `vitalcity-nyc` is a user and an org admin; `Vital-City-NYC` is the org).

- `mirror-all.yml` (runs 12:00 UTC + on demand): lists public `vitalcity-nyc` repos, creates the org
  mirror if missing, **full-clones** and force-pushes each. Public-only guard; skips the diverged
  `nyc-construction-timelines`.
- **Gotcha:** mirror with a **full clone, never `--depth=1`** — a shallow clone makes the remote
  reject the push ("index-pack failed").
- Actions are **disabled on the mirror repos** so they don't run doomed (secret-less) jobs.
- **Needs `MIRROR_TOKEN`** — an org-scoped PAT (repo contents + admin write). Until it's set, the
  mirror job skips; the existing mirrors are a current snapshot. Re-sync by hand anytime by pushing
  `origin/main` to the mirror, or run `mirror-all` once the token exists.
- The org's policy forces Actions tokens to read-only, so a token-free pull-based sync isn't possible.

---

## 12. The weekly Friday report (local)

`weekly_report.py` writes a Markdown 7-day summary to the **Desktop** every Friday 8am.

- **Why local:** it writes to the Desktop *and* the report holds internal numbers, so it's decrypted
  only on the Mac — never to a public URL. (GitHub Actions can't write to a Desktop anyway.)
- **How:** launchd agent `~/Library/LaunchAgents/com.vitalcity.weekly-report.plist` (Weekday 5, 08:00)
  → runs the script → fetches the published `*.enc` → decrypts with the passphrase → writes the file.
- **Passphrase:** from `$VC_NETWORK_PASS` or the macOS Keychain item **`vc-network-pass`**.
- **Contents:** 30-day trend; 7-day signups/unsubs vs prior week + 8-week avg; notable joins/departures;
  email; returning-vs-new (30-day); top search queries (28-day); fundraising (+ largest gift); top
  performers (articles + tagged issue/section pages). Names appear only in the local file.
- Manual run: `launchctl kickstart -k gui/$(id -u)/com.vitalcity.weekly-report`. Logs: `~/Library/Logs/vital-city-weekly.{out,err}`.

---

*Maintained via Claude Code. Front-end change → push; data change → push + run the workflow; never
re-encrypt locally; always push as `vitalcity-nyc`; hard-refresh to see changes; keep the flags honest.*
