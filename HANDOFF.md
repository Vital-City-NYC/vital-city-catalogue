# Vital City — Growth Dashboard & Contact Tool · Handoff

Two password-protected internal tools, published as **static, client-side-encrypted**
pages on GitHub Pages. Nothing sensitive is readable without the shared passphrase,
so they can live in a public repo.

- **Growth dashboard** — `/growth/` — newsletter, donor, traffic, social, and engagement metrics.
- **Contact master search** — `/network/` — searchable database of everyone in Vital City's orbit.

> ⚠️ This repo is **public**. Never commit the passphrase, a service-account key, or any
> API secret. All of those live in **GitHub Actions secrets** and are shared out-of-band.

---

## 1. Where things live

| | |
|---|---|
| Repo | `vitalcity-nyc/vital-city-catalogue` (push as the **`vitalcity-nyc`** GitHub account) |
| Deploy | GitHub Pages, built from `main` on every push |
| Live — dashboard | https://vitalcity-nyc.github.io/vital-city-catalogue/growth/ |
| Live — contacts | https://vitalcity-nyc.github.io/vital-city-catalogue/network/ |
| Passphrase | shared out-of-band; also stored as the `VC_NETWORK_PASS` secret. One passphrase covers both tools; a device stays unlocked ~90 days. |

Both tools are PWAs with **offline caching** — after any change, do a hard refresh
(**Cmd-Shift-R**) or you may keep seeing the cached version.

---

## 2. How it refreshes (the daily job)

Everything is rebuilt by one GitHub Actions workflow: **`.github/workflows/network-refresh.yml`**.

- Runs **daily at 11:00 UTC (7am ET)**, plus manual `workflow_dispatch`.
- Steps: decrypt the source bundle → pull live data (Ghost, Mailchimp, Donorbox, GA4, social, press)
  → rebuild `private/people.json` + `private/growth.json` → **re-encrypt** to `network/data.enc`
  + `growth/data.enc` → `sanity_check.py` gate → commit & push (auto-deploys Pages).
- Trigger by hand: `gh workflow run network-refresh.yml` (after `gh auth switch --user vitalcity-nyc`).
- Watch: `gh run watch <run-id> --exit-status`.

**Rules of the road**
- **Never re-encrypt `*.enc` locally.** Let the Action do it so the passphrase stays stable.
  To publish a data change: push the code change, then trigger the workflow.
- Front-end-only changes (HTML/CSS/JS in `growth/index.html` or `network/index.html`) deploy
  on push — **no rebuild needed**. Only changes that affect the *data* need a workflow run.
- Always `gh auth switch --user vitalcity-nyc` before pushing (the org owns the repo).

---

## 3. Pipeline scripts

| Script | Produces | Notes |
|---|---|---|
| `build_network.py` | `private/people.json` | Fuses Ghost members + CRM xlsx + Donorbox + Wikipedia flags + saved edits. Email-domain → affiliation inference lives here (`INST_DOMAINS`, registrable-suffix match, `WEBMAIL` blanklist, `refresh_stale_inst`). |
| `growth_pull.py` | `private/growth.json` | Mailchimp, Ghost analytics, Donorbox, **GA4**, social, press/mentions. Slow step — it scrapes ~25 news outlets + social. |
| `encrypt_people.py` / `encrypt_growth.py` | `network/data.enc` / `growth/data.enc` | AES-256-GCM, PBKDF2-SHA256 (600k iters). Passphrase from `VC_NETWORK_PASS`. |
| `sanity_check.py` | (gate) | Aborts the publish if the dataset looks gutted. |

**Decrypt a published file to inspect it** (passphrase via env, never hard-code it):

```python
import json, base64, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
b = json.load(open("growth/data.enc"))
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                 salt=base64.b64decode(b["salt"]), iterations=b["iters"]).derive(os.environ["VC_NETWORK_PASS"].encode())
data = json.loads(AESGCM(key).decrypt(base64.b64decode(b["iv"]), base64.b64decode(b["ct"]), None))
```

---

## 4. Secrets (GitHub → repo Settings → Secrets → Actions)

| Secret | Powers |
|---|---|
| `VC_NETWORK_PASS` | Encryption/decryption passphrase |
| `GHOST_ADMIN_KEY` | Ghost members, posts, signup attribution |
| `GHOST_STAFF_KEY` | Ghost site analytics (visitors, top pages, sources, weekly trend) via Tinybird |
| `MAILCHIMP_KEY` | Signups, unsubscribes, campaigns, open/click, lifecycle, power readers |
| `DONORBOX_KEY` | Donors, gifts, YTD |
| `OVERRIDES_URL` | Google-Sheet shared-edit store for the contact tool |
| `GA4_PROPERTY_ID` | GA4 property `360033941` |
| `GA4_CREDS_JSON` | GA4 service-account key — `vital-city-dashboard-reader@vital-city-dashboard.iam.gserviceaccount.com` (read-only Analytics Viewer) |

