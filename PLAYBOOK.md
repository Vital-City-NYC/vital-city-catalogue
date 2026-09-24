# Network explorer — maintenance playbook

> For the full technical logic (every matching/inference rule + how to feed in
> new data sources like a Ghost API or Mailchimp export), see **LOGIC.md**.

The explorer at **https://vitalcity-nyc.github.io/vital-city-catalogue/network/**
is generated from three lists. Here's how the team keeps it current.

Passphrase to open the page: shared separately (stored locally in
`private/.netpass`; never in the repo). Rotate any time — see bottom.

## The three source lists

| List | Who maintains it | Where it lives |
|---|---|---|
| **Contacts** (names + categories: journalist, academic, funder, gov, judge, etc.) | The team, collaboratively | **Google Sheet:** `vital-city-contacts-master` — https://docs.google.com/spreadsheets/d/1GXNFKKspPgXK_ubUB2XptrNQfXqmHeHocyN2c_6O6Q8/edit (owner jgreenman@vitalcitynyc.org) |
| **Members / subscribers** | Comes from Ghost | Export from Ghost admin |
| **Donors** | Comes from FCNY | Export from FCNY |

Everything is fused and de-duplicated by email, then name, into one record per
person. A person can be several things at once (e.g. academic + member + donor).

## Day to day: editing contacts (anyone on the team)

Edit the shared **Google Sheet** — add people, fix details, set their
categories. One row per person. Keep these columns:

`name, email, institution, role, categories, specialties`

- **categories**: a semicolon-separated list from: VC contributor, VC advisor,
  journalist, academic, foundation leadership, nonprofit leadership, city gov,
  state gov, fed gov, judge, architect. e.g. `journalist; academic`
- **specialties**: same idea, from: criminal justice, housing, transit.

(The build also still understands the older one-column-per-category layout, so
either works.)

## Publishing updates to the live page

Editing the Sheet does **not** change the live page by itself — someone
publishes when ready (a minute, start to finish):

1. **Contacts:** either ask Claude to pull the Google Sheet directly (via the
   Drive connector → it writes `private/contacts_source.csv`), or in the Sheet
   do *File ▸ Download ▸ Comma-separated values* and save it as
   `private/contacts_source.csv`.
2. **Members (if you have a fresh export):** save it as
   `private/members_source.csv`.
3. **Donors (if you have a fresh export):** save it as
   `private/donors_source.csv`.
   *(Skip 2 or 3 to keep the last version — only contacts change often.)*
4. Run:
   ```
   bash publish.sh
   ```
   It rebuilds, re-encrypts and pushes. The live page updates in ~1 minute.

## Using the explorer

Open the URL, enter the passphrase. Filter by any combination — type/specialty
(left checkboxes), Members / Non-members, Authors, Donors — and **Export CSV**
to download the exact list (e.g. "academics who are donors but not members").

## Editing people (every field)

Click the **✎** on any row to edit a person's **name, institution, emails,
types and specialties**. Gray italic names are email guesses; **✓** confirms one.

1. Edits save in your browser instantly.
2. To make them permanent for everyone, click **Export edits** (downloads
   `vital-city-edits.json`), save it as `private/people_overrides.json`, and run
   `bash publish.sh`. The build bakes them in for all users.

## Unsubscribed (former contacts)

People who left the newsletter (from the Mailchimp `unsubscribed` export, saved
as `private/unsubscribed_source.csv`) are kept **separate**, shown in **red**,
and hidden by default. Use the **Include unsubscribed** checkbox or the red
**unsubscribed** banner number to see them.

## Consolidated spreadsheet

A full spreadsheet mirroring the tool (everyone, all fields, sortable) lives in
the Workspace Drive as **Vital City — Network (master)**. Regenerate it any time
from the tool's data and re-import; it replaces the old agglomeration sheet as
the reference view.

## Rotating the passphrase

There are now **eight** encrypted payloads, not one, and CI rebuilds all of them
nightly from the `VC_NETWORK_PASS` repo secret. So the old three-line recipe is
wrong twice over: it left seven tools on the old passphrase, and because it never
touched the secret, the next nightly run re-encrypted everything with the OLD
value and silently undid the rotation.

Do it in this order. Steps 1 and 2 are yours -- they involve typing the
passphrase, so do not delegate them and do not put the value on a command line,
where it lands in shell history and in the process list.

**1. Change the repo secret first.** `gh` prompts for the value and does not echo it.

```
gh auth switch --user vitalcity-nyc
gh secret set VC_NETWORK_PASS --repo vitalcity-nyc/vital-city-catalogue
gh auth switch --user joshgreenman1973
```

**2. Update the two local copies,** so local runs and the monthly resharing
routine keep working. zsh, prompted, never echoed:

```
read -rs "np?New toolkit passphrase: " && \
  printf '%s' "$np" > private/.netpass && \
  security add-generic-password -U -a "$USER" -s vc-network-pass -w "$np" && \
  unset np && echo "local copies updated"
```

**3. Let CI re-encrypt everything.** Do NOT re-encrypt locally: several payloads
are built from `private/` files that go stale between pulls, and publishing a
local build would regress the live dashboards (see the local-runs-clobber-secrets
note in HANDOFF).

```
gh workflow run network-refresh.yml   # the seven in this repo
gh workflow run live-refresh.yml      # growth/live/live.enc
```

**4. Verify, then tell the group.** Until those runs finish, the published
payloads are still encrypted with the OLD passphrase and the old one still
works -- so there is no outage, and no moment when nobody can get in. Once the
runs are green, open each tool and unlock it with the new passphrase. Then share
it with the team out of band. Never write it into a file in this repo: it is
public, and a passphrase committed here in August stayed in history even after
the line was removed.

The eight payloads, for checking: `network/`, `growth/`, `growth/live/`,
`prospects/`, `catalogue-analysis/`, `press/`, `resharing/`, `private_sources.enc`.

## Notes / limits

- This is a static, client-side-encrypted page: great for a shared, filterable,
  exportable view, but it is **not** a live multi-user database. The Google
  Sheet is the place people edit; `publish.sh` is how edits go live.
- Source files (`private/`) and the plaintext people data never leave this
  machine — only the encrypted blob is published.

## Website manual (the Manual tab)

The Manual tab (`manual/`) is the staff guide to how vitalcitynyc.org works in
Ghost and in Obox's theme. It is a document, not a nightly dataset, so it has no
workflow step and the home page never calls it stale.

- **Source:** `private/manual/manual.html` (gitignored; the published copy is
  encrypted with the suite passphrase because it names contacts and admin steps).
- **To change it:** edit the source, run `python3 build_manual.py`, then commit
  `manual/data.enc` and push. The build refreshes `~/Desktop/Vital City website
  manual.pdf`, pulls the site's live top menu into the menus section, and moves
  the "As of" date to today only when the content or the menu actually changed.
- **Drift check:** the page compares the live Ghost menu with the one the manual
  was built from and shows a banner when they differ. Rebuild to clear it.
- **Lost the source?** `manual/data.enc` decrypts to the full built HTML, so the
  text can be recovered from it with the passphrase.
