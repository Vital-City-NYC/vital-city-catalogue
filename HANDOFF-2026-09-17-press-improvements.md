# Press map improvements — September 17, 2026

This handoff covers the email-enrichment pass and the subsequent functionality pass in `/Users/joshgreenman/Experiments/vital-city-catalogue`.

## Status and user requirements

The user subsequently authorized publication with “publish.” Source publication and a focused GitHub contact refresh are now being performed. Check the latest deployment record below and GitHub Actions for final status.

The user asked to improve email coverage and functionality without changing the design language. They subsequently clarified that **the New York Times must always be prioritized**, even when ordinary result filters would exclude its reporters. Times matches and fallbacks deliberately bypass those filters. This is a product requirement, not a bug to fix.

The static HTML before the inline application script and all CSS blocks were compared against HEAD and are unchanged. Runtime text and result grouping changed as described below, using the existing classes and components. Branding, typography, colors, layout system, dark mode, shared navigation and authentication were not redesigned.

## 1. Email enrichment

### Result

The local `private/press.json` still contains 1,308 people. The number with an email increased from **383 to 400**, exactly **17 additions**. A record-by-record comparison confirmed no existing address was replaced and no other person fields changed. The count and a report note were updated; the original full-harvest timestamp was retained rather than claiming a new full harvest.

Fourteen additions are at the Times: Matthew Haag, Dana Rubinstein, James Barron, Alex Vadukul, Anna Kodé, George Gene Gustines, Katherine Rosman, Michael Paulson, Remy Tumin, Sarah Bahr, Sharon Otterman, Sopan Deb and Stefanos Chen, plus Theodore Schleifer. The other three are Noah Powelson at the Queens Daily Eagle, Kelly Kennedy at FOX 5 and Melissa Brown at Chalkbeat. Brown was already in the roster; this pass verifies her contact information, not her relevance to NYC pitches.

Addresses were read from publisher author pages or staff directories and checked against the existing name-pairing rule. Nothing was guessed from an outlet's email pattern. No messages were sent. Some legitimate addresses that fail the existing name-pairing rule were left out rather than weakening the rule.

### Files and behavior

- `press/contact_sources.json` is a public-safe registry of 17 names, outlet IDs, publisher URLs and verification dates. **It contains no email addresses.** Its verification date describes this manual pass, not a nightly verification timestamp.
- `build_press.py` now has `read_contact_sources(people)`. It reads registered pages only for existing people who lack an email and whose normalized full name and primary/secondary outlet match the registry. It neither creates a person nor overwrites an address.
- The existing `read_author_page` parser extracts the address and source evidence. `apply_contact_sources` copies only `email`, `email_source_url` and `email_evidence`, with another name match and generic-inbox check.
- The supplemental stage runs after the curated press-list merge and before the final staff/contributor filtering, so existing curated contacts retain priority and verified outlet emails can contribute to existing staff-evidence rules.
- Results are cached in ignored `private/press_cache/contact_sources.json`, following the existing `--fast` convention. Normal builds fetch sources again; `--fast` reuses the cached results. After changing the registry, use a normal build or remove this one cache file when checking new sources.
- `curl` now accepts an optional user agent. Supplementary contact reads first use the existing browser user agent, then retry once with curl's normal user agent if no email was found. This is an ordinary public-page fetch, without authentication or paywall access.
- `read_author_page` accepts the retry option. Existing callers retain their previous behavior.
- The terminal `main()` call is protected with `if __name__ == "__main__"`. Importing the builder for tests or targeted inspection no longer starts a full network harvest. Command-line invocation is unchanged.

### Private evidence and limits

The ignored directory `private/press-email-pass/` holds the baseline, fetched HTML, research scripts/results, `additions.json`, and a readable `review.md` with all 17 addresses and source links. Do not commit that directory or plaintext contact data.

All 17 additions were verified from pages retrieved during the pass. Times pages intermittently return blocking responses: a later live recheck recovered 15 of the 17 even with the alternate user agent. **The registry is a list of pages to recheck, not a durable email backup.** A subsequent full cloud build can recover fewer than 17; this implementation does not guarantee the live count will be 400. The local private output has all 17 verified additions. No encrypted payload was generated or changed locally.

## 2. Search behavior (`press/index.html`)

### Name lookup

The new `searchText` helper removes combining accents, lowercases text and normalizes curly apostrophes. Name search and the directory's existing search now match examples such as `Anna Kode` → `Anna Kodé` and straight versus curly apostrophes in surnames.

When a query matches names and does not match any beat vocabulary, `rank` returns explicit `nameMatch` results. The renderer labels them as name matches instead of claiming their entire career story count consists of clips on the query. It also allows a name match with zero harvested stories to appear directly. Previously such people could fall into the hidden single-clip section or have total stories presented as topic evidence.

The directory retains its existing substring search across name, title, bio, email, outlets and beat labels, now normalized for accents/apostrophes. This is not fuzzy matching or semantic search.

### Unconditional Times priority

For topical searches, `pinnedBlock` now receives the unfiltered ranked results (`all`), rather than filtered `LAST`. Thus a relevant Times reporter remains the Times choice even if they lack an email or a Vital City relationship; the page does not substitute a less relevant fallback solely because of those filters. If there is no Times topic match, the existing closest-reporter fallback is retained and still bypasses filters.