---

## 5. Data sources & status

| Source | Powers | Status |
|---|---|---|
| Ghost (admin key) | subscribers, posts, per-piece signup attribution | ✅ live |
| Ghost (staff key) | website visitors, top pages, traffic sources, weekly trend | ✅ live |
| Mailchimp | signups/unsubs, campaigns, engagement, lifecycle, power readers | ✅ live |
| Donorbox | donors, gifts, YTD | ✅ live — **online gifts only** (see caveats) |
| GA4 (`360033941`) | 30-day + 1-year visitors, "most-read since Jan 1", per-piece engagement time, by-year long view | ✅ live |
| Social — LinkedIn, Bluesky | follower counts + recent posts | ✅ live |
| Social — X, Instagram | follower counts | ✍️ **manual** (`MANUAL_FOLLOWERS` in `growth_pull.py`) |
| Search Console | search queries/impressions/CTR/position | ❌ **not set up** (§7) |
| Google Trends | search-interest embed | client-side |

---

## 6. Caveats baked into the dashboard (keep them honest)

- **Ghost vs GA4 count visitors differently and must not be compared head-to-head.** Ghost is
  first-party + cookieless (ad-blockers/ITP/consent don't suppress it) so it reads *higher*; its
  24-hour-window "unique visitors" drift above GA4's deduplicated users over time; GA4's
  third-party script gets blocked. Watch each for *direction*, not absolute level. (Noted on the
  Website-traffic card.)
- **Donor data = Donorbox online gifts only.** No checks, wires, FCNY/fiscal-sponsor gifts, event
  revenue, or pre-2026 giving. So some real major donors show as "non-donors."
- **Engagement time** (GA4) is an active-tab measure, not literal reading — a *comparative* signal.
- **X + Instagram followers are hand-entered** (their live counts aren't free to read).

---

## 7. Search Console — NOT set up; how to enable

Search Console would add **what people search on Google to find Vital City** (top queries,
impressions, clicks, CTR, average position) — a different dataset from traffic counts. Currently
the dashboard renders only a "connect this" stub.

To turn it on:

1. **Enable the API** — in Google Cloud (project `vital-city-dashboard`), enable **"Google Search Console API"**.
2. **Grant the service account access** — in Search Console (search.google.com/search-console),
   open the `vitalcitynyc.org` property → **Settings → Users and permissions → Add user**, paste
   `vital-city-dashboard-reader@vital-city-dashboard.iam.gserviceaccount.com`, role **Full** or **Restricted**.
3. **Note the property identifier** — either `sc-domain:vitalcitynyc.org` (domain property) or
   `https://www.vitalcitynyc.org/` (URL-prefix property).
4. **Then (code side):** reuse the existing `GA4_CREDS_JSON` service account, add a `GSC_SITE_URL`
   secret with the identifier from step 3, and implement `pull_search_console()` in `growth_pull.py`
   (sign the same service-account JWT → call the `searchanalytics.query` endpoint) plus a dashboard
   panel. (Ask Claude Code to build this once steps 1–2 are done.)

---

## 8. Common how-tos

- **Update X / Instagram followers:** edit `MANUAL_FOLLOWERS` in `growth_pull.py` (bump `as_of`); applies on the next daily refresh or a manual trigger.
- **Publish a data change now:** push the code, then `gh workflow run network-refresh.yml`.
- **Contact-tool edits** (rename, confirm, add, delete) save to the Google-Sheet override store
  (`OVERRIDES_URL`); they show immediately for the editor and merge in for everyone on the next refresh.
- **Add a new contact list:** hand the CSV to Claude Code to fold into `build_network.py`'s sources.

---

## 9. Contact tool — quick notes

- Affiliations are auto-derived from email domains (curated `INST_DOMAINS` map + registrable-suffix
  matching + `WEBMAIL` blanklist + a `refresh_stale_inst` pass that heals stale machine-garble values).
- Filters: category tri-state chips, refine chips (starred, notable, repeat donors, 2+ emails,
  no email, **no confirmed name**), name-quality and engagement dropdowns, saved views, a built-in
  **⭐ Fundraising prospects** view, duplicate finder.
- Edit modal saves with **⌘-Enter**; per-contact deep links; "copy link to this view".

---

*Maintained via Claude Code. When in doubt: front-end change → push; data change → push + run the
workflow; never re-encrypt locally; always push as `vitalcity-nyc`; hard-refresh to see changes.*