Direct name searches also show Times contacts first. A matching Times person is shown when present; otherwise the usual Times fallback contacts appear ahead of other name matches, without falsely describing them as matches or assigning them topic clip counts. Email, Vital City and major-outlet filters continue to apply to ordinary name results.

The existing Times pinning, core-outlet priority, outlet reach weights, recency adjustment, national/metro adjustment, topic scoring and beat vocabulary otherwise remain in place. The directory's own explicit filtering behavior is unchanged.

## 3. Shortlist composition

`shortlist` previously added core-outlet reporters first, then started the TV/radio reservation counter at zero. Two TV reporters already chosen as core picks could therefore be followed by two more reserved TV picks, unnecessarily displacing stronger results.

The reservation counter now starts with the number of that medium already selected. Core-outlet priority remains first; reservations are minimums, not caps. Strong broadcast results can still earn later places by score. The existing 15-person shortlist limit and two-per-outlet rule are unchanged; the Times block remains separate.

## 4. Consistent evidence and truthful story counts

Cards, directory rows, the known-contacts table and CSV exports now use the existing `minFor(p)` threshold consistently: one clip for the Times/core outlets, two elsewhere. Previously ranking could accept a core outlet's single clip while the card hid the actual beat/example or the export omitted that beat.

The story-expansion link uses the number actually available in `p.stories`, and says, for example, “show 12 recent stories of 80 harvested.” It appears only when more than three stories are present in the payload. Previously it promised “all 80 harvested stories” even though the builder exports at most 12 per person. This does not expand the payload or change harvesting.

## 5. Selection and export preparation

Email copying and email-draft preparation trim and lowercase addresses before deduplicating them. The selection note separately counts people without an address and repeated addresses. Previously two selected people sharing an address could produce a false “without a published address” warning.

The table select-all checkbox now reflects all/none/partial selection, including its native indeterminate state. Selection controls are refreshed after result/directory/beat renders and expanded tables. Selection remains in memory across searches, as before; it is not persisted across page reloads.

CSV beat inclusion uses the corrected evidence threshold described above. No email-sending behavior was added: the existing copy, download and draft actions still require the user's click.

## 6. Validation

Run from the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_press_contacts.py'
node tests/test_press_ui.cjs
python3 -m py_compile build_press.py
git diff --check
```

Four Python tests passed, including preservation of the live roster and metadata during the focused refresh. The other tests cover: registry/name/outlet eligibility and existing-address protection; published address/provenance extraction and application; rejection of absent, mismatched, generic or unsourced addresses.

Eight JavaScript regression checks passed: normalized name lookup; matched Times bypassing filters while ordinary outlets obey them; unconditional Times fallback; Times-first direct name search including zero-story people; broadcast reservation accounting; one-clip evidence and accurate expansion count; duplicate versus missing addresses; and partial/full select-all state.

The JS tests evaluate the actual inline application script in Node's VM with a minimal DOM stub. They are not a full browser or visual regression test. No full nightly/cloud build was run. Static HTML and CSS comparisons passed, and the private data comparison confirmed exactly the 17 intended email enrichments.

## 7. Remaining issues and publication path

The roster still includes clear non-person entries, such as “Show Search,” “Apps Help,” “Donor Transparency Policy,” “Community Violence,” and “Trump Administration.” These were observed during inspection but **not removed in this pass**. Structural masthead parsing is a worthwhile next improvement; avoid treating every zero-story record as invalid, since real editors and staff also have zero harvested bylines.

Pasted URLs are still interpreted from their URL slug, not by fetching and understanding the article. Beat matching is still vocabulary-based. The previously described Mac harvest job was neither installed nor run by this pass. Intermittent publisher blocking remains a limitation.

The user authorized publishing. Tracked files are:

- `build_press.py`
- `press/contact_sources.json`
- `press/index.html`
- `tests/test_press_contacts.py`
- `tests/test_press_ui.cjs`
- `refresh_press_contacts.py`
- `.github/workflows/press-contact-refresh.yml`
- this handoff

Do not commit `private/`, plaintext emails, or locally re-encrypted toolkit data. Publish source changes through the existing repository process and let GitHub's `network-refresh.yml` build/encrypt with its repository secret. Verify the resulting press count and source coverage after the workflow finishes; a local count of 400 is not proof of a live count of 400. Do not rotate or expose the passphrase.

## Focused publication workflow added after approval

`press-contact-refresh.yml` is manual-only and shares the full refresh's `network-refresh` concurrency group. It checks out current main, decrypts the current committed `press/data.enc` using the existing repository secret, runs `refresh_press_contacts.py`, and calls `encrypt_press.py` inside GitHub. Only the newly encrypted press payload is committed. There is no local encryption or upload of the laptop's plaintext data.

`refresh_press_contacts.py` fills missing contacts using the reviewed URL registry, recomputes the email count and appends an enrichment note. It retains the roster, other fields and original full-harvest timestamp. This avoids waiting for and modifying unrelated dashboards through the full refresh. Future scheduled full builds still use the supplemental source stage in `build_press.py`. Four Python tests and eight UI checks passed before publication.
